"""Stage 1 deliverables as files: requirements doc, gap register, competitor matrix, client questions.

Plain Markdown and CSV for the demo; the document agent will render these in Prakash Infotech
templates in Phase 2.
"""
from __future__ import annotations

import csv
import io

from .gaps.register import coverage_check
from .state.models import Project


def requirements_markdown(p: Project) -> str:
    b = p.brief
    out = [f"# Requirements: {p.name}", ""]
    if b:
        out += [
            f"**Goal:** {b.goal}", f"**Domain:** {b.domain or 'unknown'}  ",
            f"**Region:** {b.region or 'unknown'}  ", f"**Intent:** {b.intent}  ",
            f"**Platforms:** {', '.join(b.platforms) or 'not decided'}  ",
            f"**Input completeness:** {b.completeness.value}", "",
        ]
    out += ["## Functional requirements", ""]
    out += [f"- **{r.id}** {r.text} _(source: {r.source.label()})_" for r in p.requirements if r.kind == "functional"]
    out += ["", "## Non-functional requirements", ""]
    out += [f"- **{r.id}** {r.text} _(source: {r.source.label()})_" for r in p.requirements if r.kind == "nfr"]
    out += ["", "## Assumptions", ""]
    out += [f"- **{a.id}** {a.text}" + (f" (for {a.related_gap_id})" if a.related_gap_id else "") for a in p.assumptions]
    rec = [g for g in p.gaps if g.status and g.status.value == "recommended"]
    out += ["", "## Recommended additions (optional, estimated separately)", ""]
    out += [f"- **{g.id}** {g.description}" for g in rec]
    report = coverage_check(p)
    out += ["", "## Coverage check", "", "Passed." if report.passed else "Failed:"]
    out += [f"- {f}" for f in report.failures]
    return "\n".join(out) + "\n"


def _csv(rows: list[dict]) -> str:
    if not rows:
        return ""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue()


def gap_rows(p: Project) -> list[dict]:
    return [{
        "id": g.id, "source": g.source.value, "description": g.description, "bucket": g.bucket.value,
        "status": g.status.value if g.status else "", "assumption": g.assumption_id or "",
        "evidence_url": g.evidence_url or "", "research_date": g.research_date.isoformat() if g.research_date else "", "found_by": g.found_by,
    } for g in p.gaps]


def gaps_csv(p: Project) -> str:
    return _csv(gap_rows(p))


def competitors_csv(p: Project) -> str:
    return _csv([
        {"competitor": c["name"], "url": c["url"], "researched_on": c["researched_on"], "feature": f}
        for c in p.competitors for f in c["features"]
    ])


def questions_markdown(p: Project) -> str:
    out = [f"# Questions for the client: {p.name}", ""]
    for q in p.questions:
        status = f"Answered: {q.answer}" if q.answer else f"We assumed: {q.assumed_answer or 'n/a'}"
        out.append(f"- **{q.id}**{' (blocking)' if q.blocking else ''} {q.text}  \n  {status}")
    return "\n".join(out) + "\n"
