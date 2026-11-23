"""Reviewer agent: checks the gap register before it reaches the humans at Gate 1.

- Model: finds duplicate gaps and rewrites unclear ones.
- Code: checks that every evidence link still opens. A broken link is cleared, so the
  coverage check fails until someone fixes it rather than passing on a dead source.
"""
from __future__ import annotations

import re
from typing import Callable

import httpx

from ..llm.base import LLMClient
from ..llm.json_call import Dicts, complete_json
from ..state.models import Project

SHAPE = {"duplicates": Dicts({"keep": "str", "remove": "strs"}), "rewrites": Dicts({"id": "str", "text": "str"})}

NAME = "reviewer"

SYSTEM = """You review a gap register for a software project before human approval.
Find gaps that describe the same thing (duplicates) and gaps whose wording is unclear. Use the gap ids
(GAP-001) in your answer. In each duplicate group keep the most specific gap; a general gap is not a
duplicate of a specific one. Rewrite unclear gaps in one plain sentence without
changing their meaning."""


def link_ok(url: str) -> bool:
    try:
        r = httpx.get(url, timeout=15, follow_redirects=True,
                      headers={"User-Agent": "AI-SDLC-Agent/0.1 (link check)"})
        return r.status_code < 400
    except httpx.HTTPError:
        return False


def run(llm: LLMClient, project: Project, *, check_link: Callable[[str], bool] = link_ok) -> dict:
    result = {"duplicates": [], "rewrites": [], "broken_links": []}
    if project.gaps:
        listing = "\n".join(f"{g.id} [{g.source.value}]: {g.description}" for g in project.gaps)
        data = complete_json(llm, SYSTEM,
            f"Gap register:\n{listing}\n\nReturn JSON: "
            '{"duplicates": [{"keep": str, "remove": [str]}], "rewrites": [{"id": str, "text": str}]}', SHAPE)
        result["duplicates"] = data.get("duplicates", []) or []
        result["rewrites"] = data.get("rewrites", []) or []
    for url in sorted({g.evidence_url for g in project.gaps if g.evidence_url}):
        if not check_link(url):
            result["broken_links"].append(url)
    return result


_GAP_ID = re.compile(r"GAP-\d+")


def _gap_id(value: str) -> str | None:
    """Models often return the whole line ("GAP-003 [nfr]: ...") instead of the id."""
    m = _GAP_ID.search(str(value or ""))
    return m.group(0) if m else None


_STOP = {"the", "and", "for", "not", "are", "with", "this", "that", "such", "from", "brief", "input", "stated",
         "specified", "does", "has", "have", "any", "into", "its", "should", "app", "the", "information", "details",
         "requirements", "requirement", "missing", "about", "there"}
_CHECKLIST_ID = re.compile(r"\(([A-Z]{2}-\d+)\)")
MIN_OVERLAP = 0.5


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 2 and w not in _STOP}


def same_thing(a: str, b: str) -> bool:
    """Code check before accepting a model's 'duplicate': different checklist items are never duplicates,
    and the two descriptions must share most of their content words."""
    ia, ib = _CHECKLIST_ID.findall(a), _CHECKLIST_ID.findall(b)
    if ia and ib and set(ia) != set(ib):
        return False
    wa, wb = _words(a), _words(b)
    return bool(wa and wb) and len(wa & wb) / min(len(wa), len(wb)) >= MIN_OVERLAP


def apply(project: Project, result: dict) -> None:
    by_id_all = {g.id: g for g in project.gaps}
    removed: set[str] = set()
    for group in result.get("duplicates", []):
        keep = _gap_id(group.get("keep"))
        if keep not in by_id_all:
            continue
        for raw in group.get("remove", []) or []:
            rid = _gap_id(raw)
            if rid not in by_id_all or rid == keep or rid in removed:
                continue
            gone, kept = by_id_all[rid], by_id_all[keep]
            # Code rules: only merge gaps of the same kind, and never drop a specific compliance check.
            if (gone.source is not kept.source or gone.description.startswith("Compliance check:")
                    or not same_thing(gone.description, kept.description)):
                project.log(f"Reviewer suggested merging {rid} into {keep}; kept both (not the same gap)")
                continue
            removed.add(rid)
            project.log(f"Reviewer merged {rid} into {keep} (duplicate)")
    if removed:
        project.gaps = [g for g in project.gaps if g.id not in removed]
        for q in project.questions:
            if q.related_gap_id in removed:
                q.related_gap_id = None
        for a in project.assumptions:
            if a.related_gap_id in removed:
                a.related_gap_id = None

    by_id = {g.id: g for g in project.gaps}
    for rw in result.get("rewrites", []):
        gap = by_id.get(_gap_id(rw.get("id")))
        if gap and str(rw.get("text", "")).strip():
            gap.description = str(rw["text"]).strip()

    for url in result.get("broken_links", []):
        for gap in project.gaps:
            if gap.evidence_url == url:
                gap.evidence_url = None
        project.log(f"Reviewer: evidence link no longer opens, cleared: {url}")
