"""Orchestrator: Stage 0 (intake), Stage 1 (requirements and gap analysis) and Gate 1, Stage 2 (platforms).

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

from ..agents import domain_research, platform_decision, requirements_analyst, reviewer
from ..config import Settings, get_settings
from ..gaps.register import add_gap, coverage_check, gate_passed, gate_status
from ..intake.brief import apply_intake_answers, build_brief, completeness_of, extract_sow_lines
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
    # Stage 2 was built on the old requirements, so it must run again after the new Gate 1.
    project.platform_matrix = None
    project.stage_status[Stage.PLATFORM] = StageStatus.PENDING
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


# ---------- Gate 1 ----------

def decide_gate1(deps: Deps, project: Project, role: str, approved: bool, comment: str = "") -> Project:
    if project.stage_status[Stage.REQUIREMENTS] not in (StageStatus.WAITING_GATE, StageStatus.REJECTED):
        raise RuntimeError("Stage 1 is not waiting for Gate 1")
    report = coverage_check(project)
    if approved and not report.passed:
        raise RuntimeError("Gate 1 cannot be approved while the coverage check has failures")
    project.gate_decisions.append(GateDecision(gate=1, role=role, approved=approved, comment=comment))
    if not approved:
        project.stage_status[Stage.REQUIREMENTS] = StageStatus.REJECTED
        project.log(f"Gate 1 rejected by {role}: {comment}")
    elif gate_passed(project, 1):
        project.stage_status[Stage.REQUIREMENTS] = StageStatus.APPROVED
        project.log("Gate 1 approved by tech lead, delivery head and sales")
    else:
        project.stage_status[Stage.REQUIREMENTS] = StageStatus.WAITING_GATE
        waiting = [r for r, v in gate_status(project, 1).items() if v is not True]
        project.log(f"Gate 1 approved by {role}; waiting for {', '.join(waiting)}")
    deps.store.save(project)
    return project


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
    _clear_stage2(project)
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
