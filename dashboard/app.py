"""Dashboard v1 for the AI SDLC Agent: all ten stages, from intake to handover.

Run from the repo root:  streamlit run dashboard/app.py
"""
from __future__ import annotations

from pathlib import Path

import httpx
import streamlit as st

from sdlc_agent import exports, traceability
from sdlc_agent.gaps.register import coverage_check, gate_status
from sdlc_agent.intake.questionnaire import build_questionnaire
from sdlc_agent.agents import estimator, handover, planner, qa
from sdlc_agent.agents.platform_decision import platform_check
from sdlc_agent.orchestrator import (
    Deps, apply_change_request, decide_gate, finish_intake, gate_failures, record_client_decision, run_stage1,
    review_plan, run_stage2, run_stage3, run_stage4, run_stage5, run_stage6, set_client_platforms, start_intake,
    submit_change_request,
)
from sdlc_agent.orchestrator.build import (
    build_next, failed_tickets, in_scope, latest, local_host, mark_done_by_developers, mark_merged,
)
from sdlc_agent.orchestrator.handover import record_signoff, run_stage9
from sdlc_agent.orchestrator.release import record_test_result, run_stage8, set_checklist_item
from sdlc_agent.orchestrator.pipeline import GATE_STAGE
from sdlc_agent.questions.queue import answer_question, open_questions
from sdlc_agent.state.models import GATE_APPROVERS, GapStatus, RawInput, Stage, StageStatus

st.set_page_config(page_title="AI SDLC Agent", layout="wide")

ROLE_LABELS = {"tech_lead": "Tech lead", "delivery_head": "Delivery head", "sales": "Sales"}
STAGE_LABELS = {
    Stage.INTAKE: "0. Intake", Stage.REQUIREMENTS: "1. Requirements and gaps", Stage.PLATFORM: "2. Platform",
    Stage.PROPOSAL: "3. Proposal", Stage.DESIGN: "4. Design", Stage.SKILLS: "5. Skills",
    Stage.PLAN: "6. Plan", Stage.BUILD: "7. Build", Stage.QA_RELEASE: "8. QA and release",
    Stage.HANDOVER: "9. Handover",
}
STATUS_ICON = {
    StageStatus.PENDING: "⚪", StageStatus.RUNNING: "🔵", StageStatus.WAITING_GATE: "🟡",
    StageStatus.APPROVED: "🟢", StageStatus.REJECTED: "🔴", StageStatus.FAILED: "🔴", StageStatus.DONE: "🟢",
}


@st.cache_resource
def get_deps() -> Deps:
    return Deps()


deps = get_deps()


def friendly_error(exc: Exception) -> str:
    if isinstance(exc, httpx.ConnectError) and deps.settings.model_provider == "ollama":
        return (f"Could not reach Ollama at {deps.settings.ollama_url}. Start it with `ollama serve` and pull the "
                f"model with `ollama pull {deps.settings.ollama_model}`.")
    return f"{type(exc).__name__}: {exc}"


# ---------- sidebar ----------
projects = deps.store.list()
with st.sidebar:
    st.subheader("AI SDLC Agent")
    st.caption(f"Model: {deps.llm.name}")
    for pid, err in deps.store.unreadable:
        st.warning(f"Project {pid} could not be loaded: {err}. If the code was just updated, restart the dashboard.")
    ids = ["New project"] + [p.id for p in projects]
    labels = ["New project"] + [f"{p.name} ({p.id})" for p in projects]
    current_id = st.session_state.get("project_id", "New project")
    default = ids.index(current_id) if current_id in ids else 0
    picked = st.selectbox("Project", labels, index=default)
    choice = ids[labels.index(picked)]
    st.session_state["project_id"] = choice
    page = None
    if choice != "New project":
        page = st.radio("Screen", ["Overview", "Questions", "Requirements", "Gap register",
                                   "Gate 1 approval", "Platforms", "Estimate", "Gate 2 approval",
                                   "Design", "Gate 3 approval", "Skills", "Plan", "Build", "QA and release", "Gate 4 approval",
                                   "Handover", "Traceability", "Change requests",
                                   "Deliverables",
                                   "Trace and cost"])


# ---------- new project ----------
def new_project_screen() -> None:
    st.header("New project")
    st.write("Add the client's requirement in any form. One line is enough; the agents fill the rest "
             "and mark everything they decided on their own.")
    name = st.text_input("Project name", placeholder="e.g. Classifieds app for Gujarat")
    text = st.text_area("Describe the project", placeholder="Build an app like OLX for Gujarat", height=120)
    urls = st.text_area("Links (one per line)", placeholder="Client website, reference app or store link", height=80)
    files = st.file_uploader("Files", accept_multiple_files=True,
                             type=["pdf", "docx", "xlsx", "csv", "txt", "md", "png", "jpg", "jpeg"])
    if st.button("Read inputs", type="primary", disabled=not name.strip()):
        inputs: list[RawInput] = []
        if text.strip():
            inputs.append(RawInput(kind="text", value=text.strip()))
        inputs += [RawInput(kind="url", value=u.strip()) for u in urls.splitlines() if u.strip()]
        if not inputs and not files:
            st.error("Add a description, a link or a file first.")
            return
        project = deps.store.create(name.strip())
        upload_dir = deps.settings.data_dir / "uploads" / project.id
        upload_dir.mkdir(parents=True, exist_ok=True)
        for f in files or []:
            path = upload_dir / Path(f.name).name
            path.write_bytes(f.getvalue())
            inputs.append(RawInput(kind="file", value=str(path)))
        with st.spinner("Reading inputs and building the project brief"):
            try:
                questions = start_intake(deps, project, inputs)
            except Exception as exc:
                st.error(friendly_error(exc))
                return
        st.session_state["project_id"] = project.id
        st.session_state[f"intake_q_{project.id}"] = [q.__dict__ for q in questions]
        st.rerun()


def intake_questionnaire(project) -> None:
    questions = st.session_state.get(f"intake_q_{project.id}") or [
        q.__dict__ for q in build_questionnaire(project.brief, project.brief.completeness, project.intake_answers)
    ] if project.brief else []
    st.subheader("A few questions before the agents start")
    st.write("Asked once. Leave anything blank and the agents will assume and log it.")
    with st.form(f"intake_{project.id}"):
        answers = {q["key"]: st.text_input(q["question"], help=q["hint"] or None) for q in questions}
        submitted = st.form_submit_button("Save answers and run Stage 1", type="primary")
    if submitted:
        finish_intake(deps, project, answers)
        with st.spinner("Running requirements analysis, domain and competitor research, and review"):
            try:
                run_stage1(deps, project.id)
            except Exception as exc:
                st.error(friendly_error(exc))
                return
        st.rerun()


# ---------- project screens ----------
def overview(project) -> None:
    st.header(project.name)
    if project.stage_status[Stage.INTAKE] is not StageStatus.APPROVED:
        intake_questionnaire(project)
        return
    cols = st.columns(5)
    for col, stage in zip(cols * 2, Stage):
        col.write(f"{STATUS_ICON[project.stage_status[stage]]} {STAGE_LABELS[stage]}")
    b = project.brief
    if b:
        st.subheader("Project brief")
        st.write(f"**Goal:** {b.goal or 'not stated'}")
        st.write(f"**Domain:** {b.domain or 'unknown'} · **Region:** {b.region or 'unknown'} · "
                 f"**Intent:** {b.intent} · **Platforms:** {', '.join(b.platforms) or 'not decided'} · "
                 f"**Input:** {b.completeness.value}")
    report = coverage_check(project)
    m = st.columns(4)
    m[0].metric("Requirements", len(project.requirements))
    m[1].metric("Gaps", len(project.gaps))
    m[2].metric("Open questions", len(open_questions(project)))
    m[3].metric("Coverage check", "Passed" if report.passed else f"{len(report.failures)} issue(s)")
    if project.stage_status[Stage.REQUIREMENTS] in (StageStatus.PENDING, StageStatus.FAILED):
        if st.button("Run Stage 1", type="primary"):
            with st.spinner("Running Stage 1"):
                try:
                    run_stage1(deps, project.id)
                except Exception as exc:
                    st.error(friendly_error(exc))
                    return
            st.rerun()
    if project.competitors:
        st.subheader("Competitors researched")
        st.dataframe([{"Name": c["name"], "Link": c["url"], "Features found": len(c["features"]),
                       "Researched on": c["researched_on"]} for c in project.competitors],
                     hide_index=True, width="stretch")
    st.subheader("Activity")
    for note in reversed(project.notes[-30:]):
        st.text(note)


def questions_screen(project) -> None:
    st.header("Questions")
    pending = open_questions(project)
    if not pending:
        st.success("No open questions.")
    answered_any = False
    for q in pending:
        with st.container(border=True):
            st.write(f"**{q.id}** {'· blocking' if q.blocking else ''}")
            st.write(q.text)
            if q.assumed_answer:
                st.caption(f"Working assumption until answered: {q.assumed_answer}")
            ans = st.text_input("Answer", key=f"ans_{q.id}")
            if st.button("Save answer", key=f"save_{q.id}") and ans.strip():
                answer_question(project, q.id, ans)
                deps.store.save(project)
                answered_any = True
    if answered_any:
        st.rerun()
    done = [q for q in project.questions if q.answer]
    if done:
        st.info("Each answer is recorded as a requirement and closes its gap. Answers that change scope after "
                "Gate 1 belong in a change request.")
        with st.expander(f"Answered ({len(done)})"):
            for q in done:
                st.write(f"**{q.id}** {q.text}  \nAnswer: {q.answer}")


def requirements_screen(project) -> None:
    st.header("Requirements")
    st.dataframe([{"ID": r.id, "Type": r.kind, "Requirement": r.text, "Source": r.source.label(),
                   "Input lines": ", ".join(r.sow_line_ids)} for r in project.requirements],
                 hide_index=True, width="stretch")
    st.subheader("Input lines")
    unmapped = [line for line in project.sow_lines if not line.requirement_ids and not line.not_a_requirement]
    if unmapped:
        st.warning(f"{len(unmapped)} input line(s) are not mapped to a requirement. Gate 1 stays closed until "
                   "each is mapped or marked as not a requirement.")
        for line in unmapped:
            c1, c2 = st.columns([5, 1])
            c1.write(f"**{line.id}** {line.text}")
            if c2.button("Not a requirement", key=f"nar_{line.id}"):
                line.not_a_requirement = True
                project.log(f"{line.id} marked as not a requirement")
                deps.store.save(project)
                st.rerun()
    st.dataframe([{"Line": line.id, "Text": line.text, "Source": line.source.label(),
                   "Requirements": ", ".join(line.requirement_ids) or ("not a requirement" if line.not_a_requirement else "")}
                  for line in project.sow_lines], hide_index=True, width="stretch")


def gaps_screen(project) -> None:
    st.header("Gap register")
    rows = exports.gap_rows(project)
    sources = sorted({r["source"] for r in rows})
    statuses = sorted({r["status"] or "no status" for r in rows})
    c1, c2 = st.columns(2)
    pick_sources = c1.multiselect("Source", sources, default=sources)
    pick_status = c2.multiselect("Status", statuses, default=statuses)
    st.dataframe([r for r in rows if r["source"] in pick_sources and (r["status"] or "no status") in pick_status],
                 hide_index=True, width="stretch",
                 column_config={"evidence_url": st.column_config.LinkColumn("Evidence")})


GATE_TEXT = {
    1: ("Approve the requirements, the competitor list, the buckets and the gap register.",
        "Coverage check"),
    2: ("Approve the platform matrix and the estimate, including the recommended additions offered to the "
        "client. Client approval of the proposal follows once the proposal document is produced.",
        "Platform and estimate checks"),
    3: ("Approve the stacks, architecture, data model, API and screens before skills setup and planning.",
        "Design check"),
    4: ("Approve the release: every test case has a result, every requirement has a passing case, no high-severity "
        "security finding, and the release checklist is complete.", "Release check"),
}


def gate_screen(project, gate: int) -> None:
    st.header(f"Gate {gate} approval")
    intro, check_name = GATE_TEXT[gate]
    st.write(f"{intro} Tech lead, delivery head and sales all need to approve.")
    failures = gate_failures(project, gate)
    if not failures:
        st.success(f"{check_name} passed.")
    else:
        st.error(f"{check_name} failed. Fix these before approving:")
        for f in failures:
            st.write(f"- {f}")
    decisions = gate_status(project, gate)
    cols = st.columns(3)
    for col, role in zip(cols, GATE_APPROVERS):
        v = decisions[role]
        col.metric(ROLE_LABELS[role], "Approved" if v is True else "Rejected" if v is False else "Waiting")
    st.subheader("Your decision")
    role_label = st.selectbox("Approving as", [ROLE_LABELS[r] for r in GATE_APPROVERS])
    role = next(r for r in GATE_APPROVERS if ROLE_LABELS[r] == role_label)
    comment = st.text_area("Comment")
    waiting = project.stage_status[GATE_STAGE[gate]] in (StageStatus.WAITING_GATE, StageStatus.REJECTED)
    c1, c2 = st.columns(2)
    if c1.button("Approve", type="primary", disabled=not (waiting and not failures)):
        decide_gate(deps, project, gate, role, True, comment)
        st.rerun()
    if c2.button("Reject", disabled=not waiting):
        decide_gate(deps, project, gate, role, False, comment)
        st.rerun()
    if gate == 2:
        client_decision_section(project)


def client_decision_section(project) -> None:
    st.subheader("Client decision")
    cd = project.client_decision
    if cd is not None:
        st.write(f"**{'Approved' if cd.approved else 'Rejected'}** by the client on {cd.decided_at:%Y-%m-%d}. "
                 f"Opted into: {', '.join(cd.opted_in_gap_ids) or 'no additions'}. {cd.comment}")
        return
    if project.stage_status[Stage.PROPOSAL] is not StageStatus.APPROVED:
        st.caption("Recorded here once tech lead, delivery head and sales have approved Gate 2.")
        return
    offered = [g for g in project.gaps if g.status is GapStatus.RECOMMENDED]
    hours = estimator.totals(project.estimate.additions(), "gap_id") if project.estimate else {}
    labels = {f"{g.id}: {g.description} ({hours[g.id].expected:.0f} h)" if g.id in hours else f"{g.id}: {g.description}": g.id
              for g in offered}
    picked = st.multiselect("Recommended additions the client opted into", list(labels))
    note = st.text_area("Client comment", key="client_comment")
    c1, c2 = st.columns(2)
    if c1.button("Record client approval", type="primary"):
        record_client_decision(deps, project, True, [labels[x] for x in picked], note)
        st.rerun()
    if c2.button("Record client rejection"):
        record_client_decision(deps, project, False, [], note)
        st.rerun()


def design_screen(project) -> None:
    st.header("Stage 4: solution design")
    st.write("Stack per platform from the tech packs, components, data model, API, and screens with their flows. "
             "Every requirement must reach a screen or an API endpoint. Approved at Gate 3.")
    cd = project.client_decision
    ready = project.stage_status[Stage.PROPOSAL] is StageStatus.APPROVED and cd is not None and cd.approved
    if not ready:
        st.info("The proposal must be approved at Gate 2 and by the client first.")
    label = "Run Stage 4" if project.design is None else "Run Stage 4 again"
    if st.button(label, type="primary", disabled=not ready):
        with st.spinner("Designing the solution"):
            try:
                run_stage4(deps, project.id)
            except Exception as exc:
                st.error(friendly_error(exc))
                return
        st.rerun()
    if project.design is None:
        return
    st.markdown(exports.architecture_markdown(project))


def skills_screen(project) -> None:
    st.header("Stage 5: skills setup")
    st.write("One skill per chosen stack, with every company rule from its tech pack plus rules added for this "
             "project, and a project context skill written from the approved design. Exported in the Claude Code "
             "skill layout for the Stage 7 coding agents.")
    ready = project.stage_status[Stage.DESIGN] is StageStatus.APPROVED
    if not ready:
        st.info("Approve the solution design at Gate 3 first.")
    label = "Run Stage 5" if project.skill_pack is None else "Run Stage 5 again"
    if st.button(label, type="primary", disabled=not ready):
        with st.spinner("Selecting and tailoring skills"):
            try:
                run_stage5(deps, project.id)
            except Exception as exc:
                st.error(friendly_error(exc))
                return
        st.rerun()
    if project.skill_pack is None:
        return
    st.download_button("Skill pack (.zip)", exports.skill_pack_zip(project), file_name=f"{project.id}-skills.zip")
    for f in project.skill_pack.files:
        added = sum(len(v) for v in f.tailored.values())
        with st.expander(f"{f.name} · {', '.join(f.platforms)}" + (f" · {added} project rules" if added else "")):
            st.markdown(f.content)


def plan_screen(project) -> None:
    st.header("Stage 6: internal plan")
    st.write("Jira tickets from the estimate (one epic per module), dependencies, sprints and a validation report. "
             "The tech lead reviews the plan; the review is recorded and does not hold the work.")
    ready = project.stage_status[Stage.SKILLS] is StageStatus.DONE
    if not ready:
        st.info("Run skills setup (Stage 5) first.")
    label = "Run Stage 6" if project.plan is None else "Run Stage 6 again"
    if st.button(label, type="primary", disabled=not ready):
        with st.spinner("Planning"):
            try:
                run_stage6(deps, project.id)
            except Exception as exc:
                st.error(friendly_error(exc))
                return
        st.rerun()
    plan = project.plan
    if plan is None:
        return
    c = st.columns(4)
    c[0].metric("Tickets", len(plan.tasks()))
    c[1].metric("Sprints", plan.sprint_count())
    c[2].metric("Sprint length", f"{plan.sprint_weeks} weeks")
    c[3].metric("Capacity per sprint", f"{plan.sprint_capacity_hours:g} h")
    if plan.jira_key == "SDLC":
        st.caption("Jira key SDLC is a placeholder; set JIRA_PROJECT_KEY in .env once the project exists.")
    report = planner.plan_check(project)
    if report.passed:
        st.success("Validation passed: every requirement maps to a ticket and the sprint order respects dependencies.")
    else:
        st.error("Validation found issues:")
        for f in report.failures:
            st.write(f"- {f}")
    c1, c2 = st.columns(2)
    c1.download_button("Jira import (.csv)", exports.jira_csv(project), file_name=f"{project.id}-jira.csv")
    c2.download_button("Sprint plan (.md)", exports.plan_markdown(project), file_name=f"{project.id}-plan.md")
    epics = {t.id: t.summary for t in plan.tickets if t.type == "epic"}
    st.dataframe([{"Sprint": t.sprint, "Ticket": t.id, "Epic": epics.get(t.epic_id, ""), "Summary": t.summary,
                   "Hours": t.hours, "Requirements": ", ".join(t.requirement_ids), "Depends on": ", ".join(t.depends_on)}
                  for t in sorted(plan.tasks(), key=lambda t: (t.sprint or 0, t.id))], hide_index=True, width="stretch")
    st.subheader("Tech lead review")
    if plan.review:
        st.write(f"**{'Approved' if plan.review.approved else 'Concerns raised'}** on "
                 f"{plan.review.reviewed_at:%Y-%m-%d}. {plan.review.comment}")
    note = st.text_area("Review comment", key="plan_review")
    r1, r2 = st.columns(2)
    if r1.button("Approve plan"):
        review_plan(deps, project, True, note)
        st.rerun()
    if r2.button("Raise concerns"):
        review_plan(deps, project, False, note)
        st.rerun()


def build_screen(project) -> None:
    st.header("Stage 7: build")
    max_sprint = deps.settings.build_max_sprint
    st.write(f"Agents build the scaffold and first modules only: tickets up to sprint {max_sprint}. Each ticket "
             "becomes a feature branch and a pull request into develop; a human reviews and merges every one, "
             "and only then can the tickets that depend on it start. Human developers take over the rest.")
    if project.plan is None or project.stage_status[Stage.PLAN] is not StageStatus.DONE:
        st.info("Run the internal plan (Stage 6) first.")
        return
    host = local_host(deps, project.id)
    st.caption(f"Everything is local: tickets use local ids (T-001...), code goes to the git repository at "
               f"{host.repo}, and pull requests are recorded next to it. Nothing is pushed and Jira is not needed. "
               "Review each change below before marking it merged.")
    if st.button("Build next ticket", type="primary"):
        with st.spinner("The developer agent is working on the next ticket"):
            try:
                _, rec = build_next(deps, project.id, host)
            except Exception as exc:
                st.error(friendly_error(exc))
                return
        if rec is None:
            st.info("No ticket is ready: waiting for reviews and merges, or all agent tickets are done.")
        else:
            st.rerun()
    rows = []
    for t in in_scope(project, max_sprint):
        rec = latest(project, t.id)
        rows.append({"Sprint": t.sprint, "Ticket": t.id, "Jira": t.jira_issue_key or "", "Summary": t.summary,
                     "Depends on": ", ".join(t.depends_on), "Status": rec.status if rec else "not started",
                     "Pull request": rec.pr_url if rec else "", "Problem": rec.error if rec else ""})
    st.dataframe(rows, hide_index=True, width="stretch")
    open_prs = [t for t in in_scope(project, max_sprint) if (r := latest(project, t.id)) and r.status == "pr_open"]
    if open_prs:
        st.subheader("Waiting for human review")
        for t in open_prs:
            rec = latest(project, t.id)
            c1, c2 = st.columns([4, 1])
            c1.write(f"**{t.id}** {t.summary}  \n`{rec.branch}` · {', '.join(rec.files)}")
            if c2.button("Mark merged", key=f"merge_{t.id}"):
                mark_merged(deps, project, t.id, host)
                st.rerun()
            with st.expander(f"Review the changes in {t.id} before merging"):
                if rec.summary:
                    st.write(rec.summary)
                try:
                    st.code(host.diff(rec.branch) or "(no changes)", language="diff")
                except Exception as exc:
                    st.error(f"Could not read the branch: {exc}")
    failed = failed_tickets(project, max_sprint)
    if failed:
        st.subheader("Failed")
        for t in failed:
            c1, c2 = st.columns([4, 1])
            c1.write(f"**{t.id}** {t.summary}: {latest(project, t.id).error}")
            if c2.button("Retry", key=f"retry_{t.id}"):
                with st.spinner("Retrying"):
                    try:
                        build_next(deps, project.id, host, retry_ticket_id=t.id)
                    except Exception as exc:
                        st.error(friendly_error(exc))
                        return
                st.rerun()
    human = [t for t in project.plan.tasks() if t not in in_scope(project, max_sprint)
             and not ((r := latest(project, t.id)) and r.status == "merged")]
    if human:
        with st.expander(f"Tickets for the team ({len(human)} open)"):
            st.caption("Design, QA planning and project management tickets, plus coding tickets after the agents' "
                       "sprint. Mark each one done when the team has finished it.")
            for t in human:
                c1, c2, c3 = st.columns([3, 2, 1])
                c1.write(f"**{t.id}** [sprint {t.sprint}] {t.summary}")
                url = c2.text_input("Pull request link", key=f"hpr_{t.id}", label_visibility="collapsed",
                                    placeholder="Pull request link (optional)")
                if c3.button("Done", key=f"hdone_{t.id}"):
                    mark_done_by_developers(deps, project, t.id, url)
                    st.rerun()
    with st.expander("Set Jira keys after the CSV import"):
        st.caption("Branches and commit messages use the Jira key once it is set, otherwise the ticket id.")
        tickets = {f"{t.id} {t.summary}": t for t in project.plan.tasks()}
        pick = st.selectbox("Ticket", list(tickets))
        key = st.text_input("Jira key", placeholder=f"{project.plan.jira_key}-12")
        if st.button("Save Jira key") and key.strip():
            tickets[pick].jira_issue_key = key.strip().upper()
            deps.store.save(project)
            st.rerun()


def traceability_screen(project) -> None:
    st.header("Traceability matrix")
    st.write("Every requirement traced from its source to the code that delivers it: input lines, gaps, platforms, "
             "estimate, design, tickets and pull requests. Breaks are shown only for stages that have run.")
    s = traceability.summary(project)
    c = st.columns(5)
    c[0].metric("Delivered", s["delivered"])
    c[1].metric("In review / build", s["in review"] + s["in build"])
    c[2].metric("Planned", s["planned"])
    c[3].metric("Chain breaks", s["breaks"])
    c[4].metric("Unaccounted input lines", s["unaccounted_lines"])
    d1, d2 = st.columns(2)
    d1.download_button("Traceability matrix (.xlsx)", traceability.xlsx(project), file_name=f"{project.id}-traceability.xlsx")
    d2.download_button("Traceability matrix (.md)", traceability.markdown(project), file_name=f"{project.id}-traceability.md")
    only_breaks = st.toggle("Only requirements with a break")
    rows = traceability.rows_for_table(project)
    st.dataframe([r for r in rows if r["Breaks"] or not only_breaks], hide_index=True, width="stretch")


def release_screen(project) -> None:
    st.header("Stage 8: QA and release")
    st.write("The QA agent writes test cases per requirement; testers run them and record results here (a sandbox "
             "runner can replace that later). Code scans the merged code on develop and builds the release checklist.")
    host = local_host(deps, project.id)
    label = "Run Stage 8" if project.release is None else "Run Stage 8 again (resets results)"
    if st.button(label, type="primary"):
        with st.spinner("Writing test cases and scanning the code"):
            try:
                run_stage8(deps, project.id, host)
            except Exception as exc:
                st.error(friendly_error(exc))
                return
        st.rerun()
    rel = project.release
    if rel is None:
        return
    done = sum(1 for c in rel.test_cases if c.result)
    c = st.columns(4)
    c[0].metric("Test cases run", f"{done}/{len(rel.test_cases)}")
    c[1].metric("Passed", sum(1 for x in rel.test_cases if x.result == "pass"))
    c[2].metric("Security findings (high)", f"{len(rel.findings)} ({sum(1 for f in rel.findings if f.severity == 'high')})")
    c[3].metric("Checklist", f"{sum(1 for i in rel.checklist if i.done)}/{len(rel.checklist)}")
    d1, d2 = st.columns(2)
    d1.download_button("Release notes (.md)", exports.release_notes_markdown(project), file_name=f"{project.id}-release-notes.md")
    d2.download_button("Test report (.csv)", exports.test_report_csv(project), file_name=f"{project.id}-test-report.csv")
    st.subheader("Test cases")
    for case in rel.test_cases:
        with st.expander(f"{case.id} [{case.kind}] {case.title} · {case.result or 'not run'}"):
            st.write(f"Requirements: {', '.join(case.requirement_ids) or 'none'} · Platform: {case.platform or 'any'}")
            for i, step in enumerate(case.steps, start=1):
                st.write(f"{i}. {step}")
            st.write(f"**Expected:** {case.expected}")
            note = st.text_input("Note", value=case.note, key=f"tcn_{case.id}")
            cols = st.columns(4)
            for col, result in zip(cols, ("pass", "fail", "blocked", "waived")):
                if col.button(result.capitalize(), key=f"tc_{case.id}_{result}"):
                    try:
                        record_test_result(deps, project, case.id, result, note)
                    except ValueError as exc:
                        st.error(str(exc))
                        return
                    st.rerun()
    st.subheader("Security findings")
    if rel.findings:
        st.dataframe([f.model_dump() for f in rel.findings], hide_index=True, width="stretch")
    else:
        st.success(f"No findings in {rel.scanned_files} files on develop.")
    st.subheader("Release checklist")
    for item in rel.checklist:
        checked = st.checkbox(f"[{item.platform}] {item.text}", value=item.done, key=f"rc_{item.id}")
        if checked != item.done:
            set_checklist_item(deps, project, item.id, checked)
            st.rerun()


def handover_screen(project) -> None:
    st.header("Stage 9: handover")
    st.write("The handover pack holds the handover summary, a maintenance guide with a project runbook, and every "
             "deliverable. The client signs off once the traceability matrix shows no break.")
    ready = project.stage_status[Stage.QA_RELEASE] is StageStatus.APPROVED
    if not ready:
        st.info("Gate 4 must approve the release first.")
    label = "Prepare handover pack" if project.handover is None else "Prepare handover pack again"
    if st.button(label, type="primary", disabled=not ready):
        with st.spinner("Writing the runbook and assembling the pack"):
            try:
                run_stage9(deps, project.id)
            except Exception as exc:
                st.error(friendly_error(exc))
                return
        st.rerun()
    if project.handover is None:
        return
    st.download_button("Handover pack (.zip)", exports.handover_zip(project), file_name=f"{project.id}-handover.zip")
    report = handover.handover_check(project)
    if report.passed:
        st.success("Traceability is complete: every requirement is traced and every input line is accounted for.")
    else:
        st.error("Sign-off is blocked until these are fixed:")
        for f in report.failures:
            st.write(f"- {f}")
    st.subheader("Open items the client signs off on")
    for label_, items in handover.open_items(project).items():
        st.write(f"**{label_}:** {len(items)}")
        for x in items:
            st.write(f"- {x}")
    with st.expander("Handover summary"):
        st.markdown(handover.handover_markdown(project))
    with st.expander("Maintenance guide"):
        st.markdown(handover.maintenance_markdown(project))
    st.subheader("Client sign-off")
    so = project.handover.signoff
    if so:
        st.write(f"**{'Accepted' if so.accepted else 'Not accepted'}** by {so.signed_by} on {so.signed_at:%Y-%m-%d}. "
                 f"{so.comment}")
    if project.stage_status[Stage.HANDOVER] in (StageStatus.WAITING_GATE, StageStatus.REJECTED):
        who = st.text_input("Signed by (client name and role)")
        note = st.text_area("Client comment", key="signoff_comment")
        c1, c2 = st.columns(2)
        if c1.button("Record acceptance", type="primary", disabled=not report.passed):
            try:
                record_signoff(deps, project, True, who, note)
            except (RuntimeError, ValueError) as exc:
                st.error(str(exc))
                return
            st.rerun()
        if c2.button("Record non-acceptance"):
            try:
                record_signoff(deps, project, False, who, note)
            except (RuntimeError, ValueError) as exc:
                st.error(str(exc))
                return
            st.rerun()


def change_requests_screen(project) -> None:
    st.header("Change requests")
    st.write("A change re-enters at Stage 1: requirements are updated, Gate 1 opens again, and after approval "
             "only the affected requirements are re-mapped to platforms and re-estimated.")
    pending = next((c for c in project.change_requests if c.status == "analysed"), None)
    if pending is None:
        text = st.text_area("Describe the change", placeholder="e.g. Sellers should be able to mark ads as sold")
        if st.button("Analyse change request", type="primary", disabled=not text.strip()):
            with st.spinner("Analysing the change"):
                try:
                    submit_change_request(deps, project.id, text)
                except Exception as exc:
                    st.error(friendly_error(exc))
                    return
            st.rerun()
    else:
        st.info(f"{pending.id} is analysed. Approve Gate 1 again, then apply it to update platforms and the estimate.")
        gate1_ok = project.stage_status[Stage.REQUIREMENTS] is StageStatus.APPROVED
        if st.button(f"Apply {pending.id}", type="primary", disabled=not gate1_ok):
            with st.spinner("Re-estimating the affected work"):
                try:
                    apply_change_request(deps, project.id)
                except Exception as exc:
                    st.error(friendly_error(exc))
                    return
            st.rerun()
    reqs = {r.id: r for r in project.requirements}
    for cr in reversed(project.change_requests):
        with st.container(border=True):
            st.write(f"**{cr.id}** · {cr.status} · received {cr.received_at:%Y-%m-%d %H:%M}")
            st.write(cr.text)
            for label, ids in (("Added", cr.added), ("Changed", cr.changed), ("Removed", cr.removed)):
                for rid in ids:
                    st.write(f"- {label} **{rid}**: {reqs[rid].text if rid in reqs else ''}")


def platform_switches(project) -> None:
    """Yes/No per platform, decided by a person at the Stage 2 review (recorded as the client's decision)."""
    from sdlc_agent.state.models import CORE_PLATFORMS

    m = project.platform_matrix
    with st.expander("Change platforms (Yes / No) and approach"):
        st.caption("Your choice is recorded as the client's decision: Yes cannot be dropped by the agent, No cannot "
                   "be added back. Saving re-runs Stage 2 to map the requirements.")
        current = {d.platform: d.included for d in m.decisions}
        choice = {name: st.toggle(name.replace("_", " "), value=current.get(name, False), key=f"pf_{name}")
                  for name in CORE_PLATFORMS}
        later = [s for s in (Stage.PROPOSAL, Stage.DESIGN, Stage.SKILLS, Stage.PLAN, Stage.BUILD, Stage.QA_RELEASE,
                             Stage.HANDOVER) if project.stage_status[s] is not StageStatus.PENDING]
        if later:
            st.warning(f"Saving resets {len(later)} later stage(s) of this project (estimate onward, including any "
                       "approvals and sign-off); they must be run again.")
        options = ["agent decides", "cross_platform", "native", "web_only"]
        set_before = project.brief.approach if project.brief and project.brief.approach else "agent decides"
        approach = st.selectbox("Delivery approach for the client apps", options, index=options.index(set_before),
                                help="cross_platform: one codebase for Android and iOS; native: separate apps")
        note = st.text_input("Reason (optional)", key="pf_note")
        changed = any(choice[n] != current.get(n, False) for n in CORE_PLATFORMS) or approach != set_before
        if st.button("Save platforms and re-run Stage 2", disabled=not changed, type="primary"):
            with st.spinner("Re-running the platform decision"):
                try:
                    set_client_platforms(deps, project.id, [n for n in CORE_PLATFORMS if choice[n]],
                                         [n for n in CORE_PLATFORMS if not choice[n]], note,
                                         None if approach == "agent decides" else approach)
                except Exception as exc:
                    st.error(friendly_error(exc))
                    return
            st.rerun()


def estimate_screen(project) -> None:
    st.header("Stage 3: estimate")
    st.write("Tasks with min, likely and max hours. Totals, the expected value and the risk buffer are computed "
             "by code. Recommended additions are estimated separately and are not in the base total.")
    ready = project.stage_status[Stage.PLATFORM] is StageStatus.DONE
    if not ready:
        st.info("Run the platform decision (Platforms screen) first.")
    label = "Run Stage 3" if project.estimate is None else "Run Stage 3 again"
    if st.button(label, type="primary", disabled=not ready):
        with st.spinner("Estimating"):
            try:
                run_stage3(deps, project.id)
            except Exception as exc:
                st.error(friendly_error(exc))
                return
        st.rerun()
    e = project.estimate
    if e is None:
        return
    base, extra = estimator.totals(e.base()), estimator.totals(e.additions())
    c = st.columns(4)
    c[0].metric("Base tasks", base.tasks)
    c[1].metric("Base hours (min-max)", f"{base.hours_min:.0f}-{base.hours_max:.0f}")
    c[2].metric(f"Expected + {e.risk_buffer_pct:g}% buffer", f"{estimator.with_buffer(base.expected, e.risk_buffer_pct):.0f} h")
    c[3].metric("Recommended additions", f"{extra.expected:.0f} h")
    st.subheader("Base scope")
    st.dataframe([{"ID": t.id, "Module": t.module, "Feature": t.feature, "Task": t.title, "Platform": t.platform,
                   "Role": t.role, "Min": t.hours_min, "Likely": t.hours_likely, "Max": t.hours_max,
                   "Expected": round(t.expected, 1), "Requirements": ", ".join(t.requirement_ids)}
                  for t in e.base()], hide_index=True, width="stretch")
    if e.additions():
        st.subheader("Recommended additions (client opts in)")
        st.dataframe([{"Gap": t.gap_id, "Task": t.title, "Platform": t.platform, "Min": t.hours_min,
                       "Likely": t.hours_likely, "Max": t.hours_max, "Expected": round(t.expected, 1)}
                      for t in e.additions()], hide_index=True, width="stretch")


def platforms_screen(project) -> None:
    st.header("Stage 2: platform decision")
    st.write("The agent maps the approved requirements to platforms. Platforms the client stated are always "
             "kept; platforms the agent adds are logged as assumptions. Reviewed at Gate 2.")
    gate1_ok = project.stage_status[Stage.REQUIREMENTS] is StageStatus.APPROVED
    if not gate1_ok:
        st.info("Approve Gate 1 first. The platform decision works from the approved requirements.")
    label = "Run Stage 2" if project.platform_matrix is None else "Run Stage 2 again"
    if st.button(label, type="primary", disabled=not gate1_ok):
        with st.spinner("Deciding platforms"):
            try:
                run_stage2(deps, project.id)
            except Exception as exc:
                st.error(friendly_error(exc))
                return
        st.rerun()
    m = project.platform_matrix
    if m is None:
        return
    st.dataframe([{"Platform": d.platform.replace("_", " "), "Included": "yes" if d.included else "no",
                   "Source": d.source, "Reason": d.reason, "Requirements": ", ".join(d.requirement_ids)}
                  for d in m.decisions], hide_index=True, width="stretch")
    st.write(f"**Delivery approach:** {m.approach.replace('_', ' ')}. {m.approach_reason}")
    platform_switches(project)
    report = platform_check(project)
    if report.passed:
        st.success("Platform check passed.")
    else:
        st.error("Platform check: resolve these before Gate 2.")
        for f in report.failures:
            st.write(f"- {f}")


def deliverables_screen(project) -> None:
    st.header("Deliverables")
    st.download_button("Requirements document (.md)", exports.requirements_markdown(project),
                       file_name=f"{project.id}-requirements.md")
    st.download_button("Gap register (.csv)", exports.gaps_csv(project), file_name=f"{project.id}-gaps.csv")
    st.download_button("Competitor feature matrix (.csv)", exports.competitors_csv(project),
                       file_name=f"{project.id}-competitors.csv", disabled=not project.competitors)
    st.download_button("Client question list (.md)", exports.questions_markdown(project),
                       file_name=f"{project.id}-questions.md")
    st.download_button("Platform matrix (.md)", exports.platform_matrix_markdown(project),
                       file_name=f"{project.id}-platforms.md", disabled=project.platform_matrix is None)
    st.download_button("Estimate sheet (.xlsx)", exports.estimate_xlsx(project), file_name=f"{project.id}-estimate.xlsx",
                       disabled=project.estimate is None)
    st.download_button("Estimate summary (.md)", exports.estimate_markdown(project),
                       file_name=f"{project.id}-estimate.md", disabled=project.estimate is None)
    st.download_button("Architecture document (.md)", exports.architecture_markdown(project),
                       file_name=f"{project.id}-architecture.md", disabled=project.design is None)
    st.download_button("Skill pack (.zip)", exports.skill_pack_zip(project), file_name=f"{project.id}-skills.zip",
                       disabled=project.skill_pack is None)
    st.download_button("Jira import (.csv)", exports.jira_csv(project), file_name=f"{project.id}-jira.csv",
                       disabled=project.plan is None, key="dl_jira")
    st.download_button("Traceability matrix (.xlsx)", traceability.xlsx(project),
                       file_name=f"{project.id}-traceability.xlsx", key="dl_trace")
    st.download_button("Release notes (.md)", exports.release_notes_markdown(project),
                       file_name=f"{project.id}-release-notes.md", disabled=project.release is None, key="dl_notes")
    st.download_button("Test report (.csv)", exports.test_report_csv(project),
                       file_name=f"{project.id}-test-report.csv", disabled=project.release is None, key="dl_tests")
    st.download_button("Handover pack (.zip)", exports.handover_zip(project), file_name=f"{project.id}-handover.zip",
                       disabled=project.handover is None, key="dl_handover")
    st.download_button("Sprint plan (.md)", exports.plan_markdown(project), file_name=f"{project.id}-plan.md",
                       disabled=project.plan is None, key="dl_plan")


def trace_screen(project) -> None:
    st.header("Trace and cost")
    t = deps.tracer.totals(project.id)
    c = st.columns(4)
    c[0].metric("Model calls", t["calls"])
    c[1].metric("Input tokens", f"{t['input_tokens']:,}")
    c[2].metric("Output tokens", f"{t['output_tokens']:,}")
    c[3].metric("Cost (USD)", f"{t['cost_usd']:.4f}")
    events = deps.tracer.read(project.id)
    st.dataframe([{k: e.get(k) for k in ("at", "type", "agent", "model", "ms", "input_tokens", "output_tokens",
                                             "cost_usd", "error")} for e in reversed(events)],
                 hide_index=True, width="stretch")


# ---------- router ----------
if choice == "New project":
    new_project_screen()
else:
    current = deps.store.load(choice)
    {
        "Overview": overview, "Questions": questions_screen, "Requirements": requirements_screen,
        "Gap register": gaps_screen, "Gate 1 approval": lambda p: gate_screen(p, 1), "Platforms": platforms_screen,
        "Estimate": estimate_screen, "Gate 2 approval": lambda p: gate_screen(p, 2),
        "Design": design_screen, "Gate 3 approval": lambda p: gate_screen(p, 3), "Skills": skills_screen,
        "Plan": plan_screen, "Build": build_screen, "QA and release": release_screen,
        "Gate 4 approval": lambda p: gate_screen(p, 4), "Handover": handover_screen,
        "Traceability": traceability_screen,
        "Change requests": change_requests_screen,
        "Deliverables": deliverables_screen,
        "Trace and cost": trace_screen,
    }[page](current)
