"""Gap register and the Gate 1 coverage check.

The coverage check is plain code on purpose: an LLM can skip an item while summarising,
a check against IDs cannot. Gate 1 stays closed until every rule below passes.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..state.models import (
    EVIDENCE_REQUIRED,
    GATE_APPROVERS,
    Bucket,
    Gap,
    GapSource,
    GapStatus,
    Project,
)
from ..state.store import next_id


def add_gap(
    project: Project,
    *,
    source: GapSource,
    description: str,
    found_by: str,
    evidence_url: str | None = None,
    research_date=None,
    bucket: Bucket = Bucket.NONE,
    status: GapStatus | None = None,
) -> Gap:
    gap = Gap(
        id=next_id("GAP", (g.id for g in project.gaps)),
        source=source,
        description=description.strip(),
        evidence_url=evidence_url,
        research_date=research_date,
        bucket=bucket,
        status=status,
        found_by=found_by,
    )
    project.gaps.append(gap)
    return gap


@dataclass
class CoverageReport:
    passed: bool
    failures: list[str] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)


def coverage_check(project: Project) -> CoverageReport:
    failures: list[str] = []
    req_ids = {r.id for r in project.requirements}
    asm_ids = {a.id for a in project.assumptions}

    # Rule 1: every input line maps to a requirement or is marked as not a requirement.
    for line in project.sow_lines:
        valid = [rid for rid in line.requirement_ids if rid in req_ids]
        if not valid and not line.not_a_requirement:
            failures.append(f"{line.id} is not mapped to any requirement: \"{line.text[:80]}\"")

    for gap in project.gaps:
        # Rule 2: every gap has a status.
        if gap.status is None:
            failures.append(f"{gap.id} has no status")
            continue
        # Rule 3: competitor and review gaps carry a source link and research date.
        if gap.source in EVIDENCE_REQUIRED and (not gap.evidence_url or not gap.research_date):
            failures.append(f"{gap.id} ({gap.source.value}) is missing its evidence link or research date")
        # Rule 4: open and assumed gaps have an assumption attached.
        if gap.status in (GapStatus.OPEN, GapStatus.ASSUMED) and gap.assumption_id not in asm_ids:
            failures.append(f"{gap.id} is {gap.status.value} but has no assumption attached")
        # Answered gaps must point at a real requirement.
        if gap.status is GapStatus.ANSWERED and gap.linked_requirement_id not in req_ids:
            failures.append(f"{gap.id} is answered but not linked to an existing requirement")

    counts = {s.value: sum(1 for g in project.gaps if g.status is s) for s in GapStatus}
    counts["no_status"] = sum(1 for g in project.gaps if g.status is None)
    counts["total"] = len(project.gaps)
    return CoverageReport(passed=not failures, failures=failures, counts=counts)


def gate_status(project: Project, gate: int) -> dict[str, bool | None]:
    """Latest decision per approver role for a gate. None means not decided yet."""
    latest: dict[str, bool | None] = {role: None for role in GATE_APPROVERS}
    for d in sorted(project.gate_decisions, key=lambda d: d.decided_at):
        if d.gate == gate:
            latest[d.role] = d.approved
    return latest


def gate_passed(project: Project, gate: int) -> bool:
    """Every gate needs approval from the tech lead, the delivery head and sales."""
    return all(v is True for v in gate_status(project, gate).values())
