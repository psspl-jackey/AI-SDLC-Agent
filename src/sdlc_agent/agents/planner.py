"""Stage 6: internal plan. Tickets, dependencies, sprints, and the validation report.

- Tickets are code: one epic per estimate module, one task ticket per base estimate task, each with
  its requirement ids, platform, estimate and the skills to follow, so Stage 7 can work from tickets.
- Dependencies are the model's proposal: code drops unknown and self links and breaks cycles.
- Sprints are code: a greedy schedule in dependency order that never puts a ticket in an earlier
  sprint than anything it depends on, and fills each sprint up to the team's capacity.
- The validation report is code: every requirement maps to a ticket, every base task has a ticket,
  no cycles, dependency order respected.

Tickets export as a CSV for the Jira importer; Jira assigns the real keys on import.
run() is pure and returns a result dict; apply() is the only writer.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..llm.base import LLMClient
from ..llm.json_call import Dicts, complete_json
from ..state.models import Plan, Project, Ticket

NAME = "planner"

SYSTEM = """You are the delivery planner of a software company. Given the project's tasks, decide
which tasks must be finished before another can start (real technical dependencies only: an API
before the screen that calls it, project setup before feature work, a data model before the
endpoints that use it). Do not add dependencies just to order the work."""
SHAPE = {"dependencies": Dicts({"task": "str", "depends_on": "strs"})}
SCHEMA = 'Return JSON: {"dependencies": [{"task": str, "depends_on": [str]}]}'


def run(llm: LLMClient, project: Project) -> dict:
    tasks = project.estimate.base()
    listing = "\n".join(f"{t.id} [{t.platform}] {t.module} / {t.title}" for t in tasks)
    return complete_json(llm, SYSTEM, f"Tasks:\n{listing}\n\n{SCHEMA}", SHAPE)


def _break_cycles(tickets: dict[str, Ticket], notes: list[str]) -> None:
    """Depth-first search; an edge back to a ticket on the current path closes a cycle and is dropped."""
    state: dict[str, int] = {}  # 1 = on path, 2 = done

    def visit(tid: str) -> None:
        state[tid] = 1
        for dep in list(tickets[tid].depends_on):
            if state.get(dep) == 1:
                tickets[tid].depends_on.remove(dep)
                notes.append(f"Planner: dropped dependency {tid} -> {dep}; it closed a cycle")
            elif state.get(dep) is None:
                visit(dep)
        state[tid] = 2

    for tid in tickets:
        if tid not in state:
            visit(tid)


def schedule(tasks: list[Ticket], capacity: float, notes: list[str]) -> None:
    """Assign sprints in dependency order. A ticket goes in the earliest sprint that is not before any of
    its dependencies' sprints and still has capacity; a ticket bigger than a sprint gets a sprint of its own."""
    by_id = {t.id: t for t in tasks}
    remaining = {t.id: len(t.depends_on) for t in tasks}
    dependents: dict[str, list[str]] = {t.id: [] for t in tasks}
    for t in tasks:
        for d in t.depends_on:
            dependents[d].append(t.id)
    ready = [t.id for t in tasks if remaining[t.id] == 0]  # keeps input order: cross-cutting first
    load: dict[int, float] = {}
    while ready:
        tid = ready.pop(0)
        t = by_id[tid]
        sprint = max((by_id[d].sprint for d in t.depends_on), default=1)
        if t.hours > capacity:
            notes.append(f"Planner: {t.id} ({t.hours:.0f} h) is bigger than one sprint ({capacity:.0f} h); "
                         "split it before the sprint starts")
            while load.get(sprint, 0) > 0:
                sprint += 1
        else:
            while load.get(sprint, 0) + t.hours > capacity:
                sprint += 1
        t.sprint = sprint
        load[sprint] = load.get(sprint, 0) + t.hours
        for nxt in dependents[tid]:
            remaining[nxt] -= 1
            if remaining[nxt] == 0:
                ready.append(nxt)


def build_plan(project: Project, result: dict, jira_key: str, sprint_weeks: int,
               capacity: float) -> tuple[Plan, list[str]]:
    notes: list[str] = []
    skills = {f.pack: f.name for f in project.skill_pack.files if f.pack} if project.skill_pack else {}
    stacks = {s.platform: s.pack for s in project.design.stacks} if project.design else {}
    tasks = project.estimate.base()
    # Cross-cutting work first, then by module, so setup lands in sprint 1 when nothing says otherwise.
    tasks = sorted(tasks, key=lambda t: (t.platform != "common", t.module, t.id))

    epics: dict[str, Ticket] = {}
    tickets: list[Ticket] = []
    n = 0

    def next_ticket_id() -> str:
        nonlocal n
        n += 1
        return f"T-{n:03d}"

    for module in dict.fromkeys(t.module for t in tasks):
        epics[module] = Ticket(id=next_ticket_id(), type="epic", summary=module,
                               description=f"All work for the {module} module.")
    tickets += epics.values()
    by_task: dict[str, Ticket] = {}
    for t in tasks:
        skill_names = ["project-context"] + ([skills[stacks[t.platform]]] if stacks.get(t.platform) in skills else [])
        desc = (f"{t.feature}: {t.title}.\n\nImplements: {', '.join(t.requirement_ids) or 'cross-cutting work'}.\n"
                f"Platform: {t.platform}. Estimate: {t.hours_min:g}-{t.hours_max:g} h (likely {t.hours_likely:g} h).\n"
                f"Follow skills: {', '.join(skill_names)}.\n"
                f"Done when: code, unit tests and a pull request into develop citing "
                f"{', '.join(t.requirement_ids) or 'this ticket'} are reviewed and merged.")
        ticket = Ticket(id=next_ticket_id(), type="task", summary=f"[{t.platform}] {t.title}", description=desc,
                        epic_id=epics[t.module].id, task_id=t.id, requirement_ids=list(t.requirement_ids),
                        platform=t.platform, role=t.role, hours=round(t.expected, 1))
        tickets.append(ticket)
        by_task[t.id] = ticket

    for dep in result.get("dependencies", []) or []:
        child = by_task.get(dep.get("task"))
        if child is None:
            if dep.get("task"):
                notes.append(f"Planner: ignored dependencies for unknown task {dep.get('task')}")
            continue
        for parent_task in dep.get("depends_on", []):
            parent = by_task.get(parent_task)
            if parent is None or parent is child:
                notes.append(f"Planner: ignored dependency {dep.get('task')} -> {parent_task}")
                continue
            if parent.id not in child.depends_on:
                child.depends_on.append(parent.id)

    task_tickets = {t.id: t for t in tickets if t.type == "task"}
    _break_cycles(task_tickets, notes)
    schedule(list(task_tickets.values()), capacity, notes)
    return Plan(jira_key=jira_key, sprint_weeks=sprint_weeks, sprint_capacity_hours=capacity, tickets=tickets), notes


def apply(project: Project, result: dict, jira_key: str, sprint_weeks: int, capacity: float) -> None:
    plan, notes = build_plan(project, result, jira_key, sprint_weeks, capacity)
    project.plan = plan
    for note in notes:
        project.log(note)


# ---------- validation report (reviewed by the tech lead, non-blocking) ----------


@dataclass
class PlanReport:
    passed: bool
    failures: list[str] = field(default_factory=list)


def plan_check(project: Project) -> PlanReport:
    p, e = project.plan, project.estimate
    if p is None or e is None:
        return PlanReport(False, ["Stage 6 has not run: no plan"])
    failures: list[str] = []
    tasks = {t.id: t for t in p.tasks()}
    mapped = {rid for t in tasks.values() for rid in t.requirement_ids}
    failures += [f"{r.id} has no ticket: \"{r.text[:80]}\""
                 for r in project.active_requirements() if r.kind == "functional" and r.id not in mapped]
    ticketed = {t.task_id for t in tasks.values()}
    failures += [f"Estimate task {t.id} has no ticket" for t in e.base() if t.id not in ticketed]
    for t in tasks.values():
        for d in t.depends_on:
            if d not in tasks:
                failures.append(f"{t.id} depends on unknown ticket {d}")
            elif (tasks[d].sprint or 0) > (t.sprint or 0):
                failures.append(f"{t.id} (sprint {t.sprint}) depends on {d}, planned later (sprint {tasks[d].sprint})")
        if t.sprint is None:
            failures.append(f"{t.id} is not in a sprint (dependency cycle?)")
    return PlanReport(passed=not failures, failures=failures)
