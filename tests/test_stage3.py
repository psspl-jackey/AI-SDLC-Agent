"""Stage 3 estimate and Gate 2: model proposes tasks, code validates hours and computes every total."""
import io

import pytest
from openpyxl import load_workbook

from conftest import fake_read_url
from sdlc_agent import exports
from sdlc_agent.agents import estimator
from sdlc_agent.orchestrator import (
    Deps, decide_gate, decide_gate1, finish_intake, gate_failures, run_stage1, run_stage2, run_stage3, start_intake,
)
from sdlc_agent.state.models import EstimateTask, GapStatus, RawInput, Stage, StageStatus


@pytest.fixture
def deps(settings, fake_llm):
    return Deps(settings=settings, llm=fake_llm, read_url=fake_read_url, check_link=lambda url: True)


def through_stage2(deps):
    project = deps.store.create("OLX-style app")
    start_intake(deps, project, [RawInput(kind="text", value="Build an Android and iOS app like OLX for Gujarat")])
    finish_intake(deps, project, {"competitors": "https://ref-one.example, https://ref-two.example"})
    project = run_stage1(deps, project.id)
    for role in ("tech_lead", "delivery_head", "sales"):
        project = decide_gate1(deps, project, role, True)
    return run_stage2(deps, project.id)


def test_stage3_needs_stage2(deps):
    project = deps.store.create("x")
    with pytest.raises(RuntimeError, match="Stage 2"):
        run_stage3(deps, project.id)


def test_stage3_estimate_follows_the_rules(deps):
    project = run_stage3(deps, through_stage2(deps).id)
    e = project.estimate
    platforms = {d.platform for d in project.platform_matrix.included()}
    # One feature task per included platform that serves REQ-001, plus 2 cross-cutting tasks.
    base = e.base()
    assert {t.platform for t in base} == (platforms & {"android", "ios", "admin_panel", "backend"}) | {"common"}
    post = [t for t in base if t.title.startswith("Post-ad flow")]
    assert all((t.hours_min, t.hours_likely, t.hours_max) == (16, 24, 40) for t in post)  # reordered by code
    assert not any(t.title == "Broken row" for t in e.tasks)  # zero hours dropped
    assert any("dropped \"Broken row\"" in n for n in project.notes)
    # Every recommended gap is estimated separately and stays out of the base total.
    recommended = {g.id for g in project.gaps if g.status is GapStatus.RECOMMENDED}
    assert recommended and {t.gap_id for t in e.additions()} == recommended
    assert estimator.totals(base).expected == pytest.approx(sum(t.expected for t in base))
    assert e.risk_buffer_pct == deps.settings.risk_buffer_pct
    assert project.stage_status[Stage.PROPOSAL] is StageStatus.WAITING_GATE
    assert gate_failures(project, 2) == []


def test_pert_expected_and_buffer():
    t = EstimateTask(id="TASK-001", module="m", feature="f", title="t", platform="android",
                     hours_min=10, hours_likely=20, hours_max=60)
    assert t.expected == pytest.approx(25.0)
    assert estimator.with_buffer(100, 15) == pytest.approx(115)


def test_check_flags_unestimated_requirements_and_additions(deps):
    project = run_stage3(deps, through_stage2(deps).id)
    project.estimate.tasks = [t for t in project.estimate.tasks if not t.requirement_ids and not t.gap_id]
    failures = estimator.estimate_check(project).failures
    assert any(f.startswith("REQ-001 has no estimated task") for f in failures)
    assert any(f.startswith("Recommended addition") for f in failures)


def test_addition_tasks_on_unknown_gap_or_excluded_platform_are_dropped(deps):
    project = through_stage2(deps)
    gid = next(g.id for g in project.gaps if g.status is GapStatus.RECOMMENDED)
    result = {"addition_tasks": [
        {"title": "ok", "gap_id": gid, "platform": "android", "hours_min": 1, "hours_likely": 2, "hours_max": 3},
        {"title": "bad gap", "gap_id": "GAP-999", "platform": "android", "hours_min": 1, "hours_likely": 2, "hours_max": 3},
        {"title": "bad platform", "gap_id": gid, "platform": "web", "hours_min": 1, "hours_likely": 2, "hours_max": 3},
    ], "platform_tasks": {"web": [{"title": "x", "hours_min": 1, "hours_likely": 2, "hours_max": 3}]}}
    e, notes = estimator.build_estimate(project, result, 15)
    assert [t.title for t in e.tasks] == ["ok"]
    assert len(notes) == 3


def test_gate2_needs_all_three_and_passing_checks(deps):
    project = run_stage3(deps, through_stage2(deps).id)
    saved = project.estimate.tasks
    project.estimate.tasks = []
    with pytest.raises(RuntimeError, match="Gate 2"):
        decide_gate(deps, project, 2, "tech_lead", True)
    project.estimate.tasks = saved
    for role in ("tech_lead", "delivery_head"):
        project = decide_gate(deps, project, 2, role, True)
    assert project.stage_status[Stage.PROPOSAL] is StageStatus.WAITING_GATE
    project = decide_gate(deps, project, 2, "sales", True)
    assert project.stage_status[Stage.PROPOSAL] is StageStatus.APPROVED


def test_rerunning_stage2_resets_stage3_and_gate2(deps):
    project = run_stage3(deps, through_stage2(deps).id)
    project = decide_gate(deps, project, 2, "tech_lead", True)
    project = run_stage2(deps, project.id)
    assert project.estimate is None
    assert project.stage_status[Stage.PROPOSAL] is StageStatus.PENDING
    assert not [d for d in project.gate_decisions if d.gate == 2]


def test_estimate_exports(deps):
    project = run_stage3(deps, through_stage2(deps).id)
    md = exports.estimate_markdown(project)
    assert "risk buffer" in md and "Recommended additions" in md and "Passed." in md
    wb = load_workbook(io.BytesIO(exports.estimate_xlsx(project)))
    assert wb.sheetnames == ["Tasks", "Summary"]
    assert wb["Tasks"].max_row == len(project.estimate.tasks) + 1
