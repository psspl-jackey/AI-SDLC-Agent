"""Stage 6 internal plan: tickets by code, model dependencies validated, sprints scheduled by code."""
import csv
import io

import pytest

from conftest import fake_read_url
from sdlc_agent import exports
from sdlc_agent.agents import planner
from sdlc_agent.orchestrator import (
    Deps, decide_gate, finish_intake, record_client_decision, review_plan, run_stage1, run_stage2, run_stage3,
    run_stage4, run_stage5, run_stage6, start_intake,
)
from sdlc_agent.state.models import RawInput, Stage, StageStatus, Ticket

ROLES = ("tech_lead", "delivery_head", "sales")


@pytest.fixture
def deps(settings, fake_llm):
    return Deps(settings=settings, llm=fake_llm, read_url=fake_read_url, check_link=lambda url: True)


def approve(deps, project, gate):
    for role in ROLES:
        project = decide_gate(deps, project, gate, role, True)
    return project


def skills_done(deps):
    project = deps.store.create("OLX-style app")
    start_intake(deps, project, [RawInput(kind="text", value="Build an Android and iOS app like OLX for Gujarat")])
    finish_intake(deps, project, {"competitors": "https://ref-one.example, https://ref-two.example"})
    project = approve(deps, run_stage1(deps, project.id), 1)
    run_stage2(deps, project.id)
    project = approve(deps, run_stage3(deps, project.id), 2)
    record_client_decision(deps, project, True)
    approve(deps, run_stage4(deps, project.id), 3)
    return run_stage5(deps, project.id)


def test_stage6_needs_stage5(deps):
    with pytest.raises(RuntimeError, match="Stage 5"):
        run_stage6(deps, deps.store.create("x").id)


def test_plan_tickets_dependencies_and_sprints(deps):
    project = run_stage6(deps, skills_done(deps).id)
    plan = project.plan
    tasks = {t.task_id: t for t in plan.tasks()}
    assert set(tasks) == {t.id for t in project.estimate.base()}  # one ticket per base task
    epics = [t for t in plan.tickets if t.type == "epic"]
    assert {e.summary for e in epics} == {t.module for t in project.estimate.base()}
    setup = next(t for t in plan.tasks() if "Project setup" in t.summary)
    qa = next(t for t in plan.tasks() if "Test plan" in t.summary)
    post = [t for t in plan.tasks() if "Post-ad flow" in t.summary]
    assert all(setup.id in t.depends_on for t in post) and qa.depends_on == [setup.id]
    # The android <-> ios cycle is broken; the self link and unknown ids are ignored.
    android = next(t for t in post if t.platform == "android")
    ios = next(t for t in post if t.platform == "ios")
    assert not (ios.id in android.depends_on and android.id in ios.depends_on)
    assert setup.depends_on == []
    assert any("closed a cycle" in n for n in project.notes)
    assert any("unknown task TASK-888" in n for n in project.notes)
    # Ticket descriptions carry what Stage 7 needs.
    assert "Follow skills: project-context, flutter" in android.description
    assert "REQ-001" in android.description and android.requirement_ids == ["REQ-001"]
    assert project.stage_status[Stage.PLAN] is StageStatus.DONE
    assert planner.plan_check(project).passed, planner.plan_check(project).failures


def _t(tid, hours, deps=()):
    return Ticket(id=tid, type="task", summary=tid, hours=hours, depends_on=list(deps))


def test_schedule_respects_capacity_and_dependencies():
    notes = []
    a, b, c, d, big = _t("A", 30), _t("B", 30, ["A"]), _t("C", 50), _t("D", 10, ["B"]), _t("E", 150)
    planner.schedule([a, b, c, d, big], capacity=60, notes=notes)
    assert (a.sprint, b.sprint, c.sprint, d.sprint) == (1, 1, 2, 2)
    assert big.sprint == 3  # bigger than a sprint: a sprint of its own
    assert any("bigger than one sprint" in n for n in notes)
    for t in (b, d):
        assert all({"A": a, "B": b}[x].sprint <= t.sprint for x in t.depends_on)


def test_tech_lead_review_is_recorded_but_not_blocking(deps):
    project = run_stage6(deps, skills_done(deps).id)
    project = review_plan(deps, project, False, "Split the admin work")
    assert project.plan.review.approved is False
    assert project.stage_status[Stage.PLAN] is StageStatus.DONE


def test_jira_csv_and_plan_document(deps):
    project = run_stage6(deps, skills_done(deps).id)
    rows = list(csv.DictReader(io.StringIO(exports.jira_csv(project))))
    assert len(rows) == len(project.plan.tickets)
    ids = {r["Issue Id"] for r in rows}
    task_rows = [r for r in rows if r["Issue Type"] == "Task"]
    assert all(r["Parent Id"] in ids and r["Sprint"].startswith("SDLC Sprint ") for r in task_rows)
    post = next(r for r in task_rows if "Post-ad flow" in r["Summary"])
    assert "REQ-001" in post["Labels"].split() and int(post["Original Estimate"]) > 0
    assert post["Depends on"] and all(x in ids for x in post["Depends on"].split())
    md = exports.plan_markdown(project)
    assert "## Sprint 1" in md and "## Validation report" in md and "Passed." in md


def test_rerunning_stage5_clears_the_plan(deps):
    project = run_stage6(deps, skills_done(deps).id)
    project = run_stage5(deps, project.id)
    assert project.plan is None and project.stage_status[Stage.PLAN] is StageStatus.PENDING
