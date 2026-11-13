"""Adaptive intake questionnaire: asked once, up front, skipping anything the input already answers."""
from __future__ import annotations

from dataclasses import dataclass

from ..state.models import Completeness, ProjectBrief


@dataclass(frozen=True)
class IntakeQuestion:
    key: str
    question: str
    hint: str = ""


BASE = [
    IntakeQuestion("domain", "What kind of product is this?", "classifieds, e-commerce, business tool, ..."),
    IntakeQuestion("region", "Which country or region is it for?", "e.g. India, Gujarat, Middle East"),
    IntakeQuestion("intent", "Is this a new product, a rebuild of an existing one, or like a reference app?",
                   "new / rebuild / like_reference"),
    IntakeQuestion("platforms", "Which platforms are needed?", "comma-separated: android, ios, web, admin panel"),
    IntakeQuestion("competitors", "Which competitor or reference apps should we compare against?",
                   "comma-separated names or links; leave empty and the agent will find them"),
    IntakeQuestion("deadline", "Is there a target launch date?", ""),
    IntakeQuestion("budget", "Is there a budget range?", ""),
]
THIN_EXTRA = [
    IntakeQuestion("target_users", "Who are the main users?", "comma-separated, e.g. buyers, sellers, admins"),
    IntakeQuestion("must_have_features", "Which features are must-haves for the first release?", "comma-separated"),
    IntakeQuestion("expected_scale", "Roughly how many users do you expect in the first year?", ""),
]


def _already_known(key: str, brief: ProjectBrief | None) -> bool:
    if brief is None:
        return False
    return {
        "domain": bool(brief.domain),
        "region": bool(brief.region),
        "intent": brief.intent != "unknown",
        "platforms": bool(brief.platforms),
        "target_users": bool(brief.target_users),
        "must_have_features": len(brief.features) >= 5,
    }.get(key, False)


def build_questionnaire(
    brief: ProjectBrief | None, completeness: Completeness, answers: dict[str, str] | None = None
) -> list[IntakeQuestion]:
    answers = answers or {}
    pool = list(BASE)
    if completeness is not Completeness.RICH:
        pool.append(THIN_EXTRA[0])
    if completeness is Completeness.THIN:
        pool.extend(THIN_EXTRA[1:])
    return [q for q in pool if not answers.get(q.key) and not _already_known(q.key, brief)]
