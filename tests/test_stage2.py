"""Stage 2 platform decision: model proposes, code enforces the rules."""
import pytest

from conftest import fake_read_url
from sdlc_agent import exports
from sdlc_agent.agents.platform_decision import build_matrix, client_platforms, normalise, platform_check
from sdlc_agent.orchestrator import Deps, decide_gate1, finish_intake, run_stage1, run_stage2, start_intake
from sdlc_agent.state.models import (
    CORE_PLATFORMS, GapSource, GapStatus, Project, ProjectBrief, RawInput, Requirement, SourceRef, Stage,
    StageStatus,
)


@pytest.fixture
def deps(settings, fake_llm):
    return Deps(settings=settings, llm=fake_llm, read_url=fake_read_url, check_link=lambda url: True)


def approved_project(deps):
    project = deps.store.create("OLX-style app")
    start_intake(deps, project, [RawInput(kind="text", value="Build an Android and iOS app like OLX for Gujarat")])
    finish_intake(deps, project, {"competitors": "https://ref-one.example, https://ref-two.example"})
    project = run_stage1(deps, project.id)
    for role in ("tech_lead", "delivery_head", "sales"):
        project = decide_gate1(deps, project, role, True)
    return project



def test_stage2_needs_gate1(deps):
    project = deps.store.create("x")
    start_intake(deps, project, [RawInput(kind="text", value="Build an Android and iOS app like OLX for Gujarat")])
    finish_intake(deps, project, {})
    run_stage1(deps, project.id)
    with pytest.raises(RuntimeError, match="Gate 1"):
        run_stage2(deps, project.id)


def test_stage2_builds_a_matrix_that_obeys_the_rules(deps):
    project = run_stage2(deps, approved_project(deps).id)
    m = project.platform_matrix
    rows = {d.platform: d for d in m.decisions}
    assert list(rows)[:5] == list(CORE_PLATFORMS)
    # The client stated android and ios (fake intake); the model dropped ios, code kept it.
    assert rows["ios"].included and rows["ios"].source == "client"
    assert rows["ios"].requirement_ids == rows["android"].requirement_ids == ["REQ-001"]  # mirrored
    assert rows["android"].source == "client"
    assert not rows["web"].included
    assert rows["admin_panel"].requirement_ids == ["REQ-001"]  # unknown REQ-999 dropped
    assert m.approach == "cross_platform"
    # Platforms the agent added on its own are visible as assumed gaps with a question.
    inferred = [g for g in project.gaps if g.found_by == "platform_decision"]
    assert {g.description.split(":")[1].split(".")[0].strip() for g in inferred} == {"admin panel", "backend"}
    assert all(g.source is GapSource.INFERRED and g.status is GapStatus.ASSUMED and g.assumption_id for g in inferred)
    assert project.stage_status[Stage.PLATFORM] is StageStatus.DONE
    assert any("left out ios" in n for n in project.notes)
    assert platform_check(project).passed, platform_check(project).failures


def test_rerunning_stage2_replaces_its_own_gaps_only(deps):
    project = run_stage2(deps, approved_project(deps).id)
    before = len(project.gaps), len(project.questions), len(project.assumptions)
    project = run_stage2(deps, project.id)
    assert (len(project.gaps), len(project.questions), len(project.assumptions)) == before


def test_rerunning_stage1_resets_stage2(deps):
    project = run_stage2(deps, approved_project(deps).id)
    project = run_stage1(deps, project.id)
    assert project.platform_matrix is None
    assert project.stage_status[Stage.PLATFORM] is StageStatus.PENDING


def _project(platforms, reqs):
    p = Project(id="p", name="t", brief=ProjectBrief(platforms=platforms))
    p.requirements = [Requirement(id=i, text=f"req {i}", source=SourceRef(kind="inferred")) for i in reqs]
    return p


def test_unmapped_requirements_go_to_every_app_and_missing_rows_are_added():
    project = _project(["web"], ["REQ-001", "REQ-002"])
    matrix, notes = build_matrix(project, {"platforms": [
        {"platform": "website", "included": True, "reason": "Customers order online", "requirement_ids": ["REQ-001"]},
    ]})
    project.platform_matrix = matrix
    failures = platform_check(project).failures
    web = next(d for d in matrix.decisions if d.platform == "web")
    assert "REQ-002" in web.requirement_ids and any("REQ-002 was not mapped" in n for n in notes)
    assert not any("REQ-002" in f for f in failures)
    assert not any("No decision" in f for f in failures)  # missing core rows are added as "no"
    assert sum("no decision returned" in n for n in notes) == 3  # android, ios, admin panel
    assert any("backend included by default" in n for n in notes)  # web needs a backend


def test_check_flags_an_included_platform_with_no_requirements():
    project = _project([], ["REQ-001"])
    project.platform_matrix, _ = build_matrix(project, {"platforms": [
        {"platform": "web", "included": True, "reason": "r", "requirement_ids": ["REQ-001"]},
        {"platform": "backend", "included": True, "reason": "r", "requirement_ids": []},
    ]})
    assert platform_check(project).failures == ["backend is included but serves no requirement"]


def test_mobile_means_android_and_ios():
    assert client_platforms(_project(["Mobile app", "Admin panel"], [])) == ["android", "ios", "admin_panel"]
    assert [normalise(x) for x in ("iPhone", "Back-end", "PWA", "back office", "Smart TV")] == \
        ["ios", "backend", "web", "admin_panel", "smart_tv"]


def test_platform_matrix_export(deps):
    project = run_stage2(deps, approved_project(deps).id)
    md = exports.platform_matrix_markdown(project)
    assert "| ios | yes | client |" in md and "Passed." in md



def test_people_can_set_platforms_yes_or_no_at_review(deps):
    from sdlc_agent.orchestrator import run_stage3, set_client_platforms

    project = run_stage2(deps, approved_project(deps).id)
    project = run_stage3(deps, project.id)
    project = set_client_platforms(deps, project.id, ["android", "ios", "web", "admin_panel"], ["backend"],
                                   "client wants mobile and moderation")
    rows = {d.platform: d for d in project.platform_matrix.decisions}
    assert all(rows[n].included and rows[n].source == "client" for n in ("android", "ios", "web", "admin_panel"))
    assert not rows["backend"].included and rows["backend"].reason == "Excluded by the client."
    assert any("the client excluded it" in n for n in project.notes)  # the fake agent wanted a backend
    assert project.estimate is None and project.stage_status[Stage.PROPOSAL] is StageStatus.PENDING  # reset
    assert project.brief.platforms == ["android", "ios", "web", "admin_panel"]
    with pytest.raises(ValueError):
        set_client_platforms(deps, project.id, [], ["android"])



def test_backend_is_included_by_default_with_client_apps():
    project = _project(["android"], ["REQ-001"])
    matrix, notes = build_matrix(project, {"platforms": [
        {"platform": "android", "included": True, "reason": "r", "requirement_ids": ["REQ-001"]}]})
    backend = next(d for d in matrix.decisions if d.platform == "backend")
    assert backend.included and backend.requirement_ids == ["REQ-001"] and backend.source == "inferred"
    project.brief.excluded_platforms = ["backend"]
    matrix, _ = build_matrix(project, {"platforms": [
        {"platform": "android", "included": True, "reason": "r", "requirement_ids": ["REQ-001"]}]})
    assert not next(d for d in matrix.decisions if d.platform == "backend").included
    matrix, _ = build_matrix(_project(["android"], ["REQ-001"]), {"platforms": [
        {"platform": "android", "included": True, "reason": "r", "requirement_ids": ["REQ-001"]},
        {"platform": "backend", "included": False, "reason": "Offline-only app", "requirement_ids": []}]})
    assert not next(d for d in matrix.decisions if d.platform == "backend").included  # a reasoned No stays



def test_approach_set_at_review_overrides_the_agent(deps):
    from sdlc_agent.orchestrator import set_client_platforms

    project = run_stage2(deps, approved_project(deps).id)  # the fake agent suggests cross_platform
    project = set_client_platforms(deps, project.id, ["android", "ios"], [], approach="native")
    assert project.platform_matrix.approach == "native"
    assert project.platform_matrix.approach_reason == "Set at the Stage 2 review."
    assert any("kept the approach set at review: native" in n for n in project.notes)
    with pytest.raises(ValueError, match="approach"):
        set_client_platforms(deps, project.id, ["android"], [], approach="hybrid")
