"""Stage 8 QA and release, and Gate 4."""
import csv
import io

import pytest

from conftest import fake_read_url
from sdlc_agent import exports
from sdlc_agent.agents import qa
from sdlc_agent.build.git_host import FakeGitHost, LocalGitHost
from sdlc_agent.orchestrator import (
    Deps, decide_gate, finish_intake, record_client_decision, run_stage1, run_stage2, run_stage3, run_stage4,
    run_stage5, run_stage6, start_intake,
)
from sdlc_agent.orchestrator.build import build_next, in_scope, latest, mark_done_by_developers, mark_merged, next_ready
from sdlc_agent.orchestrator.release import record_test_result, run_stage8, set_checklist_item
from sdlc_agent.state.models import RawInput, Stage, StageStatus

ROLES = ("tech_lead", "delivery_head", "sales")


@pytest.fixture
def deps(settings, fake_llm):
    return Deps(settings=settings, llm=fake_llm, read_url=fake_read_url, check_link=lambda url: True)


def approve(deps, project, gate):
    for role in ROLES:
        project = decide_gate(deps, project, gate, role, True)
    return project


def built(deps, git):
    """Plan, let the agents build their tickets, and mark the rest done by developers."""
    project = deps.store.create("OLX-style app")
    start_intake(deps, project, [RawInput(kind="text", value="Build an app like OLX for Gujarat")])
    finish_intake(deps, project, {"competitors": "https://ref-one.example, https://ref-two.example"})
    project = approve(deps, run_stage1(deps, project.id), 1)
    run_stage2(deps, project.id)
    project = approve(deps, run_stage3(deps, project.id), 2)
    record_client_decision(deps, project, True)
    approve(deps, run_stage4(deps, project.id), 3)
    run_stage5(deps, project.id)
    project = run_stage6(deps, project.id)
    while (t := next_ready(project, 1)) is not None:
        project, rec = build_next(deps, project.id, git)
        if rec.status == "pr_open":
            project = mark_merged(deps, project, rec.ticket_id, git)
    for t in project.plan.tasks():
        rec = latest(project, t.id)
        if rec is None or rec.status != "merged":
            if t in in_scope(project, 1):  # an agent ticket that failed (QA has no tests): a human finishes it
                project.builds.append(rec.model_copy(update={"status": "merged", "error": "", "summary": "fixed by a developer"}))
                deps.store.save(project)
            else:
                project = mark_done_by_developers(deps, project, t.id, "https://example.test/pr/1")
    return project


def test_stage8_waits_for_every_ticket(deps):
    git = FakeGitHost()
    project = built(deps, git)
    project.builds.pop()
    deps.store.save(project)
    with pytest.raises(RuntimeError, match="not merged yet"):
        run_stage8(deps, project.id, git)


def test_mark_done_by_developers_rules(deps):
    git = FakeGitHost()
    project = built(deps, git)
    agent_ticket = in_scope(project, 1)[0]
    with pytest.raises(RuntimeError, match="agent ticket"):
        mark_done_by_developers(deps, project, agent_ticket.id)


def test_stage8_test_cases_scan_and_checklist(deps):
    git = FakeGitHost()
    project = run_stage8(deps, built(deps, git).id, git)
    rel = project.release
    assert project.stage_status[Stage.QA_RELEASE] is StageStatus.WAITING_GATE
    e2e = [c for c in rel.test_cases if c.kind == "e2e" and c.requirement_ids == ["REQ-001"]]
    assert e2e and all(c.result is None for c in rel.test_cases)
    api = next(c for c in rel.test_cases if c.title.startswith("API rejects"))
    assert api.kind == "integration" and "REQ-999" not in api.requirement_ids
    assert any("filed as e2e" in n for n in project.notes)  # "smoke" kind
    assert rel.scanned_files > 0 and rel.findings == []  # merged fake code is clean
    platforms = {i.platform for i in rel.checklist}
    assert {"android", "ios", "admin_panel", "backend", "all"} <= platforms


def test_gate4_needs_results_passing_cases_and_checklist(deps):
    git = FakeGitHost()
    project = run_stage8(deps, built(deps, git).id, git)
    failures = qa.release_check(project).failures
    assert any("has no result" in f for f in failures) and any("Checklist not done" in f for f in failures)
    with pytest.raises(RuntimeError, match="Gate 4"):
        decide_gate(deps, project, 4, "tech_lead", True)
    with pytest.raises(ValueError, match="note"):
        record_test_result(deps, project, project.release.test_cases[0].id, "waived")
    for c in project.release.test_cases:
        record_test_result(deps, project, c.id, "fail" if c.title == "Smoke check" else "pass")
    assert any("failed" in f for f in qa.release_check(project).failures)
    smoke = next(c for c in project.release.test_cases if c.title == "Smoke check")
    record_test_result(deps, project, smoke.id, "waived", "Covered by the e2e cases")
    for item in project.release.checklist:
        set_checklist_item(deps, project, item.id, True)
    assert qa.release_check(project).passed, qa.release_check(project).failures
    project = approve(deps, project, 4)
    assert project.stage_status[Stage.QA_RELEASE] is StageStatus.APPROVED


def test_security_scan_rules():
    files = {
        "app/android/app/src/main/AndroidManifest.xml": '<application android:debuggable="true">',
        "app/ios/Runner/Info.plist": "<key>NSAllowsArbitraryLoads</key>\n<true/>",
        "app/lib/api.dart": "const base = 'http://api.example.com';\nconst local = 'http://localhost:8080';",
        "server/src/client.ts": "process.env.NODE_TLS_REJECT_UNAUTHORIZED = '0'; eval(code);",
        "server/src/keys.ts": "const k = 'AKIAABCDEFGHIJKLMNOP';",
        "server/src/hash.py": "hashlib.md5(x)",
        "assets/logo.png": "http://evil.example.com",
    }
    found = {(f.severity, f.rule, f.path) for f in qa.security_scan(files)}
    assert ("high", "Android build is debuggable", "app/android/app/src/main/AndroidManifest.xml") in found
    assert ("medium", "iOS allows arbitrary network loads", "app/ios/Runner/Info.plist") not in found  # two lines
    assert ("medium", "Plain HTTP endpoint", "app/lib/api.dart") in found
    assert sum(1 for f in qa.security_scan(files) if f.path == "app/lib/api.dart") == 1  # localhost allowed
    assert ("medium", "TLS verification disabled", "server/src/client.ts") in found
    assert ("medium", "Dynamic code execution", "server/src/client.ts") in found
    assert ("high", "Possible secret in code", "server/src/keys.ts") in found
    assert ("low", "Weak hash (MD5/SHA-1)", "server/src/hash.py") in found
    assert not any(p == "assets/logo.png" for _, _, p in found)
    secret = next(f for f in qa.security_scan(files) if f.rule == "Possible secret in code")
    assert "AKIAABCDEFGHIJKLMNOP" not in secret.excerpt  # never echo the secret


def test_scan_reads_merged_code_from_the_local_repo(tmp_path, deps):
    git = LocalGitHost(tmp_path / "build")
    project = built(deps, git)
    git.commit_files("develop", {"app/lib/config.dart": "const api = 'http://api.example.com';"}, "T-000: config")
    project = run_stage8(deps, project.id, git)
    assert any(f.path == "app/lib/config.dart" and f.rule == "Plain HTTP endpoint" for f in project.release.findings)


def test_release_notes_and_test_report(deps):
    git = FakeGitHost()
    project = run_stage8(deps, built(deps, git).id, git)
    record_test_result(deps, project, project.release.test_cases[0].id, "waived", "Known flaky on old devices")
    notes = exports.release_notes_markdown(project)
    assert "REQ-001" in notes and "Known flaky on old devices" in notes and "dummy gateway" in notes
    rows = list(csv.DictReader(io.StringIO(exports.test_report_csv(project))))
    assert len(rows) == len(project.release.test_cases) and rows[0]["result"] == "waived"


def test_dashboard_release_screen_records_results(deps, settings, monkeypatch):
    from pathlib import Path

    from streamlit.testing.v1 import AppTest

    from conftest import FakeLLM
    from sdlc_agent.llm.ollama import OllamaClient

    import streamlit as st

    st.cache_resource.clear()  # the app caches its Deps; another test may have cached a different data folder
    monkeypatch.setenv("DATA_DIR", str(settings.data_dir))
    fake = FakeLLM()
    monkeypatch.setattr(OllamaClient, "complete",
                        lambda self, system, prompt, json_mode=False: fake.complete(system, prompt, json_mode=json_mode))
    built_project = built(deps, FakeGitHost())
    run_stage8(deps, built_project.id, FakeGitHost())

    app = str(Path(__file__).resolve().parents[1] / "dashboard" / "app.py")
    at = AppTest.from_file(app, default_timeout=30).run()
    at.session_state["project_id"] = built_project.id
    at.run()
    at.sidebar.radio[0].set_value("QA and release").run()
    assert not at.exception
    first = deps.store.load(built_project.id).release.test_cases[0]
    next(b for b in at.button if b.key == f"tc_{first.id}_pass").click().run()
    assert not at.exception
    assert deps.store.load(built_project.id).release.test_cases[0].result == "pass"
    at.sidebar.radio[0].set_value("Gate 4 approval").run()
    assert not at.exception
