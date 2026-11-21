"""Shared test fakes: a scripted model, so the full flow runs without Ollama or Claude."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from sdlc_agent.config import Settings
from sdlc_agent.llm.base import LLMResponse
from sdlc_agent.state.models import Chunk, SourceRef


class FakeLLM:
    """Answers by matching the system prompt of each agent."""

    name = "fake"

    def __init__(self):
        self.calls: list[str] = []

    def complete(self, system: str, prompt: str, *, json_mode: bool = False) -> LLMResponse:
        self.calls.append(system[:40])
        if "intake agent" in system:
            data = {
                "goal": "A classifieds app for buying and selling used goods",
                "domain": "classifieds", "region": "Gujarat, India",
                "target_users": ["buyers", "sellers"], "intent": "new", "platforms": ["android", "ios"],
                "features": [
                    {"text": "Post an ad with photos", "source": "intake"},
                    {"text": "Search ads", "source": "intake"},
                    {"text": "Admin panel", "source": "inferred"},
                ],
                "nfrs": [], "constraints": [], "references": [],
            }
        elif "business analyst" in system:
            data = {
                "requirements": [
                    {"text": "Sellers can post an ad with up to 10 photos", "kind": "functional", "sow_line_ids": ["L-001"]},
                ],
                "not_requirement_line_ids": [],
                "gaps": [
                    {"source": "sow", "description": "Search filters are not defined", "question": "Which filters?",
                     "blocking": False, "assumed_answer": "Price, category, location"},
                    {"source": "nfr", "description": "No expected user scale", "question": "How many users?",
                     "blocking": True, "assumed_answer": "10,000 in year one"},
                ],
                "feasibility": [{"concern": "Timeline not given", "severity": "low"}],
            }
        elif "standard feature checklist" in system:
            data = {"items": [
                {"id": "CL-01", "status": "covered", "reason": ""},
                {"id": "CL-05", "status": "missing", "reason": "no chat"},
                {"id": "CL-13", "status": "missing", "reason": "no verification"},
            ]}
        elif "public web page" in system:
            data = {"name": "RefApp", "features": ["In-app chat", "Saved searches"],
                    "complaints": ["Too many fake ads"]}
        elif "competitor apps" in system:
            data = {"missing": [{"feature": "In-app chat", "competitor_ids": ["C1", "C2"]},
                                {"feature": "Saved searches", "competitor_ids": ["C1"]}]}
        elif "solution architect" in system:
            data = {
                "platforms": [
                    {"platform": "Android", "included": True, "reason": "Sellers post from phones",
                     "requirement_ids": ["REQ-001"]},
                    {"platform": "iOS", "included": False, "reason": "Android dominates in Gujarat",
                     "requirement_ids": []},
                    {"platform": "web", "included": False, "reason": "Mobile-first audience", "requirement_ids": []},
                    {"platform": "Admin panel", "included": True, "reason": "Moderators review ads",
                     "requirement_ids": ["REQ-001", "REQ-999"]},
                    {"platform": "backend", "included": True, "reason": "Stores ads and users",
                     "requirement_ids": ["REQ-001"]},
                ],
                "approach": "cross_platform", "approach_reason": "One codebase for Android and iOS",
            }
        elif "gap register" in system:
            data = {"duplicates": [], "rewrites": []}
        else:
            raise AssertionError(f"Unexpected prompt: {system[:80]}")
        return LLMResponse(text=json.dumps(data), model="fake", input_tokens=100, output_tokens=50)


def fake_read_url(url: str):
    return [Chunk(text=f"Page title: {url}\nText: chat, saved searches", source=SourceRef(kind="url", ref=url))]


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        model_provider="ollama", ollama_url="http://localhost:11434", ollama_model="test",
        anthropic_model="test", cost_input_per_mtok=1.0, cost_output_per_mtok=2.0,
        data_dir=tmp_path, max_tokens=1000,
    )


@pytest.fixture
def fake_llm() -> FakeLLM:
    return FakeLLM()
