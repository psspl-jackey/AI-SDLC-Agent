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
    out += [f"- **{r.id}** {r.text} _(source: {r.source.label()})_" for r in p.active_requirements() if r.kind == "functional"]
    out += ["", "## Non-functional requirements", ""]
    out += [f"- **{r.id}** {r.text} _(source: {r.source.label()})_" for r in p.active_requirements() if r.kind == "nfr"]
    out += ["", "## Assumptions", ""]
    out += [f"- **{a.id}** {a.text}" + (f" (for {a.related_gap_id})" if a.related_gap_id else "") for a in p.assumptions]
    removed = [r for r in p.requirements if not r.active]
    if removed:
        out += ["", "## Removed by change requests", ""]
        out += [f"- ~~**{r.id}** {r.text}~~ (removed by {r.removed_by})" for r in removed]
    if p.change_requests:
        out += ["", "## Change requests", ""]
        for cr in p.change_requests:
            parts = [f"{label} {', '.join(ids)}" for label, ids in
                     (("added", cr.added), ("changed", cr.changed), ("removed", cr.removed)) if ids]
            out.append(f"- **{cr.id}** ({cr.status}): {cr.text} _({'; '.join(parts) or 'no requirement changes'})_")
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


def platform_matrix_markdown(p: Project) -> str:
    from .agents.platform_decision import platform_check

    m = p.platform_matrix
    out = [f"# Platform matrix: {p.name}", ""]
    if m is None:
        return "\n".join(out + ["Stage 2 has not run yet."]) + "\n"
    req = {r.id: r.text for r in p.requirements}
    out += ["| Platform | Included | Source | Reason | Requirements |", "| --- | --- | --- | --- | --- |"]
    for d in m.decisions:
        out.append(f"| {d.platform.replace('_', ' ')} | {'yes' if d.included else 'no'} | {d.source} | "
                   f"{d.reason} | {', '.join(d.requirement_ids)} |")
    out += ["", f"**Delivery approach:** {m.approach.replace('_', ' ')}. {m.approach_reason}", ""]
    unserved = [r for r in p.active_requirements() if r.kind == "functional"
                and not any(r.id in d.requirement_ids for d in m.included())]
    if unserved:
        out += ["## Requirements not served by any included platform", ""]
        out += [f"- **{r.id}** {req[r.id]}" for r in unserved] + [""]
    report = platform_check(p)
    out += ["## Platform check", "", "Passed." if report.passed else "Failed:"]
    out += [f"- {f}" for f in report.failures]
    return "\n".join(out) + "\n"


def _fmt(h: float) -> str:
    return f"{h:.0f}"


def estimate_markdown(p: Project) -> str:
    from .agents import estimator as est

    e = p.estimate
    out = [f"# Estimate: {p.name}", ""]
    if e is None:
        return "\n".join(out + ["Stage 3 has not run yet."]) + "\n"
    base = est.totals(e.base())
    out += [
        f"**Base scope:** {base.tasks} tasks, {_fmt(base.hours_min)}-{_fmt(base.hours_max)} hours "
        f"(likely {_fmt(base.hours_likely)}, expected {_fmt(base.expected)}).  ",
        f"**With {e.risk_buffer_pct:g}% risk buffer:** {_fmt(est.with_buffer(base.expected, e.risk_buffer_pct))} hours.  ",
        "Expected = (min + 4 x likely + max) / 6 per task. Team plan, timeline and cost need a rate card "
        "and are not included yet.", "",
        "## By module", "", "| Module | Tasks | Min | Likely | Max | Expected |", "| --- | --- | --- | --- | --- | --- |",
    ]
    for name, t in est.totals(e.base(), "module").items():
        out.append(f"| {name} | {t.tasks} | {_fmt(t.hours_min)} | {_fmt(t.hours_likely)} | {_fmt(t.hours_max)} | {_fmt(t.expected)} |")
    out += ["", "## By platform", "", "| Platform | Tasks | Expected hours |", "| --- | --- | --- |"]
    for name, t in est.totals(e.base(), "platform").items():
        out.append(f"| {name.replace('_', ' ')} | {t.tasks} | {_fmt(t.expected)} |")
    gaps = {g.id: g.description for g in p.gaps}
    out += ["", "## Recommended additions (optional, not in the base total)", ""]
    adds = est.totals(e.additions(), "gap_id")
    if adds:
        out += ["| Gap | Addition | Tasks | Expected hours |", "| --- | --- | --- | --- |"]
        out += [f"| {gid} | {gaps.get(gid, '')} | {t.tasks} | {_fmt(t.expected)} |" for gid, t in adds.items()]
    else:
        out.append("None.")
    report = est.estimate_check(p)
    out += ["", "## Estimate check", "", "Passed." if report.passed else "Failed:"]
    out += [f"- {f}" for f in report.failures]
    return "\n".join(out) + "\n"


def estimate_xlsx(p: Project) -> bytes:
    """Estimate sheet: every task, plus summaries. Plain workbook until the company template arrives."""
    from openpyxl import Workbook
    from openpyxl.styles import Font

    from .agents import estimator as est

    e = p.estimate
    wb = Workbook()
    ws = wb.active
    ws.title = "Tasks"
    header = ["ID", "Module", "Feature", "Task", "Platform", "Role", "Min h", "Likely h", "Max h",
              "Expected h", "Requirements", "Recommended addition (gap)"]
    ws.append(header)
    for t in (e.tasks if e else []):
        ws.append([t.id, t.module, t.feature, t.title, t.platform, t.role, t.hours_min, t.hours_likely,
                   t.hours_max, round(t.expected, 1), ", ".join(t.requirement_ids), t.gap_id or ""])
    summary = wb.create_sheet("Summary")
    summary.append(["Group", "Name", "Tasks", "Min h", "Likely h", "Max h", "Expected h"])
    if e:
        def row(group: str, name: str, t) -> None:
            summary.append([group, name, t.tasks, round(t.hours_min, 1), round(t.hours_likely, 1),
                            round(t.hours_max, 1), round(t.expected, 1)])
        base = est.totals(e.base())
        row("Total", "Base scope", base)
        summary.append(["Total", f"Base scope with {e.risk_buffer_pct:g}% risk buffer", "", "", "", "",
                        round(est.with_buffer(base.expected, e.risk_buffer_pct), 1)])
        row("Total", "Recommended additions (optional)", est.totals(e.additions()))
        for by, label in (("module", "Module"), ("platform", "Platform"), ("role", "Role")):
            for name, t in est.totals(e.base(), by).items():
                row(label, name, t)
        for gid, t in est.totals(e.additions(), "gap_id").items():
            row("Addition", gid, t)
    for sheet in (ws, summary):
        for cell in sheet[1]:
            cell.font = Font(bold=True)
        sheet.freeze_panes = "A2"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _node(name: str) -> str:
    return "n_" + "".join(ch if ch.isalnum() else "_" for ch in name)


def architecture_markdown(p: Project) -> str:
    """Architecture document and stack decision record, with Mermaid diagrams (render on GitHub)."""
    from .agents.solution_design import GROUP_LABELS, design_check
    from .domain_packs import load_tech_packs

    d = p.design
    out = [f"# Architecture: {p.name}", ""]
    if d is None:
        return "\n".join(out + ["Stage 4 has not run yet."]) + "\n"
    packs = load_tech_packs()
    out += ["## Stack decision record", "", "| Platform | Stack | Reason | Alternatives |", "| --- | --- | --- | --- |"]
    for s in d.stacks:
        title = packs.get(s.pack, {}).get("title", f"{s.pack} (no tech pack)")
        out.append(f"| {s.platform.replace('_', ' ')} | {title} | {s.reason} | {', '.join(s.alternatives)} |")
    if d.decisions:
        out += ["", "## Design decisions", ""]
        for i, dec in enumerate(d.decisions, start=1):
            out.append(f"{i}. **{dec.title}**: {dec.decision}. {dec.reason}"
                       + (f" Alternatives considered: {', '.join(dec.alternatives)}." if dec.alternatives else ""))
    out += ["", "## Components", "", "```mermaid", "flowchart LR"]
    shape = {"client": ("[", "]"), "service": ("(", ")"), "datastore": ("[(", ")]"), "external": ("{{", "}}")}
    for c in d.components:
        o, cl = shape[c.kind]
        out.append(f'    {_node(c.name)}{o}"{c.name}"{cl}')
    out += [f"    {_node(c.name)} --> {_node(u)}" for c in d.components for u in c.uses]
    out += ["```", ""]
    out += [f"- **{c.name}** ({c.kind}): {c.responsibility}" for c in d.components]
    if d.entities:
        out += ["", "## Data model", "", "| Entity | Fields | Requirements |", "| --- | --- | --- |"]
        out += [f"| {e.name} | {', '.join(e.fields)} | {', '.join(e.requirement_ids)} |" for e in d.entities]
    if d.endpoints:
        out += ["", "## API", "", "| Method | Path | Purpose | Requirements |", "| --- | --- | --- | --- |"]
        out += [f"| {e.method} | `{e.path}` | {e.purpose} | {', '.join(e.requirement_ids)} |" for e in d.endpoints]
    groups = list(dict.fromkeys(s.platform for s in d.screens))
    if groups:
        out += ["", "## Screens and flows", ""]
    for g in groups:
        screens = [s for s in d.screens if s.platform == g]
        out += [f"### {GROUP_LABELS.get(g, g).capitalize()}", "", "```mermaid", "flowchart TD"]
        out += [f'    {s.id.replace("-", "_")}["{s.name}"]' for s in screens]
        out += [f'    {s.id.replace("-", "_")} --> {t.replace("-", "_")}' for s in screens for t in s.navigates_to]
        out += ["```", ""]
        out += [f"- **{s.id} {s.name}**: {s.purpose} _({', '.join(s.requirement_ids) or 'no requirement'})_" for s in screens]
        out.append("")
    report = design_check(p)
    out += ["## Design check", "", "Passed." if report.passed else "Failed:"]
    out += [f"- {f}" for f in report.failures]
    return "\n".join(out) + "\n"


def skill_pack_zip(p: Project) -> bytes:
    """Project skill pack as skills/<name>/SKILL.md files (Claude Code skill layout)."""
    import zipfile

    from .agents.skills_setup import skill_markdown

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in (p.skill_pack.files if p.skill_pack else []):
            zf.writestr(f"skills/{f.name}/SKILL.md", skill_markdown(f))
    return buf.getvalue()


def jira_csv(p: Project) -> str:
    """Tickets for the Jira CSV importer. Map the columns on import: Issue Id, Parent Id (epic link),
    Issue Type, Summary, Description, Labels, Original Estimate (seconds), Sprint; "Depends on" lists
    Issue Ids and can be mapped to a "blocks" issue link."""
    plan = p.plan
    if plan is None:
        return ""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["Issue Id", "Parent Id", "Issue Type", "Summary", "Description", "Labels",
                     "Original Estimate", "Sprint", "Depends on"])
    num = {t.id: i for i, t in enumerate(plan.tickets, start=1)}  # Jira wants numeric Issue Ids
    for t in plan.tickets:
        labels = " ".join([t.platform, *t.requirement_ids]).strip() if t.type == "task" else ""
        writer.writerow([
            num[t.id], num[t.epic_id] if t.epic_id else "", "Epic" if t.type == "epic" else "Task",
            t.summary, t.description, labels,
            int(round(t.hours * 3600)) if t.type == "task" else "",
            f"{plan.jira_key} Sprint {t.sprint}" if t.sprint else "",
            " ".join(str(num[d]) for d in t.depends_on),
        ])
    return buf.getvalue()


def plan_markdown(p: Project) -> str:
    from .agents.planner import plan_check

    plan = p.plan
    out = [f"# Internal plan: {p.name}", ""]
    if plan is None:
        return "\n".join(out + ["Stage 6 has not run yet."]) + "\n"
    tasks = plan.tasks()
    out += [f"Jira project: {plan.jira_key}. {len(tasks)} tickets in {plan.sprint_count()} sprint(s) of "
            f"{plan.sprint_weeks} weeks; capacity {plan.sprint_capacity_hours:g} h per sprint.", ""]
    if plan.review:
        out += [f"Tech lead review: {'approved' if plan.review.approved else 'concerns'} "
                f"({plan.review.reviewed_at:%Y-%m-%d}). {plan.review.comment}", ""]
    epics = {t.id: t.summary for t in plan.tickets if t.type == "epic"}
    for sprint in range(1, plan.sprint_count() + 1):
        in_sprint = [t for t in tasks if t.sprint == sprint]
        out += [f"## Sprint {sprint} ({sum(t.hours for t in in_sprint):.0f} h)", "",
                "| Ticket | Epic | Summary | Hours | Requirements | Depends on |", "| --- | --- | --- | --- | --- | --- |"]
        out += [f"| {t.id} | {epics.get(t.epic_id, '')} | {t.summary} | {t.hours:g} | {', '.join(t.requirement_ids)} | "
                f"{', '.join(t.depends_on)} |" for t in in_sprint]
        out.append("")
    report = plan_check(p)
    out += ["## Validation report", "", "Passed." if report.passed else "Failed:"]
    out += [f"- {f}" for f in report.failures]
    return "\n".join(out) + "\n"
