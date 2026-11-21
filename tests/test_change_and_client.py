"""Client decision after Gate 2, and the change-request path (re-enter Stage 1, re-estimate only what changed)."""
import pytest

from conftest import fake_read_url
from sdlc_agent import exports
from sdlc_agent.agents import change_analyst, estimator
from sdlc_agent.gaps.register import coverage_check
from sdlc_agent.orchestrator import (
    Deps, apply_change_request, decide_gate, finish_intake, gate_failures, record_client_decision, run_stage1,
    run_stage2, run_stage3, start_intake, submit_change_request,
)
from sdlc_agent.state.models import (
    ChangeRequest, GapStatus, Project, RawInput, Requirement, SourceRef, SowLine, Stage, StageStatus,
)

ROLES = ("tech_lead", "delivery_head", "sales")


@pytest.fixture
def deps(settings, fake_llm):
    return Deps(settings=settings, llm=fake_llm, read_url=fake_read_url, check_link=lambda url: True)


def approve(deps, project, gate):
    for role in ROLES:
        project = decide_gate(deps, project, gate, role, True)
    return project


def through_gate2(deps):
    project = deps.store.create("OLX-style app")
    start_intake(deps, project, [RawInput(kind="text", value="Build an app like OLX for Gujarat")])
    finish_intake(deps, project, {"competitors": "https://ref-one.example, https://ref-two.example"})
    project = approve(deps, run_stage1(deps, project.id), 1)
    run_stage2(deps, project.id)
    return approve(deps, run_stage3(deps, project.id), 2)


# ---------- client decision ----------

def test_client_opts_into_one_addition(deps):
    project = through_gate2(deps)
    offered = [g.id for g in project.gaps if g.status is GapStatus.RECOMMENDED]
    before = estimator.totals(project.estimate.base()).expected
    take = offered[0]
    project = record_client_decision(deps, project, True, [take], "Go ahead")

    gap = next(g for g in project.gaps if g.id == take)
    req = next(r for r in project.requirements if r.id == gap.linked_requirement_id)
    assert gap.status is GapStatus.ANSWERED and req.source.kind == "client_decision"
    assert all(g.status is GapStatus.OUT_OF_SCOPE for g in project.gaps if g.id in offered[1:])
    added = [t for t in project.estimate.tasks if t.gap_id == take]
    assert estimator.totals(project.estimate.base()).expected == pytest.approx(before + sum(t.expected for t in added))
    assert project.estimate.additions() == []
    assert coverage_check(project).passed and gate_failures(project, 2) == []


def test_client_decision_rules(deps):
    project = through_gate2(deps)
    with pytest.raises(ValueError, match="Not recommended"):
        record_client_decision(deps, project, True, ["GAP-999"])
    with pytest.raises(ValueError, match="only be opted into"):
        offered = next(g.id for g in project.gaps if g.status is GapStatus.RECOMMENDED)
        record_client_decision(deps, project, False, [offered])
    project = record_client_decision(deps, project, False, [], "Too expensive")
    assert project.stage_status[Stage.PROPOSAL] is StageStatus.REJECTED


def test_client_decision_needs_internal_gate2(deps):
    project = deps.store.create("x")
    with pytest.raises(RuntimeError, match="Gate 2"):
        record_client_decision(deps, project, True)


# ---------- change requests ----------

def test_change_request_reenters_stage1_and_reestimates_only_affected_work(deps):
    project = through_gate2(deps)
    common_before = [t.model_dump() for t in project.estimate.tasks if t.platform == "common"]
    additions_before = [t.model_dump() for t in project.estimate.additions()]

    project = submit_change_request(deps, project.id, "Sellers should be able to mark ads as sold. Allow 20 photos.")
    cr = project.change_requests[0]
    assert cr.id == "CR-001" and cr.status == "analysed"
    new_req = next(r for r in project.requirements if r.id in cr.added)
    assert new_req.source.kind == "change_request" and cr.changed == ["REQ-001"]
    assert project.requirements[0].text.endswith("20 photos") and project.requirements[0].changed_by == ["CR-001"]
    assert all(line.source.kind == "change_request" for line in project.sow_lines if line.id in cr.line_ids)
    assert any(g.description.startswith("CR-001:") and g.status is GapStatus.ASSUMED for g in project.gaps)
    # Re-enters at Stage 1: Gate 1 open, later stages pending, approvals and client decision cleared.
    assert project.stage_status[Stage.REQUIREMENTS] is StageStatus.WAITING_GATE
    assert project.stage_status[Stage.PLATFORM] is StageStatus.PENDING
    assert not project.gate_decisions and coverage_check(project).passed
    with pytest.raises(RuntimeError, match="Gate 1"):
        apply_change_request(deps, project.id)

    project = apply_change_request(deps, approve(deps, project, 1).id)
    rows = {d.platform: d for d in project.platform_matrix.decisions}
    assert new_req.id in rows["android"].requirement_ids and new_req.id in rows["ios"].requirement_ids
    assert any("smart_tv" in n for n in project.notes)  # unknown platform reported, not added
    # Only affected work was re-estimated: cross-cutting tasks and offered additions are untouched.
    assert [t.model_dump() for t in project.estimate.tasks if t.platform == "common"] == common_before
    assert [t.model_dump() for t in project.estimate.additions()] == additions_before
    ids = [t.id for t in project.estimate.tasks]
    assert len(ids) == len(set(ids))
    assert {new_req.id, "REQ-001"} <= {r for t in project.estimate.base() for r in t.requirement_ids}
    assert project.change_requests[0].status == "applied"
    assert project.stage_status[Stage.PROPOSAL] is StageStatus.WAITING_GATE
    assert gate_failures(project, 2) == []
    project = approve(deps, project, 2)
    assert record_client_decision(deps, project, True).client_decision.approved


def test_one_pending_change_request_at_a_time(deps):
    project = through_gate2(deps)
    submit_change_request(deps, project.id, "Add a dark mode to the app please")
    with pytest.raises(RuntimeError, match="pending"):
        submit_change_request(deps, project.id, "Another change for the app")


def test_full_stage1_rerun_supersedes_a_pending_change(deps):
    project = through_gate2(deps)
    project = run_stage1(deps, submit_change_request(deps, project.id, "Add a dark mode to the app").id)
    assert project.change_requests[0].status == "applied"
    assert any("covered by the full Stage 1 re-run" in n for n in project.notes)


def test_removed_requirements_stay_for_traceability():
    project = Project(id="p", name="t")
    project.requirements = [Requirement(id=f"REQ-00{i}", text=f"r{i}", source=SourceRef(kind="inferred"))
                            for i in (1, 2)]
    project.sow_lines = [SowLine(id="L-001", text="Drop the second feature please",
                                 source=SourceRef(kind="change_request", ref="CR-001"))]
    cr = ChangeRequest(id="CR-001", text="Drop the second feature please", line_ids=["L-001"])
    change_analyst.apply(project, cr, {"removed": [{"id": "REQ-002", "line_ids": ["L-001"]},
                                                  {"id": "REQ-404", "line_ids": []}]})
    assert cr.removed == ["REQ-002"]
    assert [r.id for r in project.active_requirements()] == ["REQ-001"]
    assert project.requirements[1].removed_by == "CR-001"
    assert project.sow_lines[0].requirement_ids == ["REQ-002"]  # the line is accounted for
    project.change_requests.append(cr)
    md = exports.requirements_markdown(project)
    assert "~~**REQ-002** r2~~ (removed by CR-001)" in md and "**CR-001** (analysed)" in md


def test_change_request_lines_continue_numbering():
    project = Project(id="p", name="t", sow_lines=[
        SowLine(id="L-001", text="a b c", source=SourceRef(kind="intake")),
        SowLine(id="L-002", text="d e f", source=SourceRef(kind="intake")),
    ])
    lines = change_analyst.lines_for(project, "CR-001", "- Add a dark mode\n- Remove chat")
    assert [line.id for line in lines] == ["L-003"]  # "Remove chat" is under 3 words
    assert lines[0].source.label() == "change_request:CR-001"
    assert [line.id for line in change_analyst.lines_for(project, "CR-002", "Remove chat")] == ["L-003"]
