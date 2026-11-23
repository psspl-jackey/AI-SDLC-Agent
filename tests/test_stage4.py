"""Stage 4 solution design and Gate 3: stacks from tech packs, traceability, dummy payment."""
import pytest

from conftest import fake_read_url
from sdlc_agent.agents import solution_design
from sdlc_agent.domain_packs import load_tech_packs
from sdlc_agent.orchestrator import (
    Deps, decide_gate, finish_intake, gate_failures, record_client_decision, run_stage1, run_stage2, run_stage3,
    run_stage4, start_intake, submit_change_request,
)
from sdlc_agent.state.models import (
    PlatformDecision, PlatformMatrix, Project, RawInput, Requirement, SourceRef, Stage, StageStatus,
)

ROLES = ("tech_lead", "delivery_head", "sales")


@pytest.fixture
def deps(settings, fake_llm):
    return Deps(settings=settings, llm=fake_llm, read_url=fake_read_url, check_link=lambda url: True)


def approve(deps, project, gate):
    for role in ROLES:
        project = decide_gate(deps, project, gate, role, True)
    return project


def client_approved(deps):
    project = deps.store.create("OLX-style app")
    start_intake(deps, project, [RawInput(kind="text", value="Build an Android and iOS app like OLX for Gujarat")])
    finish_intake(deps, project, {"competitors": "https://ref-one.example, https://ref-two.example"})
    project = approve(deps, run_stage1(deps, project.id), 1)
    run_stage2(deps, project.id)
    project = approve(deps, run_stage3(deps, project.id), 2)
    return record_client_decision(deps, project, True)


def test_tech_packs_are_well_formed():
    packs = load_tech_packs()
    assert {"flutter", "kotlin_android", "swift_ios", "react_web", "nodejs_backend"} <= set(packs)
    for name, p in packs.items():
        assert p["name"] == name
        assert set(p["platforms"]) <= {"android", "ios", "web", "admin_panel", "backend"}
        assert p["approach"] in ("native", "cross_platform", "web", "backend")
        for k in ("architecture", "conventions", "security", "testing", "ci"):
            # An unquoted "Label: text" list item parses as a dict, not a rule.
            assert p.get(k) and all(isinstance(r, str) for r in p[k]), f"{name}.{k}: quote rules containing ': '"


def test_stage4_needs_client_approval(deps):
    project = client_approved(deps)
    project.client_decision = None
    deps.store.save(project)
    with pytest.raises(RuntimeError, match="client"):
        run_stage4(deps, project.id)


def test_stage4_design_follows_the_rules(deps):
    project = run_stage4(deps, client_approved(deps).id)
    d = project.design
    assert {s.platform: s.pack for s in d.stacks} == {
        "android": "flutter", "ios": "flutter", "admin_panel": "react_web", "backend": "nodejs_backend"}
    api = next(c for c in d.components if c.name == "API")
    assert api.uses == ["Database"]  # unknown "Ghost service" link dropped
    assert [(e.method, e.path) for e in d.endpoints] == [("POST", "/ads")]  # normalised, deduped, bad dropped
    mobile = [s for s in d.screens if s.platform == "mobile"]  # cross-platform: one set of mobile screens
    assert [s.name for s in mobile] == ["Home", "Post ad"]
    assert mobile[0].navigates_to == [mobile[1].id]  # unknown S9 dropped
    assert {s.platform for s in d.screens} == {"mobile", "admin_panel"}
    assert project.stage_status[Stage.DESIGN] is StageStatus.WAITING_GATE
    assert gate_failures(project, 3) == []
    project = approve(deps, project, 3)
    assert project.stage_status[Stage.DESIGN] is StageStatus.APPROVED


def _project(approach, platforms, req_text="Sellers post ads"):
    p = Project(id="p", name="t")
    p.requirements = [Requirement(id="REQ-001", text=req_text, source=SourceRef(kind="inferred"))]
    p.platform_matrix = PlatformMatrix(approach=approach, decisions=[
        PlatformDecision(platform=x, included=True, reason="r", requirement_ids=["REQ-001"]) for x in platforms])
    return p


def _arch(stacks, components=()):
    return {"architecture": {"stacks": [{"platform": k, "pack": v} for k, v in stacks.items()],
                             "components": list(components)},
            "data": {"entities": [{"name": "Ad", "requirement_ids": ["REQ-001"]}],
                     "endpoints": [{"method": "GET", "path": "/ads", "requirement_ids": ["REQ-001"]}]},
            "screens": {"android": {"screens": [{"key": "S1", "name": "Home", "requirement_ids": ["REQ-001"]}]},
                        "ios": {"screens": [{"key": "S1", "name": "Home", "requirement_ids": ["REQ-001"]}]}}}


def test_check_rejects_mixed_stacks_for_cross_platform_and_unknown_packs():
    project = _project("cross_platform", ["android", "ios", "backend"])
    project.design, _ = solution_design.build_design(
        project, _arch({"android": "flutter", "ios": "swift_ios", "backend": "django"}))
    failures = solution_design.design_check(project).failures
    assert any("cross-platform" in f for f in failures)
    assert any("backend: stack 'django' has no tech pack" in f for f in failures)


def test_check_rejects_a_pack_on_the_wrong_platform_and_unscreened_apps():
    project = _project("native", ["android", "ios", "web", "backend"])
    project.design, _ = solution_design.build_design(
        project, _arch({"android": "kotlin_android", "ios": "swift_ios", "web": "flutter", "backend": "nodejs_backend"}))
    failures = solution_design.design_check(project).failures
    assert "web: tech pack flutter does not support web" in failures
    assert "web has no screens" in failures


def test_payment_always_goes_through_the_dummy_gateway():
    project = _project("native", ["android", "ios", "backend"], "Customers pay online at checkout")
    stacks = {"android": "kotlin_android", "ios": "swift_ios", "backend": "nodejs_backend"}
    project.design, notes = solution_design.build_design(project, _arch(stacks))
    assert any(c.name == "Dummy payment gateway" for c in project.design.components)
    assert solution_design.design_check(project).passed
    project.design, _ = solution_design.build_design(project, _arch(stacks, [
        {"name": "Razorpay", "kind": "external", "responsibility": "Card payments"}]))
    assert any("Razorpay: real payment providers are out of scope" in f
               for f in solution_design.design_check(project).failures)


def test_change_request_sends_design_back_to_pending(deps):
    project = approve(deps, run_stage4(deps, client_approved(deps).id), 3)
    project = submit_change_request(deps, project.id, "Sellers should be able to mark ads as sold")
    assert project.stage_status[Stage.DESIGN] is StageStatus.PENDING
    assert not [d for d in project.gate_decisions if d.gate == 3]


def test_rerunning_stage3_clears_the_design(deps):
    project = run_stage4(deps, client_approved(deps).id)
    project = run_stage3(deps, project.id)
    assert project.design is None and project.stage_status[Stage.DESIGN] is StageStatus.PENDING


def test_architecture_document(deps):
    from sdlc_agent import exports

    project = run_stage4(deps, client_approved(deps).id)
    md = exports.architecture_markdown(project)
    assert "| android | Flutter (Dart) | One codebase |" in md
    assert "n_API --> n_Database" in md and 'n_Database[("Database")]' in md
    assert "SCR_001 --> SCR_002" in md and "Passed." in md
