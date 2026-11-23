"""A client's answer becomes a requirement and closes its gap (no Stage 1 re-run needed)."""
from sdlc_agent import traceability
from sdlc_agent.gaps.register import add_gap, coverage_check
from sdlc_agent.questions.queue import answer_question, apply_saved_answers, ask, open_questions
from sdlc_agent.state.models import GapSource, GapStatus, Project


def _project():
    p = Project(id="p", name="t")
    blocking = add_gap(p, source=GapSource.NFR, description="No expected user scale", found_by="x")
    ask(p, "How many users in year one?", blocking=True, assumed_answer="10,000", related_gap_id=blocking.id)
    offered = add_gap(p, source=GapSource.DOMAIN_CHECKLIST, description="Chat (CL-05) is not in the brief",
                      found_by="x", status=GapStatus.RECOMMENDED)
    ask(p, "Do you want chat?", related_gap_id=offered.id)
    offered.status = GapStatus.RECOMMENDED  # ask() set it to assumed; offers stay offers
    return p


def test_answer_closes_the_gap_with_a_requirement():
    p = _project()
    changed = answer_question(p, "Q-001", "About 50,000 users, 2,000 at peak")
    gap = p.gaps[0]
    req = next(r for r in p.requirements if r.id == gap.linked_requirement_id)
    assert changed == ["GAP-001"] and gap.status is GapStatus.ANSWERED
    assert req.kind == "nfr" and req.source.label() == "client_answer:Q-001" and req.text.startswith("About 50,000")
    assert coverage_check(p).passed
    row = next(x for x in traceability.matrix(p) if x.requirement_id == req.id)
    assert "no input line" not in row.breaks
    assert [q.id for q in open_questions(p)] == ["Q-002"]


def test_answers_to_offered_additions_do_not_turn_them_into_requirements():
    p = _project()
    answer_question(p, "Q-002", "Yes please")
    assert p.gaps[1].status is GapStatus.RECOMMENDED and len(p.requirements) == 0  # opt-in happens at Gate 2


def test_saved_answers_from_older_projects_are_applied_once():
    p = _project()
    p.questions[0].answer = "Working assumption until answered: 10,000 users"  # caption pasted as the answer
    assert apply_saved_answers(p) == ["GAP-001"]
    assert p.requirements[0].text.startswith("10,000 users")
    assert apply_saved_answers(p) == []  # idempotent



def test_answer_to_an_inferred_item_confirms_the_assumption():
    p = Project(id="p", name="t")
    gap = add_gap(p, source=GapSource.INFERRED, description="Inferred platform: backend", found_by="x")
    ask(p, "Please confirm the backend", assumed_answer="Include backend", related_gap_id=gap.id)
    answer_question(p, "Q-001", "Yes, include the backend")
    assert p.requirements == [] and gap.status is GapStatus.ASSUMED
    assert p.assumptions[0].text.startswith("Client answer in Q-001: Yes, include the backend")
    assert open_questions(p) == []
