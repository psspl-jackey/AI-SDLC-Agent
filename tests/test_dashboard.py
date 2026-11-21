"""Smoke test: every dashboard screen renders and Gate 1 can be approved by all three roles."""
from pathlib import Path

from streamlit.testing.v1 import AppTest

from conftest import FakeLLM, fake_read_url
from sdlc_agent.llm.ollama import OllamaClient
from sdlc_agent.orchestrator import Deps, finish_intake, run_stage1, start_intake
from sdlc_agent.state.models import RawInput, Stage, StageStatus

APP = str(Path(__file__).resolve().parents[1] / "dashboard" / "app.py")


def test_dashboard_screens_and_gate1(settings, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(settings.data_dir))
    monkeypatch.setenv("MODEL_PROVIDER", "ollama")
    fake = FakeLLM()
    monkeypatch.setattr(OllamaClient, "complete",
                        lambda self, system, prompt, json_mode=False: fake.complete(system, prompt, json_mode=json_mode))
    deps = Deps(settings=settings, llm=FakeLLM(), read_url=fake_read_url, check_link=lambda u: True)
    project = deps.store.create("Dashboard test")
    start_intake(deps, project, [RawInput(kind="text", value="Build an app like OLX for Gujarat")])
    finish_intake(deps, project, {"competitors": "https://a.example, https://b.example"})
    run_stage1(deps, project.id)

    at = AppTest.from_file(APP, default_timeout=30).run()
    assert not at.exception
    at.session_state["project_id"] = project.id
    at.run()
    for screen in ["Overview", "Questions", "Requirements", "Gap register",
                   "Gate 1 approval", "Platforms", "Estimate", "Gate 2 approval", "Change requests",
                   "Deliverables", "Trace and cost"]:
        at.sidebar.radio[0].set_value(screen).run()
        assert not at.exception, screen

    at.sidebar.radio[0].set_value("Gate 1 approval").run()
    for i in range(3):
        next(x for x in at.selectbox if x.label == "Approving as").select_index(i).run()
        next(b for b in at.button if b.label == "Approve").click().run()
        assert not at.exception
    assert deps.store.load(project.id).stage_status[Stage.REQUIREMENTS] is StageStatus.APPROVED

    # Stage 2 runs inside the dashboard, through the app's own (Ollama) client, patched to the fake model.
    at.sidebar.radio[0].set_value("Platforms").run()
    next(b for b in at.button if b.label == "Run Stage 2").click().run()
    assert not at.exception
    assert deps.store.load(project.id).stage_status[Stage.PLATFORM] is StageStatus.DONE
    assert any("Platform check passed" in s.value for s in at.success)

    at.sidebar.radio[0].set_value("Estimate").run()
    next(b for b in at.button if b.label == "Run Stage 3").click().run()
    assert not at.exception
    at.sidebar.radio[0].set_value("Gate 2 approval").run()
    for i in range(3):
        next(x for x in at.selectbox if x.label == "Approving as").select_index(i).run()
        next(b for b in at.button if b.label == "Approve").click().run()
        assert not at.exception
    assert deps.store.load(project.id).stage_status[Stage.PROPOSAL] is StageStatus.APPROVED
    at.multiselect[0].select(at.multiselect[0].options[0]).run()
    next(b for b in at.button if b.label == "Record client approval").click().run()
    assert not at.exception
    decision = deps.store.load(project.id).client_decision
    assert decision.approved and len(decision.opted_in_gap_ids) == 1

    at.sidebar.radio[0].set_value("Change requests").run()
    at.text_area[0].input("Sellers should be able to mark ads as sold").run()
    next(b for b in at.button if b.label == "Analyse change request").click().run()
    assert not at.exception
    assert deps.store.load(project.id).change_requests[0].status == "analysed"
    at.sidebar.radio[0].set_value("Deliverables").run()
    assert not at.exception
