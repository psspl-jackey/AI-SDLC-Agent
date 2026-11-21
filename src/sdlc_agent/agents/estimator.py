"""Stage 3: estimator. Breaks the approved scope into modules, features and tasks with
min-likely-max hours.

The model proposes tasks in small calls (one per included platform, one for cross-cutting work,
one for recommended additions) so local models are not asked for everything at once.
Code does the rest:
- hours are validated (positive, min <= likely <= max); bad rows are fixed or dropped and logged;
- tasks on a platform that is not in the matrix are dropped and logged;
- totals, the PERT expected value and the risk buffer are computed here, never by the model;
- recommended additions (market gaps) are estimated separately and never enter the base total.

There is no estimation history yet: ranges are reviewed by the approvers at Gate 2, and actual
effort should be recorded on every project so later estimates can be calibrated.
Team plan, timeline and cost need a rate card and are not produced yet.

run() is pure and returns a result dict; apply() is the only writer.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from ..llm.base import LLMClient, parse_json
from ..state.models import Estimate, EstimateTask, GapStatus, Project
from ..state.store import next_id

NAME = "estimator"
COMMON = "common"

SYSTEM = """You are a senior estimator at a software delivery company. You break approved
requirements into modules, features and development tasks, and estimate each task in hours as a
range: minimum (everything goes well), likely, and maximum (realistic trouble). Tasks are small
enough for one person to finish in 2 to 40 hours. Include the work a team really does: UI, API,
data model, validation, error states, unit tests. Payment uses a dummy gateway with static
responses; real payment and third-party integrations are out of scope. Never estimate features
that are not in the list you are given."""

TASK_SCHEMA = """Return JSON:
{"tasks": [{"module": str, "feature": str, "title": str, "role": str,
            "hours_min": number, "hours_likely": number, "hours_max": number,
            "requirement_ids": [str]%s}]}"""

COMMON_ASK = """List the cross-cutting work this project needs that is not tied to one feature:
project setup and architecture, UX and UI design, CI/CD, test planning and QA, deployment,
app store or web release, project management. Use module "Cross-cutting"."""

ADDITIONS_ASK = """These are recommended additions: features the client did not ask for, offered
as optional extras. Estimate each one separately so the client can opt in. Every task must carry the
gap_id of the addition it belongs to, and must be on one of these platforms: %s."""


def _project_context(project: Project) -> str:
    b = project.brief
    m = project.platform_matrix
    return (
        f"Goal: {b.goal if b else ''}\nDomain: {b.domain if b else ''}\n"
        f"Platforms: {', '.join(d.platform for d in m.included()) if m else ''}\n"
        f"Delivery approach: {m.approach if m else ''}\n"
    )


def run(llm: LLMClient, project: Project) -> dict:
    m = project.platform_matrix
    reqs = {r.id: r for r in project.requirements}
    nfrs = "\n".join(f"{r.id}: {r.text}" for r in project.requirements if r.kind == "nfr") or "(none)"
    result: dict = {"platform_tasks": {}, "common_tasks": [], "addition_tasks": []}
    ctx = _project_context(project)

    for d in m.included():
        served = [reqs[i] for i in d.requirement_ids if i in reqs]
        if not served:
            continue
        listing = "\n".join(f"{r.id}: {r.text}" for r in served)
        data = parse_json(llm.complete(
            SYSTEM,
            f"{ctx}\nEstimate the {d.platform.replace('_', ' ')} work for these requirements:\n{listing}\n\n"
            f"Non-functional requirements to respect:\n{nfrs}\n\n" + TASK_SCHEMA % "",
            json_mode=True,
        ).text)
        result["platform_tasks"][d.platform] = data.get("tasks", []) or []

    data = parse_json(llm.complete(
        SYSTEM,
        f"{ctx}\nRequirements:\n" + "\n".join(f"{r.id}: {r.text}" for r in project.requirements)
        + f"\n\n{COMMON_ASK}\n\n" + TASK_SCHEMA % "",
        json_mode=True,
    ).text)
    result["common_tasks"] = data.get("tasks", []) or []

    additions = [g for g in project.gaps if g.status is GapStatus.RECOMMENDED]
    if additions:
        platforms = ", ".join(d.platform for d in m.included())
        listing = "\n".join(f"{g.id}: {g.description}" for g in additions)
        data = parse_json(llm.complete(
            SYSTEM,
            f"{ctx}\n{ADDITIONS_ASK % platforms}\n\nRecommended additions:\n{listing}\n\n"
            + TASK_SCHEMA % ', "gap_id": str, "platform": str',
            json_mode=True,
        ).text)
        result["addition_tasks"] = data.get("tasks", []) or []
    return result


def _hours(item: dict) -> tuple[float, float, float] | None:
    try:
        values = [float(item.get(k)) for k in ("hours_min", "hours_likely", "hours_max")]
    except (TypeError, ValueError):
        return None
    if any(v <= 0 for v in values):
        return None
    lo, mid, hi = sorted(values)
    return lo, mid, hi


def build_estimate(project: Project, result: dict, risk_buffer_pct: float) -> tuple[Estimate, list[str]]:
    notes: list[str] = []
    req_ids = {r.id for r in project.requirements}
    included = {d.platform for d in project.platform_matrix.included()}
    additions = {g.id for g in project.gaps if g.status is GapStatus.RECOMMENDED}
    tasks: list[EstimateTask] = []

    def add(item: dict, platform: str, gap_id: str | None = None) -> None:
        title = str(item.get("title", "")).strip()
        if not title:
            return
        hours = _hours(item)
        if hours is None:
            notes.append(f"Estimator: dropped \"{title}\" ({platform}): hours missing or not positive")
            return
        if [float(item[k]) for k in ("hours_min", "hours_likely", "hours_max")] != list(hours):
            notes.append(f"Estimator: reordered hours for \"{title}\" so min <= likely <= max")
        tasks.append(EstimateTask(
            id=next_id("TASK", (t.id for t in tasks)),
            module=str(item.get("module") or "General").strip(),
            feature=str(item.get("feature") or title).strip(),
            title=title,
            platform=platform,
            role=str(item.get("role", "")).strip(),
            hours_min=hours[0], hours_likely=hours[1], hours_max=hours[2],
            requirement_ids=[i for i in item.get("requirement_ids", []) or [] if i in req_ids],
            gap_id=gap_id,
        ))

    for platform, items in (result.get("platform_tasks") or {}).items():
        if platform not in included:
            notes.append(f"Estimator: dropped {len(items)} task(s) for {platform}, which is not an included platform")
            continue
        for item in items:
            add(item, platform)
    for item in result.get("common_tasks", []) or []:
        add(item, COMMON)
    for item in result.get("addition_tasks", []) or []:
        gap_id, platform = item.get("gap_id"), str(item.get("platform", "")).strip().lower()
        if gap_id not in additions:
            notes.append(f"Estimator: dropped addition task \"{item.get('title', '')}\": unknown gap id {gap_id}")
            continue
        if platform not in included:
            notes.append(f"Estimator: dropped addition task \"{item.get('title', '')}\": platform "
                         f"{platform or 'missing'} is not included")
            continue
        add(item, platform, gap_id=gap_id)
    return Estimate(tasks=tasks, risk_buffer_pct=risk_buffer_pct), notes


def apply(project: Project, result: dict, risk_buffer_pct: float = 15.0) -> None:
    estimate, notes = build_estimate(project, result, risk_buffer_pct)
    project.estimate = estimate
    for note in notes:
        project.log(note)


# ---------- totals and the code check (reviewed at Gate 2) ----------


@dataclass
class Totals:
    hours_min: float = 0.0
    hours_likely: float = 0.0
    hours_max: float = 0.0
    expected: float = 0.0
    tasks: int = 0

    def add(self, t: EstimateTask) -> None:
        self.hours_min += t.hours_min
        self.hours_likely += t.hours_likely
        self.hours_max += t.hours_max
        self.expected += t.expected
        self.tasks += 1


def totals(tasks: list[EstimateTask], by: str | None = None) -> dict[str, Totals] | Totals:
    """Sum tasks, or group them by an attribute (module, platform, role, gap_id)."""
    if by is None:
        total = Totals()
        for t in tasks:
            total.add(t)
        return total
    groups: dict[str, Totals] = defaultdict(Totals)
    for t in tasks:
        groups[str(getattr(t, by) or "")].add(t)
    return dict(groups)


def with_buffer(hours: float, pct: float) -> float:
    return hours * (1 + pct / 100)


@dataclass
class EstimateReport:
    passed: bool
    failures: list[str] = field(default_factory=list)


def estimate_check(project: Project) -> EstimateReport:
    e = project.estimate
    if e is None:
        return EstimateReport(False, ["Stage 3 has not run: no estimate"])
    failures: list[str] = []
    if not e.base():
        failures.append("The estimate has no tasks")
    covered = {rid for t in e.base() for rid in t.requirement_ids}
    failures += [f"{r.id} has no estimated task: \"{r.text[:80]}\""
                 for r in project.requirements if r.kind == "functional" and r.id not in covered]
    estimated = {t.gap_id for t in e.additions()}
    failures += [f"Recommended addition {g.id} is not estimated: \"{g.description[:80]}\""
                 for g in project.gaps if g.status is GapStatus.RECOMMENDED and g.id not in estimated]
    failures += [f"{t.id} has invalid hours" for t in e.tasks
                 if not (0 < t.hours_min <= t.hours_likely <= t.hours_max)]
    return EstimateReport(passed=not failures, failures=failures)
