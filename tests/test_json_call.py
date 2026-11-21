"""complete_json: retry on bad JSON, coerce replies from small models into the expected shape."""
import pytest

from sdlc_agent.llm.base import LLMResponse
from sdlc_agent.llm.json_call import Dicts, coerce, complete_json


class Scripted:
    name = "scripted"

    def __init__(self, *replies):
        self.replies, self.prompts = list(replies), []

    def complete(self, system, prompt, *, json_mode=False):
        self.prompts.append(prompt)
        return LLMResponse(text=self.replies.pop(0), model="scripted")


SHAPE = {"tasks": Dicts({"title": "str", "requirement_ids": "strs", "included": "bool"}, text_key="title")}


def test_retries_once_with_the_error_then_succeeds():
    llm = Scripted("Sure! Here are the tasks:", '{"tasks": []}')
    assert complete_json(llm, "s", "p", SHAPE) == {"tasks": []}
    assert "could not be used" in llm.prompts[1] and llm.prompts[1].startswith("p")


def test_gives_up_with_a_clear_error():
    with pytest.raises(ValueError, match="unusable after 2 attempt"):
        complete_json(Scripted("nope", "still nope"), "s", "p", SHAPE)


def test_bare_list_is_wrapped_under_the_only_list_key():
    llm = Scripted('[{"title": "Login screen", "requirement_ids": "REQ-001, REQ-002"}]')
    assert complete_json(llm, "s", "p", SHAPE)["tasks"] == [
        {"title": "Login screen", "requirement_ids": ["REQ-001", "REQ-002"], "included": False}]


def test_coercion_of_common_small_model_mistakes():
    data = coerce({"tasks": ["Bare string task", 42, {"title": 7, "requirement_ids": None, "included": "false"}],
                   "extra": "kept"}, SHAPE)
    assert data["tasks"] == [
        {"title": "Bare string task", "requirement_ids": [], "included": False},
        {"title": "7", "requirement_ids": [], "included": False},
    ]
    assert data["extra"] == "kept"
    assert coerce({"tasks": {"title": "one object", "included": "Yes"}}, SHAPE)["tasks"] == [
        {"title": "one object", "requirement_ids": [], "included": True}]
    assert coerce({}, {"name": "str", "ids": "strs"}) == {"name": "", "ids": []}


def test_stage_survives_a_badly_shaped_platform_reply(settings):
    """End to end: the platform agent gets strings where lists belong and 'false' as a string."""
    from sdlc_agent.agents import platform_decision
    from sdlc_agent.state.models import Project, ProjectBrief, Requirement, SourceRef

    project = Project(id="p", name="t", brief=ProjectBrief(platforms=["web"]))
    project.requirements = [Requirement(id="REQ-001", text="r", source=SourceRef(kind="inferred"))]
    llm = Scripted('{"platforms": [{"platform": "web", "included": "true", "reason": "r", "requirement_ids": "REQ-001"},'
                   ' {"platform": "android", "included": "false", "reason": "no", "requirement_ids": ""}],'
                   ' "approach": "web_only"}')
    project.platform_matrix, _ = platform_decision.build_matrix(project, platform_decision.run(llm, project))
    rows = {d.platform: d for d in project.platform_matrix.decisions}
    assert rows["web"].requirement_ids == ["REQ-001"] and not rows["android"].included
    assert platform_decision.platform_check(project).passed
