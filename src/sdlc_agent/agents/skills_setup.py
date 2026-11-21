"""Stage 5: skills setup. Selects company skills (tech packs) for the chosen stacks and tailors them.

- Selection is code: one skill per tech pack used in the approved design, carrying every company
  rule from the pack (architecture, conventions, security, testing, CI/CD).
- Tailoring is the model: per stack, it may only ADD project-specific rules. Company rules cannot be
  dropped or rewritten; code removes duplicates and caps additions per section.
- One project context skill is written entirely by code from the approved design: stacks,
  components, data model, API, screens, and the delivery rules every developer (human or agent) follows.

Skills are exported in the Claude Code skill layout (<name>/SKILL.md with name and description front
matter), so Stage 7 coding agents can load them as they are.

run() is pure and returns a result dict; apply() is the only writer.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..domain_packs import load_tech_packs
from ..llm.base import LLMClient
from ..llm.json_call import complete_json
from ..state.models import Project, SkillFile, SkillPack

NAME = "skills_setup"
SECTIONS = ("architecture", "conventions", "security", "testing", "ci")
SECTION_TITLES = {"architecture": "Architecture", "conventions": "Codebase conventions", "security": "Security",
                  "testing": "Testing", "ci": "CI/CD"}
MAX_ADDED_PER_SECTION = 6

SYSTEM = """You tailor a software company's engineering skill for one project. You receive the
company's standard rules for a technology stack and the project's approved design. Add only rules
that are specific to THIS project (its components, data, API, screens and decisions) and that a
developer would otherwise get wrong. Do not repeat, weaken or contradict the company rules. Each rule
is one short imperative sentence. Payment uses a dummy gateway; real payment providers and other
third-party integrations are out of scope."""
SHAPE = {k: "strs" for k in SECTIONS}
SCHEMA = 'Return JSON: {"architecture": [str], "conventions": [str], "security": [str], "testing": [str], "ci": [str]}'


def stacks_by_pack(project: Project) -> dict[str, list[str]]:
    """Tech pack -> platforms it is used for in the approved design."""
    packs: dict[str, list[str]] = {}
    for s in project.design.stacks if project.design else []:
        packs.setdefault(s.pack, []).append(s.platform)
    return packs


def _design_summary(project: Project, platforms: list[str]) -> str:
    d = project.design
    screens = [s for s in d.screens if s.platform in platforms or (s.platform == "mobile" and
                                                                  {"android", "ios"} & set(platforms))]
    lines = [f"Goal: {project.brief.goal if project.brief else ''}",
             f"Used for: {', '.join(platforms)}",
             "Components: " + "; ".join(f"{c.name} ({c.kind}): {c.responsibility}" for c in d.components),
             "Decisions: " + "; ".join(f"{x.title}: {x.decision}" for x in d.decisions)]
    if "backend" in platforms:
        lines.append("Entities: " + "; ".join(f"{e.name} ({', '.join(e.fields)})" for e in d.entities))
        lines.append("Endpoints: " + "; ".join(f"{e.method} {e.path}" for e in d.endpoints))
    if screens:
        lines.append("Screens: " + "; ".join(s.name for s in screens))
    return "\n".join(lines)


def run(llm: LLMClient, project: Project) -> dict:
    packs = load_tech_packs()
    result: dict = {"tailored": {}}
    for pack, platforms in stacks_by_pack(project).items():
        if pack not in packs:
            continue
        rules = "\n".join(f"{SECTION_TITLES[k]}:\n" + "\n".join(f"- {r}" for r in packs[pack].get(k, []))
                          for k in SECTIONS)
        result["tailored"][pack] = complete_json(
            llm, SYSTEM,
            f"Stack: {packs[pack].get('title', pack)}\n\nCompany rules:\n{rules}\n\n"
            f"Project design:\n{_design_summary(project, platforms)}\n\n{SCHEMA}",
            SHAPE,
        )
    return result


def _norm(rule: str) -> str:
    return " ".join(rule.lower().strip(" .").split())


def _stack_skill(project: Project, pack_name: str, pack: dict, platforms: list[str],
                 added: dict) -> tuple[SkillFile, list[str]]:
    notes: list[str] = []
    tailored: dict[str, list[str]] = {}
    for k in SECTIONS:
        base = {_norm(r) for r in pack.get(k, [])}
        keep: list[str] = []
        for rule in added.get(k, []) or []:
            rule = rule.strip()
            if rule and _norm(rule) not in base and _norm(rule) not in {_norm(x) for x in keep}:
                keep.append(rule)
        if len(keep) > MAX_ADDED_PER_SECTION:
            notes.append(f"Skills setup: kept the first {MAX_ADDED_PER_SECTION} of {len(keep)} {k} rules for {pack_name}")
            keep = keep[:MAX_ADDED_PER_SECTION]
        if keep:
            tailored[k] = keep
    title = pack.get("title", pack_name)
    used_for = ", ".join(p.replace("_", " ") for p in platforms)
    body = [f"# {title}: {project.name}", "",
            f"Rules for building the {used_for} of {project.name} with {title}. Company rules come from the "
            f"`{pack_name}` tech pack; project rules were added for this project and approved with the design.", ""]
    for k in SECTIONS:
        body += [f"## {SECTION_TITLES[k]}", ""]
        body += [f"- {r}" for r in pack.get(k, [])]
        body += [f"- {r} _(project)_" for r in tailored.get(k, [])]
        body.append("")
    return SkillFile(
        name=f"{pack_name.replace('_', '-')}",
        description=f"Use when writing, reviewing or testing {title} code for the {used_for} of {project.name}.",
        platforms=platforms, pack=pack_name, content="\n".join(body), tailored=tailored,
    ), notes


def project_context_skill(project: Project) -> SkillFile:
    d, m = project.design, project.platform_matrix
    reqs = project.active_requirements()
    body = [f"# Project context: {project.name}", "",
            f"Goal: {project.brief.goal if project.brief else ''}", "",
            "## Delivery rules", "",
            "- Work only from Jira tickets; put the Jira key first in every commit message and branch name "
            "(`feature/<JIRA-KEY>-short-name`).",
            "- Cite the requirement ids (REQ-xxx) a change implements in the pull request description and in test names.",
            "- Never push to `main`; open pull requests into `develop`. A human reviews every pull request.",
            "- Payment is built against the dummy payment gateway with static responses. Real payment providers "
            "and other third-party integrations are out of scope.",
            "- Never put secrets or API keys in code; use environment configuration.",
            "- Build only what the approved requirements and design say. Raise a question instead of guessing.", "",
            "## Platforms and stacks", ""]
    stacks = {s.platform: s.pack for s in d.stacks}
    body += [f"- {x.platform.replace('_', ' ')}: {stacks.get(x.platform, 'not chosen')}" for x in m.included()]
    body += ["", f"Delivery approach: {m.approach.replace('_', ' ')}.", "", "## Components", ""]
    body += [f"- **{c.name}** ({c.kind}): {c.responsibility}" + (f" Uses: {', '.join(c.uses)}." if c.uses else "")
             for c in d.components]
    if d.entities:
        body += ["", "## Data model", ""] + [f"- **{e.name}**: {', '.join(e.fields)}" for e in d.entities]
    if d.endpoints:
        body += ["", "## API", ""] + [f"- `{e.method} {e.path}`: {e.purpose} ({', '.join(e.requirement_ids)})"
                                      for e in d.endpoints]
    if d.screens:
        body += ["", "## Screens", ""] + [f"- {s.id} {s.name} [{s.platform}]: {s.purpose} ({', '.join(s.requirement_ids)})"
                                          for s in d.screens]
    if d.decisions:
        body += ["", "## Design decisions", ""] + [f"- {x.title}: {x.decision}. {x.reason}" for x in d.decisions]
    body += ["", "## Requirements", ""] + [f"- **{r.id}** [{r.kind}] {r.text}" for r in reqs]
    return SkillFile(
        name="project-context",
        description=f"Use before any work on {project.name}: requirements, design, and the delivery rules to follow.",
        platforms=[x.platform for x in m.included()], content="\n".join(body) + "\n",
    )


def build_skill_pack(project: Project, result: dict) -> tuple[SkillPack, list[str]]:
    packs = load_tech_packs()
    notes: list[str] = []
    files = [project_context_skill(project)]
    for pack_name, platforms in stacks_by_pack(project).items():
        if pack_name not in packs:
            notes.append(f"Skills setup: no tech pack '{pack_name}'; no skill created for {', '.join(platforms)}")
            continue
        skill, n = _stack_skill(project, pack_name, packs[pack_name], platforms,
                                (result.get("tailored") or {}).get(pack_name, {}))
        files.append(skill)
        notes += n
    return SkillPack(files=files), notes


def apply(project: Project, result: dict) -> None:
    pack, notes = build_skill_pack(project, result)
    project.skill_pack = pack
    for note in notes:
        project.log(note)


def skill_markdown(skill: SkillFile) -> str:
    """SKILL.md with front matter, as Claude Code loads it."""
    description = skill.description.replace('"', "'")
    return f'---\nname: {skill.name}\ndescription: "{description}"\n---\n\n{skill.content}'


@dataclass
class SkillsReport:
    passed: bool
    failures: list[str] = field(default_factory=list)


def skills_check(project: Project) -> SkillsReport:
    sp = project.skill_pack
    if sp is None:
        return SkillsReport(False, ["Stage 5 has not run: no skill pack"])
    failures: list[str] = []
    names = {f.name for f in sp.files}
    if "project-context" not in names:
        failures.append("The project context skill is missing")
    by_pack = {f.pack for f in sp.files if f.pack}
    failures += [f"No skill for stack {pack} ({', '.join(pl)})" for pack, pl in stacks_by_pack(project).items()
                 if pack not in by_pack]
    return SkillsReport(passed=not failures, failures=failures)
