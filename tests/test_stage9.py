"""Stage 9 handover: pack contents, runbook rules, client sign-off blocked by traceability breaks."""
import io
import zipfile

import pytest

from conftest import fake_read_url
from sdlc_agent import exports
from sdlc_agent.agents import handover
from sdlc_agent.build.git_host import FakeGitHost
from sdlc_agent.orchestrator import Deps, decide_gate
from sdlc_agent.orchestrator.handover import record_signoff, run_stage9
from sdlc_agent.orchestrator.release import record_test_result, run_stage8, set_checklist_item
from sdlc_agent.state.models import Stage, StageStatus
from test_stage8 import built

ROLES = ("tech_lead", "delivery_head", "sales")


@pytest.fixture
def deps(settings, fake_llm):
    return Deps(settings=settings, llm=fake_llm, read_url=fake_read_url, check_link=lambda url: True)


def released(deps):
    git = FakeGitHost()
    project = run_stage8(deps, built(deps, git).id, git)
    for c in project.release.test_cases:
        if c.title == "Smoke check":
            record_test_result(deps, project, c.id, "waived", "Covered by e2e")
        else:
            record_test_result(deps, project, c.id, "pass")
    for item in project.release.checklist:
        set_checklist_item(deps, project, item.id, True)
    for role in ROLES:
        project = decide_gate(deps, project, 4, role, True)
    return project


def test_stage9_needs_gate4(deps):
    with pytest.raises(RuntimeError, match="Gate 4"):
        run_stage9(deps, deps.store.create("x").id)


def test_runbook_only_keeps_items_with_steps(deps):
    project = run_stage9(deps, released(deps).id)
    tasks = [r.task for r in project.handover.runbook]
    assert tasks == ["Remove a reported ad", "Restore the database from backup"]  # no-steps and duplicate dropped
    assert project.handover.runbook[1].steps == ["Stop the API", "Restore the latest backup", "Start the API"]
    assert any("dropped runbook item" in n for n in project.notes)
    assert project.handover.version == "1.0.0"
    assert project.stage_status[Stage.HANDOVER] is StageStatus.WAITING_GATE


def test_documents_and_pack(deps):
    project = run_stage9(deps, released(deps).id)
    md = handover.handover_markdown(project)
    assert "**REQ-001**" in md and "dummy gateway" in md and "Covered by e2e" in md  # waived test listed
    guide = handover.maintenance_markdown(project)
    assert "## Flutter (Dart) (android, ios)" in guide and "### Remove a reported ad" in guide
    zf = zipfile.ZipFile(io.BytesIO(exports.handover_zip(project)))
    names = {n.split("/", 1)[1] for n in zf.namelist()}
    assert {"handover.md", "maintenance-guide.md", "traceability.xlsx", "release-notes.md", "architecture.md",
            "jira-import.csv", "estimate.xlsx", "skills/project-context/SKILL.md"} <= names


def test_signoff_blocked_by_traceability_breaks(deps):
    project = run_stage9(deps, released(deps).id)
    for d in project.platform_matrix.decisions:
        d.requirement_ids = [x for x in d.requirement_ids if x != "REQ-001"]
    with pytest.raises(RuntimeError, match="traceability"):
        record_signoff(deps, project, True, "Client PM")
    project = record_signoff(deps, project, False, "Client PM", "Platform mapping incomplete")
    assert project.stage_status[Stage.HANDOVER] is StageStatus.REJECTED


def test_signoff_completes_the_project(deps):
    project = run_stage9(deps, released(deps).id)
    assert handover.handover_check(project).passed, handover.handover_check(project).failures
    with pytest.raises(ValueError, match="who signed"):
        record_signoff(deps, project, True, " ")
    project = record_signoff(deps, project, True, "Client PM", "Accepted")
    assert project.stage_status[Stage.HANDOVER] is StageStatus.APPROVED
    assert "Accepted by Client PM" in handover.handover_markdown(project)


def test_dashboard_handover_signoff(deps, settings, monkeypatch):
    from pathlib import Path

    import streamlit as st
    from streamlit.testing.v1 import AppTest

    st.cache_resource.clear()
    monkeypatch.setenv("DATA_DIR", str(settings.data_dir))
    project = run_stage9(deps, released(deps).id)
    at = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "dashboard" / "app.py"), default_timeout=30).run()
    at.session_state["project_id"] = project.id
    at.run()
    at.sidebar.radio[0].set_value("Handover").run()
    assert not at.exception
    next(t for t in at.text_input if t.label.startswith("Signed by")).input("Client PM").run()
    next(b for b in at.button if b.label == "Record acceptance").click().run()
    assert not at.exception
    assert deps.store.load(project.id).stage_status[Stage.HANDOVER] is StageStatus.APPROVED
