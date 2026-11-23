"""Runs Stage 0 -> Stage 1 -> Gate 1 end to end with a scripted model (no Ollama or Claude needed)."""
import pytest

from conftest import fake_read_url
from sdlc_agent.orchestrator import Deps, decide_gate1, finish_intake, run_stage1, start_intake
from sdlc_agent.gaps.register import coverage_check
from sdlc_agent.state.models import Bucket, GapSource, GapStatus, RawInput, Stage, StageStatus


@pytest.fixture
def deps(settings, fake_llm):
    return Deps(settings=settings, llm=fake_llm, read_url=fake_read_url, check_link=lambda url: True)


def run_to_gate(deps):
    project = deps.store.create("OLX-style app")
    questions = start_intake(deps, project, [RawInput(kind="text", value="Build an Android and iOS app like OLX for Gujarat")])
    asked = {q.key for q in questions}
    assert "domain" not in asked  # the brief already knows it
    finish_intake(deps, project, {"competitors": "https://ref-one.example, https://ref-two.example, QuickSell"})
    return run_stage1(deps, project.id)


def test_stage1_builds_a_complete_gap_register(deps):
    project = run_to_gate(deps)
    sources = {g.source for g in project.gaps}
    assert {GapSource.SOW, GapSource.NFR, GapSource.DOMAIN_CHECKLIST,
            GapSource.COMPETITOR_TABLE_STAKES, GapSource.COMPETITOR_DIFFERENTIATOR,
            GapSource.REVIEW_MINED, GapSource.INFERRED} <= sources
    chat = next(g for g in project.gaps if g.description.startswith("In-app chat"))
    assert chat.bucket is Bucket.TABLE_STAKES  # 2 of 2 competitors have it
    saved = next(g for g in project.gaps if g.description.startswith("Saved searches"))
    assert saved.bucket is Bucket.DIFFERENTIATOR  # only 1 of 2
    blocking = next(g for g in project.gaps if g.description == "No expected user scale")
    assert blocking.status is GapStatus.OPEN and blocking.assumption_id
    assert any("QuickSell" in q.text for q in project.questions)  # competitor without a link
    assert any("Digital Personal Data Protection" in g.description for g in project.gaps)  # Gujarat -> India
    assert project.stage_status[Stage.REQUIREMENTS] is StageStatus.WAITING_GATE
    assert coverage_check(project).passed, coverage_check(project).failures


def test_gate1_needs_all_three_approvers(deps):
    project = run_to_gate(deps)
    project = decide_gate1(deps, project, "tech_lead", True)
    project = decide_gate1(deps, project, "delivery_head", True)
    assert project.stage_status[Stage.REQUIREMENTS] is StageStatus.WAITING_GATE
    project = decide_gate1(deps, project, "sales", True)
    assert project.stage_status[Stage.REQUIREMENTS] is StageStatus.APPROVED


def test_gate1_blocked_when_coverage_fails(deps):
    project = run_to_gate(deps)
    project.gaps[0].status = None
    with pytest.raises(RuntimeError):
        decide_gate1(deps, project, "tech_lead", True)


def test_every_model_call_is_traced(deps):
    project = run_to_gate(deps)
    totals = deps.tracer.totals(project.id)
    assert totals["calls"] == len(deps.llm.calls) > 0
    assert totals["cost_usd"] > 0



def test_checklist_rules_are_enforced_by_code(deps):
    project = run_to_gate(deps)
    ids = {g.description.split("(")[-1].split(")")[0] for g in project.gaps if g.source is GapSource.DOMAIN_CHECKLIST}
    assert "CL-01" not in ids  # covered, with a real planned feature cited
    assert "CL-02" in ids  # "covered" without citing a planned feature is treated as missing
    assert "CL-10" in ids  # table stakes the model never answered are missing
    assert "CL-17" not in ids  # a common item may be ruled not relevant
    assert any("CL-02 claimed covered without citing" in n for n in project.notes)
