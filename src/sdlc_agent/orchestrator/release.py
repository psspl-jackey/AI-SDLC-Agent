"""Stage 8 orchestration: QA and release, then Gate 4."""
from __future__ import annotations

from ..agents import qa
from ..build.git_host import GitHost
from ..state.models import Project, Stage, StageStatus, now
from .build import all_tickets_done, local_host
from .pipeline import Deps, _reset_from, gate_failures


def run_stage8(deps: Deps, project_id: str, git: GitHost | None = None, version: str = "1.0.0") -> Project:
    project = deps.store.load(project_id)
    if project.plan is None:
        raise RuntimeError("There is no plan; run Stages 6 and 7 first")
    open_tickets = all_tickets_done(project)
    if open_tickets:
        raise RuntimeError(f"{len(open_tickets)} ticket(s) are not merged yet ({', '.join(open_tickets[:8])}"
                           f"{'...' if len(open_tickets) > 8 else ''}); QA starts when the build is complete")
    _reset_from(project, Stage.QA_RELEASE)
    project.stage_status[Stage.QA_RELEASE] = StageStatus.RUNNING
    deps.store.save(project)
    deps.tracer.record(project_id, {"type": "stage_start", "stage": Stage.QA_RELEASE.value})
    try:
        result = qa.run(deps.llm_for(project.id, qa.NAME), project)
    except Exception as exc:
        project.stage_status[Stage.QA_RELEASE] = StageStatus.FAILED
        project.log(f"Stage 8 failed: {exc!r}")
        deps.store.save(project)
        deps.tracer.record(project_id, {"type": "stage_failed", "stage": Stage.QA_RELEASE.value, "error": repr(exc)})
        raise
    git = git or local_host(deps, project.id)
    files = git.read_tree("develop") if hasattr(git, "read_tree") else {}
    if not files:
        project.log("Security scan: no code found on develop to scan")
    project.release, notes = qa.build_release(project, result, files, version)
    for note in notes:
        project.log(note)
    rel = project.release
    high = sum(1 for f in rel.findings if f.severity == "high")
    project.stage_status[Stage.QA_RELEASE] = StageStatus.WAITING_GATE
    project.log(f"Release {rel.version}: {len(rel.test_cases)} test cases to run, {len(rel.findings)} security "
                f"finding(s) ({high} high) in {rel.scanned_files} files, {len(rel.checklist)} checklist items.")
    deps.store.save(project)
    deps.tracer.record(project_id, {"type": "stage_end", "stage": Stage.QA_RELEASE.value})
    return project


def record_test_result(deps: Deps, project: Project, case_id: str, result: str, note: str = "") -> Project:
    if project.release is None:
        raise RuntimeError("Stage 8 has not run")
    if result not in ("pass", "fail", "blocked", "waived"):
        raise ValueError(f"Unknown result {result}")
    if result == "waived" and not note.strip():
        raise ValueError("A waiver needs a note explaining why the release can go ahead")
    case = next((c for c in project.release.test_cases if c.id == case_id), None)
    if case is None:
        raise ValueError(f"Unknown test case {case_id}")
    case.result, case.note, case.run_at = result, note.strip(), now()
    deps.store.save(project)
    return project


def set_checklist_item(deps: Deps, project: Project, item_id: str, done: bool, note: str = "") -> Project:
    if project.release is None:
        raise RuntimeError("Stage 8 has not run")
    item = next((i for i in project.release.checklist if i.id == item_id), None)
    if item is None:
        raise ValueError(f"Unknown checklist item {item_id}")
    item.done, item.note = done, note.strip()
    deps.store.save(project)
    return project


def release_ready(project: Project) -> list[str]:
    return gate_failures(project, 4)
