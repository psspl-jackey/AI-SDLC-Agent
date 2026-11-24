"""Stage 7 runnable apps: starter apps written by code, then install, test, start and stop.

- add_starter_apps(): renders starters/ for the approved stacks and puts them on develop through the
  same GuardedGit rules as agent work (feature branch, ticket key T-000, pull request). Starter code
  is a reviewed template, not model output, so it is merged by code; this is logged.
- check_apps(): installs and tests every app on a checkout of develop; results go to project.run_checks
  so "done" can be compared with "it runs".
- start_apps() / stop_apps() / app_status(): run the apps with their dummy data for people to try.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

from ..build.git_host import GitHost, GuardedGit, LocalGitHost
from ..build.runner import AppRunner, lan_ip, lan_ips, port_open
from ..build.starters import AppPlan, plan_apps, render_apps, theme_files
from ..state.models import Project, RunCheck
from .pipeline import Deps

STARTER_KEY = "T-000"
INSTALL_TIMEOUT, TEST_TIMEOUT, START_WAIT = 1200, 900, 90


def runner(deps: Deps, project_id: str) -> AppRunner:
    return AppRunner(deps.settings.data_dir / "build" / project_id)


def add_starter_apps(deps: Deps, project_id: str, git: GitHost | None = None,
                     refresh: list[str] | None = None) -> Project:
    """Add the starter apps not yet in the repo. refresh: app folders to re-write from the current
    templates (overwrites starter files there, so only use it before tickets have changed them)."""
    project = deps.store.load(project_id)
    if project.design is None:
        raise RuntimeError("Approve the solution design (Stage 4) first: starter apps follow the chosen stacks")
    files_by_app, apps, notes = render_apps(project)
    new = {d: f for d, f in files_by_app.items() if d not in project.starter_apps or d in (refresh or [])}
    for note in notes:
        project.log(f"Starter apps: {note}")
    if not new:
        deps.store.save(project)
        return project
    git = git or LocalGitHost(deps.settings.data_dir / "build" / project.id)
    guarded = GuardedGit(git)
    attempt = sum(1 for line in project.notes if "Starter apps: pull request" in line)
    branch = "feature/T-000-starter-apps" + (f"-r{attempt + 1}" if attempt else "")
    guarded.create_branch(branch)
    for app_dir, files in new.items():
        guarded.commit_files(branch, files, f"{STARTER_KEY}: starter app {app_dir} (written by code from starters/)",
                             STARTER_KEY)
    body = "\n".join([
        "Starter apps written by code from the approved stacks (starters/), not by the model.", "",
        *[f"- `{d}` ({a.pack}, {', '.join(a.platforms)})" for a in apps for d in [a.dir] if d in new], "",
        "Each app runs with dummy data; agent and developer tickets add features inside them.",
    ])
    pr = guarded.open_pull_request(branch, f"{STARTER_KEY}: starter apps", body, [])
    if hasattr(git, "merge"):
        git.merge(branch)
    project.starter_apps += [d for d in new if d not in project.starter_apps]
    project.log(f"Starter apps: pull request {pr} from {branch} merged into develop by code "
                f"(templates, not model output): {', '.join(new)}")
    deps.store.save(project)
    return project


def apply_theme(deps: Deps, project_id: str, git: GitHost | None = None) -> Project:
    """Re-write only the theme files of the starter apps (src/theme.ts) after the UI theme changed.
    Feature code is untouched. Running apps pick the change up live (their dev servers watch files)."""
    project = deps.store.load(project_id)
    files = theme_files(project)
    if not files:
        raise RuntimeError("No starter apps with a UI yet: add the starter apps first")
    git = git or LocalGitHost(deps.settings.data_dir / "build" / project.id)
    if hasattr(git, "read_tree"):
        current = git.read_tree("develop")
        files = {k: v for k, v in files.items() if current.get(k, "").strip() != v.strip()}
        if not files:
            project.log("UI theme: the apps already use this theme")
            deps.store.save(project)
            return project
    guarded = GuardedGit(git)
    n = sum(1 for line in project.notes if "UI theme applied" in line) + 1
    branch = f"feature/T-000-ui-theme-{n}"
    guarded.create_branch(branch)
    guarded.commit_files(branch, files, f"{STARTER_KEY}: apply the UI theme ({project.design.theme.source.replace('_', ' ')})"
                         if project.design and project.design.theme else f"{STARTER_KEY}: apply the UI theme", STARTER_KEY)
    pr = guarded.open_pull_request(branch, f"{STARTER_KEY}: UI theme", "Theme files re-written from the approved UI "
                                   "theme (Stage 4). No feature code changed.", [])
    if hasattr(git, "merge"):
        git.merge(branch)
    r = runner(deps, project_id)
    if (r.workspace / ".git").exists():
        r.sync()  # running dev servers reload the new theme
    project.log(f"UI theme applied to {', '.join(sorted(files))} ({pr}, merged by code)")
    deps.store.save(project)
    return project


def _apps(project: Project) -> list[AppPlan]:
    apps, _ = plan_apps(project)
    return [a for a in apps if a.dir in project.starter_apps]


def _record(project: Project, app: AppPlan, step: str, ok: bool, command: str, output: str, seconds: float, commit: str):
    project.run_checks.append(RunCheck(app=app.dir, step=step, ok=ok, command=command, output=output,
                                       seconds=seconds, commit=commit))
    project.log(f"Run check: {app.dir} {step} {'passed' if ok else 'FAILED'} ({seconds:.0f} s)")


def _steps(r: AppRunner, project: Project, app: AppPlan, step: str, commands: list[str], timeout: int, commit: str) -> bool:
    outputs, total = [], 0.0
    for cmd in commands:
        command = r.format(cmd, app.port)
        ok, out, secs = r.run(app.dir, command, timeout)
        outputs.append(f"$ {command}\n{out}")
        total += secs
        if not ok:
            _record(project, app, step, False, command, "\n".join(outputs)[-4000:], total, commit)
            return False
    _record(project, app, step, True, " && ".join(commands), "\n".join(outputs)[-4000:], total, commit)
    return True


def check_apps(deps: Deps, project_id: str, steps: tuple[str, ...] = ("install", "test")) -> Project:
    """Install and test every starter app on the current develop."""
    project = deps.store.load(project_id)
    apps = _apps(project)
    if not apps:
        raise RuntimeError("No starter apps yet: add them first")
    r = runner(deps, project_id)
    commit = r.sync()
    for app in apps:
        ok = True
        if "install" in steps:
            ok = _steps(r, project, app, "install", app.install, INSTALL_TIMEOUT, commit)
        if ok and "test" in steps and app.test:
            _steps(r, project, app, "test", app.test, TEST_TIMEOUT, commit)
        deps.store.save(project)
    return project


def _installed(r: AppRunner, app: AppPlan) -> bool:
    base = r.workspace / app.dir
    return (base / "node_modules").exists() or (base / ".venv").exists()


def start_apps(deps: Deps, project_id: str) -> Project:
    """Start every app (installing first where needed) and wait until each one listens on its port."""
    project = deps.store.load(project_id)
    apps = _apps(project)
    if not apps:
        raise RuntimeError("No starter apps yet: add them first")
    r = runner(deps, project_id)
    if not any(r.pid(a.dir) for a in apps):
        commit = r.sync()
    else:
        commit = r._git("rev-parse", "--short", "HEAD", cwd=r.workspace)
    for app in sorted(apps, key=lambda a: a.surface != "backend"):  # backend first
        if not _installed(r, app) and not _steps(r, project, app, "install", app.install, INSTALL_TIMEOUT, commit):
            continue
        command = r.format(app.start, app.port)
        r.start(app.dir, command)
        began = time.monotonic()
        while time.monotonic() - began < START_WAIT and not port_open(app.port) and r.pid(app.dir):
            time.sleep(1)
        ok = port_open(app.port) and r.pid(app.dir) is not None
        _record(project, app, "start", ok, command, r.log_tail(app.dir), round(time.monotonic() - began, 1), commit)
        deps.store.save(project)
    return project


def stop_apps(deps: Deps, project_id: str) -> list[str]:
    project = deps.store.load(project_id)
    r = runner(deps, project_id)
    stopped = [a.dir for a in _apps(project) if r.stop(a.dir)]
    return stopped


@dataclass
class AppStatus:
    dir: str
    surface: str
    pack: str
    platforms: list[str]
    running: bool
    listening: bool
    url: str
    urls: list[str]  # mobile: one Expo address per local network
    log: str
    last_install: RunCheck | None
    last_test: RunCheck | None


def app_status(deps: Deps, project: Project) -> list[AppStatus]:
    r = runner(deps, project.id)
    ip = lan_ip()
    out = []
    for app in _apps(project):
        last = lambda step: next((c for c in reversed(project.run_checks) if c.app == app.dir and c.step == step), None)  # noqa: E731
        out.append(AppStatus(
            dir=app.dir, surface=app.surface, pack=app.pack, platforms=app.platforms,
            running=r.pid(app.dir) is not None, listening=port_open(app.port),
            url=app.url.format(port=app.port, lan_ip=ip),
            urls=[app.url.format(port=app.port, lan_ip=x) for x in lan_ips()] if "{lan_ip}" in app.url else [],
            log=r.log_tail(app.dir, 3000),
            last_install=last("install"), last_test=last("test"),
        ))
    return out
