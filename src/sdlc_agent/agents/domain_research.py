"""Domain and market research agent.

1. Compare the brief against the matching domain pack (domain checklist gaps, compliance prompts).
2. Read competitor or reference apps from public pages, extract their features and user complaints.
3. Bucket missing features: table stakes vs differentiator is decided by code from how many
   competitors have the feature, not by the model.

Competitors come from the intake answers and the brief's references. Automatic competitor discovery
through web search plugs in via SearchProvider once a search option is chosen.
"""
from __future__ import annotations

import math
from datetime import date
from typing import Callable, Protocol

from ..domain_packs import load_packs, match_pack
from ..llm.base import LLMClient
from ..llm.json_call import Dicts, complete_json
from ..state.models import Chunk, Project

CHECKLIST_SHAPE = {"items": Dicts({"id": "str", "status": "str", "covered_by": "str", "reason": "str"})}
COMPETITOR_SHAPE = {"name": "str", "features": "strs", "complaints": "strs"}
GAP_SHAPE = {"missing": Dicts({"feature": "str", "competitor_ids": "strs"})}

NAME = "domain_research"

INDIA_HINTS = (
    "india", "gujarat", "ahmedabad", "maharashtra", "mumbai", "pune", "karnataka", "bengaluru",
    "bangalore", "delhi", "tamil nadu", "chennai", "telangana", "hyderabad", "rajasthan", "kerala",
    "west bengal", "kolkata", "uttar pradesh", "punjab", "madhya pradesh",
)


class SearchProvider(Protocol):
    def find_competitors(self, domain: str, region: str, limit: int = 5) -> list[str]: ...


class NoSearch:
    """Default: no automatic discovery. Competitors must come from intake or references."""

    def find_competitors(self, domain: str, region: str, limit: int = 5) -> list[str]:
        return []


def _region_matches(pack_region: str, brief_region: str) -> bool:
    p, b = pack_region.lower(), (brief_region or "").lower()
    if not b:
        return False
    if p == "india":
        return any(h in b for h in INDIA_HINTS)
    return p in b


CHECKLIST_SYSTEM = """You compare a project's planned features with a standard feature checklist for its domain.
An item is "covered" ONLY when one planned feature clearly states it; cite that feature's id (F1, F2...).
A feature that is merely implied, likely, or "part of the nature of the app" is NOT covered: mark it
"missing". Mark "not_relevant" only when the item cannot apply to this kind of product at all, and say why.
When unsure, choose "missing"; a human reviews every missing item."""

COMPETITOR_SYSTEM = """You read a public web page of an app or website and list what it offers.
Extract product features a user can see or use (short noun phrases), and any user complaints
visible on the page (for example from reviews). Do not invent anything that is not on the page."""

GAP_SYSTEM = """You compare a project's planned features with features found in competitor apps.
Group the competitor features that mean the same thing, and list only those the project does NOT
already plan. For each, list the competitor ids that have it. Ignore payment-provider specifics and
third-party integrations; those are out of scope for now."""


def _brief_features(project: Project) -> list[str]:
    return [f.text for f in project.brief.features] if project.brief else []


def run(
    llm: LLMClient,
    project: Project,
    *,
    search: SearchProvider | None = None,
    read_url: Callable[[str], list[Chunk]] | None = None,
    today: date | None = None,
) -> dict:
    from ..intake.readers import read_url as default_read_url

    read_url = read_url or default_read_url
    search = search or NoSearch()
    today = today or date.today()
    brief = project.brief
    result: dict = {
        "pack": None, "checklist": [], "compliance": [], "competitors": [], "competitor_gaps": [],
        "complaints": [], "notes": [], "questions": [],
    }

    # 1. Domain pack comparison
    matched = match_pack(brief.domain if brief else "", load_packs())
    if matched:
        pack_name, pack = matched
        result["pack"] = pack_name
        items = "\n".join(f"{f['id']}: {f['name']}" for f in pack.get("features", []))
        planned = {f"F{i}": text for i, text in enumerate(_brief_features(project), start=1)}
        prompt = (
            f"Project goal: {brief.goal}\nPlanned features:\n"
            + ("\n".join(f"{k}: {v}" for k, v in planned.items()) or "(none)")
            + f"\n\nChecklist:\n{items}\n\n"
            'Return JSON: {"items": [{"id": str, "status": "covered" | "missing" | "not_relevant", '
            '"covered_by": str, "reason": str}]}  (covered_by: the planned feature id, or "" if not covered)'
        )
        data = complete_json(llm, CHECKLIST_SYSTEM, prompt, CHECKLIST_SHAPE)
        answers = {item.get("id"): item for item in data.get("items", [])}
        for feat in pack.get("features", []):
            item = answers.get(feat["id"], {})
            status, cited = item.get("status", ""), item.get("covered_by", "").strip()
            table_stakes = feat.get("tier", "common") == "table_stakes"
            # Code decides: covered needs a real planned feature cited; table stakes are never "not relevant".
            if status == "covered" and cited in planned:
                continue
            if status == "not_relevant" and not table_stakes:
                continue
            if status == "covered":
                result["notes"].append(f"Checklist: {feat['id']} claimed covered without citing a planned feature; "
                                       "treated as missing")
            elif status == "not_relevant":
                result["notes"].append(f"Checklist: {feat['id']} is table stakes; 'not relevant' needs a human "
                                       f"decision at Gate 1 ({item.get('reason', '')})")
            elif feat["id"] not in answers:
                result["notes"].append(f"Checklist: no answer for {feat['id']}; treated as missing")
            result["checklist"].append({"id": feat["id"], "name": feat["name"], "tier": feat.get("tier", "common")})
        for c in pack.get("compliance", []) or []:
            if _region_matches(c.get("region", ""), brief.region if brief else ""):
                result["compliance"].append(c["note"])
    else:
        result["notes"].append(
            f"No domain pack matches '{brief.domain if brief else ''}'. Add one under domain_packs/ to enable checklist gaps."
        )

    # 2. Competitors: from intake answers and brief references, then optional search
    refs = list(dict.fromkeys(brief.references if brief else []))
    urls = [r for r in refs if r.startswith(("http://", "https://"))]
    names_without_link = [r for r in refs if r not in urls]
    if not urls:
        urls = search.find_competitors(brief.domain if brief else "", brief.region if brief else "")
    if names_without_link:
        result["questions"].append(
            "Please add a public link for these competitors so they can be compared: " + ", ".join(names_without_link)
        )
    if not urls:
        result["questions"].append(
            "No competitor links were given and automatic search is not set up yet. "
            "Which 3 to 5 apps or websites should we compare against?"
        )

    for idx, url in enumerate(urls[:5], start=1):
        try:
            chunks = read_url(url)
        except Exception as exc:  # network errors, blocked pages
            result["notes"].append(f"Could not read competitor page {url}: {exc}")
            continue
        page = "\n".join(c.text for c in chunks)[:15000]
        data = complete_json(llm, COMPETITOR_SYSTEM,
            f"Page URL: {url}\n\n{page}\n\nReturn JSON: "
            '{"name": str, "features": [str], "complaints": [str]}', COMPETITOR_SHAPE)
        comp = {
            "id": f"C{idx}", "name": data.get("name") or url, "url": url,
            "features": [str(f) for f in data.get("features", []) or []][:60],
            "researched_on": today.isoformat(),
        }
        result["competitors"].append(comp)
        for complaint in data.get("complaints", []) or []:
            result["complaints"].append({"text": str(complaint), "url": url, "researched_on": today.isoformat()})

    # 3. Competitor features missing from the brief; bucket decided by code
    if result["competitors"]:
        listing = "\n".join(
            f"{c['id']} ({c['name']}): " + "; ".join(c["features"]) for c in result["competitors"]
        )
        data = complete_json(llm, GAP_SYSTEM,
            "Planned features:\n- " + "\n- ".join(_brief_features(project) or ["(none)"])
            + f"\n\nCompetitor features:\n{listing}\n\n"
            'Return JSON: {"missing": [{"feature": str, "competitor_ids": [str]}]}', GAP_SHAPE)
        by_id = {c["id"]: c for c in result["competitors"]}
        n = len(result["competitors"])
        threshold = max(2, math.ceil(n * 0.6))
        for m in data.get("missing", []) or []:
            ids = [i for i in m.get("competitor_ids", []) or [] if i in by_id]
            if not ids or not m.get("feature"):
                continue
            result["competitor_gaps"].append({
                "feature": str(m["feature"]),
                "bucket": "table_stakes" if len(ids) >= threshold else "differentiator",
                "competitors": [by_id[i]["name"] for i in ids],
                "evidence_url": by_id[ids[0]]["url"],
                "researched_on": by_id[ids[0]]["researched_on"],
            })
    return result


def apply(project: Project, result: dict) -> None:
    from ..gaps.register import add_gap
    from ..questions.queue import ask
    from ..state.models import Bucket, GapSource, GapStatus

    project.domain_pack = result.get("pack")
    project.competitors = result.get("competitors", [])

    for item in result.get("checklist", []):
        table_stakes = item["tier"] == "table_stakes"
        add_gap(
            project,
            source=GapSource.DOMAIN_CHECKLIST,
            description=f"{item['name']} ({item['id']}) is not in the brief",
            found_by=NAME,
            bucket=Bucket.TABLE_STAKES if table_stakes else Bucket.DIFFERENTIATOR,
            status=GapStatus.RECOMMENDED,
        )

    for note in result.get("compliance", []):
        gap = add_gap(project, source=GapSource.NFR, description=f"Compliance check: {note}", found_by=NAME)
        ask(project, f"Does the product need to comply with: {note}?", blocking=False,
            assumed_answer="Yes; design data handling to comply.", related_gap_id=gap.id)

    for g in result.get("competitor_gaps", []):
        table_stakes = g["bucket"] == "table_stakes"
        add_gap(
            project,
            source=GapSource.COMPETITOR_TABLE_STAKES if table_stakes else GapSource.COMPETITOR_DIFFERENTIATOR,
            description=f"{g['feature']} (seen in {', '.join(g['competitors'])})",
            found_by=NAME,
            evidence_url=g["evidence_url"],
            research_date=date.fromisoformat(g["researched_on"]),
            bucket=Bucket.TABLE_STAKES if table_stakes else Bucket.DIFFERENTIATOR,
            status=GapStatus.RECOMMENDED,
        )

    for c in result.get("complaints", []):
        add_gap(
            project,
            source=GapSource.REVIEW_MINED,
            description=f"Opportunity from competitor complaints: {c['text']}",
            found_by=NAME,
            evidence_url=c["url"],
            research_date=date.fromisoformat(c["researched_on"]),
            bucket=Bucket.DIFFERENTIATOR,
            status=GapStatus.RECOMMENDED,
        )

    for q in result.get("questions", []):
        ask(project, q, blocking=False)
    for note in result.get("notes", []):
        project.log(note)
