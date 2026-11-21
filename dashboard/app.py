"""Dashboard v1 for the AI SDLC Agent (intake through Stage 3 estimate and Gate 2).

Run from the repo root:  streamlit run dashboard/app.py
"""
from __future__ import annotations

from pathlib import Path

import httpx
import streamlit as st

from sdlc_agent import exports
from sdlc_agent.gaps.register import coverage_check, gate_status
from sdlc_agent.intake.questionnaire import build_questionnaire
from sdlc_agent.agents import estimator
from sdlc_agent.agents.platform_decision import platform_check
from sdlc_agent.orchestrator import (
    Deps, apply_change_request, decide_gate, finish_intake, gate_failures, record_client_decision, run_stage1,
    run_stage2, run_stage3, start_intake, submit_change_request,
)
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
                                   "Change requests", "Deliverables", "Trace and cost"])


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
        st.info("Answers are saved. Run Stage 1 again from Overview to apply them to the requirements and gaps.")
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
        "Change requests": change_requests_screen,
        "Deliverables": deliverables_screen,
        "Trace and cost": trace_screen,
    }[page](current)
