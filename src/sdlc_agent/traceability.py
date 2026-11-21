"""Traceability matrix: every requirement traced from its source to the code that delivers it.

Pure code, no model. One row per requirement (removed ones included, marked), following the chain:

    source and input lines -> gaps -> platforms -> estimate tasks -> design (screens, API, data)
    -> tickets (Jira key, sprint) -> build (branch, pull request, test files, status)

Each row also lists where the chain breaks for the stages that have run, so the matrix doubles as a
check at every gate and as the Stage 9 proof that every input line was delivered or accounted for.
"""
from __future__ import annotations

import io
from dataclasses import dataclass, field

from .state.models import Project, Requirement, Stage, StageStatus

STATUS_ORDER = ("delivered", "in review", "in build", "planned", "estimated", "designed", "approved", "removed")


@dataclass
class TraceRow:
    requirement_id: str
    kind: str
    text: str
    source: str
    input_lines: list[str] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    change_requests: list[str] = field(default_factory=list)
    platforms: list[str] = field(default_factory=list)
    tasks: list[str] = field(default_factory=list)
    hours: float = 0.0
    screens: list[str] = field(default_factory=list)
    endpoints: list[str] = field(default_factory=list)
    entities: list[str] = field(default_factory=list)
    tickets: list[str] = field(default_factory=list)
    sprints: list[int] = field(default_factory=list)
    pull_requests: list[str] = field(default_factory=list)
    test_files: list[str] = field(default_factory=list)
    status: str = "approved"
    breaks: list[str] = field(default_factory=list)


def _ran(project: Project, stage: Stage) -> bool:
    return project.stage_status[stage] not in (StageStatus.PENDING, StageStatus.RUNNING, StageStatus.FAILED)


def _row(project: Project, r: Requirement) -> TraceRow:
    from .agents.developer import is_test_file
    from .orchestrator.build import latest

    row = TraceRow(requirement_id=r.id, kind=r.kind, text=r.text, source=r.source.label(),
                   input_lines=list(r.sow_line_ids),
                   gaps=[g.id for g in project.gaps if g.linked_requirement_id == r.id],
                   change_requests=list(dict.fromkeys(r.changed_by + ([r.removed_by] if r.removed_by else []))))
    if not r.active:
        row.status = "removed"
        return row
    m, e, d, plan = project.platform_matrix, project.estimate, project.design, project.plan
    if m:
        row.platforms = [x.platform for x in m.included() if r.id in x.requirement_ids]
    if e:
        tasks = [t for t in e.base() if r.id in t.requirement_ids]
        row.tasks = [t.id for t in tasks]
        row.hours = round(sum(t.expected for t in tasks), 1)
    if d:
        row.screens = [s.id for s in d.screens if r.id in s.requirement_ids]
        row.endpoints = [f"{x.method} {x.path}" for x in d.endpoints if r.id in x.requirement_ids]
        row.entities = [x.name for x in d.entities if r.id in x.requirement_ids]
    tickets = [t for t in plan.tasks() if r.id in t.requirement_ids] if plan else []
    row.tickets = [t.key for t in tickets]
    row.sprints = sorted({t.sprint for t in tickets if t.sprint})
    builds = [b for t in tickets if (b := latest(project, t.id))]
    row.pull_requests = [b.pr_url for b in builds if b.pr_url]
    row.test_files = sorted({f for b in builds if b.status in ("pr_open", "merged") for f in b.files if is_test_file(f)})

    if tickets and builds and len(builds) == len(tickets) and all(b.status == "merged" for b in builds):
        row.status = "delivered"
    elif any(b.status == "pr_open" for b in builds):
        row.status = "in review"
    elif builds:
        row.status = "in build"
    elif tickets:
        row.status = "planned"
    elif row.tasks:
        row.status = "estimated"
    elif row.screens or row.endpoints:
        row.status = "designed"

    functional = r.kind == "functional"
    if not r.sow_line_ids and r.source.kind not in ("client_decision", "inferred"):
        row.breaks.append("no input line")
    if functional and _ran(project, Stage.PLATFORM) and not row.platforms:
        row.breaks.append("no platform")
    if functional and _ran(project, Stage.PROPOSAL) and not row.tasks:
        row.breaks.append("not estimated")
    if functional and _ran(project, Stage.DESIGN) and not (row.screens or row.endpoints):
        row.breaks.append("not in the design")
    if functional and _ran(project, Stage.PLAN) and not row.tickets:
        row.breaks.append("no ticket")
    return row


def matrix(project: Project) -> list[TraceRow]:
    return [_row(project, r) for r in project.requirements]


def unaccounted_lines(project: Project) -> list[str]:
    """Input lines that map to no requirement and are not marked as not a requirement."""
    return [line.id for line in project.sow_lines if not line.requirement_ids and not line.not_a_requirement]


def summary(project: Project) -> dict[str, int]:
    rows = [x for x in matrix(project) if x.status != "removed"]
    counts = {s: sum(1 for x in rows if x.status == s) for s in STATUS_ORDER if s != "removed"}
    counts["breaks"] = sum(1 for x in rows if x.breaks)
    counts["unaccounted_lines"] = len(unaccounted_lines(project))
    return counts


COLUMNS = [
    ("Requirement", "requirement_id"), ("Type", "kind"), ("Text", "text"), ("Source", "source"),
    ("Input lines", "input_lines"), ("Gaps", "gaps"), ("Change requests", "change_requests"),
    ("Platforms", "platforms"), ("Estimate tasks", "tasks"), ("Expected h", "hours"), ("Screens", "screens"),
    ("API", "endpoints"), ("Data", "entities"), ("Tickets", "tickets"), ("Sprints", "sprints"),
    ("Pull requests", "pull_requests"), ("Test files", "test_files"), ("Status", "status"), ("Breaks", "breaks"),
]


def _cell(value) -> str | float:
    if isinstance(value, list):
        return ", ".join(str(v) for v in value)
    return value


def rows_for_table(project: Project) -> list[dict]:
    return [{label: _cell(getattr(x, attr)) for label, attr in COLUMNS} for x in matrix(project)]


def xlsx(project: Project) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill

    wb = Workbook()
    ws = wb.active
    ws.title = "Traceability"
    ws.append([label for label, _ in COLUMNS])
    warn = PatternFill("solid", fgColor="FFF2CC")
    for x in matrix(project):
        ws.append([_cell(getattr(x, attr)) for _, attr in COLUMNS])
        if x.breaks:
            for cell in ws[ws.max_row]:
                cell.fill = warn
    for cell in ws[1]:
        cell.font = Font(bold=True)
    ws.freeze_panes = "B2"
    lines = wb.create_sheet("Input lines")
    lines.append(["Line", "Text", "Source", "Requirements", "Not a requirement"])
    for line in project.sow_lines:
        lines.append([line.id, line.text, line.source.label(), ", ".join(line.requirement_ids),
                      "yes" if line.not_a_requirement else ""])
    for cell in lines[1]:
        cell.font = Font(bold=True)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def markdown(project: Project) -> str:
    s = summary(project)
    out = [f"# Traceability matrix: {project.name}", "",
           "Status counts: " + ", ".join(f"{k} {v}" for k, v in s.items() if k not in ("breaks", "unaccounted_lines")),
           f"Requirements with a break in the chain: {s['breaks']}. Input lines not accounted for: {s['unaccounted_lines']}.",
           "", "| Requirement | Status | Platforms | Tasks | Screens / API | Tickets | Pull requests | Breaks |",
           "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for x in matrix(project):
        out.append(f"| {x.requirement_id} {x.text[:60]} | {x.status} | {', '.join(x.platforms)} | {', '.join(x.tasks)} | "
                   f"{', '.join(x.screens + x.endpoints)} | {', '.join(x.tickets)} | {', '.join(x.pull_requests)} | "
                   f"{', '.join(x.breaks)} |")
    return "\n".join(out) + "\n"
