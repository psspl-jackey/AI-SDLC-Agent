"""Requirements analyst: requirements with IDs, SOW and NFR gaps, feasibility, client questions.

run() is pure (returns a result dict) so it can run in parallel with the research agent;
apply() merges the result into the project.
"""
from __future__ import annotations

import re

from pathlib import Path

from ..gaps.register import add_gap
from ..llm.base import LLMClient
from ..llm.json_call import Dicts, complete_json
from ..questions.queue import ask
from ..state.models import GapSource, Project, Requirement, SourceRef
from ..state.store import next_id

SHAPE = {
    "requirements": Dicts({"text": "str", "kind": "str", "sow_line_ids": "strs"}, text_key="text"),
    "not_requirement_line_ids": "strs",
    "gaps": Dicts({"description": "str", "question": "str", "assumed_answer": "str", "source": "str",
                   "blocking": "bool"},
                  text_key="description"),
    "feasibility": Dicts({"concern": "str", "severity": "str"}, text_key="concern"),
}

NAME = "requirements_analyst"
SKILL = Path(__file__).resolve().parents[3] / "skills" / "nfr_checklist.md"

SYSTEM = """You are a senior business analyst at a software delivery company.
From the project brief and the numbered input lines, you:
1. Write clear, testable requirements. Each one cites the input line ids it comes from. Also write a
   requirement for each feature in the brief that no input line covers (cite no line ids for those).
2. Account for EVERY input line: each line id appears in some requirement's sow_line_ids or in
   not_requirement_line_ids (greetings, background, company info).
3. Read each input line on its own and raise a "sow" gap when it is vague or not measurable ("fast",
   "easy", "modern"), has no date or number where one is needed ("before Diwali" with no year),
   conflicts with another line, or leaves out who, which platform, or how (for example how users log in).
4. Then raise "nfr" gaps for checklist items that are missing AND would change cost or architecture for
   THIS project. Be specific to the project; do not copy the checklist wording.
5. For every gap, write one question for the client, say whether it blocks work, and give the most
   reasonable assumed answer so work can continue.
6. Note feasibility concerns (technical or timeline).
Real payment and third-party integrations are out of scope for now: if the input needs payment,
write the requirement against a dummy payment gateway with static responses.
Never invent client facts. Keep every item to one or two sentences."""

SCHEMA = """Return JSON:
{
  "requirements": [{"text": str, "kind": "functional" | "nfr", "sow_line_ids": [str]}],
  "not_requirement_line_ids": [str],
  "gaps": [{"source": "sow" | "nfr", "description": str, "question": str,
            "blocking": bool, "assumed_answer": str}],
  "feasibility": [{"concern": str, "severity": "low" | "medium" | "high"}]
}"""


def run(llm: LLMClient, project: Project) -> dict:
    brief = project.brief.model_dump_json(include={
        "goal", "domain", "region", "target_users", "intent", "platforms", "features", "nfrs", "constraints",
    }) if project.brief else "{}"
    lines = "\n".join(f"{line.id}: {line.text}" for line in project.sow_lines) or "(no input lines)"
    checklist = SKILL.read_text(encoding="utf-8") if SKILL.exists() else ""
    prompt = (
        f"Project brief (JSON):\n{brief}\n\nInput lines:\n{lines}\n\n"
        f"NFR checklist:\n{checklist}\n\n{SCHEMA}"
    )
    result = complete_json(llm, SYSTEM, prompt, SHAPE)

    # Small models often skip lines. Ask again for just the lines nothing accounts for.
    mapped = {lid for r in result.get("requirements", []) for lid in r.get("sow_line_ids", [])}
    mapped |= set(result.get("not_requirement_line_ids", []))
    missing = [line for line in project.sow_lines if line.id not in mapped]
    if missing:
        listing = "\n".join(f"{line.id}: {line.text}" for line in missing)
        extra = complete_json(llm, SYSTEM, (
            f"Project brief (JSON):\n{brief}\n\nThese input lines are not yet accounted for:\n{listing}\n\n"
            "For each line, write the requirement it states (citing the line id), or list it in "
            f"not_requirement_line_ids. Raise a sow gap if the line is vague.\n\n{SCHEMA}"
        ), SHAPE)
        for key in ("requirements", "gaps", "feasibility"):
            result[key] = result.get(key, []) + extra.get(key, [])
        result["not_requirement_line_ids"] = result.get("not_requirement_line_ids", []) + extra.get(
            "not_requirement_line_ids", [])
    return result


_PAYMENT = re.compile(r"\bpay(s|ing|ment|ments)?\b|\bcheckout\b", re.IGNORECASE)
_DUMMY = re.compile(r"\b(dummy|mock|stub|simulated|static)\b", re.IGNORECASE)
DUMMY_NOTE = " Payment uses the dummy payment gateway with static responses; real payment is out of scope for now."


def with_payment_rule(text: str) -> str:
    """Rule from the team decisions: payment is built against a dummy gateway. Enforced in code."""
    return text + DUMMY_NOTE if _PAYMENT.search(text) and not _DUMMY.search(text) else text


def apply(project: Project, result: dict) -> None:
    line_by_id = {line.id: line for line in project.sow_lines}

    for item in result.get("requirements", []) or []:
        text = str(item.get("text", "")).strip()
        if not text:
            continue
        line_ids = [lid for lid in item.get("sow_line_ids", []) or [] if lid in line_by_id]
        source = line_by_id[line_ids[0]].source if line_ids else SourceRef(kind="inferred")
        req = Requirement(
            id=next_id("REQ", (r.id for r in project.requirements)),
            text=with_payment_rule(text),
            kind="nfr" if item.get("kind") == "nfr" else "functional",
            source=source,
            sow_line_ids=line_ids,
        )
        project.requirements.append(req)
        for lid in line_ids:
            line_by_id[lid].requirement_ids.append(req.id)

    for lid in result.get("not_requirement_line_ids", []) or []:
        if lid in line_by_id and not line_by_id[lid].requirement_ids:
            line_by_id[lid].not_a_requirement = True

    for g in result.get("gaps", []) or []:
        description = str(g.get("description", "")).strip()
        if not description:
            continue
        gap = add_gap(
            project,
            source=GapSource.NFR if g.get("source") == "nfr" else GapSource.SOW,
            description=description,
            found_by=NAME,
        )
        ask(
            project,
            str(g.get("question") or f"Please confirm: {description}"),
            blocking=bool(g.get("blocking")),
            assumed_answer=str(g.get("assumed_answer") or "") or None,
            related_gap_id=gap.id,
        )

    for f in result.get("feasibility", []) or []:
        if f.get("concern"):
            project.log(f"Feasibility ({f.get('severity', 'medium')}): {f['concern']}")
