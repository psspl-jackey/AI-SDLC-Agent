"""Traceability matrix: one row per requirement from source to pull request, with breaks flagged."""
import io

import pytest
from openpyxl import load_workbook

from conftest import fake_read_url
from sdlc_agent import traceability
from sdlc_agent.build.git_host import FakeGitHost
from sdlc_agent.orchestrator import (
    Deps, decide_gate, finish_intake, record_client_decision, run_stage1, run_stage2, run_stage3, run_stage4,
    run_stage5, run_stage6, start_intake,
)
from sdlc_agent.orchestrator.build import build_next, mark_merged, next_ready
from sdlc_agent.state.models import RawInput

ROLES = ("tech_lead", "delivery_head", "sales")


@pytest.fixture
def deps(settings, fake_llm):
    return Deps(settings=settings, llm=fake_llm, read_url=fake_read_url, check_link=lambda url: True)


def approve(deps, project, gate):
    for role in ROLES:
        project = decide_gate(deps, project, gate, role, True)
    return project


def stage1(deps):
    project = deps.store.create("OLX-style app")
    start_intake(deps, project, [RawInput(kind="text", value="Build an app like OLX for Gujarat")])
    finish_intake(deps, project, {"competitors": "https://ref-one.example, https://ref-two.example"})
    return run_stage1(deps, project.id)


def planned(deps):
    project = approve(deps, stage1(deps), 1)
    run_stage2(deps, project.id)
    project = approve(deps, run_stage3(deps, project.id), 2)
    record_client_decision(deps, project, True)
    approve(deps, run_stage4(deps, project.id), 3)
    run_stage5(deps, project.id)
    return run_stage6(deps, project.id)


def row(project, rid):
    return next(x for x in traceability.matrix(project) if x.requirement_id == rid)


def test_after_stage1_only_no_later_breaks_are_reported(deps):
    r = row(stage1(deps), "REQ-001")
    assert r.input_lines == ["L-001"] and r.status == "approved" and r.breaks == []


def test_full_chain_from_input_line_to_pull_request(deps):
    project = planned(deps)
    r = row(project, "REQ-001")
    assert r.platforms and r.tasks and r.hours > 0
    assert r.screens and r.endpoints == ["POST /ads"] and r.entities == ["Ad"]
    assert r.tickets and r.sprints == [1] and r.status == "planned" and r.breaks == []

    git = FakeGitHost()
    project, setup = build_next(deps, project.id, git)  # setup first; REQ-001 tickets depend on it
    project = mark_merged(deps, project, setup.ticket_id, git)
    req_tickets = {t.id for t in project.plan.tasks() if "REQ-001" in t.requirement_ids}
    rec = None
    while rec is None or rec.ticket_id not in req_tickets:  # QA (cross-cutting) may come first
        project, rec = build_next(deps, project.id, git)
    r = row(project, "REQ-001")
    assert r.status == "in review" and r.pull_requests == [rec.pr_url]
    assert r.test_files and all("test" in f for f in r.test_files)

    while (t := next_ready(project, 1)) is not None or any(b.status == "pr_open" for b in project.builds):
        if t is not None:
            project, rec = build_next(deps, project.id, git)
        for b in [b for b in project.builds if b.status == "pr_open"]:
            project = mark_merged(deps, project, b.ticket_id, git)
    assert row(project, "REQ-001").status == "delivered"


def test_breaks_and_removed_requirements(deps):
    project = planned(deps)
    for d in project.platform_matrix.decisions:
        d.requirement_ids = [x for x in d.requirement_ids if x != "REQ-001"]
    assert "no platform" in row(project, "REQ-001").breaks
    project.requirements[0].removed_by = "CR-001"
    r = row(project, "REQ-001")
    assert r.status == "removed" and r.change_requests == ["CR-001"] and r.breaks == []


def test_exports(deps):
    project = planned(deps)
    wb = load_workbook(io.BytesIO(traceability.xlsx(project)))
    assert wb.sheetnames == ["Traceability", "Input lines"]
    assert wb["Traceability"].max_row == len(project.requirements) + 1
    assert wb["Input lines"].max_row == len(project.sow_lines) + 1
    md = traceability.markdown(project)
    assert "| REQ-001" in md and "Input lines not accounted for: 0" in md
    assert traceability.summary(project)["planned"] >= 1
