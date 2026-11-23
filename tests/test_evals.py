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
input: {kind: text, value: "Build an Android and iOS app like OLX for Gujarat"}
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
    assert "classifieds_fake: gaps 3/3" in out  # unanswered checklist items (moderation) count as missing
    reports = list((settings.data_dir / "reports").glob("*-classifieds_fake.md"))
    assert len(reports) == 1
    text = reports[0].read_text()
    assert "found | P-3" in text and "Gate 1 coverage check: passed" in text
    assert list((settings.data_dir / "reports").glob("*-classifieds_fake.json"))


# Expected planted gap for each classifieds pack item, worded exactly as domain_research words it.
CLASSIFIEDS_PACK_EXPECTED = {
    "CL-01": None, "CL-02": "P-03", "CL-03": "P-11", "CL-04": "P-12", "CL-05": "P-13", "CL-06": "P-02",
    "CL-07": "P-14", "CL-08": "P-15", "CL-09": "P-16", "CL-10": "P-17", "CL-11": "P-18", "CL-12": "P-19",
    "CL-13": "P-20", "CL-14": "P-04", "CL-15": None, "CL-16": None, "CL-17": "P-05",
}


def test_classifieds_pack_wordings_match_one_planted_gap_each():
    from sdlc_agent.domain_packs import load_packs

    key = load_key(SAMPLES / "one_line_classifieds.answers.yaml")
    pack = load_packs()["classifieds"]
    assert {f["id"] for f in pack["features"]} == set(CLASSIFIEDS_PACK_EXPECTED)
    for feat in pack["features"]:
        text = f"{feat['name']} ({feat['id']}) is not in the brief"
        expected = CLASSIFIEDS_PACK_EXPECTED[feat["id"]]
        assert [g.id for g in key.gaps if g.matches(text)] == ([expected] if expected else []), text
    notes = [f"Compliance check: {c['note']}" for c in pack["compliance"]]
    assert [[g.id for g in key.gaps if g.matches(n)] for n in notes] == [["P-08"], ["P-09"]]


@pytest.mark.parametrize("wording, expected", [
    ("Target platforms (Android, iOS, web) are not stated", "P-01"),
    ("Login method is not defined", "P-02"),
    ("Item categories are not defined", "P-03"),
    ("No revenue model: are listings free or are there paid featured ads?", "P-04"),
    ("Gujarati language support is not stated", "P-05"),
    ("No expected number of users", "P-06"),
    ("Images should be compressed for slow mobile networks", "P-07"),
    ("No spam or fake listing detection", "P-10"),
])
def test_classifieds_sow_and_nfr_wordings(wording, expected):
    key = load_key(SAMPLES / "one_line_classifieds.answers.yaml")
    assert [g.id for g in key.gaps if g.matches(wording)] == [expected]


def test_exclude_terms_reject_a_match():
    item = KeyItem(id="X", text="", match=(("chat",),), exclude=("notif",))
    assert item.matches("In-app buyer-seller chat")
    assert not item.matches("Push notifications for chats")



@pytest.mark.parametrize("key_file, wording", [
    # False matches seen in the first qwen2.5:7b run; none of these is the planted gap.
    ("ecommerce_brief.answers.yaml", "No details on maintenance and support, such as post-launch support period"),
    ("ecommerce_brief.answers.yaml", "No information on devices and OS, such as minimum Android and iOS versions"),
    ("ecommerce_brief.answers.yaml", "No information on analytics, such as what must be tracked."),
    ("ecommerce_brief.answers.yaml", "Compliance check: Consumer Protection (E-Commerce) Rules, 2020: return policy"),
    ("one_line_classifieds.answers.yaml", "No devices and OS requirements are stated (minimum Android version)"),
])
def test_known_false_matches_stay_unmatched(key_file, wording):
    key = load_key(SAMPLES / key_file)
    planted = {"ecommerce_brief.answers.yaml": {"P-02", "P-03", "P-08", "P-10"},
               "one_line_classifieds.answers.yaml": {"P-01"}}[key_file]
    assert not [g.id for g in key.gaps if g.id in planted and g.matches(wording)]
