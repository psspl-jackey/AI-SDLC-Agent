"""Stage 7 build: guarded git rules, ticket order, human merge, local git host."""
import json
import subprocess

import pytest

from conftest import fake_read_url
from sdlc_agent.agents import developer
from sdlc_agent.build.git_host import FakeGitHost, GitRuleError, GuardedGit, LocalGitHost, check_files
from sdlc_agent.orchestrator import (
    Deps, decide_gate, finish_intake, record_client_decision, run_stage1, run_stage2, run_stage3, run_stage4,
    run_stage5, run_stage6, start_intake,
)
from sdlc_agent.orchestrator.build import build_next, in_scope, mark_merged, next_ready
from sdlc_agent.state.models import RawInput, Stage, StageStatus

ROLES = ("tech_lead", "delivery_head", "sales")


@pytest.fixture
def deps(settings, fake_llm):
    return Deps(settings=settings, llm=fake_llm, read_url=fake_read_url, check_link=lambda url: True)


def approve(deps, project, gate):
    for role in ROLES:
        project = decide_gate(deps, project, gate, role, True)
    return project


def planned(deps):
    project = deps.store.create("OLX-style app")
    start_intake(deps, project, [RawInput(kind="text", value="Build an Android and iOS app like OLX for Gujarat")])
    finish_intake(deps, project, {"competitors": "https://ref-one.example, https://ref-two.example"})
    project = approve(deps, run_stage1(deps, project.id), 1)
    run_stage2(deps, project.id)
    project = approve(deps, run_stage3(deps, project.id), 2)
    record_client_decision(deps, project, True)
    approve(deps, run_stage4(deps, project.id), 3)
    run_stage5(deps, project.id)
    return run_stage6(deps, project.id)


# ---------- guard rules ----------

@pytest.mark.parametrize("branch", ["main", "develop", "master", "feature/no-key", "fix/T-001-x", "feature/T-001-UPPER"])
def test_guard_refuses_bad_branches(branch):
    with pytest.raises(GitRuleError):
        GuardedGit(FakeGitHost()).create_branch(branch)


@pytest.mark.parametrize("files", [
    {"../outside.txt": "x"}, {"/etc/passwd": "x"}, {".git/config": "x"}, {".env": "A=1"}, {"app/.env.local": "A=1"},
    {"keys/release.jks": "x"}, {"a.py": "KEY = 'sk-ant-api03-abcdefghijklmnop'"}, {"a.py": "AKIAABCDEFGHIJKLMNOP"},
    {"a.pem": "x"}, {"big.txt": "x" * 100_001}, {f"f{i}.py": "" for i in range(26)}, {},
])
def test_guard_refuses_unsafe_files(files):
    with pytest.raises(GitRuleError):
        check_files(files)


def test_guard_commit_and_pr_rules():
    git = GuardedGit(FakeGitHost())
    git.create_branch("feature/T-001-login")
    with pytest.raises(GitRuleError, match="must start"):
        git.commit_files("feature/T-001-login", {"a.py": "x"}, "add login", "T-001")
    with pytest.raises(GitRuleError, match="feature branches"):
        git.commit_files("develop", {"a.py": "x"}, "T-001: add login", "T-001")
    with pytest.raises(GitRuleError, match="REQ-002"):
        git.open_pull_request("feature/T-001-login", "T-001: login", "Implements REQ-001", ["REQ-001", "REQ-002"])
    assert git.open_pull_request("feature/T-001-login", "T-001: login", "Implements REQ-001", ["REQ-001"])
    assert git.host.pull_requests[0]["base"] == "develop"


def test_test_file_detection():
    assert all(developer.is_test_file(p) for p in (
        "app/test/x_test.dart", "src/__tests__/a.ts", "tests/test_api.py", "Foo.spec.ts", "LoginTest.kt"))
    assert not any(developer.is_test_file(p) for p in ("app/lib/login.dart", "src/latest.py", "contest.md"))


# ---------- the build flow ----------

def test_build_order_merge_and_handover(deps):
    project = planned(deps)
    git = FakeGitHost()
    scope = in_scope(project, deps.settings.build_max_sprint)
    setup = next(t for t in scope if "Project setup" in t.summary)
    assert next_ready(project, 1).id == setup.id  # everything else depends on setup

    project, rec = build_next(deps, project.id, git)
    assert rec.status == "pr_open" and rec.ticket_id == setup.id
    assert rec.branch == f"feature/{setup.id}-project-setup-and-ci"
    assert git.commits[0][1].startswith(f"{setup.id}: ")
    assert "Implements cross-cutting work" in git.pull_requests[0]["body"]
    assert next_ready(project, 1) is None  # blocked until a human merges setup
    project, rec = build_next(deps, project.id, git)
    assert rec is None and project.stage_status[Stage.BUILD] is StageStatus.RUNNING

    project = mark_merged(deps, project, setup.id, git)
    built = []
    while (t := next_ready(project, 1)) is not None:
        project, rec = build_next(deps, project.id, git)
        built.append(rec)
        if rec.status == "pr_open":
            project = mark_merged(deps, project, rec.ticket_id, git)
    assert all(b.status == "pr_open" or b.status == "merged" for b in built)
    assert all("REQ-001" in pr["body"] and pr["base"] == "develop" for pr in git.pull_requests[1:])
    assert len(git.pull_requests) == len(scope)  # every agent ticket built
    qa = next(t for t in project.plan.tasks() if "Test plan" in t.summary)
    assert qa not in scope  # QA planning is the team's ticket, not the developer agent's
    assert project.stage_status[Stage.BUILD] is StageStatus.DONE


def test_non_coding_tickets_go_to_the_team():
    from sdlc_agent.orchestrator.build import is_agent_ticket
    from sdlc_agent.state.models import Ticket

    def t(summary, role):
        return Ticket(id="T-1", type="task", summary=summary, role=role)

    # The ticket qwen2.5:7b's plan put in sprint 1 and the developer agent wrongly coded.
    assert not is_agent_ticket(t("[common] Design user interface for web platform", "UI/UX Designer"))
    assert not is_agent_ticket(t("[common] Test plan and regression", "QA"))
    assert not is_agent_ticket(t("[common] Sprint planning", "Project Manager"))
    assert is_agent_ticket(t("[web] Login screen", "Frontend Developer"))
    assert is_agent_ticket(t("[backend] Ads API", "Backend Engineer"))
    assert is_agent_ticket(t("[common] Project setup and CI", "tech lead"))
    assert is_agent_ticket(t("[web] Build design system components", "UI Developer"))
    assert is_agent_ticket(t("[web] Design and implement ad category selection", "Frontend Developer"))
    assert not is_agent_ticket(t("[web] Design the checkout wireframes", "Frontend Developer"))
    assert not is_agent_ticket(t("[common] Prepare and release application to app stores or web", "DevOps Engineer"))
    assert not is_agent_ticket(t("[android] Submit the build to the Play Store", "Mobile Developer"))
    assert not is_agent_ticket(t("[backend] Deploy to production", "DevOps Engineer"))
    assert is_agent_ticket(t("[common] Set up CI pipeline and deploy scripts", "DevOps Engineer"))


def test_docs_only_change_needs_no_tests_but_code_does():
    from sdlc_agent.agents.developer import needs_tests

    assert not needs_tests({"docs/test-plan.md": "# plan", "app/pubspec.yaml": "name: app"})
    assert needs_tests({"web/src/pages/index.tsx": "export default () => null"})
    assert not needs_tests({"web/src/pages/index.tsx": "x", "web/src/__tests__/index.test.tsx": "y"})


def test_handover_when_every_agent_ticket_is_merged(deps):
    project = planned(deps)
    git = FakeGitHost()
    while next_ready(project, 1) is not None:
        project, rec = build_next(deps, project.id, git)
        project = mark_merged(deps, project, rec.ticket_id, git)
    assert project.stage_status[Stage.BUILD] is StageStatus.DONE
    assert any("Human developers take over" in n for n in project.notes)


def test_build_needs_a_plan(deps):
    with pytest.raises(RuntimeError, match="Stage 6"):
        build_next(deps, deps.store.create("x").id, FakeGitHost())


def test_code_without_tests_is_asked_again_then_refused_and_not_repicked(deps):
    project = planned(deps)
    git = FakeGitHost()
    ticket = next(t for t in in_scope(project, 1) if "Post-ad flow" in t.summary)
    ticket.summary, ticket.depends_on = "[android] No tests feature", []
    project.plan.tickets = [t for t in project.plan.tickets if t.type == "epic" or t.id == ticket.id]
    deps.store.save(project)
    calls = len(deps.llm.calls)
    _, first = build_next(deps, project.id, git)
    assert first.status == "failed" and "even after asking again" in first.error
    assert len(deps.llm.calls) - calls == 2  # the ticket, then one follow-up asking only for tests
    project, again = build_next(deps, project.id, git)
    assert again is None  # not picked again automatically
    _, second = build_next(deps, project.id, git, retry_ticket_id=ticket.id)
    assert second.status == "failed" and second.branch.endswith("-r2")
    with pytest.raises(RuntimeError, match="not a failed ticket"):
        build_next(deps, project.id, git, retry_ticket_id="T-999")


def test_follow_up_call_adds_missing_tests(deps):
    project = planned(deps)
    git = FakeGitHost()
    ticket = next(t for t in in_scope(project, 1) if "Post-ad flow" in t.summary)
    ticket.summary, ticket.depends_on = "[android] Tests later feature", []
    project.plan.tickets = [t for t in project.plan.tickets if t.type == "epic" or t.id == ticket.id]
    deps.store.save(project)
    _, rec = build_next(deps, project.id, git)
    assert rec.status == "pr_open" and any("_test" in f for f in rec.files)


def test_local_git_host_creates_real_branches_and_merges(tmp_path, deps):
    project = planned(deps)
    host = LocalGitHost(tmp_path / "build")
    project, rec = build_next(deps, project.id, host)
    assert rec.status == "pr_open", rec.error
    repo = tmp_path / "build" / "repo"
    branches = subprocess.run(["git", "branch", "--list"], cwd=repo, capture_output=True, text=True).stdout
    assert rec.branch in branches and "develop" in branches
    prs = json.loads((tmp_path / "build" / "pull_requests.json").read_text())
    assert prs[0]["head"] == rec.branch and prs[0]["base"] == "develop"
    assert not (repo / "app" / "pubspec.yaml").exists()  # develop is untouched until the merge
    diff = host.diff(rec.branch)
    assert "app/pubspec.yaml" in diff and "+name: app" in diff  # what the reviewer sees before merging
    mark_merged(deps, project, rec.ticket_id, host)
    assert (repo / "app" / "pubspec.yaml").exists()


def test_new_plan_supersedes_build_records(deps):
    project = planned(deps)
    project, rec = build_next(deps, project.id, FakeGitHost())
    project = run_stage6(deps, project.id)
    assert all(b.status == "superseded" for b in project.builds)
    assert project.stage_status[Stage.BUILD] is StageStatus.PENDING


@pytest.mark.parametrize("path, content, expected", [
    ("web/package.json", '```json\n{"name": "web"}\n```', '{"name": "web"}\n'),
    ("src/app.py", "```python\nprint(1)\n```\n", "print(1)\n"),
    ("src/app.py", "print(1)\n", "print(1)\n"),
    ("README.md", "```bash\nnpm i\n```", "```bash\nnpm i\n```"),
])
def test_code_fences_around_generated_files_are_removed(path, content, expected):
    from sdlc_agent.agents.developer import clean_content
    assert clean_content(path, content) == expected
