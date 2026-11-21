"""Change analyst: turns a client change request into requirement changes (added, changed, removed).

A change request re-enters at Stage 1. Its text becomes input lines (source change_request:CR-xxx)
so the Gate 1 rule still holds: every line maps to a requirement or is marked not a requirement.
Requirement ids stay stable: changed requirements keep their id, removed ones are kept and marked,
so traceability to tasks and earlier documents is never lost.

run() is pure and returns a result dict; apply() is the only writer.
"""
from __future__ import annotations

from ..gaps.register import add_gap
from ..llm.base import LLMClient, parse_json
from ..questions.queue import ask
from ..state.models import ChangeRequest, GapSource, Project, Requirement, SourceRef, SowLine
from ..state.store import next_id
from .platform_decision import normalise

NAME = "change_analyst"

SYSTEM = """You analyse a client's change request against a project's current requirements.
Decide exactly what changes: new requirements to add, existing requirements whose wording must
change (keep their id), and existing requirements to remove. Touch only what the change request
affects; leave everything else alone. Cite the change request line ids each change comes from.
For new or changed requirements, list the platforms they need, chosen from the project's platforms.
Raise a gap with a client question when the change request is vague or conflicts with other
requirements, with the most reasonable assumed answer so work can continue.
Real payment and third-party integrations are out of scope for now (payment uses a dummy gateway)."""

SCHEMA = """Return JSON:
{
  "added": [{"text": str, "kind": "functional" | "nfr", "line_ids": [str], "platforms": [str]}],
  "changed": [{"id": str, "text": str, "line_ids": [str], "platforms": [str]}],
  "removed": [{"id": str, "line_ids": [str]}],
  "not_requirement_line_ids": [str],
  "gaps": [{"source": "sow" | "nfr", "description": str, "question": str, "blocking": bool, "assumed_answer": str}]
}"""


def run(llm: LLMClient, project: Project, cr: ChangeRequest) -> dict:
    lines = {line.id: line for line in project.sow_lines}
    reqs = "\n".join(f"{r.id} [{r.kind}]: {r.text}" for r in project.active_requirements()) or "(none)"
    cr_lines = "\n".join(f"{lid}: {lines[lid].text}" for lid in cr.line_ids if lid in lines)
    m = project.platform_matrix
    platforms = ", ".join(d.platform for d in m.included()) if m else "not decided yet"
    prompt = (
        f"Project platforms: {platforms}\n\nCurrent requirements:\n{reqs}\n\n"
        f"Change request {cr.id} lines:\n{cr_lines}\n\n{SCHEMA}"
    )
    return parse_json(llm.complete(SYSTEM, prompt, json_mode=True).text)


def apply(project: Project, cr: ChangeRequest, result: dict) -> None:
    lines = {line.id: line for line in project.sow_lines}
    cr_lines = set(cr.line_ids)
    active = {r.id: r for r in project.active_requirements()}
    source = SourceRef(kind="change_request", ref=cr.id)

    def line_ids(item: dict) -> list[str]:
        return [lid for lid in item.get("line_ids", []) or [] if lid in cr_lines]

    def platforms(item: dict) -> list[str]:
        return list(dict.fromkeys(normalise(p) for p in item.get("platforms", []) or [] if str(p).strip()))

    def link(req_id: str, ids: list[str]) -> None:
        for lid in ids:
            if req_id not in lines[lid].requirement_ids:
                lines[lid].requirement_ids.append(req_id)

    for item in result.get("changed", []) or []:
        req = active.get(item.get("id"))
        text = str(item.get("text", "")).strip()
        if req is None or not text or req.id in cr.changed:
            continue
        project.log(f"{cr.id} changed {req.id}: \"{req.text}\" -> \"{text}\"")
        req.text = text
        req.changed_by.append(cr.id)
        ids = line_ids(item)
        req.sow_line_ids = list(dict.fromkeys(req.sow_line_ids + ids))
        link(req.id, ids)
        cr.changed.append(req.id)
        if platforms(item):
            cr.platforms[req.id] = platforms(item)

    for item in result.get("removed", []) or []:
        req = active.get(item.get("id"))
        if req is None or req.id in cr.changed or req.id in cr.removed:
            continue
        req.removed_by = cr.id
        link(req.id, line_ids(item))
        cr.removed.append(req.id)
        project.log(f"{cr.id} removed {req.id}: \"{req.text}\"")

    for item in result.get("added", []) or []:
        text = str(item.get("text", "")).strip()
        if not text:
            continue
        req = Requirement(
            id=next_id("REQ", (r.id for r in project.requirements)), text=text,
            kind="nfr" if item.get("kind") == "nfr" else "functional", source=source, sow_line_ids=line_ids(item),
        )
        project.requirements.append(req)
        link(req.id, req.sow_line_ids)
        cr.added.append(req.id)
        cr.platforms[req.id] = platforms(item)
        project.log(f"{cr.id} added {req.id}: \"{text}\"")

    for lid in result.get("not_requirement_line_ids", []) or []:
        if lid in cr_lines and not lines[lid].requirement_ids:
            lines[lid].not_a_requirement = True

    for g in result.get("gaps", []) or []:
        description = str(g.get("description", "")).strip()
        if not description:
            continue
        gap = add_gap(project, source=GapSource.NFR if g.get("source") == "nfr" else GapSource.SOW,
                      description=f"{cr.id}: {description}", found_by=NAME)
        ask(project, str(g.get("question") or f"Please confirm: {description}"), blocking=bool(g.get("blocking")),
            assumed_answer=str(g.get("assumed_answer") or "") or None, related_gap_id=gap.id)


def lines_for(project: Project, cr_id: str, text: str) -> list[SowLine]:
    """Split change request text into input lines, numbered after the project's existing lines."""
    from ..intake.brief import extract_sow_lines
    from ..state.models import Chunk

    chunk = Chunk(text=text, source=SourceRef(kind="change_request", ref=cr_id))
    # extract_sow_lines reads client text only; a change request is client text.
    raw = extract_sow_lines([chunk.model_copy(update={"source": SourceRef(kind="intake", ref=cr_id)})])
    if not raw and text.strip():  # a short request ("Remove chat") is still one line
        raw = [SowLine(id="L-001", text=text.strip(), source=chunk.source)]
    used = [line.id for line in project.sow_lines]
    out = []
    for line in raw:
        new_id = next_id("L", used)
        used.append(new_id)
        out.append(SowLine(id=new_id, text=line.text, source=chunk.source))
    return out
