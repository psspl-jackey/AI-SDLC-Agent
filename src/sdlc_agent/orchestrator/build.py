"""Stage 7 orchestration: build tickets one at a time, each as a branch and a pull request.

- Scope: agents build the scaffold and first modules only, i.e. tickets up to BUILD_MAX_SPRINT
  (default sprint 1). Human developers take over the rest.
- Order: sprint, then ticket id; a ticket is ready when every ticket it depends on is merged.
- Review: every pull request waits for a human. mark_merged() records the merge (and, for the local
  host, merges the branch into develop), which unblocks the tickets that depend on it.
- Only coding tickets go to the developer agent (is_agent_ticket); design, QA planning and project
  management tickets are the team's, marked done on the Build screen.
- Code without unit tests gets one follow-up call for the tests. A change that still breaks a rule
  (no unit tests, secret found, path outside the repo...) is recorded as failed with the reason;
  nothing is committed for it.
"""
from __future__ import annotations

import re
from typing import Optional

from ..agents import developer
from ..build.git_host import GitHost, GitRuleError, GuardedGit, LocalGitHost
from ..state.models import BuildRecord, Project, Stage, StageStatus, Ticket
from .pipeline import Deps

ACTIVE = ("pr_open", "merged")


def local_host(deps: Deps, project_id: str) -> LocalGitHost:
    return LocalGitHost(deps.settings.data_dir / "build" / project_id)


NON_CODING_ROLES = re.compile(
    r"design|ux|ui/|project manag|product manag|\bpm\b|scrum|\bqa\b|test(er|ing)? (lead|analyst|engineer)?|"
    r"business analyst|\bba\b|delivery|account|content|copywrit|marketing", re.IGNORECASE)
NON_CODING_TITLES = re.compile(r"^\[[^\]]*\]\s*(design|wireframe|mock-?up|test plan|plan |user research|"
                               r"project management|documentation of requirements)", re.IGNORECASE)
# Releasing is people's work, checked by the Stage 8 release checklist; it wins even over "build".
RELEASE_TITLES = re.compile(r"^\[[^\]]*\]\s*((prepare (and|for) )?(release|deploy|publish|launch|go[- ]live)|"
                            r"(submit|upload)\w* .*(app|play) store)", re.IGNORECASE)


def is_agent_ticket(t: Ticket) -> bool:
    """The developer agent writes code. Design, QA planning, project management, analysis and release
    tickets go to the team, who mark them done on the Build screen (release is Stage 8's checklist)."""
    if RELEASE_TITLES.search(t.summary):
        return False
    builds_code = re.search(r"\b(implement|build|develop|code|integrate|set ?up)\w*", t.summary, re.IGNORECASE)
    if NON_CODING_TITLES.search(t.summary) and not builds_code:
        return False
    coding_role = re.search(r"develop|engineer|devops|tech lead|programmer", t.role or "", re.IGNORECASE)
    return bool(coding_role) or not (t.role and NON_CODING_ROLES.search(t.role))


def in_scope(project: Project, max_sprint: int) -> list[Ticket]:
    """Tickets the agents build: coding tickets up to max_sprint."""
    tasks = project.plan.tasks() if project.plan else []
    return sorted((t for t in tasks if t.sprint and t.sprint <= max_sprint and is_agent_ticket(t)),
                  key=lambda t: (t.sprint, t.id))


def latest(project: Project, ticket_id: str) -> Optional[BuildRecord]:
    records = [b for b in project.builds if b.ticket_id == ticket_id and b.status != "superseded"]
    return records[-1] if records else None


def _deps_merged(project: Project, t: Ticket) -> bool:
    return all((latest(project, d) or BuildRecord(ticket_id=d, status="failed")).status == "merged"
               for d in t.depends_on)


def next_ready(project: Project, max_sprint: int) -> Optional[Ticket]:
    """The next ticket never attempted whose dependencies are merged. Failed tickets are not picked
    again automatically (that would repeat the same model calls); retry them explicitly."""
    for t in in_scope(project, max_sprint):
        if latest(project, t.id) is None and _deps_merged(project, t):
            return t
    return None


def failed_tickets(project: Project, max_sprint: int) -> list[Ticket]:
    return [t for t in in_scope(project, max_sprint)
            if (rec := latest(project, t.id)) is not None and rec.status == "failed"]


def _slug(text: str) -> str:
    text = re.sub(r"^\[[^\]]*\]\s*", "", text.lower())
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")[:40].strip("-") or "change"


def _pr_body(ticket: Ticket, result: dict, files: list[str]) -> str:
    return "\n".join([
        f"Implements {', '.join(ticket.requirement_ids) or 'cross-cutting work'} (ticket {ticket.key}).", "",
        "## What changed", "", result.get("summary", "") or "See files.", "",
        "## Files", "", *[f"- `{f}`" for f in files], "",
        *(["## Notes from the agent", "", *[f"- {n}" for n in result.get("notes", [])], ""] if result.get("notes") else []),
        "## Reviewer checklist", "",
        "- [ ] Matches the ticket and the cited requirements, nothing more",
        "- [ ] Follows the project skills (architecture, conventions, security, testing)",
        "- [ ] Unit tests are meaningful and pass locally",
        "- [ ] No secrets; payment uses the dummy gateway only", "",
        "Generated by the AI SDLC Agent developer agent. A human must review before merging.",
    ])


def build_next(deps: Deps, project_id: str, git: GitHost | None = None,
               retry_ticket_id: str | None = None) -> tuple[Project, Optional[BuildRecord]]:
    """Build the next ready ticket, or retry one failed ticket when retry_ticket_id is given."""
    project = deps.store.load(project_id)
    if project.stage_status[Stage.PLAN] is not StageStatus.DONE or project.plan is None:
        raise RuntimeError("Run the internal plan (Stage 6) before the build (Stage 7)")
    max_sprint = deps.settings.build_max_sprint
    if retry_ticket_id:
        ticket = next((t for t in failed_tickets(project, max_sprint) if t.id == retry_ticket_id), None)
        if ticket is None:
            raise RuntimeError(f"{retry_ticket_id} is not a failed ticket in the agents' scope")
        if not _deps_merged(project, ticket):
            raise RuntimeError(f"{retry_ticket_id} still waits for its dependencies to be merged")
    else:
        ticket = next_ready(project, max_sprint)
    if ticket is None:
        _update_stage(project, max_sprint)
        deps.store.save(project)
        return project, None

    project.stage_status[Stage.BUILD] = StageStatus.RUNNING
    git = git or local_host(deps, project.id)
    attempts = sum(1 for b in project.builds if b.ticket_id == ticket.id)
    branch = f"feature/{ticket.key}-{_slug(ticket.summary)}" + (f"-r{attempts + 1}" if attempts else "")
    record = BuildRecord(ticket_id=ticket.id, status="failed", branch=branch)
    deps.tracer.record(project_id, {"type": "build_start", "ticket": ticket.id, "branch": branch})
    try:
        result = developer.run(deps.llm_for(project.id, developer.NAME), project, ticket)
        llm = deps.llm_for(project.id, developer.NAME)
        files = {f["path"].strip(): f["content"] for f in result.get("files", []) if f.get("path", "").strip()}
        if developer.needs_tests(files):
            files.update(developer.add_tests(llm, project, ticket, files))
            if developer.needs_tests(files):
                raise GitRuleError("The change has code but no unit tests, even after asking again; "
                                   "the definition of done requires them")
        guarded = GuardedGit(git)
        guarded.create_branch(branch)
        record.commit = guarded.commit_files(branch, files, f"{ticket.key}: {ticket.summary}", ticket.key)
        record.pr_url = guarded.open_pull_request(branch, f"{ticket.key}: {ticket.summary}",
                                                  _pr_body(ticket, result, sorted(files)), ticket.requirement_ids)
        record.status, record.files, record.summary = "pr_open", sorted(files), result.get("summary", "")
        project.log(f"{ticket.id} ({ticket.key}): pull request opened from {branch}: {record.pr_url}")
    except (GitRuleError, ValueError) as exc:
        record.error = str(exc)
        project.log(f"{ticket.id} ({ticket.key}): build refused: {exc}")
    except Exception as exc:  # model or git failure; keep the record so the dashboard shows it
        record.error = repr(exc)
        project.log(f"{ticket.id} ({ticket.key}): build failed: {exc!r}")
    project.builds.append(record)
    deps.tracer.record(project_id, {"type": "build_end", "ticket": ticket.id, "status": record.status})
    _update_stage(project, max_sprint)
    deps.store.save(project)
    return project, record


def mark_merged(deps: Deps, project: Project, ticket_id: str, git: GitHost | None = None) -> Project:
    """A human reviewed and merged the pull request. Unblocks the tickets that depend on it."""
    rec = latest(project, ticket_id)
    if rec is None or rec.status != "pr_open":
        raise RuntimeError(f"{ticket_id} has no open pull request")
    git = git or local_host(deps, project.id)
    if hasattr(git, "merge"):
        git.merge(rec.branch)
    rec.status = "merged"
    project.log(f"{ticket_id}: pull request merged into develop after human review")
    _update_stage(project, deps.settings.build_max_sprint)
    deps.store.save(project)
    return project


def _update_stage(project: Project, max_sprint: int) -> None:
    scope = in_scope(project, max_sprint)
    if scope and all((latest(project, t.id) or BuildRecord(ticket_id=t.id, status="failed")).status == "merged"
                     for t in scope):
        if project.stage_status[Stage.BUILD] is not StageStatus.DONE:
            project.log(f"Build: all {len(scope)} agent ticket(s) up to sprint {max_sprint} are merged. "
                        "Human developers take over the remaining tickets.")
        project.stage_status[Stage.BUILD] = StageStatus.DONE
    elif any(b.status != "superseded" for b in project.builds):
        project.stage_status[Stage.BUILD] = StageStatus.RUNNING


def mark_done_by_developers(deps: Deps, project: Project, ticket_id: str, pr_url: str = "") -> Project:
    """Record a ticket outside the agents' scope as built and merged by human developers."""
    ticket = next((t for t in (project.plan.tasks() if project.plan else []) if t.id == ticket_id), None)
    if ticket is None:
        raise RuntimeError(f"Unknown ticket {ticket_id}")
    if ticket in in_scope(project, deps.settings.build_max_sprint):
        raise RuntimeError(f"{ticket_id} is an agent ticket; merge its pull request instead")
    rec = latest(project, ticket_id)
    if rec is not None and rec.status == "merged":
        raise RuntimeError(f"{ticket_id} is already done")
    project.builds.append(BuildRecord(ticket_id=ticket_id, status="merged", pr_url=pr_url.strip(),
                                      summary="Built and merged by the development team"))
    project.log(f"{ticket_id} ({ticket.key}) done by the development team" + (f": {pr_url}" if pr_url else ""))
    deps.store.save(project)
    return project


def all_tickets_done(project: Project) -> list[str]:
    """Ticket ids still not merged (agent or human)."""
    return [t.id for t in (project.plan.tasks() if project.plan else [])
            if (latest(project, t.id) or BuildRecord(ticket_id=t.id, status="failed")).status != "merged"]
