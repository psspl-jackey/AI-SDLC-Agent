"""Stage 9 handover: handover summary, maintenance guide, and the sign-off check.

- The handover summary is code: what was delivered, platforms and stacks, release, decisions, what is
  out of scope, and everything still open (questions, assumptions, waived tests, security findings).
- The maintenance guide is code from the tech packs, design and release checklist (how to build, test,
  deploy, monitor, back up, rotate secrets, update dependencies), plus a project-specific runbook that
  the model adds (routine tasks and troubleshooting). The model only adds; code drops empty items.
- The sign-off check is code: the traceability matrix has no break and every input line is accounted
  for. Open items do not block; they are listed so the client signs off knowingly.

run() is pure and returns a result dict; apply() is the only writer.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..domain_packs import load_tech_packs
from ..llm.base import LLMClient
from ..llm.json_call import Dicts, complete_json
from ..questions.queue import open_questions
from ..state.models import GapStatus, Handover, Project, RunbookItem

NAME = "handover"
MAX_RUNBOOK = 12

SYSTEM = """You are a support engineer writing the runbook a client's team will use after handover.
List the routine maintenance tasks and the likely troubleshooting cases for THIS system (its components,
data, API and platforms), each with when it is needed and short numbered steps. Do not repeat generic
advice such as "keep dependencies up to date"; that is covered elsewhere. Payment runs against a dummy
gateway; real payment and third-party integrations are not part of this system."""
SHAPE = {"runbook": Dicts({"task": "str", "when": "str", "steps": "strs"}, text_key="task")}
SCHEMA = 'Return JSON: {"runbook": [{"task": str, "when": str, "steps": [str]}]}'


def run(llm: LLMClient, project: Project) -> dict:
    d = project.design
    summary = "\n".join([
        f"Goal: {project.brief.goal if project.brief else ''}",
        "Components: " + "; ".join(f"{c.name} ({c.kind}): {c.responsibility}" for c in d.components),
        "Data: " + "; ".join(e.name for e in d.entities),
        "API: " + "; ".join(f"{e.method} {e.path}" for e in d.endpoints),
        "Stacks: " + "; ".join(f"{s.platform}: {s.pack}" for s in d.stacks),
    ])
    return complete_json(llm, SYSTEM, f"{summary}\n\n{SCHEMA}", SHAPE)


def build_handover(project: Project, result: dict) -> tuple[Handover, list[str]]:
    notes: list[str] = []
    items: list[RunbookItem] = []
    for it in result.get("runbook", []):
        task, steps = it.get("task", "").strip(), [s for s in it.get("steps", []) if s.strip()]
        if not task or not steps:
            notes.append(f"Handover: dropped runbook item without steps: {task or '(no title)'}")
            continue
        if task.lower() in {x.task.lower() for x in items}:
            continue
        items.append(RunbookItem(task=task, when=it.get("when", ""), steps=steps))
    if len(items) > MAX_RUNBOOK:
        notes.append(f"Handover: kept the first {MAX_RUNBOOK} of {len(items)} runbook items")
        items = items[:MAX_RUNBOOK]
    return Handover(version=project.release.version if project.release else "", runbook=items), notes


def apply(project: Project, result: dict) -> None:
    project.handover, notes = build_handover(project, result)
    for note in notes:
        project.log(note)


# ---------- documents (code) ----------


def open_items(project: Project) -> dict[str, list[str]]:
    rel = project.release
    return {
        "Unanswered client questions": [f"{q.id}{' (blocking)' if q.blocking else ''}: {q.text}"
                                        + (f" Assumed: {q.assumed_answer}" if q.assumed_answer else "")
                                        for q in open_questions(project)],
        "Gaps still open": [f"{g.id}: {g.description}" for g in project.gaps if g.status is GapStatus.OPEN],
        "Waived test cases": [f"{c.id} {c.title}: {c.note}" for c in (rel.test_cases if rel else [])
                              if c.result == "waived"],
        "Security findings": [f"[{f.severity}] {f.rule}: {f.path}:{f.line}" for f in (rel.findings if rel else [])],
    }


def handover_markdown(project: Project) -> str:
    from .. import traceability

    d, m, rel = project.design, project.platform_matrix, project.release
    packs = load_tech_packs()
    s = traceability.summary(project)
    out = [f"# Handover: {project.name}", "",
           f"Release {rel.version if rel else ''}. Goal: {project.brief.goal if project.brief else ''}", "",
           "## Delivered", "",
           f"{s['delivered']} requirement(s) delivered; full chain in traceability.xlsx.", ""]
    out += [f"- **{r.id}** {r.text}" for r in project.active_requirements() if r.kind == "functional"]
    nfrs = [r for r in project.active_requirements() if r.kind == "nfr"]
    if nfrs:
        out += ["", "Non-functional:", ""] + [f"- **{r.id}** {r.text}" for r in nfrs]
    out += ["", "## Platforms and stacks", ""]
    stacks = {x.platform: x.pack for x in d.stacks} if d else {}
    out += [f"- {x.platform.replace('_', ' ')}: {packs.get(stacks.get(x.platform, ''), {}).get('title', stacks.get(x.platform, '?'))}"
            for x in (m.included() if m else [])]
    if d and d.decisions:
        out += ["", "## Key decisions", ""] + [f"- {x.title}: {x.decision}. {x.reason}" for x in d.decisions]
    out += ["", "## Not included", "", "- Real payment and third-party integrations (payment uses a dummy gateway)."]
    out += [f"- {g.description}" for g in project.gaps if g.status is GapStatus.OUT_OF_SCOPE]
    if project.assumptions:
        out += ["", "## Assumptions made during the project", ""]
        out += [f"- {a.id}: {a.text}" for a in project.assumptions]
    out += ["", "## Open items the client signs off on", ""]
    for label, items in open_items(project).items():
        out += [f"### {label}", ""] + ([f"- {x}" for x in items] or ["- None."]) + [""]
    out += ["## In this pack", "",
            "- handover.md (this file), maintenance-guide.md, architecture.md, requirements.md",
            "- traceability.xlsx, release-notes.md, test-report.csv, gap-register.csv, client-questions.md",
            "- platform-matrix.md, estimate.xlsx, plan.md, jira-import.csv, skills/ (project skill pack)"]
    if project.handover and project.handover.signoff:
        so = project.handover.signoff
        out += ["", "## Client sign-off", "",
                f"{'Accepted' if so.accepted else 'Not accepted'} by {so.signed_by} on {so.signed_at:%Y-%m-%d}. {so.comment}"]
    return "\n".join(out) + "\n"


def maintenance_markdown(project: Project) -> str:
    d, rel = project.design, project.release
    packs = load_tech_packs()
    used = list(dict.fromkeys(x.pack for x in d.stacks)) if d else []
    out = [f"# Maintenance guide: {project.name}", "",
           "How to build, test, release and run the system after handover. Stack rules come from the company tech "
           "packs; the runbook at the end was written for this project.", ""]
    for name in used:
        pack = packs.get(name)
        if not pack:
            continue
        platforms = ", ".join(x.platform.replace("_", " ") for x in d.stacks if x.pack == name)
        out += [f"## {pack.get('title', name)} ({platforms})", "",
                "Build and release:", ""] + [f"- {r}" for r in pack.get("ci", [])] + [
                "", "Testing:", ""] + [f"- {r}" for r in pack.get("testing", [])] + [
                "", "Security:", ""] + [f"- {r}" for r in pack.get("security", [])] + [""]
    out += ["## Operating the system", "",
            "- Keep secrets in the secret manager or CI secret store; rotate them at least yearly and when people leave.",
            "- Update dependencies monthly; apply security patches as they are published; re-run the full test suite.",
            "- Review store requirements (target SDK, privacy forms) before each mobile release.",
            "- Every change follows the same rules as the build: Jira ticket, feature branch, pull request into develop, review."]
    if rel:
        ops = [i for i in rel.checklist if i.platform in ("backend", "web", "admin_panel")]
        if ops:
            out += ["", "Release checks carried over from this release:", ""] + [f"- [{i.platform}] {i.text}" for i in ops]
    if project.handover and project.handover.runbook:
        out += ["", "## Runbook for this project", ""]
        for it in project.handover.runbook:
            out += [f"### {it.task}", ""] + ([f"When: {it.when}", ""] if it.when else [])
            out += [f"{i}. {step}" for i, step in enumerate(it.steps, start=1)] + [""]
    return "\n".join(out).rstrip() + "\n"


# ---------- sign-off check ----------


@dataclass
class HandoverReport:
    passed: bool
    failures: list[str] = field(default_factory=list)


def handover_check(project: Project) -> HandoverReport:
    from .. import traceability

    if project.handover is None:
        return HandoverReport(False, ["Stage 9 has not run: no handover pack"])
    failures = [f"{r.requirement_id}: {', '.join(r.breaks)}" for r in traceability.matrix(project) if r.breaks]
    failures += [f"Input line {lid} is not accounted for" for lid in traceability.unaccounted_lines(project)]
    return HandoverReport(passed=not failures, failures=failures)
