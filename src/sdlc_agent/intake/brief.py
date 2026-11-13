"""Build one normalized project brief from whatever came in, and score how complete it is."""
from __future__ import annotations

import re

from ..llm.base import LLMClient, parse_json
from ..state.models import (
    BriefItem,
    Chunk,
    Completeness,
    InputType,
    ProjectBrief,
    SourceRef,
    SowLine,
)
from ..state.store import next_id

_BULLET = re.compile(r"^\s*(?:[-*•▪◦]|\d+[.)]|[a-z][.)])\s+", re.IGNORECASE)
_SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")


def _client_chunks(chunks: list[Chunk]) -> list[Chunk]:
    """Text the client wrote or sent (files, notes). Crawled pages are references, not SOW lines."""
    return [c for c in chunks if c.source.kind in ("file", "intake")]


def extract_sow_lines(chunks: list[Chunk]) -> list[SowLine]:
    lines: list[SowLine] = []
    for chunk in _client_chunks(chunks):
        for raw in chunk.text.splitlines():
            text = _BULLET.sub("", raw).strip()
            if len(text.split()) < 3:
                continue
            parts = _SENTENCE.split(text) if len(text) > 300 else [text]
            for part in parts:
                if len(part.split()) >= 3:
                    lines.append(SowLine(id=next_id("L", (x.id for x in lines)), text=part.strip(), source=chunk.source))
    return lines


def completeness_of(chunks: list[Chunk], input_type: InputType) -> Completeness:
    if input_type is InputType.ONE_LINE:
        return Completeness.THIN
    words = sum(len(c.text.split()) for c in _client_chunks(chunks))
    if words >= 1200:
        return Completeness.RICH
    if words >= 120 or input_type in (InputType.URL, InputType.APP_STORE_URL, InputType.MIXED):
        return Completeness.PARTIAL
    return Completeness.THIN


BRIEF_SYSTEM = """You are the intake agent of a software delivery company.
You turn a client's requirement, in whatever form it arrived, into one normalized project brief.
Rules:
- Extract only what the input says. When you fill something the input does not say, set its source to "inferred".
- Every feature, NFR and constraint carries a source: the exact source label shown in the input (for example "file:SOW.pdf p.3" or "url:https://..."), "intake", or "inferred".
- Keep each item to one short sentence.
- Payment and third-party integrations: list them if mentioned, but do not invent them."""

BRIEF_SCHEMA = """Return JSON with exactly these keys:
{
  "goal": str,
  "domain": str,                 // e.g. "classifieds", "e-commerce", "business tool"
  "region": str,                 // target country or region, "" if unknown
  "target_users": [str],
  "intent": "new" | "rebuild" | "like_reference" | "unknown",
  "platforms": [str],            // only if stated, e.g. "android", "ios", "web", "admin panel"
  "features": [{"text": str, "source": str}],
  "nfrs": [{"text": str, "source": str}],
  "constraints": [{"text": str, "source": str}],
  "references": [str]            // URLs or product names the client pointed to
}"""


def _to_source(label: str) -> SourceRef:
    label = (label or "").strip()
    for kind in ("file", "url"):
        if label.startswith(f"{kind}:"):
            return SourceRef(kind=kind, ref=label[len(kind) + 1 :])
    if label == "intake":
        return SourceRef(kind="intake", ref="client text")
    return SourceRef(kind="inferred")


def _render_chunks(chunks: list[Chunk], max_chars: int = 30000) -> str:
    out, used = [], 0
    for c in chunks:
        block = f"[source: {c.source.label()}]\n{c.text}\n"
        if used + len(block) > max_chars:
            out.append(f"[source: {c.source.label()}]\n{c.text[: max(0, max_chars - used)]}\n[truncated]")
            break
        out.append(block)
        used += len(block)
    return "\n".join(out)


def build_brief(llm: LLMClient, chunks: list[Chunk], completeness: Completeness) -> ProjectBrief:
    prompt = f"Client input:\n\n{_render_chunks(chunks)}\n\n{BRIEF_SCHEMA}"
    data = parse_json(llm.complete(BRIEF_SYSTEM, prompt, json_mode=True).text)

    def items(key: str) -> list[BriefItem]:
        return [
            BriefItem(text=str(x.get("text", "")).strip(), source=_to_source(x.get("source", "")))
            for x in data.get(key, []) or []
            if isinstance(x, dict) and str(x.get("text", "")).strip()
        ]

    intent = data.get("intent", "unknown")
    return ProjectBrief(
        goal=str(data.get("goal", "")),
        domain=str(data.get("domain", "")).lower().strip(),
        region=str(data.get("region", "")),
        target_users=[str(x) for x in data.get("target_users", []) or []],
        intent=intent if intent in ("new", "rebuild", "like_reference") else "unknown",
        platforms=[str(x).lower() for x in data.get("platforms", []) or []],
        features=items("features"),
        nfrs=items("nfrs"),
        constraints=items("constraints"),
        references=[str(x) for x in data.get("references", []) or []],
        completeness=completeness,
    )


def apply_intake_answers(brief: ProjectBrief, answers: dict[str, str]) -> ProjectBrief:
    """Answers from the up-front questionnaire override what the agent inferred."""
    b = brief.model_copy(deep=True)
    intake = SourceRef(kind="intake", ref="questionnaire")
    if answers.get("domain"):
        b.domain = answers["domain"].lower().strip()
    if answers.get("region"):
        b.region = answers["region"].strip()
    if answers.get("intent") in ("new", "rebuild", "like_reference"):
        b.intent = answers["intent"]
    if answers.get("platforms"):
        b.platforms = [p.strip().lower() for p in answers["platforms"].split(",") if p.strip()]
    if answers.get("target_users"):
        b.target_users = [u.strip() for u in answers["target_users"].split(",") if u.strip()]
    if answers.get("must_have_features"):
        for f in answers["must_have_features"].split(","):
            if f.strip():
                b.features.append(BriefItem(text=f.strip(), source=intake))
    for key, label in (("deadline", "Deadline"), ("budget", "Budget"), ("expected_scale", "Expected scale")):
        if answers.get(key):
            b.constraints.append(BriefItem(text=f"{label}: {answers[key].strip()}", source=intake))
    if answers.get("competitors"):
        b.references.extend(x.strip() for x in answers["competitors"].split(",") if x.strip())
    return b
