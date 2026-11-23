"""Question queue for the ask-but-do-not-stop rule.

Non-blocking: the agent's assumed answer is logged as an assumption and work continues.
Blocking: only the related item waits (its gap stays open, with the assumption attached so
the rest of the flow can continue); everything else carries on.
"""
from __future__ import annotations

from ..state.models import Assumption, GapStatus, Project, Question, now
from ..state.store import next_id


def ask(
    project: Project,
    text: str,
    *,
    blocking: bool = False,
    assumed_answer: str | None = None,
    related_gap_id: str | None = None,
) -> Question:
    q = Question(
        id=next_id("Q", (x.id for x in project.questions)),
        text=text.strip(),
        blocking=blocking,
        related_gap_id=related_gap_id,
        assumed_answer=assumed_answer,
    )
    project.questions.append(q)

    if related_gap_id:
        gap = next((g for g in project.gaps if g.id == related_gap_id), None)
        if gap is not None:
            asm = Assumption(
                id=next_id("ASM", (a.id for a in project.assumptions)),
                text=assumed_answer or "No answer yet; proceed without this item until the client confirms.",
                related_gap_id=gap.id,
            )
            project.assumptions.append(asm)
            gap.assumption_id = asm.id
            gap.status = GapStatus.OPEN if blocking else GapStatus.ASSUMED
    return q


_CAPTION = "Working assumption until answered:"


def _close_gap_with_answer(project: Project, q: Question) -> str | None:
    """The client's answer feeds back into the requirements: it becomes a requirement (source: the question)
    and the gap is ANSWERED, linked to it. Gaps the system offered as additions or exclusions are left alone."""
    from ..state.models import Requirement, SourceRef

    gap = next((g for g in project.gaps if g.id == q.related_gap_id), None)
    if gap is None or gap.status not in (GapStatus.OPEN, GapStatus.ASSUMED) or not q.answer:
        return None
    answer = q.answer[len(_CAPTION):].strip() if q.answer.startswith(_CAPTION) else q.answer
    if gap.source.value == "inferred":
        # Something the system decided (a platform, an inferred feature) and the work already reflects:
        # the answer confirms or corrects the assumption; it does not add a new requirement.
        asm = next((a for a in project.assumptions if a.id == gap.assumption_id), None)
        if asm is not None and not asm.text.startswith("Client answer"):
            asm.text = f"Client answer in {q.id}: {answer} (was assumed: {asm.text})"
            gap.status = GapStatus.ASSUMED
            return f"assumption {asm.id}"
        return None
    kind = "nfr" if gap.source.value == "nfr" else "functional"
    req = Requirement(
        id=next_id("REQ", (r.id for r in project.requirements)),
        text=f"{answer} (client answer to {q.id}: {q.text})",
        kind=kind,
        source=SourceRef(kind="client_answer", ref=q.id),
    )
    project.requirements.append(req)
    gap.status, gap.linked_requirement_id = GapStatus.ANSWERED, req.id
    return req.id


def answer_question(project: Project, question_id: str, answer: str) -> list[str]:
    """Record an answer. The answer becomes a requirement and closes the related gap.
    Returns the gap ids that changed, so later stages can pick up the new requirement."""
    q = next(x for x in project.questions if x.id == question_id)
    q.answer, q.answered_at = answer.strip(), now()
    affected: list[str] = []
    req_id = _close_gap_with_answer(project, q) if q.related_gap_id else None
    if req_id:
        affected.append(q.related_gap_id)
        project.log(f"{q.id} answered; {q.related_gap_id} updated: {req_id}")
    else:
        project.log(f"{q.id} answered")
    return affected


def apply_saved_answers(project: Project) -> list[str]:
    """Close gaps whose questions were answered before answers became requirements (older projects)."""
    closed = []
    for q in project.questions:
        if q.answer and q.related_gap_id and _close_gap_with_answer(project, q):
            closed.append(q.related_gap_id)
    if closed:
        project.log(f"Applied {len(closed)} earlier client answer(s) as requirements: {', '.join(closed)}")
    return closed


def open_questions(project: Project) -> list[Question]:
    return [q for q in project.questions if q.answer is None]
