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


def test_ollama_errors_say_what_to_do(monkeypatch):
    import httpx
    import pytest

    from sdlc_agent.llm.ollama import OllamaClient

    client = OllamaClient("http://localhost:11434", "qwen2.5:14b")
    monkeypatch.setattr(httpx, "post", lambda *a, **k: httpx.Response(404, request=httpx.Request("POST", a[0])))
    with pytest.raises(RuntimeError, match="ollama pull qwen2.5:14b"):
        client.complete("s", "p")

    def refuse(*a, **k):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(httpx, "post", refuse)
    with pytest.raises(RuntimeError, match="ollama serve"):
        client.complete("s", "p")


def test_pack_entries_have_exactly_id_name_tier():
    # An unquoted comma inside a YAML flow mapping silently splits a feature name into extra keys.
    for name, pack in load_packs().items():
        for feat in pack.get("features", []):
            assert set(feat) == {"id", "name", "tier"}, f"{name} {feat.get('id')}: quote the name"
            assert feat["tier"] in ("table_stakes", "common"), f"{name} {feat['id']}"
        for c in pack.get("compliance", []) or []:
            assert set(c) == {"region", "note"}, f"{name} compliance: {c}"



def test_store_skips_an_unreadable_project(tmp_path):
    from sdlc_agent.state.store import ProjectStore

    store = ProjectStore(tmp_path)
    good = store.create("good")
    (tmp_path / "broken.json").write_text('{"id": "broken", "requirements": [{"source": {"kind": "from_the_future"}}]}')
    assert [p.id for p in store.list()] == [good.id]
    assert store.unreadable and store.unreadable[0][0] == "broken"
