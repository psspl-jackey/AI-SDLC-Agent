"""Reviewer agent: checks the gap register before it reaches the humans at Gate 1.

- Model: finds duplicate gaps and rewrites unclear ones.
- Code: checks that every evidence link still opens. A broken link is cleared, so the
  coverage check fails until someone fixes it rather than passing on a dead source.
"""
from __future__ import annotations

from typing import Callable

import httpx

from ..llm.base import LLMClient, parse_json
from ..state.models import Project

NAME = "reviewer"

SYSTEM = """You review a gap register for a software project before human approval.
Find gaps that describe the same thing (duplicates) and gaps whose wording is unclear.
Keep the earliest id of each duplicate group. Rewrite unclear gaps in one plain sentence without
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
        data = parse_json(llm.complete(
            SYSTEM,
            f"Gap register:\n{listing}\n\nReturn JSON: "
            '{"duplicates": [{"keep": str, "remove": [str]}], "rewrites": [{"id": str, "text": str}]}',
            json_mode=True,
        ).text)
        result["duplicates"] = data.get("duplicates", []) or []
        result["rewrites"] = data.get("rewrites", []) or []
    for url in sorted({g.evidence_url for g in project.gaps if g.evidence_url}):
        if not check_link(url):
            result["broken_links"].append(url)
    return result


def apply(project: Project, result: dict) -> None:
    ids = {g.id for g in project.gaps}
    removed: set[str] = set()
    for group in result.get("duplicates", []):
        keep = group.get("keep")
        if keep not in ids:
            continue
        for rid in group.get("remove", []) or []:
            if rid in ids and rid != keep and rid not in removed:
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
        gap = by_id.get(rw.get("id"))
        if gap and str(rw.get("text", "")).strip():
            gap.description = str(rw["text"]).strip()

    for url in result.get("broken_links", []):
        for gap in project.gaps:
            if gap.evidence_url == url:
                gap.evidence_url = None
        project.log(f"Reviewer: evidence link no longer opens, cleared: {url}")
