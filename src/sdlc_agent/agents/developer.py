"""Stage 7 developer agent: implements one ticket as files (code plus unit tests).

The brief is built by code from the ticket, its skills (project context plus the stack skill) and
the slice of the approved design that the ticket's requirements touch. The model returns files;
everything after that (validation, branch, commit, pull request) is code in orchestrator/build.py.

This version calls the configured model through TracedLLM. Claude Code in headless mode can replace
it behind the same run() signature once an API key and a sandbox are available.
"""
from __future__ import annotations

import re

from ..llm.base import LLMClient
from ..llm.json_call import Dicts, complete_json
from ..state.models import Project, Ticket

NAME = "developer"

SYSTEM = """You are a developer agent at a software company. You implement exactly one ticket, following
the project's skills (architecture, conventions, security, testing). Write complete, compilable files.
Every change that adds code MUST include unit test files in the stack's test folder (for example
test/..._test.dart, src/__tests__/....test.tsx, tests/test_....py). Change only what the ticket needs. Never include secrets, API
keys or passwords; read configuration from the environment. Payment uses the dummy payment gateway with
static responses; do not integrate real payment providers or other third-party services.
Keep the whole reply short (under about 2,500 words): at most 6 files, only the code this ticket needs,
no generated or boilerplate files (lock files, build outputs, Gradle wrappers, icons); put TODO comments
where later tickets will continue."""
SHAPE = {"files": Dicts({"path": "str", "content": "str"}), "summary": "str", "notes": "strs"}
SCHEMA = 'Return JSON: {"files": [{"path": str, "content": str}], "summary": str, "notes": [str]}'

TEST_PATH = re.compile(r"(^|/)(tests?|__tests__|spec|test)(/|$)|(_test|\.test|\.spec|Test|Tests)\.[a-z]+$|(^|/)test_[^/]+$")


def is_test_file(path: str) -> bool:
    return bool(TEST_PATH.search(path))


CODE_EXT = re.compile(r"\.(py|js|jsx|ts|tsx|dart|kt|kts|java|swift|go|rb|php|cs|m|mm|vue|svelte)$", re.IGNORECASE)


def needs_tests(files: dict[str, str]) -> bool:
    """Code needs unit tests; a change with only docs or configuration does not."""
    return any(CODE_EXT.search(p) and not is_test_file(p) for p in files) and not any(is_test_file(p) for p in files)


TESTS_SYSTEM = """You are a developer agent writing unit tests for code another agent just wrote. Use the test
framework of the stack skill. Put tests where that stack expects them (for example test/..._test.dart,
src/__tests__/....test.tsx, tests/test_....py). Test real behaviour, not just that a file imports."""


def add_tests(llm: LLMClient, project: Project, ticket: Ticket, files: dict[str, str]) -> dict[str, str]:
    code = "\n\n".join(f"### {p}\n{c[:4000]}" for p, c in files.items() if CODE_EXT.search(p))[:16000]
    reply = complete_json(llm, TESTS_SYSTEM, f"{brief(project, ticket)}\n## Code to test\n\n{code}\n\n"
                          'Return JSON: {"files": [{"path": str, "content": str}]} with only the new test files.', SHAPE)
    return {f["path"].strip(): f["content"] for f in reply.get("files", [])
            if f.get("path", "").strip() and is_test_file(f["path"].strip())}


def brief(project: Project, ticket: Ticket) -> str:
    """Everything the developer needs for one ticket, and nothing else (context engineering)."""
    skills = {f.name: f for f in project.skill_pack.files} if project.skill_pack else {}
    stack = next((s.pack for s in project.design.stacks if s.platform == ticket.platform), None) if project.design else None
    stack_skill = next((f for f in skills.values() if f.pack == stack), None)
    reqs = {r.id: r for r in project.active_requirements()}
    d = project.design
    ids = set(ticket.requirement_ids)
    endpoints = [e for e in d.endpoints if ids & set(e.requirement_ids)] if d else []
    screens = [s for s in d.screens if ids & set(s.requirement_ids)] if d else []
    entities = [e for e in d.entities if ids & set(e.requirement_ids)] if d else []
    parts = [
        f"# Ticket {ticket.key}: {ticket.summary}", "", ticket.description, "",
        "## Requirements", "",
        *([f"- {i}: {reqs[i].text}" for i in ticket.requirement_ids if i in reqs] or ["- Cross-cutting work"]),
    ]
    if entities:
        parts += ["", "## Data model", ""] + [f"- {e.name}: {', '.join(e.fields)}" for e in entities]
    if endpoints:
        parts += ["", "## API", ""] + [f"- {e.method} {e.path}: {e.purpose}" for e in endpoints]
    if screens:
        parts += ["", "## Screens", ""] + [f"- {s.id} {s.name}: {s.purpose}" for s in screens]
    if stack_skill:
        parts += ["", "## Stack skill", "", stack_skill.content]
    if "project-context" in skills:
        rules = skills["project-context"].content.split("## Platforms and stacks")[0]
        parts += ["", rules.strip()]
    return "\n".join(parts) + "\n"


def run(llm: LLMClient, project: Project, ticket: Ticket) -> dict:
    return complete_json(llm, SYSTEM, f"{brief(project, ticket)}\n{SCHEMA}", SHAPE)
