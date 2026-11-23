"""Rules added after the first real-model run (qwen2.5:7b)."""
import json

from sdlc_agent.agents import requirements_analyst, reviewer
from sdlc_agent.gaps.register import add_gap
from sdlc_agent.llm.base import LLMResponse
from sdlc_agent.state.models import GapSource, Project, SourceRef, SowLine


def test_reviewer_reads_ids_from_text_and_keeps_compliance_gaps():
    p = Project(id="p", name="t")
    add_gap(p, source=GapSource.NFR, description="No privacy and compliance requirements are stated.", found_by="x")
    add_gap(p, source=GapSource.NFR, description="Compliance check: Digital Personal Data Protection Act, 2023",
            found_by="x")
    add_gap(p, source=GapSource.SOW, description="Search filters are not defined", found_by="x")
    add_gap(p, source=GapSource.SOW, description="Filters for search not defined", found_by="x")
    add_gap(p, source=GapSource.DOMAIN_CHECKLIST, description="Search and filters (EC-02) is not in the brief",
            found_by="x")
    reviewer.apply(p, {"duplicates": [
        {"keep": "GAP-001 [nfr]: No privacy and compliance requirements are stated.",
         "remove": ["GAP-002 [nfr]: Compliance check: Digital Personal Data Protection Act, 2023"]},
        {"keep": "GAP-003", "remove": ["GAP-004 [sow]: Filters for search not defined", "GAP-005"]},
    ], "rewrites": [{"id": "GAP-003 [sow]: Search...", "text": "Search filters (price, category) are not defined"}]})
    assert [g.id for g in p.gaps] == ["GAP-001", "GAP-002", "GAP-003", "GAP-005"]  # only the same-source dup removed
    assert p.gaps[2].description == "Search filters (price, category) are not defined"


def test_payment_requirements_always_name_the_dummy_gateway():
    assert requirements_analyst.with_payment_rule("Customers pay online at checkout.").endswith(
        requirements_analyst.DUMMY_NOTE)
    assert requirements_analyst.with_payment_rule("Checkout uses a dummy gateway.") == "Checkout uses a dummy gateway."
    assert requirements_analyst.with_payment_rule("Customers see past orders.") == "Customers see past orders."
    assert requirements_analyst.with_payment_rule("Display the payload size") == "Display the payload size"


class TwoReplies:
    name = "scripted"

    def __init__(self, *replies):
        self.replies, self.prompts = [json.dumps(r) for r in replies], []

    def complete(self, system, prompt, *, json_mode=False):
        self.prompts.append(prompt)
        return LLMResponse(text=self.replies.pop(0), model="scripted")


def test_analyst_asks_again_for_lines_it_skipped():
    p = Project(id="p", name="t", sow_lines=[
        SowLine(id="L-001", text="Customers can see past orders", source=SourceRef(kind="intake")),
        SowLine(id="L-002", text="The app should be fast", source=SourceRef(kind="intake")),
    ])
    llm = TwoReplies(
        {"requirements": [{"text": "Customers can see past orders", "sow_line_ids": ["L-001"]}], "gaps": []},
        {"requirements": [{"text": "Screens load quickly", "kind": "nfr", "sow_line_ids": ["L-002"]}],
         "gaps": [{"source": "sow", "description": "'Fast' has no measurable target", "question": "How fast?"}]},
    )
    result = requirements_analyst.run(llm, p)
    assert len(llm.prompts) == 2 and "L-002: The app should be fast" in llm.prompts[1]
    assert "L-001: Customers" not in llm.prompts[1].split("not yet accounted for")[1]
    requirements_analyst.apply(p, result)
    assert all(line.requirement_ids for line in p.sow_lines)
    assert any("measurable" in g.description for g in p.gaps)


def test_reviewer_merge_needs_real_overlap():
    from sdlc_agent.agents.reviewer import same_thing

    # The merge qwen2.5:7b proposed in round 1: two different checklist items.
    assert not same_thing("Returns and cancellations (EC-08) is not in the brief",
                          "Ratings and reviews (EC-12) is not in the brief")
    assert not same_thing("No expected user scale", "No details on offline support")
    assert same_thing("Search filters are not defined", "Filters for search are not defined")


def test_reviewer_keeps_distinct_checklist_gaps():
    p = Project(id="p", name="t")
    for name in ("Returns and cancellations (EC-08)", "Ratings and reviews (EC-12)", "Coupons and offers (EC-13)"):
        add_gap(p, source=GapSource.DOMAIN_CHECKLIST, description=f"{name} is not in the brief", found_by="x")
    reviewer.apply(p, {"duplicates": [{"keep": "GAP-001", "remove": ["GAP-002", "GAP-003"]}]})
    assert len(p.gaps) == 3


def test_thin_brief_is_filled_from_the_domain_pack():
    from sdlc_agent.intake.brief import fill_thin_brief
    from sdlc_agent.state.models import BriefItem, Completeness, ProjectBrief

    brief = ProjectBrief(domain="classifieds", completeness=Completeness.THIN,
                         features=[BriefItem(text="Post an ad with photos", source=SourceRef(kind="intake"))])
    added = fill_thin_brief(brief)
    texts = [f.text for f in brief.features]
    assert added == len(texts) - 1 and "In-app buyer-seller chat (CL-05)" in texts
    assert not any(t.startswith("Post an ad with photos (") for t in texts)  # already planned
    assert all(f.source.kind == "inferred" for f in brief.features[1:])
    assert not any("(CL-12)" in t for t in texts)  # only table stakes
    rich = ProjectBrief(domain="classifieds", completeness=Completeness.RICH)
    assert fill_thin_brief(rich) == 0
