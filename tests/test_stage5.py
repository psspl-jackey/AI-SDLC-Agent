"""Stage 5 skills setup: company rules kept, project rules only added, Claude Code skill layout."""
import io
import zipfile

import pytest
import yaml

from conftest import fake_read_url
from sdlc_agent import exports
from sdlc_agent.agents import skills_setup
from sdlc_agent.domain_packs import load_tech_packs
from sdlc_agent.orchestrator import (
    Deps, decide_gate, finish_intake, record_client_decision, run_stage1, run_stage2, run_stage3, run_stage4,
    run_stage5, start_intake,
)
from sdlc_agent.state.models import RawInput, Stage, StageStatus

ROLES = ("tech_lead", "delivery_head", "sales")


@pytest.fixture
def deps(settings, fake_llm):
    return Deps(settings=settings, llm=fake_llm, read_url=fake_read_url, check_link=lambda url: True)


def approve(deps, project, gate):
    for role in ROLES:
        project = decide_gate(deps, project, gate, role, True)
    return project


def design_approved(deps):
    project = deps.store.create("OLX-style app")
    start_intake(deps, project, [RawInput(kind="text", value="Build an Android and iOS app like OLX for Gujarat")])
    finish_intake(deps, project, {"competitors": "https://ref-one.example, https://ref-two.example"})
    project = approve(deps, run_stage1(deps, project.id), 1)
    run_stage2(deps, project.id)
    project = approve(deps, run_stage3(deps, project.id), 2)
    record_client_decision(deps, project, True)
    return approve(deps, run_stage4(deps, project.id), 3)


def test_stage5_needs_gate3(deps):
    project = deps.store.create("x")
    with pytest.raises(RuntimeError, match="Gate 3"):
        run_stage5(deps, project.id)


def test_skill_pack_keeps_company_rules_and_only_adds_project_rules(deps):
    project = run_stage5(deps, design_approved(deps).id)
    files = {f.name: f for f in project.skill_pack.files}
    # One skill per tech pack in the design (flutter serves android and ios), plus the project context.
    assert set(files) == {"project-context", "flutter", "react-web", "nodejs-backend"}
    assert files["flutter"].platforms == ["android", "ios"]
    flutter = load_tech_packs()["flutter"]
    for section in skills_setup.SECTIONS:
        for rule in flutter[section]:
            assert f"- {rule}\n" in files["flutter"].content  # every company rule kept verbatim
    t = files["flutter"].tailored
    assert t["conventions"] == ["Name screens after the design's screen ids, e.g. SCR-001"]  # duplicate removed
    assert t["security"] == ["Never log ad photos' EXIF location", "Strip EXIF before upload"]  # string split
    assert len(t["testing"]) == skills_setup.MAX_ADDED_PER_SECTION  # capped
    assert "ci" not in t
    assert "_(project)_" in files["flutter"].content
    assert project.stage_status[Stage.SKILLS] is StageStatus.DONE
    assert skills_setup.skills_check(project).passed


def test_project_context_skill_is_built_from_the_design(deps):
    project = run_stage5(deps, design_approved(deps).id)
    ctx = next(f for f in project.skill_pack.files if f.name == "project-context")
    assert "`POST /ads`" in ctx.content and "**REQ-001**" in ctx.content
    assert "dummy payment gateway" in ctx.content and "Never push to `main`" in ctx.content
    assert ctx.tailored == {}  # written by code, no model


def test_skill_pack_zip_uses_claude_code_layout(deps):
    project = run_stage5(deps, design_approved(deps).id)
    zf = zipfile.ZipFile(io.BytesIO(exports.skill_pack_zip(project)))
    assert sorted(zf.namelist()) == ["skills/flutter/SKILL.md", "skills/nodejs-backend/SKILL.md",
                                     "skills/project-context/SKILL.md", "skills/react-web/SKILL.md"]
    text = zf.read("skills/flutter/SKILL.md").decode()
    front = yaml.safe_load(text.split("---")[1])
    assert front["name"] == "flutter" and front["description"].startswith("Use when")


def test_rerunning_stage4_clears_skills(deps):
    project = run_stage5(deps, design_approved(deps).id)
    project = run_stage4(deps, project.id)
    assert project.skill_pack is None and project.stage_status[Stage.SKILLS] is StageStatus.PENDING
