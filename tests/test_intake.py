import pytest

from sdlc_agent.intake.brief import completeness_of, extract_sow_lines
from sdlc_agent.intake.detect import detect_input_type, overall_input_type
from sdlc_agent.intake.questionnaire import build_questionnaire
from sdlc_agent.state.models import (
    Chunk, Completeness, InputType, ProjectBrief, RawInput, SourceRef,
)


@pytest.mark.parametrize("raw,expected", [
    (RawInput(kind="text", value="Build an Android and iOS app like OLX for Gujarat"), InputType.ONE_LINE),
    (RawInput(kind="text", value="Line one\nLine two"), InputType.NOTES),
    (RawInput(kind="url", value="https://example.com"), InputType.URL),
    (RawInput(kind="url", value="https://play.google.com/store/apps/details?id=x"), InputType.APP_STORE_URL),
    (RawInput(kind="file", value="scope.docx"), InputType.DOCUMENT),
    (RawInput(kind="file", value="screen.png"), InputType.IMAGE),
])
def test_detect(raw, expected):
    assert detect_input_type(raw) is expected


def test_mixed_inputs():
    inputs = [RawInput(kind="text", value="An app"), RawInput(kind="url", value="https://a.com")]
    assert overall_input_type(inputs) is InputType.MIXED


def test_unsupported_file_rejected():
    with pytest.raises(ValueError):
        detect_input_type(RawInput(kind="file", value="video.mp4"))


def test_sow_lines_skip_urls_and_short_lines():
    chunks = [
        Chunk(text="- Users can post ads\n- Hi\n2. Admin approves every ad", source=SourceRef(kind="file", ref="s.docx")),
        Chunk(text="Page text that should not become lines", source=SourceRef(kind="url", ref="https://a.com")),
    ]
    lines = extract_sow_lines(chunks)
    assert [line.text for line in lines] == ["Users can post ads", "Admin approves every ad"]
    assert [line.id for line in lines] == ["L-001", "L-002"]


def test_completeness():
    one = [Chunk(text="Build an app like OLX", source=SourceRef(kind="intake"))]
    assert completeness_of(one, InputType.ONE_LINE) is Completeness.THIN
    long = [Chunk(text="word " * 1300, source=SourceRef(kind="file", ref="sow.pdf"))]
    assert completeness_of(long, InputType.DOCUMENT) is Completeness.RICH


def test_questionnaire_skips_known_and_grows_for_thin_input():
    brief = ProjectBrief(domain="classifieds", region="Gujarat", platforms=["android"])
    keys = [q.key for q in build_questionnaire(brief, Completeness.THIN)]
    assert "domain" not in keys and "region" not in keys and "platforms" not in keys
    assert "must_have_features" in keys
    rich = [q.key for q in build_questionnaire(brief, Completeness.RICH)]
    assert "must_have_features" not in rich
    answered = [q.key for q in build_questionnaire(brief, Completeness.RICH, {"deadline": "March"})]
    assert "deadline" not in answered


def test_reads_word_and_excel(tmp_path):
    import docx
    from openpyxl import Workbook

    from sdlc_agent.intake.readers import read_input

    d = docx.Document()
    d.add_paragraph("Users can post ads with photos")
    table = d.add_table(rows=1, cols=2)
    table.rows[0].cells[0].text, table.rows[0].cells[1].text = "Search", "Filter by price"
    d.save(tmp_path / "scope.docx")
    chunks = read_input(RawInput(kind="file", value=str(tmp_path / "scope.docx")))
    assert "post ads" in chunks[0].text and "Filter by price" in chunks[0].text
    assert chunks[0].source.ref == "scope.docx"

    wb = Workbook()
    wb.active.title = "Features"
    wb.active.append(["Feature", "Priority"])
    wb.active.append(["Chat", "High"])
    wb.save(tmp_path / "features.xlsx")
    chunks = read_input(RawInput(kind="file", value=str(tmp_path / "features.xlsx")))
    assert "Chat | High" in chunks[0].text and chunks[0].source.ref == "features.xlsx sheet Features"


def test_brief_keeps_only_platforms_the_client_mentioned():
    from sdlc_agent.intake.brief import _stated_platforms
    from sdlc_agent.state.models import Chunk, SourceRef

    one_line = [Chunk(text="Build an app like OLX for Gujarat", source=SourceRef(kind="intake"))]
    assert _stated_platforms(["web", "android"], one_line) == []  # the model invented both
    stated = [Chunk(text="We need an iPhone app and an admin side", source=SourceRef(kind="intake"))]
    assert _stated_platforms(["ios", "admin panel", "web"], stated) == ["ios", "admin panel"]
    crawled = [Chunk(text="Download on Android", source=SourceRef(kind="url", ref="https://x"))]
    assert _stated_platforms(["android"], crawled) == []  # a reference site is not the client's request
