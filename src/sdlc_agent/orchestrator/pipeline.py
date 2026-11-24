"""Orchestrator: Stage 0 (intake), Stage 1 (requirements and gap analysis) and Gate 1, Stage 2 (platforms),
Stage 3 (estimate) and Gate 2.

Stage 1 is a LangGraph graph:

    START -> requirements_analyst --\
          -> domain_research -------+-> merge -> reviewer -> coverage -> END (waiting for Gate 1)

The analyst and research agents run in parallel and return results; only the merge node writes
to the project, so the two never overwrite each other.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional, TypedDict

from langgraph.graph import END, START, StateGraph

from ..agents import domain_research, estimator, planner, platform_decision, requirements_analyst, reviewer, skills_setup, solution_design, ui_designer
from ..config import Settings, get_settings
from ..gaps.register import add_gap, coverage_check, gate_passed, gate_status
from ..intake.brief import apply_intake_answers, build_brief, completeness_of, extract_sow_lines, fill_thin_brief
from ..intake.detect import detect_input_type, overall_input_type
from ..intake.questionnaire import IntakeQuestion, build_questionnaire
from ..intake.readers import read_input
from ..llm.base import LLMClient
from ..llm.factory import get_llm
from ..questions.queue import ask
from ..state.models import (
    GapSource,
    GateDecision,
    Project,
    RawInput,
    Stage,
    StageStatus,
)
from ..state.store import ProjectStore
from ..tracing import TracedLLM, Tracer


@dataclass
class Deps:
    """Everything the orchestrator needs; tests swap in fakes."""

    settings: Settings = field(default_factory=get_settings)
    llm: Optional[LLMClient] = None
    store: Optional[ProjectStore] = None
    tracer: Optional[Tracer] = None
    search: Any = None
    read_url: Optional[Callable] = None
    check_link: Optional[Callable[[str], bool]] = None

    def __post_init__(self) -> None:
        self.llm = self.llm or get_llm(self.settings)
        self.store = self.store or ProjectStore(self.settings.projects_dir)
        self.tracer = self.tracer or Tracer(self.settings)

    def llm_for(self, project_id: str, agent: str) -> TracedLLM:
        return TracedLLM(self.llm, self.tracer, project_id, agent)


# ---------- Stage 0: intake ----------

def start_intake(deps: Deps, project: Project, inputs: list[RawInput]) -> list[IntakeQuestion]:
    """Read every input, build the draft brief, and return only the intake questions still needed."""
    project.stage_status[Stage.INTAKE] = StageStatus.RUNNING
    for raw in inputs:
        raw.detected_type = detect_input_type(raw)
    project.raw_inputs = inputs
    chunks = [c for raw in inputs for c in read_input(raw)]
    input_type = overall_input_type(inputs)
    completeness = completeness_of(chunks, input_type)
    project.brief = build_brief(deps.llm_for(project.id, "intake"), chunks, completeness)
    project.sow_lines = extract_sow_lines(chunks)
    project.log(
        f"Intake read {len(inputs)} input(s) as {input_type.value}; completeness {completeness.value}; "
        f"{len(project.sow_lines)} input line(s)"
    )
    deps.store.save(project)
    return build_questionnaire(project.brief, completeness, project.intake_answers)


def finish_intake(deps: Deps, project: Project, answers: dict[str, str]) -> None:
    project.intake_answers.update({k: v for k, v in answers.items() if v and v.strip()})
    project.brief = apply_intake_answers(project.brief, project.intake_answers)
    added = fill_thin_brief(project.brief)
    if added:
        project.log(f"Thin input: added {added} table-stakes feature(s) from the domain pack, tagged inferred")
    project.stage_status[Stage.INTAKE] = StageStatus.APPROVED
    project.log("Intake questionnaire answered; brief finalised")
    deps.store.save(project)


# ---------- Stage 1: requirements and gap analysis ----------

class Stage1State(TypedDict, total=False):
    project_id: str
    analyst: dict
    research: dict


def _record_inferred_items(project: Project) -> None:
    """Everything the system decided on its own enters the register as assumed (doc: Stage 0 in detail)."""
    if not project.brief:
        return
    for kind, items in (("feature", project.brief.features), ("NFR", project.brief.nfrs),
                        ("constraint", project.brief.constraints)):
        for item in items:
            if item.source.kind == "inferred":
                gap = add_gap(project, source=GapSource.INFERRED,
                              description=f"Inferred {kind}, not stated by the client: {item.text}",
                              found_by="intake")
                ask(project, f"Please confirm this {kind}: {item.text}", blocking=False,
                    assumed_answer=f"Include: {item.text}", related_gap_id=gap.id)


def build_stage1_graph(deps: Deps):
    def analyst_node(state: Stage1State) -> dict:
        project = deps.store.load(state["project_id"])
        return {"analyst": requirements_analyst.run(deps.llm_for(project.id, requirements_analyst.NAME), project)}

    def research_node(state: Stage1State) -> dict:
        project = deps.store.load(state["project_id"])
        return {"research": domain_research.run(
            deps.llm_for(project.id, domain_research.NAME), project,
            search=deps.search, read_url=deps.read_url,
        )}

    def merge_node(state: Stage1State) -> dict:
        project = deps.store.load(state["project_id"])
        requirements_analyst.apply(project, state.get("analyst", {}))
        domain_research.apply(project, state.get("research", {}))
        _record_inferred_items(project)
        project.log(f"Merged results: {len(project.requirements)} requirements, {len(project.gaps)} gaps")
        deps.store.save(project)
        return {}

    def review_node(state: Stage1State) -> dict:
        project = deps.store.load(state["project_id"])
        kwargs = {"check_link": deps.check_link} if deps.check_link else {}
        reviewer.apply(project, reviewer.run(deps.llm_for(project.id, reviewer.NAME), project, **kwargs))
        deps.store.save(project)
        return {}

    def coverage_node(state: Stage1State) -> dict:
        project = deps.store.load(state["project_id"])
        report = coverage_check(project)
        project.stage_status[Stage.REQUIREMENTS] = StageStatus.WAITING_GATE
        project.log(
            "Coverage check passed; Gate 1 is open for approval" if report.passed
            else f"Coverage check found {len(report.failures)} issue(s); fix them before Gate 1 can be approved"
        )
        deps.store.save(project)
        return {}

    g = StateGraph(Stage1State)
    g.add_node("requirements_analyst", analyst_node)
    g.add_node("domain_research", research_node)
    g.add_node("merge", merge_node)
    g.add_node("reviewer", review_node)
    g.add_node("coverage", coverage_node)
    g.add_edge(START, "requirements_analyst")
    g.add_edge(START, "domain_research")
    g.add_edge(["requirements_analyst", "domain_research"], "merge")
    g.add_edge("merge", "reviewer")
    g.add_edge("reviewer", "coverage")
    g.add_edge("coverage", END)
    return g.compile()


def run_stage1(deps: Deps, project_id: str) -> Project:
    project = deps.store.load(project_id)
    if project.stage_status[Stage.INTAKE] is not StageStatus.APPROVED:
        raise RuntimeError("Finish the intake questionnaire before running Stage 1")
    # Re-running Stage 1 starts from a clean slate; intake results are kept.
    project.requirements, project.gaps, project.assumptions = [], [], []
    project.questions, project.competitors = [], []
    # Later stages were built on the old requirements, so they must run again after the new Gate 1.
    _reset_from(project, Stage.PLATFORM)
    _supersede_pending_change(project, "Stage 1")
    for line in project.sow_lines:
        line.requirement_ids, line.not_a_requirement = [], False
    project.gate_decisions = [d for d in project.gate_decisions if d.gate != 1]
    project.stage_status[Stage.REQUIREMENTS] = StageStatus.RUNNING
    deps.store.save(project)
    deps.tracer.record(project_id, {"type": "stage_start", "stage": Stage.REQUIREMENTS.value})
    try:
        build_stage1_graph(deps).invoke({"project_id": project_id})
    except Exception as exc:
        project = deps.store.load(project_id)
        project.stage_status[Stage.REQUIREMENTS] = StageStatus.FAILED
        project.log(f"Stage 1 failed: {exc!r}")
        deps.store.save(project)
        deps.tracer.record(project_id, {"type": "stage_failed", "stage": Stage.REQUIREMENTS.value, "error": repr(exc)})
        raise
    deps.tracer.record(project_id, {"type": "stage_end", "stage": Stage.REQUIREMENTS.value})
    return deps.store.load(project_id)


# ---------- Gates ----------

GATE_STAGE = {1: Stage.REQUIREMENTS, 2: Stage.PROPOSAL, 3: Stage.DESIGN, 4: Stage.QA_RELEASE}


def gate_failures(project: Project, gate: int) -> list[str]:
    """Code checks that must pass before a gate can be approved."""
    if gate == 1:
        return coverage_check(project).failures
    if gate == 2:
        return platform_decision.platform_check(project).failures + estimator.estimate_check(project).failures
    if gate == 3:
        return solution_design.design_check(project).failures
    if gate == 4:
        from ..agents import qa
        return qa.release_check(project).failures
    raise ValueError(f"Unknown gate {gate}")


def decide_gate(deps: Deps, project: Project, gate: int, role: str, approved: bool, comment: str = "") -> Project:
    stage = GATE_STAGE[gate]
    if project.stage_status[stage] not in (StageStatus.WAITING_GATE, StageStatus.REJECTED):
        raise RuntimeError(f"Nothing is waiting for Gate {gate}")
    if approved and gate_failures(project, gate):
        raise RuntimeError(f"Gate {gate} cannot be approved while its checks have failures")
    project.gate_decisions.append(GateDecision(gate=gate, role=role, approved=approved, comment=comment))
    if not approved:
        project.stage_status[stage] = StageStatus.REJECTED
        project.log(f"Gate {gate} rejected by {role}: {comment}")
    elif gate_passed(project, gate):
        project.stage_status[stage] = StageStatus.APPROVED
        project.log(f"Gate {gate} approved by tech lead, delivery head and sales")
    else:
        project.stage_status[stage] = StageStatus.WAITING_GATE
        waiting = [r for r, v in gate_status(project, gate).items() if v is not True]
        project.log(f"Gate {gate} approved by {role}; waiting for {', '.join(waiting)}")
    deps.store.save(project)
    return project


def decide_gate1(deps: Deps, project: Project, role: str, approved: bool, comment: str = "") -> Project:
    return decide_gate(deps, project, 1, role, approved, comment)


def _reset_from(project: Project, stage: Stage) -> None:
    """A stage re-runs on new inputs, so everything after it must run again."""
    order = [Stage.PLATFORM, Stage.PROPOSAL, Stage.DESIGN, Stage.SKILLS, Stage.PLAN, Stage.BUILD, Stage.QA_RELEASE,
             Stage.HANDOVER]
    for s in order[order.index(stage):] if stage in order else []:
        project.stage_status[s] = StageStatus.PENDING
        if s is Stage.PLATFORM:
            _clear_stage2(project)
        if s is Stage.PROPOSAL:
            project.estimate = None
            project.client_decision = None
            project.gate_decisions = [d for d in project.gate_decisions if d.gate != 2]
        if s is Stage.DESIGN:
            project.design = None
            project.gate_decisions = [d for d in project.gate_decisions if d.gate != 3]
        if s is Stage.SKILLS:
            project.skill_pack = None
        if s is Stage.PLAN:
            project.plan = None
        if s is Stage.BUILD:
            # Ticket ids are regenerated by a new plan, so earlier build records no longer match them.
            # Merged work stays in develop; open pull requests from the old plan should be closed.
            old = [b for b in project.builds if b.status != "superseded"]
            for b in old:
                b.status = "superseded"
            if old:
                project.log(f"{len(old)} build record(s) superseded by the new plan; close any open pull requests "
                            "from the old plan and check develop before rebuilding")
        if s is Stage.QA_RELEASE:
            project.release = None
            project.gate_decisions = [d for d in project.gate_decisions if d.gate != 4]
        if s is Stage.HANDOVER:
            project.handover = None


def _supersede_pending_change(project: Project, by: str) -> None:
    """A full re-run already covers a pending change request, so it must not be applied on top."""
    from ..state.models import now

    for cr in project.change_requests:
        if cr.status == "analysed":
            cr.status, cr.applied_at = "applied", now()
            project.log(f"{cr.id} is covered by the full {by} re-run")


# ---------- Stage 2: platform decision (no gate of its own; reviewed at Gate 2) ----------

def _clear_stage2(project: Project) -> None:
    """Re-running Stage 2 replaces its own inferred gaps, questions and assumptions; nothing else."""
    old = {g.id for g in project.gaps if g.found_by == platform_decision.NAME}
    project.gaps = [g for g in project.gaps if g.id not in old]
    project.questions = [q for q in project.questions if q.related_gap_id not in old]
    project.assumptions = [a for a in project.assumptions if a.related_gap_id not in old]
    project.platform_matrix = None


def run_stage2(deps: Deps, project_id: str) -> Project:
    project = deps.store.load(project_id)
    if project.stage_status[Stage.REQUIREMENTS] is not StageStatus.APPROVED:
        raise RuntimeError("Gate 1 must be approved before the platform decision (Stage 2)")
    _reset_from(project, Stage.PLATFORM)
    _supersede_pending_change(project, "Stage 2")
    project.stage_status[Stage.PLATFORM] = StageStatus.RUNNING
    deps.store.save(project)
    deps.tracer.record(project_id, {"type": "stage_start", "stage": Stage.PLATFORM.value})
    try:
        result = platform_decision.run(deps.llm_for(project.id, platform_decision.NAME), project)
    except Exception as exc:
        project.stage_status[Stage.PLATFORM] = StageStatus.FAILED
        project.log(f"Stage 2 failed: {exc!r}")
        deps.store.save(project)
        deps.tracer.record(project_id, {"type": "stage_failed", "stage": Stage.PLATFORM.value, "error": repr(exc)})
        raise
    platform_decision.apply(project, result)
    report = platform_decision.platform_check(project)
    included = ", ".join(d.platform for d in project.platform_matrix.included())
    project.stage_status[Stage.PLATFORM] = StageStatus.DONE
    project.log(
        f"Platform decision: {included}; approach {project.platform_matrix.approach}. "
        + ("Platform check passed." if report.passed
           else f"Platform check found {len(report.failures)} issue(s) to resolve before Gate 2.")
    )
    deps.store.save(project)
    deps.tracer.record(project_id, {"type": "stage_end", "stage": Stage.PLATFORM.value})
    return project



def set_client_platforms(deps: Deps, project_id: str, included: list[str], excluded: list[str],
                         note: str = "", approach: str | None = None) -> Project:
    """A person sets platforms Yes/No at the Stage 2 review. Yes becomes client-stated (the agent cannot drop
    it), No is excluded (the agent cannot add it). Stage 2 re-runs to map requirements, which resets Stages 3-9."""
    from ..agents.platform_decision import normalise

    project = deps.store.load(project_id)
    inc = list(dict.fromkeys(normalise(x) for x in included if str(x).strip()))
    exc = [x for x in dict.fromkeys(normalise(x) for x in excluded if str(x).strip()) if x not in inc]
    if not inc:
        raise ValueError("Choose at least one platform")
    before = [d.platform for d in project.platform_matrix.included()] if project.platform_matrix else []
    if approach not in (None, "", "native", "cross_platform", "web_only", "not_applicable"):
        raise ValueError(f"Unknown approach {approach}")
    project.brief.platforms, project.brief.excluded_platforms = inc, exc
    project.brief.approach = approach or None
    project.log(f"Platforms set at Stage 2 review: yes {', '.join(inc)}; no {', '.join(exc) or 'none'}; "
                f"approach {approach or 'agent decides'}"
                + (f" ({note})" if note else "") + f". Was: {', '.join(before) or 'none'}. Stage 2 re-runs; "
                "Stages 3-9 must run again.")
    deps.store.save(project)
    return run_stage2(deps, project_id)


# ---------- Stage 3: estimate, then Gate 2 ----------

def run_stage3(deps: Deps, project_id: str) -> Project:
    project = deps.store.load(project_id)
    if project.stage_status[Stage.PLATFORM] is not StageStatus.DONE:
        raise RuntimeError("Run the platform decision (Stage 2) before the estimate (Stage 3)")
    _reset_from(project, Stage.PROPOSAL)
    project.stage_status[Stage.PROPOSAL] = StageStatus.RUNNING
    deps.store.save(project)
    deps.tracer.record(project_id, {"type": "stage_start", "stage": Stage.PROPOSAL.value})
    try:
        result = estimator.run(deps.llm_for(project.id, estimator.NAME), project)
    except Exception as exc:
        project.stage_status[Stage.PROPOSAL] = StageStatus.FAILED
        project.log(f"Stage 3 failed: {exc!r}")
        deps.store.save(project)
        deps.tracer.record(project_id, {"type": "stage_failed", "stage": Stage.PROPOSAL.value, "error": repr(exc)})
        raise
    estimator.apply(project, result, deps.settings.risk_buffer_pct)
    e = project.estimate
    base, extra = estimator.totals(e.base()), estimator.totals(e.additions())
    failures = gate_failures(project, 2)
    project.stage_status[Stage.PROPOSAL] = StageStatus.WAITING_GATE
    project.log(
        f"Estimate: {base.tasks} tasks, {base.hours_min:.0f}-{base.hours_max:.0f} h "
        f"(expected {base.expected:.0f} h, {estimator.with_buffer(base.expected, e.risk_buffer_pct):.0f} h with "
        f"{e.risk_buffer_pct:g}% buffer); recommended additions {extra.expected:.0f} h. "
        + ("Gate 2 is open for approval." if not failures
           else f"{len(failures)} check issue(s) to fix before Gate 2 can be approved.")
    )
    deps.store.save(project)
    deps.tracer.record(project_id, {"type": "stage_end", "stage": Stage.PROPOSAL.value})
    return project


# ---------- Client decision on the proposal (after internal Gate 2) ----------

def record_client_decision(
    deps: Deps, project: Project, approved: bool, opted_in_gap_ids: list[str] | None = None, comment: str = ""
) -> Project:
    """The client approves or rejects the proposal and opts into recommended additions.

    Accepted additions become requirements (their gaps ANSWERED) and join the base estimate.
    On approval, additions the client did not take become out of scope (exclusions).
    """
    from ..state.models import ClientDecision, GapStatus, Requirement, SourceRef
    from ..state.store import next_id

    if project.stage_status[Stage.PROPOSAL] is not StageStatus.APPROVED:
        raise RuntimeError("Gate 2 must be approved internally before recording the client's decision")
    offered = {g.id: g for g in project.gaps if g.status is GapStatus.RECOMMENDED}
    opted = list(dict.fromkeys(opted_in_gap_ids or []))
    unknown = [g for g in opted if g not in offered]
    if unknown:
        raise ValueError(f"Not recommended additions on offer: {', '.join(unknown)}")
    if opted and not approved:
        raise ValueError("Additions can only be opted into when the client approves")
    project.client_decision = ClientDecision(approved=approved, opted_in_gap_ids=opted, comment=comment)
    if not approved:
        project.stage_status[Stage.PROPOSAL] = StageStatus.REJECTED
        project.log(f"Client rejected the proposal: {comment}. Submit a change request or revise and re-approve Gate 2.")
        deps.store.save(project)
        return project

    e = project.estimate
    m = project.platform_matrix
    for gid in opted:
        gap = offered[gid]
        req = Requirement(
            id=next_id("REQ", (r.id for r in project.requirements)),
            text=f"Recommended addition accepted by the client ({gid}): {gap.description}",
            source=SourceRef(kind="client_decision", ref="proposal approval"),
        )
        project.requirements.append(req)
        gap.status, gap.linked_requirement_id = GapStatus.ANSWERED, req.id
        tasks = [t for t in e.tasks if t.gap_id == gid]
        for t in tasks:
            t.requirement_ids.append(req.id)
        for d in m.included():
            if any(t.platform == d.platform for t in tasks):
                d.requirement_ids.append(req.id)
        e.accepted_gap_ids.append(gid)
    for gid, gap in offered.items():
        if gid not in opted:
            gap.status = GapStatus.OUT_OF_SCOPE
            e.declined_gap_ids.append(gid)
    project.log(f"Client approved the proposal; opted into {', '.join(opted) or 'no additions'}; "
                f"{len(offered) - len(opted)} addition(s) moved to exclusions")
    deps.store.save(project)
    return project


# ---------- Change requests: re-enter at Stage 1, re-estimate only what changed ----------

def submit_change_request(deps: Deps, project_id: str, text: str) -> Project:
    """Analyse a change request against the current requirements and reopen Gate 1.

    Later stages keep their data but go back to pending; apply_change_request() updates them
    for the affected requirements only, once Gate 1 is approved again.
    """
    from ..agents import change_analyst
    from ..state.models import ChangeRequest
    from ..state.store import next_id

    project = deps.store.load(project_id)
    if project.stage_status[Stage.REQUIREMENTS] not in (
        StageStatus.WAITING_GATE, StageStatus.REJECTED, StageStatus.APPROVED
    ):
        raise RuntimeError("Stage 1 has not run yet; add the change to the project inputs instead")
    if any(cr.status == "analysed" for cr in project.change_requests):
        raise RuntimeError("Apply the pending change request before submitting another")
    if not text.strip():
        raise ValueError("The change request is empty")
    cr = ChangeRequest(id=next_id("CR", (c.id for c in project.change_requests)), text=text.strip())
    new_lines = change_analyst.lines_for(project, cr.id, cr.text)
    project.sow_lines.extend(new_lines)
    cr.line_ids = [line.id for line in new_lines]
    result = change_analyst.run(deps.llm_for(project.id, change_analyst.NAME), project, cr)
    change_analyst.apply(project, cr, result)
    project.change_requests.append(cr)

    project.stage_status[Stage.REQUIREMENTS] = StageStatus.WAITING_GATE
    project.gate_decisions = [d for d in project.gate_decisions if d.gate not in (1, 2, 3, 4)]
    project.client_decision = None
    for s in (Stage.PLATFORM, Stage.PROPOSAL, Stage.DESIGN, Stage.SKILLS, Stage.PLAN, Stage.BUILD, Stage.QA_RELEASE,
              Stage.HANDOVER):
        if project.stage_status[s] is not StageStatus.PENDING:
            project.stage_status[s] = StageStatus.PENDING
    project.log(f"{cr.id} analysed: {len(cr.added)} added, {len(cr.changed)} changed, {len(cr.removed)} removed. "
                "Gate 1 is open again.")
    deps.store.save(project)
    return project


def apply_change_request(deps: Deps, project_id: str) -> Project:
    """After Gate 1 is re-approved: update the platform matrix and re-estimate only the affected work."""
    from ..agents import estimator as est
    from ..state.models import now

    project = deps.store.load(project_id)
    cr = next((c for c in project.change_requests if c.status == "analysed"), None)
    if cr is None:
        raise RuntimeError("No change request is waiting to be applied")
    if project.stage_status[Stage.REQUIREMENTS] is not StageStatus.APPROVED:
        raise RuntimeError("Gate 1 must be approved again before the change request is applied")

    m, e = project.platform_matrix, project.estimate
    if m is not None:
        included = {d.platform: d for d in m.included()}
        for d in m.decisions:
            d.requirement_ids = [r for r in d.requirement_ids if r not in cr.removed]
        for rid, platforms in cr.platforms.items():
            unknown = [p for p in platforms if p not in included]
            if unknown:
                project.log(f"{cr.id}: {rid} asks for platform(s) not in the matrix: {', '.join(unknown)}. "
                            "Re-run Stage 2 if the project needs them.")
            for p in platforms:
                if p in included and rid not in included[p].requirement_ids:
                    included[p].requirement_ids.append(rid)
        project.stage_status[Stage.PLATFORM] = StageStatus.DONE

    if m is not None and e is not None:
        affected = cr.affected()
        dropped = [t for t in e.tasks if set(t.requirement_ids) & affected]
        # Requirements that shared a dropped task lose coverage too, so they are re-estimated with it.
        active = {r.id for r in project.active_requirements()}
        redo = ({rid for t in dropped for rid in t.requirement_ids} | set(cr.added) | set(cr.changed)) & active
        e.tasks = [t for t in e.tasks if t not in dropped]
        result = est.run(deps.llm_for(project.id, est.NAME), project, only=redo)
        fresh, notes = est.build_estimate(project, result, e.risk_buffer_pct, existing_ids=tuple(t.id for t in e.tasks))
        e.tasks.extend(fresh.tasks)
        for note in notes:
            project.log(note)
        project.stage_status[Stage.PROPOSAL] = StageStatus.WAITING_GATE
        project.log(f"{cr.id} applied: dropped {len(dropped)} task(s), re-estimated {len(redo)} requirement(s) "
                    f"as {len(fresh.tasks)} task(s); other tasks unchanged. Gate 2 is open again.")
    else:
        project.log(f"{cr.id} applied to the requirements; later stages have not run yet.")
    cr.status, cr.applied_at = "applied", now()
    deps.store.save(project)
    return project


# ---------- Stage 4: solution design, then Gate 3 ----------

def run_stage4(deps: Deps, project_id: str) -> Project:
    project = deps.store.load(project_id)
    if project.stage_status[Stage.PROPOSAL] is not StageStatus.APPROVED or not (
        project.client_decision and project.client_decision.approved
    ):
        raise RuntimeError("The proposal must be approved at Gate 2 and by the client before solution design (Stage 4)")
    _reset_from(project, Stage.DESIGN)
    project.stage_status[Stage.DESIGN] = StageStatus.RUNNING
    deps.store.save(project)
    deps.tracer.record(project_id, {"type": "stage_start", "stage": Stage.DESIGN.value})
    try:
        result = solution_design.run(deps.llm_for(project.id, solution_design.NAME), project)
    except Exception as exc:
        project.stage_status[Stage.DESIGN] = StageStatus.FAILED
        project.log(f"Stage 4 failed: {exc!r}")
        deps.store.save(project)
        deps.tracer.record(project_id, {"type": "stage_failed", "stage": Stage.DESIGN.value, "error": repr(exc)})
        raise
    solution_design.apply(project, result)
    d = project.design
    d.theme = _theme(deps, project)
    failures = gate_failures(project, 3)
    project.stage_status[Stage.DESIGN] = StageStatus.WAITING_GATE
    project.log(
        f"Solution design: stacks {', '.join(f'{s.platform}={s.pack}' for s in d.stacks)}; {len(d.components)} "
        f"components, {len(d.entities)} entities, {len(d.endpoints)} endpoints, {len(d.screens)} screens. "
        + ("Gate 3 is open for approval." if not failures
           else f"{len(failures)} check issue(s) to fix before Gate 3 can be approved.")
    )
    deps.store.save(project)
    deps.tracer.record(project_id, {"type": "stage_end", "stage": Stage.DESIGN.value})
    return project


def _theme(deps: Deps, project: Project):
    """Theme from the domain pack, adjusted by the UI direction. A failed model call keeps the default."""
    try:
        theme = ui_designer.design_theme(deps.llm_for(project.id, ui_designer.NAME), project)
    except Exception as exc:  # the look must never block the design
        project.log(f"UI theme: could not read the UI direction ({exc!r}); used the domain default")
        theme = ui_designer.build_theme(project)
    project.log(f"UI theme ({theme.source.replace('_', ' ')}): primary {theme.primary}, accent {theme.accent}, "
                f"{theme.font} font, {theme.radius} corners"
                + (f"; code adjusted: {'; '.join(theme.adjustments)}" if theme.adjustments else ""))
    return theme


def set_ui_direction(deps: Deps, project_id: str, direction: str) -> Project:
    """Change the look and feel (client or team suggestions) without re-running the whole design.
    The theme is cosmetic, so Gate 3 stays as it is; the change is logged."""
    project = deps.store.load(project_id)
    if project.design is None:
        raise RuntimeError("Run the solution design (Stage 4) first")
    project.ui_direction = direction.strip()
    project.design.theme = _theme(deps, project)
    project.log("UI direction " + (f"set: {project.ui_direction}" if project.ui_direction else "cleared: domain default"))
    deps.store.save(project)
    return project


# ---------- Stage 5: skills setup (no gate of its own) ----------

def run_stage5(deps: Deps, project_id: str) -> Project:
    project = deps.store.load(project_id)
    if project.stage_status[Stage.DESIGN] is not StageStatus.APPROVED:
        raise RuntimeError("Gate 3 must approve the solution design before skills setup (Stage 5)")
    _reset_from(project, Stage.SKILLS)
    project.stage_status[Stage.SKILLS] = StageStatus.RUNNING
    deps.store.save(project)
    deps.tracer.record(project_id, {"type": "stage_start", "stage": Stage.SKILLS.value})
    try:
        result = skills_setup.run(deps.llm_for(project.id, skills_setup.NAME), project)
    except Exception as exc:
        project.stage_status[Stage.SKILLS] = StageStatus.FAILED
        project.log(f"Stage 5 failed: {exc!r}")
        deps.store.save(project)
        deps.tracer.record(project_id, {"type": "stage_failed", "stage": Stage.SKILLS.value, "error": repr(exc)})
        raise
    skills_setup.apply(project, result)
    report = skills_setup.skills_check(project)
    added = sum(len(v) for f in project.skill_pack.files for v in f.tailored.values())
    project.stage_status[Stage.SKILLS] = StageStatus.DONE
    project.log(f"Skill pack: {len(project.skill_pack.files)} skills, {added} project-specific rules added. "
                + ("Skills check passed." if report.passed else f"Skills check: {'; '.join(report.failures)}"))
    deps.store.save(project)
    deps.tracer.record(project_id, {"type": "stage_end", "stage": Stage.SKILLS.value})
    return project


# ---------- Stage 6: internal plan and validation (tech lead review, non-blocking) ----------

def run_stage6(deps: Deps, project_id: str) -> Project:
    project = deps.store.load(project_id)
    if project.stage_status[Stage.SKILLS] is not StageStatus.DONE:
        raise RuntimeError("Run skills setup (Stage 5) before the internal plan (Stage 6)")
    _reset_from(project, Stage.PLAN)
    project.stage_status[Stage.PLAN] = StageStatus.RUNNING
    deps.store.save(project)
    deps.tracer.record(project_id, {"type": "stage_start", "stage": Stage.PLAN.value})
    try:
        result = planner.run(deps.llm_for(project.id, planner.NAME), project)
    except Exception as exc:
        project.stage_status[Stage.PLAN] = StageStatus.FAILED
        project.log(f"Stage 6 failed: {exc!r}")
        deps.store.save(project)
        deps.tracer.record(project_id, {"type": "stage_failed", "stage": Stage.PLAN.value, "error": repr(exc)})
        raise
    st = deps.settings
    planner.apply(project, result, st.jira_project_key, st.sprint_weeks, st.sprint_capacity_hours)
    report = planner.plan_check(project)
    p = project.plan
    project.stage_status[Stage.PLAN] = StageStatus.DONE
    project.log(f"Plan: {len(p.tasks())} tickets in {p.sprint_count()} sprint(s) of {p.sprint_weeks} weeks "
                f"({p.sprint_capacity_hours:g} h capacity). "
                + ("Validation passed." if report.passed else f"Validation found {len(report.failures)} issue(s).")
                + " Waiting for the tech lead's review (non-blocking).")
    deps.store.save(project)
    deps.tracer.record(project_id, {"type": "stage_end", "stage": Stage.PLAN.value})
    return project


def review_plan(deps: Deps, project: Project, approved: bool, comment: str = "") -> Project:
    """The tech lead reviews the plan. Non-blocking: it is recorded, and work is not held for it."""
    from ..state.models import PlanReview

    if project.plan is None:
        raise RuntimeError("There is no plan to review")
    project.plan.review = PlanReview(approved=approved, comment=comment)
    project.log(f"Tech lead {'approved' if approved else 'raised concerns on'} the plan: {comment}")
    deps.store.save(project)
    return project
