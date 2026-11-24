"""Shared test fakes: a scripted model, so the full flow runs without Ollama or Claude."""
from __future__ import annotations

import json
import re
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
                {"id": "CL-01", "status": "covered", "covered_by": "F1", "reason": ""},
                {"id": "CL-02", "status": "covered", "reason": "implied by buying and selling"},  # no citation
                {"id": "CL-17", "status": "not_relevant", "reason": "single language"},  # common: allowed
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
        elif "senior estimator" in system:
            if "cross-cutting" in prompt:
                data = {"tasks": [
                    {"module": "Cross-cutting", "feature": "Setup", "title": "Project setup and CI", "role": "tech lead",
                     "hours_min": 8, "hours_likely": 12, "hours_max": 20, "requirement_ids": []},
                    {"module": "Cross-cutting", "feature": "QA", "title": "Test plan and regression", "role": "QA",
                     "hours_min": 16, "hours_likely": 24, "hours_max": 40, "requirement_ids": []},
                ]}
            elif "recommended additions" in prompt:
                gap_ids = sorted(set(re.findall(r"^(GAP-\d+):", prompt, re.MULTILINE)))
                data = {"tasks": [
                    {"module": "Additions", "feature": gid, "title": f"Build {gid}", "role": "mobile developer",
                     "hours_min": 4, "hours_likely": 8, "hours_max": 16, "requirement_ids": [],
                     "gap_id": gid, "platform": "android"} for gid in gap_ids
                ]}
            else:
                platform = re.search(r"Estimate the (.+?) work", prompt).group(1)
                listed = prompt.split("requirements:\n", 1)[1].split("\n\nNon-functional", 1)[0]
                req_ids = re.findall(r"^(REQ-\d+):", listed, re.MULTILINE)
                data = {"tasks": [
                    {"module": "Ads", "feature": "Post an ad", "title": f"Post-ad flow ({platform})",
                     "role": "developer", "hours_min": 24, "hours_likely": 16, "hours_max": 40,  # unordered on purpose
                     "requirement_ids": req_ids},
                    {"module": "Ads", "feature": "Post an ad", "title": "Broken row", "role": "developer",
                     "hours_min": 0, "hours_likely": 0, "hours_max": 0, "requirement_ids": req_ids},
                ]}
        elif "change request" in system:
            cr_line = re.search(r"lines:\n(L-\d+):", prompt).group(1)
            data = {
                "added": [{"text": "Sellers can mark an ad as sold", "kind": "functional", "line_ids": [cr_line],
                           "platforms": ["Android", "iOS", "Smart TV"]}],
                "changed": [{"id": "REQ-001", "text": "Sellers can post an ad with up to 20 photos",
                             "line_ids": [cr_line], "platforms": []}],
                "removed": [],
                "not_requirement_line_ids": [],
                "gaps": [{"source": "sow", "description": "Photo size limit not given", "question": "Max photo size?",
                          "blocking": False, "assumed_answer": "5 MB each"}],
            }
        elif "technical architect" in system:
            req_ids = sorted(set(re.findall(r"^(REQ-\d+)", prompt, re.MULTILINE)))
            if "Tech pack catalogue" in prompt:
                data = {
                    "stacks": [{"platform": "android", "pack": "flutter", "reason": "One codebase"},
                               {"platform": "iOS", "pack": "flutter", "reason": "One codebase"},
                               {"platform": "admin panel", "pack": "react_web", "reason": "Internal tool"},
                               {"platform": "backend", "pack": "nodejs_backend", "reason": "Team skills"}],
                    "components": [
                        {"name": "Mobile app", "kind": "client", "responsibility": "Buyers and sellers", "uses": ["API"]},
                        {"name": "Admin panel", "kind": "client", "responsibility": "Moderation", "uses": ["API"]},
                        {"name": "API", "kind": "service", "responsibility": "Business logic",
                         "uses": ["Database", "Ghost service"]},
                        {"name": "Database", "kind": "datastore", "responsibility": "Ads and users"},
                    ],
                    "decisions": [{"title": "Backend style", "decision": "Modular monolith",
                                   "reason": "Small team", "alternatives": ["Microservices"]}],
                }
            elif "data model" in prompt:
                data = {
                    "entities": [{"name": "Ad", "fields": ["id", "title", "price", "photos"], "requirement_ids": req_ids}],
                    "endpoints": [{"method": "post", "path": "ads", "purpose": "Create an ad", "requirement_ids": req_ids},
                                  {"method": "POST", "path": "/ads", "purpose": "duplicate", "requirement_ids": []},
                                  {"method": "FETCH", "path": "/x", "purpose": "bad", "requirement_ids": []}],
                }
            else:
                data = {"screens": [
                    {"key": "S1", "name": "Home", "purpose": "Browse ads", "requirement_ids": [], "navigates_to": ["S2", "S9"]},
                    {"key": "S2", "name": "Post ad", "purpose": "Create an ad", "requirement_ids": req_ids,
                     "navigates_to": ["S1"]},
                ]}
        elif "tailor a software company" in system:
            data = {
                "architecture": ["Keep the Ad entity as the single source for listing data"],
                "conventions": ["Effective Dart style; flutter analyze and dart format clean before every pull request",
                                "Name screens after the design's screen ids, e.g. SCR-001"],
                "security": "Never log ad photos' EXIF location, Strip EXIF before upload",
                "testing": [f"Rule {i}" for i in range(9)],
                "ci": [],
            }
        elif "delivery planner" in system:
            tasks = re.findall(r"^(TASK-\d+) \[(\S+)\] .*? / (.+)$", prompt, re.MULTILINE)
            setup = next(t for t, _, title in tasks if title.startswith("Project setup"))
            qa = next(t for t, _, title in tasks if title.startswith("Test plan"))
            post = {p: t for t, p, title in tasks if title.startswith("Post-ad")}
            deps = [{"task": t, "depends_on": [setup]} for t in post.values()]
            deps += [{"task": post["android"], "depends_on": [post["ios"]]},  # android <-> ios is a cycle
                     {"task": post["ios"], "depends_on": [post["android"]]},
                     {"task": setup, "depends_on": [setup, "TASK-999"]},  # self link, unknown task
                     {"task": qa, "depends_on": [setup]},
                     {"task": "TASK-888", "depends_on": [setup]}]
            data = {"dependencies": deps}
        elif "developer agent" in system:
            title = re.search(r"^# Ticket \S+: (.+)$", prompt, re.MULTILINE).group(1)
            writing_tests = "writing unit tests" in system
            if "No tests" in title:  # code without tests, even when asked again
                files = [{"path": "app/lib/no_tests.dart", "content": "// code\n"}]
            elif "Tests later" in title:  # tests only on the follow-up call
                files = ([{"path": "app/test/later_test.dart", "content": "void main() {}\n"}] if writing_tests
                         else [{"path": "app/lib/later.dart", "content": "// code\n"}])
            elif "Test plan" in title:
                files = [{"path": "docs/test-plan.md", "content": "# Test plan\n"}]
            elif "Project setup" in title:
                files = [{"path": "app/pubspec.yaml", "content": "name: app\n"},
                         {"path": "app/test/smoke_test.dart", "content": "void main() {}\n"}]
            else:
                slug = re.sub(r"[^a-z]+", "_", title.lower()).strip("_")
                files = [{"path": f"app/lib/{slug}.dart", "content": "// post ad\n"},
                         {"path": f"app/test/{slug}_test.dart", "content": "void main() {}\n"}]
            data = {"files": files, "summary": f"Implemented {title}", "notes": ["Generated in a test"]}
        elif "QA engineer" in system:
            ids = re.findall(r"^(REQ-\d+):", prompt.split("Non-functional")[0], re.MULTILINE)
            data = {"test_cases": [
                {"title": f"Post an ad end to end ({i})", "kind": "e2e", "platform": "android",
                 "requirement_ids": [i], "steps": ["Open app", "Post ad"], "expected": "Ad is listed"} for i in ids
            ] + [
                {"title": "API rejects ad without title", "kind": "Integration", "platform": "backend",
                 "requirement_ids": ids + ["REQ-999"], "steps": ["POST /ads without title"], "expected": "400"},
                {"title": "Smoke check", "kind": "smoke", "requirement_ids": [], "steps": [], "expected": "Loads"},
            ]}
        elif "support engineer" in system:
            data = {"runbook": [
                {"task": "Remove a reported ad", "when": "A user reports an ad",
                 "steps": ["Open the admin panel", "Find the ad", "Remove it and note the reason"]},
                "Restart the API",  # string item, no steps: dropped
                {"task": "remove a reported ad", "steps": ["duplicate"]},
                {"task": "Restore the database from backup", "when": "Data loss",
                 "steps": "Stop the API, Restore the latest backup, Start the API"},
            ]}
        elif "gap register" in system:
            data = {"duplicates": [], "rewrites": []}
        elif "senior UI designer" in system:
            data = {"tagline": "Local deals, fast", "primary": "green", "accent": "#FFD700", "background": "#101010",
                    "text": "#222222", "font": "comic", "radius": "round", "density": "compact", "mood": "fresh",
                    "ux_principles": ["Nice", "Show the seller's city on every card so buyers know the distance"],
                    "reason": "fresh market feel"}
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
