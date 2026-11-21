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


def answer_question(project: Project, question_id: str, answer: str) -> list[str]:
    """Record an answer. Returns the gap ids whose downstream work should be re-run."""
    q = next(x for x in project.questions if x.id == question_id)
    q.answer, q.answered_at = answer.strip(), now()
    affected: list[str] = []
    if q.related_gap_id:
        gap = next((g for g in project.gaps if g.id == q.related_gap_id), None)
        if gap is not None:
            affected.append(gap.id)
    project.log(f"{q.id} answered; re-run needed for {', '.join(affected) or 'nothing'}")
    return affected


def open_questions(project: Project) -> list[Question]:
    return [q for q in project.questions if q.answer is None]
