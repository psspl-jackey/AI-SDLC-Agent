from datetime import date

from sdlc_agent.gaps.register import add_gap, coverage_check
from sdlc_agent.questions.queue import ask
from sdlc_agent.state.models import (
    GapSource, GapStatus, Project, Requirement, SourceRef, SowLine,
)


def make_project() -> Project:
    p = Project(id="t1", name="Test")
    p.sow_lines = [SowLine(id="L-001", text="Users can post ads", source=SourceRef(kind="intake"))]
    return p


def test_unmapped_line_fails_then_passes_when_mapped():
    p = make_project()
    assert not coverage_check(p).passed
    p.requirements.append(Requirement(id="REQ-001", text="Post ads", source=SourceRef(kind="intake")))
    p.sow_lines[0].requirement_ids.append("REQ-001")
    assert coverage_check(p).passed


def test_line_marked_not_a_requirement_passes():
    p = make_project()
    p.sow_lines[0].not_a_requirement = True
    assert coverage_check(p).passed


def test_gap_without_status_fails():
    p = make_project()
    p.sow_lines[0].not_a_requirement = True
    add_gap(p, source=GapSource.SOW, description="Filters undefined", found_by="t")
    report = coverage_check(p)
    assert not report.passed and "no status" in report.failures[0]


def test_competitor_gap_needs_evidence_and_date():
    p = make_project()
    p.sow_lines[0].not_a_requirement = True
    gap = add_gap(p, source=GapSource.COMPETITOR_TABLE_STAKES, description="Chat",
                  found_by="t", status=GapStatus.RECOMMENDED)
    assert not coverage_check(p).passed
    gap.evidence_url, gap.research_date = "https://example.com", date(2026, 11, 13)
    assert coverage_check(p).passed


def test_open_gap_needs_assumption_and_ask_attaches_one():
    p = make_project()
    p.sow_lines[0].not_a_requirement = True
    gap = add_gap(p, source=GapSource.NFR, description="Scale unknown", found_by="t", status=GapStatus.OPEN)
    assert not coverage_check(p).passed
    ask(p, "How many users?", blocking=True, assumed_answer="10k", related_gap_id=gap.id)
    assert gap.status is GapStatus.OPEN and gap.assumption_id
    assert coverage_check(p).passed


def test_answered_gap_must_link_real_requirement():
    p = make_project()
    p.sow_lines[0].not_a_requirement = True
    add_gap(p, source=GapSource.SOW, description="x", found_by="t", status=GapStatus.ANSWERED)
    assert not coverage_check(p).passed
