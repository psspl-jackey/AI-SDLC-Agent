"""Build one normalized project brief from whatever came in, and score how complete it is."""
from __future__ import annotations

import re

from ..llm.base import LLMClient
from ..llm.json_call import Dicts, complete_json
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

BRIEF_SHAPE = {
    "goal": "str", "domain": "str", "region": "str", "intent": "str", "target_users": "strs", "platforms": "strs",
    "references": "strs", "features": Dicts(text_key="text"), "nfrs": Dicts(text_key="text"),
    "constraints": Dicts(text_key="text"),
}

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


_PLATFORM_WORDS = {
    "android": ("android",), "ios": ("ios", "iphone", "ipad", "apple"),
    "web": ("web", "website", "browser", "pwa"), "admin panel": ("admin",),
    "mobile": ("mobile", "app store", "play store", "smartphone"),
}


def _stated_platforms(proposed: list, chunks: list[Chunk]) -> list[str]:
    """Keep a platform only if the client's own text mentions it; small models tend to invent one."""
    text = " ".join(c.text for c in _client_chunks(chunks)).lower()
    kept = []
    for p in proposed or []:
        name = str(p).lower().strip()
        words = next((w for key, w in _PLATFORM_WORDS.items() if key in name or name in key), (name,))
        if name and any(re.search(rf"\b{re.escape(w)}", text) for w in words):
            kept.append(name)
    return kept


def build_brief(llm: LLMClient, chunks: list[Chunk], completeness: Completeness) -> ProjectBrief:
    prompt = f"Client input:\n\n{_render_chunks(chunks)}\n\n{BRIEF_SCHEMA}"
    data = complete_json(llm, BRIEF_SYSTEM, prompt, BRIEF_SHAPE)

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
        platforms=_stated_platforms(data.get("platforms", []), chunks),
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


def fill_thin_brief(brief: ProjectBrief) -> int:
    """Thin input (one line): fill the brief from the domain pack's table-stakes features, tagged inferred.
    Each one then enters the gap register as assumed and is confirmed or dropped at Gate 1."""
    from ..domain_packs import match_pack

    if brief is None or brief.completeness is not Completeness.THIN:
        return 0
    matched = match_pack(brief.domain)
    if not matched:
        return 0
    have = {_norm_words(f.text) for f in brief.features}
    added = 0
    for feat in matched[1].get("features", []):
        if feat.get("tier") != "table_stakes":
            continue
        words = _norm_words(feat["name"])
        if any(len(words & h) / max(1, len(words)) >= 0.6 for h in have):
            continue
        brief.features.append(BriefItem(text=f"{feat['name']} ({feat['id']})", source=SourceRef(kind="inferred")))
        added += 1
    return added


def _norm_words(text: str) -> frozenset[str]:
    return frozenset(w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 2)
