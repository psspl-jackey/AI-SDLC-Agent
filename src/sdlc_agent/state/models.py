"""Project state: everything the orchestrator tracks for one project.

Field names follow the team definition doc (Stage 0 and Stage 1 in detail).
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field


def now() -> datetime:
    return datetime.now(timezone.utc)


class Stage(str, Enum):
    INTAKE = "0_intake"
    REQUIREMENTS = "1_requirements"
    PLATFORM = "2_platform"
    PROPOSAL = "3_proposal"
    DESIGN = "4_design"
    SKILLS = "5_skills"
    PLAN = "6_plan"
    BUILD = "7_build"
    QA_RELEASE = "8_qa_release"
    HANDOVER = "9_handover"


class StageStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING_GATE = "waiting_gate"
    APPROVED = "approved"
    REJECTED = "rejected"
    FAILED = "failed"
    DONE = "done"  # finished; the stage has no gate of its own (its output is reviewed at a later gate)


class InputType(str, Enum):
    ONE_LINE = "one_line"
    URL = "url"
    APP_STORE_URL = "app_store_url"
    DOCUMENT = "document"
    IMAGE = "image"
    NOTES = "notes"
    MIXED = "mixed"


class Completeness(str, Enum):
    RICH = "rich"
    PARTIAL = "partial"
    THIN = "thin"


class SourceRef(BaseModel):
    """Where an item came from: a file and page, a URL, the intake form, or inferred by an agent."""

    kind: Literal["file", "url", "intake", "inferred", "change_request", "client_decision"]
    ref: str = ""

    def label(self) -> str:
        return f"{self.kind}:{self.ref}" if self.ref else self.kind


class RawInput(BaseModel):
    kind: Literal["text", "file", "url"]
    value: str  # the text itself, a file path, or a URL
    detected_type: Optional[InputType] = None


class Chunk(BaseModel):
    """A piece of readable text extracted from one input, with its source."""

    text: str
    source: SourceRef


class BriefItem(BaseModel):
    text: str
    source: SourceRef


class ProjectBrief(BaseModel):
    goal: str = ""
    domain: str = ""
    region: str = ""
    target_users: list[str] = Field(default_factory=list)
    intent: Literal["new", "rebuild", "like_reference", "unknown"] = "unknown"
    platforms: list[str] = Field(default_factory=list)
    features: list[BriefItem] = Field(default_factory=list)
    nfrs: list[BriefItem] = Field(default_factory=list)
    constraints: list[BriefItem] = Field(default_factory=list)
    references: list[str] = Field(default_factory=list)
    completeness: Completeness = Completeness.THIN


class SowLine(BaseModel):
    """One line of the client's input. Gate 1 requires every line to map to a requirement or be marked."""

    id: str
    text: str
    source: SourceRef
    requirement_ids: list[str] = Field(default_factory=list)
    not_a_requirement: bool = False


class Requirement(BaseModel):
    id: str
    text: str
    kind: Literal["functional", "nfr"] = "functional"
    source: SourceRef
    sow_line_ids: list[str] = Field(default_factory=list)
    changed_by: list[str] = Field(default_factory=list)  # change request ids that rewrote this requirement
    removed_by: Optional[str] = None  # change request id that removed it; kept for traceability

    @property
    def active(self) -> bool:
        return self.removed_by is None


class GapSource(str, Enum):
    SOW = "sow"
    NFR = "nfr"
    DOMAIN_CHECKLIST = "domain_checklist"
    COMPETITOR_TABLE_STAKES = "competitor_table_stakes"
    COMPETITOR_DIFFERENTIATOR = "competitor_differentiator"
    REVIEW_MINED = "review_mined"
    INFERRED = "inferred"


# Gaps from these sources must carry an evidence link and a research date (Gate 1 rule).
EVIDENCE_REQUIRED = {
    GapSource.COMPETITOR_TABLE_STAKES,
    GapSource.COMPETITOR_DIFFERENTIATOR,
    GapSource.REVIEW_MINED,
}


class Bucket(str, Enum):
    TABLE_STAKES = "table_stakes"
    DIFFERENTIATOR = "differentiator"
    ALREADY_IN_SOW = "already_in_sow"
    NOT_RELEVANT = "not_relevant"
    NONE = "none"


class GapStatus(str, Enum):
    ANSWERED = "answered"  # became a requirement
    ASSUMED = "assumed"  # in the assumption log
    OUT_OF_SCOPE = "out_of_scope"  # in exclusions
    RECOMMENDED = "recommended"  # market gap offered to the client as an addition
    OPEN = "open"  # waiting on the client, with an assumption attached


class Gap(BaseModel):
    id: str
    source: GapSource
    description: str
    evidence_url: Optional[str] = None
    research_date: Optional[date] = None
    bucket: Bucket = Bucket.NONE
    status: Optional[GapStatus] = None
    linked_requirement_id: Optional[str] = None
    assumption_id: Optional[str] = None
    found_by: str = ""
    found_at: datetime = Field(default_factory=now)


class Assumption(BaseModel):
    id: str
    text: str
    related_gap_id: Optional[str] = None
    created_at: datetime = Field(default_factory=now)


class Question(BaseModel):
    id: str
    text: str
    blocking: bool = False
    related_gap_id: Optional[str] = None
    assumed_answer: Optional[str] = None
    answer: Optional[str] = None
    asked_at: datetime = Field(default_factory=now)
    answered_at: Optional[datetime] = None


ApproverRole = Literal["tech_lead", "delivery_head", "sales"]
GATE_APPROVERS: tuple[str, ...] = ("tech_lead", "delivery_head", "sales")


class GateDecision(BaseModel):
    gate: int
    role: ApproverRole
    approved: bool
    comment: str = ""
    decided_at: datetime = Field(default_factory=now)


# Platforms every project gets an explicit yes/no decision on in Stage 2.
CORE_PLATFORMS: tuple[str, ...] = ("android", "ios", "web", "admin_panel", "backend")


class PlatformDecision(BaseModel):
    platform: str  # one of CORE_PLATFORMS, or another lower-case name such as "smart_tv"
    included: bool
    reason: str = ""
    source: Literal["client", "inferred"] = "inferred"  # client stated it, or the agent decided
    requirement_ids: list[str] = Field(default_factory=list)


class PlatformMatrix(BaseModel):
    decisions: list[PlatformDecision] = Field(default_factory=list)
    approach: Literal["native", "cross_platform", "web_only", "not_applicable"] = "not_applicable"
    approach_reason: str = ""
    decided_at: datetime = Field(default_factory=now)

    def included(self) -> list[PlatformDecision]:
        return [d for d in self.decisions if d.included]


class EstimateTask(BaseModel):
    id: str
    module: str
    feature: str
    title: str
    platform: str  # an included platform from the matrix, or "common" for cross-cutting work
    role: str = ""  # e.g. mobile developer, backend developer, QA, designer, project manager
    hours_min: float
    hours_likely: float
    hours_max: float
    requirement_ids: list[str] = Field(default_factory=list)
    gap_id: Optional[str] = None  # set for recommended additions (market gaps the client may opt into)

    @property
    def recommended(self) -> bool:
        return self.gap_id is not None

    @property
    def expected(self) -> float:
        """Three-point (PERT) expected hours."""
        return (self.hours_min + 4 * self.hours_likely + self.hours_max) / 6


class Estimate(BaseModel):
    tasks: list[EstimateTask] = Field(default_factory=list)
    risk_buffer_pct: float = 15.0
    accepted_gap_ids: list[str] = Field(default_factory=list)  # additions the client opted into
    declined_gap_ids: list[str] = Field(default_factory=list)  # additions the client did not take (kept for record)
    created_at: datetime = Field(default_factory=now)

    def base(self) -> list[EstimateTask]:
        """Agreed scope: tasks for requirements, plus additions the client accepted."""
        return [t for t in self.tasks if not t.recommended or t.gap_id in self.accepted_gap_ids]

    def additions(self) -> list[EstimateTask]:
        """Optional extras still on offer."""
        return [t for t in self.tasks
                if t.recommended and t.gap_id not in self.accepted_gap_ids and t.gap_id not in self.declined_gap_ids]


class ClientDecision(BaseModel):
    approved: bool
    opted_in_gap_ids: list[str] = Field(default_factory=list)
    comment: str = ""
    decided_at: datetime = Field(default_factory=now)


class ChangeRequest(BaseModel):
    id: str  # CR-001
    text: str
    line_ids: list[str] = Field(default_factory=list)  # input lines created from the text
    status: Literal["analysed", "applied"] = "analysed"
    added: list[str] = Field(default_factory=list)  # requirement ids
    changed: list[str] = Field(default_factory=list)
    removed: list[str] = Field(default_factory=list)
    platforms: dict[str, list[str]] = Field(default_factory=dict)  # requirement id -> platforms (added/changed)
    received_at: datetime = Field(default_factory=now)
    applied_at: Optional[datetime] = None

    def affected(self) -> set[str]:
        return set(self.added) | set(self.changed) | set(self.removed)


class StackChoice(BaseModel):
    platform: str
    pack: str  # tech pack name (tech_packs/<pack>.yaml)
    reason: str = ""
    alternatives: list[str] = Field(default_factory=list)


class Component(BaseModel):
    name: str
    kind: Literal["client", "service", "datastore", "external"] = "service"
    responsibility: str = ""
    uses: list[str] = Field(default_factory=list)  # names of other components


class Entity(BaseModel):
    name: str
    fields: list[str] = Field(default_factory=list)
    requirement_ids: list[str] = Field(default_factory=list)


class ApiEndpoint(BaseModel):
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"]
    path: str
    purpose: str = ""
    requirement_ids: list[str] = Field(default_factory=list)


class Screen(BaseModel):
    id: str  # SCR-001
    platform: str  # android, ios, web, admin_panel; "mobile" when android and ios share the screens
    name: str
    purpose: str = ""
    requirement_ids: list[str] = Field(default_factory=list)
    navigates_to: list[str] = Field(default_factory=list)  # screen ids


class DesignDecision(BaseModel):
    title: str
    decision: str
    reason: str = ""
    alternatives: list[str] = Field(default_factory=list)


class SolutionDesign(BaseModel):
    stacks: list[StackChoice] = Field(default_factory=list)
    components: list[Component] = Field(default_factory=list)
    entities: list[Entity] = Field(default_factory=list)
    endpoints: list[ApiEndpoint] = Field(default_factory=list)
    screens: list[Screen] = Field(default_factory=list)
    decisions: list[DesignDecision] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=now)


class SkillFile(BaseModel):
    name: str  # kebab-case; exported as <name>/SKILL.md
    description: str  # when to use the skill (skill front matter)
    platforms: list[str] = Field(default_factory=list)
    pack: Optional[str] = None  # tech pack it came from; None for the project-wide context skill
    content: str  # Markdown body
    tailored: dict[str, list[str]] = Field(default_factory=dict)  # section -> rules added for this project


class SkillPack(BaseModel):
    files: list[SkillFile] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=now)


class Ticket(BaseModel):
    id: str  # T-001; Jira assigns the real key (e.g. SDLC-12) on import
    type: Literal["epic", "task"]
    summary: str
    description: str = ""
    epic_id: Optional[str] = None
    task_id: Optional[str] = None  # the estimate task it comes from
    requirement_ids: list[str] = Field(default_factory=list)
    platform: str = ""
    role: str = ""
    hours: float = 0.0  # expected hours from the estimate
    depends_on: list[str] = Field(default_factory=list)  # ticket ids
    sprint: Optional[int] = None  # 1-based; epics have none
    jira_issue_key: Optional[str] = None  # set after the CSV import, e.g. SDLC-12

    @property
    def key(self) -> str:
        """Key used in branch names and commit messages: the Jira key once known, else the ticket id."""
        return self.jira_issue_key or self.id


class PlanReview(BaseModel):
    approved: bool
    comment: str = ""
    reviewed_at: datetime = Field(default_factory=now)


class Plan(BaseModel):
    jira_key: str
    sprint_weeks: int
    sprint_capacity_hours: float
    tickets: list[Ticket] = Field(default_factory=list)
    review: Optional[PlanReview] = None  # tech lead review; non-blocking
    created_at: datetime = Field(default_factory=now)

    def tasks(self) -> list[Ticket]:
        return [t for t in self.tickets if t.type == "task"]

    def sprint_count(self) -> int:
        return max((t.sprint or 0 for t in self.tasks()), default=0)


class BuildRecord(BaseModel):
    ticket_id: str
    status: Literal["pr_open", "merged", "failed", "superseded"]
    branch: str = ""
    pr_url: str = ""
    commit: str = ""
    files: list[str] = Field(default_factory=list)
    summary: str = ""
    error: str = ""
    created_at: datetime = Field(default_factory=now)


class Project(BaseModel):
    id: str
    name: str
    created_at: datetime = Field(default_factory=now)
    raw_inputs: list[RawInput] = Field(default_factory=list)
    intake_answers: dict[str, str] = Field(default_factory=dict)
    domain_pack: Optional[str] = None
    brief: Optional[ProjectBrief] = None
    sow_lines: list[SowLine] = Field(default_factory=list)
    requirements: list[Requirement] = Field(default_factory=list)
    gaps: list[Gap] = Field(default_factory=list)
    assumptions: list[Assumption] = Field(default_factory=list)
    questions: list[Question] = Field(default_factory=list)
    competitors: list[dict] = Field(default_factory=list)  # [{name, url, features: [...], researched_on}]
    platform_matrix: Optional[PlatformMatrix] = None  # Stage 2
    estimate: Optional[Estimate] = None  # Stage 3
    client_decision: Optional[ClientDecision] = None  # after Gate 2
    design: Optional[SolutionDesign] = None  # Stage 4
    skill_pack: Optional[SkillPack] = None  # Stage 5
    plan: Optional[Plan] = None  # Stage 6
    builds: list[BuildRecord] = Field(default_factory=list)  # Stage 7; kept as history across re-plans
    change_requests: list[ChangeRequest] = Field(default_factory=list)
    gate_decisions: list[GateDecision] = Field(default_factory=list)
    stage_status: dict[Stage, StageStatus] = Field(
        default_factory=lambda: {s: StageStatus.PENDING for s in Stage}
    )
    notes: list[str] = Field(default_factory=list)  # orchestrator log visible on the dashboard

    def active_requirements(self) -> list[Requirement]:
        return [r for r in self.requirements if r.active]

    def log(self, message: str) -> None:
        self.notes.append(f"{now():%Y-%m-%d %H:%M:%S} {message}")
