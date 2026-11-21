"""Stage 9 orchestration: handover pack and client sign-off."""
from __future__ import annotations

from ..agents import handover
from ..state.models import ClientSignoff, Project, Stage, StageStatus
from .pipeline import Deps, _reset_from


def run_stage9(deps: Deps, project_id: str) -> Project:
    project = deps.store.load(project_id)
    if project.stage_status[Stage.QA_RELEASE] is not StageStatus.APPROVED:
        raise RuntimeError("Gate 4 must approve the release before handover (Stage 9)")
    _reset_from(project, Stage.HANDOVER)
    project.stage_status[Stage.HANDOVER] = StageStatus.RUNNING
    deps.store.save(project)
    deps.tracer.record(project_id, {"type": "stage_start", "stage": Stage.HANDOVER.value})
    try:
        result = handover.run(deps.llm_for(project.id, handover.NAME), project)
    except Exception as exc:
        project.stage_status[Stage.HANDOVER] = StageStatus.FAILED
        project.log(f"Stage 9 failed: {exc!r}")
        deps.store.save(project)
        deps.tracer.record(project_id, {"type": "stage_failed", "stage": Stage.HANDOVER.value, "error": repr(exc)})
        raise
    handover.apply(project, result)
    report = handover.handover_check(project)
    project.stage_status[Stage.HANDOVER] = StageStatus.WAITING_GATE
    project.log(f"Handover pack ready with {len(project.handover.runbook)} runbook item(s). "
                + ("Ready for client sign-off." if report.passed
                   else f"{len(report.failures)} traceability issue(s) to fix before sign-off."))
    deps.store.save(project)
    deps.tracer.record(project_id, {"type": "stage_end", "stage": Stage.HANDOVER.value})
    return project


def record_signoff(deps: Deps, project: Project, accepted: bool, signed_by: str, comment: str = "") -> Project:
    if project.handover is None or project.stage_status[Stage.HANDOVER] not in (
        StageStatus.WAITING_GATE, StageStatus.REJECTED
    ):
        raise RuntimeError("There is no handover pack waiting for sign-off")
    if not signed_by.strip():
        raise ValueError("Record who signed off for the client")
    if accepted:
        failures = handover.handover_check(project).failures
        if failures:
            raise RuntimeError(f"Sign-off is blocked: {len(failures)} traceability issue(s), e.g. {failures[0]}")
    project.handover.signoff = ClientSignoff(accepted=accepted, signed_by=signed_by.strip(), comment=comment.strip())
    project.stage_status[Stage.HANDOVER] = StageStatus.APPROVED if accepted else StageStatus.REJECTED
    project.log(f"Client {'accepted' if accepted else 'did not accept'} the handover ({signed_by.strip()}): {comment}"
                + ("" if accepted else " Raise a change request for what is missing."))
    deps.store.save(project)
    return project
