"""Starter apps and the app runner: code-written skeletons per stack, and install/test/start on develop."""
import json
import re
import subprocess
import sys

import pytest

from sdlc_agent.build.git_host import FakeGitHost, LocalGitHost, check_files
from sdlc_agent.build.runner import AppRunner, port_open
from sdlc_agent.build.starters import app_name, load_starters, plan_apps, render_apps, seed_data
from sdlc_agent.orchestrator import Deps
from sdlc_agent.orchestrator.apps import add_starter_apps
from sdlc_agent.state.models import (
    PlatformDecision, PlatformMatrix, Project, ProjectBrief, RawInput, SolutionDesign, StackChoice,
)

STACKS = {"android": "react_native", "ios": "react_native", "web": "react_web", "admin_panel": "nextjs",
          "backend": "python_fastapi_backend"}


def project(stacks=STACKS, name="Build an app like OLX for Gujarat", domain="classifieds", region="India"):
    p = Project(id="p1", name=name, domain_pack=domain)
    p.raw_inputs = [RawInput(kind="text", value=name)]
    p.brief = ProjectBrief(summary="s", region=region)
    p.platform_matrix = PlatformMatrix(approach="cross_platform", decisions=[
        PlatformDecision(platform=k, included=True, reason="r") for k in stacks])
    p.design = SolutionDesign(stacks=[StackChoice(platform=k, pack=v) for k, v in stacks.items()])
    return p


def test_every_starter_names_a_real_tech_pack():
    from sdlc_agent.domain_packs import load_tech_packs
    packs = load_tech_packs()
    for name, spec in load_starters().items():
        assert name in packs and set(spec.platforms) <= set(packs[name]["platforms"])
        assert spec.raw["install"] and spec.raw["start"] and spec.raw["url"]


def test_one_app_per_surface_and_one_mobile_app_for_a_shared_pack():
    apps, notes = plan_apps(project())
    assert {a.surface: a.dir for a in apps} == {"web": "apps/web", "admin_panel": "apps/admin",
                                                "backend": "apps/backend", "mobile": "apps/mobile"}
    assert next(a for a in apps if a.surface == "mobile").platforms == ["android", "ios"]
    assert len({a.port for a in apps}) == 4 and notes == []


def test_packs_without_a_starter_are_reported_not_faked():
    apps, notes = plan_apps(project({"android": "kotlin_android", "ios": "swift_ios", "backend": "nodejs_backend"}))
    assert apps == []
    assert len(notes) == 3 and all("no starter app" in n for n in notes)


def test_rendered_files_are_complete_and_pass_the_git_guard():
    files, apps, _ = render_apps(project())
    for app_dir, f in files.items():
        assert all(path.startswith(app_dir + "/") for path in f)
        assert not [p for p, c in f.items() if re.search(r"\{\{\w+\}\}", c)], "unrendered placeholder"
        check_files(f)  # size, count, paths, secret scan: the same rules as agent code
    admin = files["apps/admin"]
    assert "apps/admin/src/App.tsx" in admin and "apps/admin/src/api.ts" in admin
    assert ":8000" in admin["apps/admin/src/api.ts"]
    seed = json.loads(files["apps/backend"]["apps/backend/seed.json"])
    assert seed["users"] and seed["items"] and any(i["status"] == "pending" for i in seed["items"])


def test_seed_follows_domain_and_region_and_never_uses_a_competitor_brand():
    seed = seed_data(project())
    assert seed["config"]["app_name"] == "Gujarat Classifieds"  # not "OLX for Gujarat"
    assert seed["config"]["currency"] == "INR" and "Ahmedabad" in seed["config"]["cities"]
    assert "Mobiles" in seed["categories"]
    shop = seed_data(project(name="Saree shop", domain="ecommerce", region="USA"))
    assert shop["config"]["app_name"] == "Saree shop" and shop["config"]["items_label"] == "Products"
    assert shop["config"]["currency"] == "USD"
    assert app_name(project(name="Build an app similar to Amazon", domain="ecommerce", region="India")) == "India Ecommerce"


def test_add_starter_apps_goes_through_the_guarded_flow(settings):
    deps = Deps(settings=settings)
    p = project()
    p.id = deps.store.create("x").id
    deps.store.save(p)
    git = FakeGitHost()
    p = add_starter_apps(deps, p.id, git)
    assert sorted(p.starter_apps) == ["apps/admin", "apps/backend", "apps/mobile", "apps/web"]
    assert {b for b, _ in git.commits} == {"feature/T-000-starter-apps"}
    assert all(m.startswith("T-000: ") for _, m in git.commits)
    assert git.pull_requests[0]["base"] == "develop" and "apps/mobile/App.tsx" in git.branches["develop"]
    # running it again adds nothing; refresh re-writes only the named app on a new branch
    add_starter_apps(deps, p.id, git)
    assert len(git.pull_requests) == 1
    add_starter_apps(deps, p.id, git, refresh=["apps/web"])
    assert git.pull_requests[1]["head"] == "feature/T-000-starter-apps-r2"


@pytest.mark.skipif(subprocess.run([sys.executable, "-c", "import fastapi, sqlalchemy, httpx"]).returncode != 0,
                    reason="fastapi not installed in this environment")
def test_backend_starter_tests_pass(tmp_path):
    files, _, _ = render_apps(project())
    for path, content in files["apps/backend"].items():
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"], cwd=tmp_path / "apps/backend",
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def test_runner_checks_out_develop_runs_commands_and_starts_and_stops(tmp_path):
    host = LocalGitHost(tmp_path)
    host.create_branch("feature/T-001-x", "develop")
    host.commit_files("feature/T-001-x", {"apps/hello/index.html": "hello"}, "T-001: x")
    host.merge("feature/T-001-x")
    r = AppRunner(tmp_path)
    commit = r.sync()
    assert (r.workspace / "apps/hello/index.html").read_text() == "hello" and commit
    assert r.run("apps/hello", "test -f index.html")[0] is True
    ok, out, _ = r.run("apps/hello", "echo boom && exit 3")
    assert ok is False and "boom" in out

    import socket
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = (f"import socket, time; s = socket.socket(); s.bind(('127.0.0.1', {port})); s.listen(); "
              "time.sleep(60)")  # http.server does a reverse DNS lookup that can hang offline
    pid = r.start("apps/hello", f'{sys.executable} -c "{server}"')
    try:
        for _ in range(50):
            if port_open(port):
                break
            import time
            time.sleep(0.1)
        assert port_open(port) and r.pid("apps/hello") == pid
        assert r.start("apps/hello", "ignored") == pid  # already running
    finally:
        assert r.stop("apps/hello")
    assert r.pid("apps/hello") is None
