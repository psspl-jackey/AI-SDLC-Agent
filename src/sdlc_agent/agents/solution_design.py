"""Stage 4: solution design. Stack per platform, architecture, data model, APIs, screens and flows.

The model proposes in three small calls (stacks and architecture; data model and APIs; screens per
client app). Code enforces the rules:
- stacks come only from the tech packs (tech_packs/*.yaml) and must support their platform;
- cross-platform delivery means android and ios share one cross-platform pack; native means native packs;
- every active functional requirement is traced to at least one screen or API endpoint;
- payment always goes through a dummy gateway (added by code when missing); a real payment
  provider is out of scope and fails the check.
Screen wireframes are listed as screens and flows; drawn wireframes need a design tool.

run() is pure and returns a result dict; apply() is the only writer.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..domain_packs import load_tech_packs
from ..llm.base import LLMClient
from ..llm.json_call import Dicts, complete_json
from ..state.models import (
    ApiEndpoint, Component, DesignDecision, Entity, Project, Screen, SolutionDesign, StackChoice,
)
from ..state.store import next_id
from .platform_decision import normalise

NAME = "solution_design"
CLIENT_PLATFORMS = ("android", "ios", "web", "admin_panel")
METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE")
_PAY = re.compile(r"\bpay(ment|ments|s|ing)?\b|\bcheckout\b", re.IGNORECASE)
_DUMMY = re.compile(r"\b(dummy|mock|stub|fake|simulat\w*|static)\b", re.IGNORECASE)
_REAL_GATEWAYS = re.compile(r"\b(razorpay|stripe|paytm|paypal|phonepe|ccavenue|payu|cashfree|braintree|adyen)\b",
                            re.IGNORECASE)

SYSTEM = """You are the technical architect of a software delivery company. You design the solution
for an approved proposal: the technology stack per platform, the main components, the data model,
the API, and the screens with their navigation. Keep the design as simple as the requirements allow:
prefer a modular monolith backend over microservices unless a requirement needs otherwise.
Choose stacks only from the tech pack catalogue you are given. Real payment providers and other
third-party integrations are out of scope: payment uses a dummy gateway with static responses.
Cite requirement ids for everything you design."""

ARCH_ASK = """Choose one tech pack per platform, list the main components (clients, services, data
stores, external systems) and which components each one uses, and record the key design decisions
with the reason and the alternatives considered."""
ARCH_SHAPE = {
    "stacks": Dicts({"platform": "str", "pack": "str", "reason": "str", "alternatives": "strs"}),
    "components": Dicts({"name": "str", "kind": "str", "responsibility": "str", "uses": "strs"}, text_key="name"),
    "decisions": Dicts({"title": "str", "decision": "str", "reason": "str", "alternatives": "strs"}),
}
ARCH_SCHEMA = """Return JSON:
{"stacks": [{"platform": str, "pack": str, "reason": str, "alternatives": [str]}],
 "components": [{"name": str, "kind": "client" | "service" | "datastore" | "external", "responsibility": str,
                 "uses": [str]}],
 "decisions": [{"title": str, "decision": str, "reason": str, "alternatives": [str]}]}"""

DATA_ASK = "Design the data model (entities and their main fields) and the REST API the clients call."
DATA_SHAPE = {
    "entities": Dicts({"name": "str", "fields": "strs", "requirement_ids": "strs"}, text_key="name"),
    "endpoints": Dicts({"method": "str", "path": "str", "purpose": "str", "requirement_ids": "strs"}),
}
DATA_SCHEMA = """Return JSON:
{"entities": [{"name": str, "fields": [str], "requirement_ids": [str]}],
 "endpoints": [{"method": "GET" | "POST" | "PUT" | "PATCH" | "DELETE", "path": str, "purpose": str,
                "requirement_ids": [str]}]}"""

SCREENS_ASK = """List the screens of the %s and how users move between them. Give each screen a short
key (S1, S2, ...) and use those keys in navigates_to."""
SCREENS_SHAPE = {
    "screens": Dicts({"key": "str", "name": "str", "purpose": "str", "requirement_ids": "strs",
                      "navigates_to": "strs"}, text_key="name"),
}
SCREENS_SCHEMA = """Return JSON:
{"screens": [{"key": str, "name": str, "purpose": str, "requirement_ids": [str], "navigates_to": [str]}]}"""

GROUP_LABELS = {"mobile": "mobile app (android and ios share these screens)", "android": "android app",
                "ios": "ios app", "web": "customer web app", "admin_panel": "admin panel"}


def screen_groups(project: Project) -> dict[str, list[str]]:
    """Client app -> requirement ids it serves. Cross-platform android and ios share one set of screens."""
    m = project.platform_matrix
    rows = {d.platform: d for d in m.included()} if m else {}
    groups: dict[str, list[str]] = {}
    shared = m is not None and m.approach == "cross_platform" and "android" in rows and "ios" in rows
    if shared:
        groups["mobile"] = list(dict.fromkeys(rows["android"].requirement_ids + rows["ios"].requirement_ids))
    for p in CLIENT_PLATFORMS:
        if p in rows and not (shared and p in ("android", "ios")):
            groups[p] = list(rows[p].requirement_ids)
    return groups


def _catalogue(packs: dict[str, dict]) -> str:
    return "\n".join(f"- {name}: {p.get('title', name)}; platforms {', '.join(p.get('platforms', []))}; "
                     f"approach {p.get('approach', '')}" for name, p in packs.items())


def run(llm: LLMClient, project: Project) -> dict:
    m = project.platform_matrix
    reqs = {r.id: r for r in project.active_requirements()}
    req_list = "\n".join(f"{r.id} [{r.kind}]: {r.text}" for r in reqs.values()) or "(none)"
    ctx = (f"Goal: {project.brief.goal if project.brief else ''}\n"
           f"Platforms: {', '.join(d.platform for d in m.included())}\nDelivery approach: {m.approach}\n")
    result: dict = {}

    result["architecture"] = complete_json(
        llm, SYSTEM,
        f"{ctx}\nTech pack catalogue:\n{_catalogue(load_tech_packs())}\n\nRequirements:\n{req_list}\n\n"
        f"{ARCH_ASK}\n\n{ARCH_SCHEMA}",
        ARCH_SHAPE,
    )
    if "backend" in {d.platform for d in m.included()}:
        result["data"] = complete_json(
            llm, SYSTEM, f"{ctx}\nRequirements:\n{req_list}\n\n{DATA_ASK}\n\n{DATA_SCHEMA}", DATA_SHAPE,
        )
    result["screens"] = {}
    for group, ids in screen_groups(project).items():
        served = "\n".join(f"{i}: {reqs[i].text}" for i in ids if i in reqs)
        if not served:
            continue
        result["screens"][group] = complete_json(
            llm, SYSTEM,
            f"{ctx}\nRequirements for the {GROUP_LABELS[group]}:\n{served}\n\n"
            f"{SCREENS_ASK % GROUP_LABELS[group]}\n\n{SCREENS_SCHEMA}",
            SCREENS_SHAPE,
        )
    return result


def _align_mobile_stacks(project: Project, stacks: dict[str, StackChoice]) -> list[str]:
    """Make the Android and iOS packs follow the Stage 2 approach; small models often mix them."""
    m = project.platform_matrix
    included = {d.platform for d in m.included()} if m else set()
    if m is None or not {"android", "ios"} <= included or m.approach not in ("cross_platform", "native"):
        return []
    packs = load_tech_packs()

    def fits(name: str, platform: str) -> bool:
        p = packs.get(name, {})
        return p.get("approach") == m.approach and platform in p.get("platforms", [])

    before = {p: stacks[p].pack if p in stacks else None for p in ("android", "ios")}
    if m.approach == "cross_platform":
        chosen = next((before[p] for p in ("android", "ios")
                       if before[p] and fits(before[p], "android") and fits(before[p], "ios")), None)
        chosen = chosen or next(n for n in packs if fits(n, "android") and fits(n, "ios"))
        target = {"android": chosen, "ios": chosen}
    else:
        target = {p: before[p] if before[p] and fits(before[p], p) else next(n for n in packs if fits(n, p))
                  for p in ("android", "ios")}
    notes = []
    for p in ("android", "ios"):
        if before[p] == target[p]:
            continue
        reason = f"Set by code to follow the {m.approach.replace('_', '-')} approach chosen at Stage 2."
        if p in stacks:
            old = stacks[p]
            stacks[p] = StackChoice(platform=p, pack=target[p], reason=reason,
                                    alternatives=[a for a in [old.pack, *old.alternatives] if a and a != target[p]])
        else:
            stacks[p] = StackChoice(platform=p, pack=target[p], reason=reason, alternatives=[])
        notes.append(f"Solution design: {p} stack changed from {before[p] or 'none'} to {target[p]} "
                     f"({m.approach.replace('_', '-')} approach)")
    return notes


def build_design(project: Project, result: dict) -> tuple[SolutionDesign, list[str]]:
    notes: list[str] = []
    req_ids = {r.id for r in project.active_requirements()}

    def ids(values: list[str]) -> list[str]:
        return [i for i in values if i in req_ids]

    arch = result.get("architecture") or {}
    stacks: dict[str, StackChoice] = {}
    for s in arch.get("stacks", []):
        platform = normalise(s.get("platform", ""))
        if platform and platform not in stacks:
            stacks[platform] = StackChoice(platform=platform, pack=normalise(s.get("pack", "")),
                                           reason=s.get("reason", ""), alternatives=s.get("alternatives", []))
    notes += _align_mobile_stacks(project, stacks)

    components: dict[str, Component] = {}
    for c in arch.get("components", []):
        name = c.get("name", "").strip()
        if not name or name.lower() in {k.lower() for k in components}:
            continue
        kind = c.get("kind", "").lower()
        components[name] = Component(name=name, kind=kind if kind in ("client", "service", "datastore", "external")
                                     else "service", responsibility=c.get("responsibility", ""), uses=c.get("uses", []))
    known = set(components)
    for c in components.values():
        dropped = [u for u in c.uses if u not in known]
        c.uses = [u for u in c.uses if u in known and u != c.name]
        if dropped:
            notes.append(f"Solution design: {c.name} uses unknown component(s) {', '.join(dropped)}; link dropped")

    if any(_PAY.search(r.text) for r in project.active_requirements()) and not any(
        _PAY.search(c.name) and _DUMMY.search(c.name + " " + c.responsibility) for c in components.values()
    ):
        components["Dummy payment gateway"] = Component(
            name="Dummy payment gateway", kind="external",
            responsibility="Returns static success and failure responses so the payment flow can be demoed; "
                           "real payment integration is out of scope for now.",
        )
        notes.append("Solution design: added the dummy payment gateway (payment is built against static responses)")

    data = result.get("data") or {}
    entities = []
    for e in data.get("entities", []):
        if e.get("name", "").strip():
            entities.append(Entity(name=e["name"].strip(), fields=e.get("fields", []), requirement_ids=ids(e.get("requirement_ids", []))))
    endpoints: list[ApiEndpoint] = []
    seen: set[tuple[str, str]] = set()
    for ep in data.get("endpoints", []):
        method, path = ep.get("method", "").upper().strip(), ep.get("path", "").strip()
        if method not in METHODS or not path:
            notes.append(f"Solution design: dropped endpoint '{method} {path}' (unknown method or no path)")
            continue
        path = path if path.startswith("/") else "/" + path
        if (method, path) in seen:
            continue
        seen.add((method, path))
        endpoints.append(ApiEndpoint(method=method, path=path, purpose=ep.get("purpose", ""),
                                     requirement_ids=ids(ep.get("requirement_ids", []))))

    screens: list[Screen] = []
    for group, reply in (result.get("screens") or {}).items():
        key_to_id: dict[str, str] = {}
        batch = []
        for sc in reply.get("screens", []):
            if not sc.get("name", "").strip():
                continue
            sid = next_id("SCR", [x.id for x in screens] + [x.id for x, _ in batch])
            if sc.get("key"):
                key_to_id[sc["key"]] = sid
            batch.append((Screen(id=sid, platform=group, name=sc["name"].strip(), purpose=sc.get("purpose", ""),
                                 requirement_ids=ids(sc.get("requirement_ids", []))), sc.get("navigates_to", [])))
        for screen, targets in batch:
            screen.navigates_to = [key_to_id[t] for t in targets if t in key_to_id and key_to_id[t] != screen.id]
            screens.append(screen)

    decisions = [DesignDecision(title=d.get("title", ""), decision=d.get("decision", ""), reason=d.get("reason", ""),
                                alternatives=d.get("alternatives", []))
                 for d in arch.get("decisions", []) if d.get("title") or d.get("decision")]
    return SolutionDesign(stacks=list(stacks.values()), components=list(components.values()), entities=entities,
                          endpoints=endpoints, screens=screens, decisions=decisions), notes


def apply(project: Project, result: dict) -> None:
    design, notes = build_design(project, result)
    project.design = design
    for note in notes:
        project.log(note)


# ---------- code check, reviewed at Gate 3 ----------


@dataclass
class DesignReport:
    passed: bool
    failures: list[str] = field(default_factory=list)


def design_check(project: Project) -> DesignReport:
    d, m = project.design, project.platform_matrix
    if d is None or m is None:
        return DesignReport(False, ["Stage 4 has not run: no solution design"])
    failures: list[str] = []
    packs = load_tech_packs()
    included = [x.platform for x in m.included()]
    stacks = {s.platform: s for s in d.stacks}
    for p in included:
        s = stacks.get(p)
        if s is None:
            failures.append(f"No stack chosen for {p}")
        elif s.pack not in packs:
            failures.append(f"{p}: stack '{s.pack}' has no tech pack; choose from {', '.join(packs)} or add a pack")
        elif p not in packs[s.pack].get("platforms", []):
            failures.append(f"{p}: tech pack {s.pack} does not support {p}")
    if "android" in stacks and "ios" in stacks and "android" in included and "ios" in included:
        a, i = stacks["android"].pack, stacks["ios"].pack
        if m.approach == "cross_platform" and (a != i or packs.get(a, {}).get("approach") != "cross_platform"):
            failures.append(f"Approach is cross-platform, but android uses {a} and ios uses {i}; "
                            "use one cross-platform pack for both")
        if m.approach == "native" and any(packs.get(x, {}).get("approach") != "native" for x in (a, i)):
            failures.append(f"Approach is native, but android uses {a} and ios uses {i}")

    traced = {rid for x in d.screens for rid in x.requirement_ids} | {rid for e in d.endpoints for rid in e.requirement_ids}
    failures += [f"{r.id} is not traced to any screen or API endpoint: \"{r.text[:80]}\""
                 for r in project.active_requirements() if r.kind == "functional" and r.id not in traced]
    if "backend" in included and not (d.endpoints and d.entities):
        failures.append("Backend is included but the design has no API endpoints or no data model")
    covered = {x.platform for x in d.screens}
    if "mobile" in covered:
        covered |= {"android", "ios"}
    failures += [f"{p} has no screens" for p in included if p in CLIENT_PLATFORMS and p not in covered]
    failures += [f"{c.name}: real payment providers are out of scope; use the dummy gateway"
                 for c in d.components if _REAL_GATEWAYS.search(c.name + " " + c.responsibility)]
    return DesignReport(passed=not failures, failures=failures)
