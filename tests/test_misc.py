from sdlc_agent.domain_packs import load_packs, match_pack
from sdlc_agent.llm.base import parse_json
from sdlc_agent.state.store import next_id


def test_next_id():
    assert next_id("GAP", []) == "GAP-001"
    assert next_id("GAP", ["GAP-001", "GAP-009", "REQ-020"]) == "GAP-010"


def test_parse_json_tolerates_fences_and_prose():
    assert parse_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json('Here you go: {"a": [1, 2]} thanks') == {"a": [1, 2]}


def test_packs_load_and_match():
    packs = load_packs()
    assert {"classifieds", "ecommerce", "business_tools"} <= set(packs)
    assert match_pack("classifieds marketplace", packs)[0] == "classifieds"
    assert match_pack("online store", packs)[0] == "ecommerce"
    assert match_pack("space rockets", packs) is None
