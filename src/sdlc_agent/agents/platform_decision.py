"""Stage 2: platform decision. Maps approved requirements to platforms, with a reason for each.

The model proposes; code enforces the rules:
- every core platform (android, ios, web, admin_panel, backend) gets an explicit yes/no row;
- platforms the client stated are always included, whatever the model says;
- requirement ids must exist; platform names are normalised;
- platforms the agent added on its own are tagged inferred and enter the gap register as assumed,
  with a non-blocking question to the client (rule: everything inferred is visible at the gate).

run() is pure and returns a result dict; apply() is the only writer.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..llm.base import LLMClient, parse_json
from ..state.models import CORE_PLATFORMS, PlatformDecision, PlatformMatrix, Project

NAME = "platform_decision"

SYSTEM = """You are the solution architect of a software delivery company, deciding which platforms
a project needs before it is estimated. Platforms: android, ios, web (customer-facing website or web
app), admin_panel (internal back office), backend (server, APIs, database), plus any other the
requirements clearly need. For each platform decide whether it is included, give a one-sentence
reason tied to the requirements or users, and list the requirement ids it serves.
Also recommend the delivery approach for the client apps: native, cross_platform (one codebase for
android and ios), web_only, or not_applicable, with a one-sentence reason. Do not choose a framework
or language yet; that is decided in solution design.
Platforms the client stated are fixed. Payment and third-party integrations are out of scope for now
(payment uses a dummy gateway)."""

SCHEMA = """Return JSON:
{
  "platforms": [{"platform": str, "included": bool, "reason": str, "requirement_ids": [str]}],
  "approach": "native" | "cross_platform" | "web_only" | "not_applicable",
  "approach_reason": str
}"""

_ALIASES = {
    "android": "android", "android app": "android",
    "ios": "ios", "iphone": "ios", "ios app": "ios", "ipad": "ios",
    "web": "web", "website": "web", "web app": "web", "webapp": "web", "pwa": "web", "web application": "web",
    "admin": "admin_panel", "admin panel": "admin_panel", "admin_panel": "admin_panel", "admin side": "admin_panel",
    "back office": "admin_panel", "backoffice": "admin_panel", "cms": "admin_panel", "admin dashboard": "admin_panel",
    "backend": "backend", "back end": "backend", "back-end": "backend", "server": "backend", "api": "backend",
    "apis": "backend", "backend api": "backend",
}
_APPROACHES = ("native", "cross_platform", "web_only", "not_applicable")


def normalise(name: str) -> str:
    key = " ".join(str(name).lower().replace("_", " ").replace("-", " ").split())
    if key in _ALIASES:
        return _ALIASES[key]
    if "mobile" in key and "app" in key:  # "mobile app" stated without naming the OS
        return "mobile"
    return key.replace(" ", "_")


def client_platforms(project: Project) -> list[str]:
    """Platforms the client stated (brief or intake). "mobile" means both android and ios."""
    stated: list[str] = []
    for p in (project.brief.platforms if project.brief else []):
        n = normalise(p)
        stated += ["android", "ios"] if n == "mobile" else [n]
    return list(dict.fromkeys(stated))


def run(llm: LLMClient, project: Project) -> dict:
    b = project.brief
    reqs = "\n".join(f"{r.id} [{r.kind}]: {r.text}" for r in project.requirements) or "(none)"
    stated = client_platforms(project)
    prompt = (
        f"Goal: {b.goal if b else ''}\nDomain: {b.domain if b else ''}\nRegion: {b.region if b else ''}\n"
        f"Target users: {', '.join(b.target_users) if b else ''}\n"
        f"Platforms stated by the client: {', '.join(stated) or 'none'}\n\n"
        f"Requirements:\n{reqs}\n\n{SCHEMA}"
    )
    return parse_json(llm.complete(SYSTEM, prompt, json_mode=True).text)


def build_matrix(project: Project, result: dict) -> tuple[PlatformMatrix, list[str]]:
    """Turn the model's answer into a matrix that obeys the rules. Returns the matrix and notes."""
    notes: list[str] = []
    req_ids = {r.id for r in project.requirements}
    stated = set(client_platforms(project))
    rows: dict[str, PlatformDecision] = {}

    for item in result.get("platforms", []) or []:
        name = normalise(item.get("platform", ""))
        if not name or name == "mobile":
            continue
        ids = [i for i in item.get("requirement_ids", []) or [] if i in req_ids]
        unknown = [i for i in item.get("requirement_ids", []) or [] if i not in req_ids]
        if unknown:
            notes.append(f"Platform decision: ignored unknown requirement ids for {name}: {', '.join(map(str, unknown))}")
        row = rows.get(name)
        if row:  # the model listed the same platform twice: merge
            row.included = row.included or bool(item.get("included"))
            row.requirement_ids = list(dict.fromkeys(row.requirement_ids + ids))
            continue
        rows[name] = PlatformDecision(
            platform=name, included=bool(item.get("included")), reason=str(item.get("reason", "")).strip(),
            requirement_ids=ids,
        )

    for name in stated:
        row = rows.setdefault(name, PlatformDecision(platform=name, included=True, reason="Stated by the client."))
        if not row.included:
            notes.append(f"Platform decision: the agent left out {name}, but the client stated it; kept it in. "
                         f"Agent's reason: {row.reason or 'none given'}")
            row.included = True
        row.source = "client"
        row.reason = row.reason or "Stated by the client."

    for name in CORE_PLATFORMS:
        if name not in rows:
            rows[name] = PlatformDecision(platform=name, included=False,
                                          reason="No decision returned by the agent; review at Gate 2.")
            notes.append(f"Platform decision: no decision returned for {name}; marked as not included for review")

    ordered = [rows[n] for n in CORE_PLATFORMS] + [r for n, r in rows.items() if n not in CORE_PLATFORMS]
    approach = result.get("approach")
    return PlatformMatrix(
        decisions=ordered,
        approach=approach if approach in _APPROACHES else "not_applicable",
        approach_reason=str(result.get("approach_reason", "")).strip(),
    ), notes


def apply(project: Project, result: dict) -> None:
    from ..gaps.register import add_gap
    from ..questions.queue import ask
    from ..state.models import GapSource

    matrix, notes = build_matrix(project, result)
    project.platform_matrix = matrix
    for note in notes:
        project.log(note)
    for d in matrix.included():
        if d.source == "inferred":
            label = d.platform.replace("_", " ")
            gap = add_gap(project, source=GapSource.INFERRED,
                          description=f"Inferred platform, not stated by the client: {label}. {d.reason}".strip(),
                          found_by=NAME)
            ask(project, f"Please confirm the project needs this platform: {label}. Reason: {d.reason}",
                blocking=False, assumed_answer=f"Include {label}", related_gap_id=gap.id)


# ---------- code check, reviewed at Gate 2 ----------


@dataclass
class PlatformReport:
    passed: bool
    failures: list[str] = field(default_factory=list)


def platform_check(project: Project) -> PlatformReport:
    m = project.platform_matrix
    if m is None:
        return PlatformReport(False, ["Stage 2 has not run: no platform matrix"])
    failures: list[str] = []
    names = {d.platform for d in m.decisions}
    failures += [f"No decision for platform {n}" for n in CORE_PLATFORMS if n not in names]
    included = m.included()
    if not included:
        failures.append("No platform is included")
    failures += [f"{d.platform} is included without a reason" for d in included if not d.reason]
    failures += [f"{p} was stated by the client but is not included"
                 for p in client_platforms(project) if p not in {d.platform for d in included}]
    served = {rid for d in included for rid in d.requirement_ids}
    failures += [f"{r.id} is not served by any included platform: \"{r.text[:80]}\""
                 for r in project.requirements if r.kind == "functional" and r.id not in served]
    return PlatformReport(passed=not failures, failures=failures)
