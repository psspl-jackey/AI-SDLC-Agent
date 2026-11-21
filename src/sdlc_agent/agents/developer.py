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
the project's skills (architecture, conventions, security, testing). Write complete, compilable files,
including unit tests for what you build. Change only what the ticket needs. Never include secrets, API
keys or passwords; read configuration from the environment. Payment uses the dummy payment gateway with
static responses; do not integrate real payment providers or other third-party services."""
SHAPE = {"files": Dicts({"path": "str", "content": "str"}), "summary": "str", "notes": "strs"}
SCHEMA = 'Return JSON: {"files": [{"path": str, "content": str}], "summary": str, "notes": [str]}'

TEST_PATH = re.compile(r"(^|/)(tests?|__tests__|spec|test)(/|$)|(_test|\.test|\.spec|Test|Tests)\.[a-z]+$|(^|/)test_[^/]+$")


def is_test_file(path: str) -> bool:
    return bool(TEST_PATH.search(path))


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
