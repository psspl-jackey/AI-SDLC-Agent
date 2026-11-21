"""Eval runner: answer keys, code-based matching, scoring, and the CLI with the scripted model."""
from pathlib import Path

import pytest

from conftest import fake_read_url
from sdlc_agent.evals import KeyItem, load_key, main, score
from sdlc_agent.gaps.register import add_gap
from sdlc_agent.orchestrator import Deps
from sdlc_agent.questions.queue import ask
from sdlc_agent.state.models import GapSource, Project, Requirement, SourceRef

SAMPLES = Path(__file__).resolve().parents[1] / "samples"


def test_terms_match_at_word_start_only():
    item = KeyItem(id="X", text="", match=(("fast", "notif"),))
    assert item.matches("The app should be FAST")
    assert item.matches("No order notifications")
    assert not item.matches("Breakfast menu")


def test_all_groups_must_match():
    item = KeyItem(id="X", text="", match=(("pay",), ("dummy", "mock")))
    assert item.matches("Payment at checkout uses a dummy gateway")
    assert not item.matches("Customers pay online at checkout")


def test_ecommerce_key_loads():
    key = load_key(SAMPLES / "ecommerce_brief.answers.yaml")
    assert len(key.gaps) == 13 and len(key.requirements) == 8
    assert Path(key.input.value).exists()
    assert "platforms" not in key.intake_answers  # planted gap must not be answered at intake


@pytest.mark.parametrize("wording, expected", [
    ("Performance target is vague: 'fast' is not measurable", "P-01"),
    ("Launch before Diwali has no year, so the timeline cannot be checked", "P-02"),
    ("Target platforms (Android, iOS) are not stated", "P-03"),
    ("Login method is not defined (phone OTP or email)", "P-04"),
    ("No expected number of users or concurrent sessions", "P-05"),
    ("Compliance check: Digital Personal Data Protection Act, 2023", "P-06"),
    ("Search and filters (EC-02) is not in the brief", "P-07"),
    ("Returns and cancellations (EC-08) is not in the brief", "P-08"),
    ("Order and delivery notifications (EC-11) is not in the brief", "P-09"),
    ("Order history and order tracking (EC-07) is not in the brief", "P-10"),
    ("Ratings and reviews (EC-12) is not in the brief", "P-11"),
    ("Coupons and offers (EC-13) is not in the brief", "P-12"),
    ("GST invoice download (EC-16) is not in the brief", "P-13"),
])
def test_realistic_wordings_match_only_their_planted_gap(wording, expected):
    key = load_key(SAMPLES / "ecommerce_brief.answers.yaml")
    assert [g.id for g in key.gaps if g.matches(wording)] == [expected]


def test_bad_key_is_rejected(tmp_path):
    bad = tmp_path / "bad.answers.yaml"
    bad.write_text("input: {kind: text, value: hi}\ngaps:\n  - {id: G1, match: [fast]}\n")
    with pytest.raises(ValueError):
        load_key(bad)


def _key(tmp_path, body: str):
    path = tmp_path / "s.answers.yaml"
    path.write_text(body)
    return load_key(path)


KEY = """
name: classifieds_fake
input: {kind: text, value: "Build an app like OLX for Gujarat"}
intake_answers: {region: "Gujarat, India"}
gaps:
  - {id: P-1, text: Search filters undefined, match: [[filter]]}
  - {id: P-2, text: No user scale, match: [[scale]]}
  - {id: P-3, text: No moderation flow, match: [[moderation]]}
requirements:
  - {id: R-1, text: Post an ad, match: [[post], [ad]]}
  - {id: R-2, text: Chat, match: [[chat]]}
also_valid:
  - {id: V-1, text: Admin panel, match: [[admin]]}
"""


def test_score_counts_found_missed_and_extras(tmp_path):
    key = _key(tmp_path, KEY)
    project = Project(id="p1", name="t")
    project.requirements.append(Requirement(id="REQ-001", text="Sellers can post an ad", source=SourceRef(kind="inferred")))
    g1 = add_gap(project, source=GapSource.SOW, description="Search is vague", found_by="t")
    ask(project, "Which filters do buyers need?", related_gap_id=g1.id, assumed_answer="Price")  # match via question
    add_gap(project, source=GapSource.INFERRED, description="Inferred feature: Admin panel", found_by="t")
    add_gap(project, source=GapSource.SOW, description="Colour of the logo", found_by="t")

    result = score(project, key)
    assert result.found == {"P-1": ["GAP-001"]}
    assert result.missed == ["P-2", "P-3"]
    assert result.req_found == {"R-1": ["REQ-001"]} and result.req_missed == ["R-2"]
    assert result.also_valid_gaps == ["GAP-002"] and result.unmatched_gaps == ["GAP-003"]
    assert result.gap_recall == pytest.approx(1 / 3)


def test_cli_runs_stage0_and_stage1_and_writes_reports(tmp_path, settings, fake_llm, capsys):
    key_path = tmp_path / "s.answers.yaml"
    key_path.write_text(KEY)
    deps = Deps(settings=settings, llm=fake_llm, read_url=fake_read_url, check_link=lambda url: True)

    assert main([str(key_path)], deps=deps) == 0

    out = capsys.readouterr().out
    assert "classifieds_fake: gaps 2/3" in out  # filters and scale found, moderation missed
    reports = list((settings.data_dir / "reports").glob("*-classifieds_fake.md"))
    assert len(reports) == 1
    text = reports[0].read_text()
    assert "**missed** | P-3" in text and "Gate 1 coverage check: passed" in text
    assert list((settings.data_dir / "reports").glob("*-classifieds_fake.json"))
