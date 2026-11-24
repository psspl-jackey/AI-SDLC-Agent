# CLAUDE.md: context for Claude Code

Read this first in every session. It holds the decisions made while designing this project
(November 2026, with Jackey Kabra, mobile tech lead, Prakash Infotech).
The full team definition is in `docs/system-definition.md` (exported from the team doc).

## What this project is

An AI agent system that takes a client requirement in ANY form (full SOW, short brief, one-line idea,
website or app-store link, Word/PDF/Excel, screenshots, notes) and carries it through 10 stages to a
working project, with human approval gates. Works for any domain (classifieds, e-commerce, fintech,
healthcare, business tools) and any tech stack; domain and tech knowledge come from plug-in packs,
not new agents.

## The flow (10 stages, 4 gates)

0 Intake -> 1 Requirements and gaps -> [Gate 1] -> 2 Platform -> 3 Estimation and proposal -> [Gate 2]
-> 4 Solution design -> [Gate 3] -> 5 Skills setup -> 6 Internal plan -> 7 Build -> 8 QA and release
-> [Gate 4] -> 9 Handover. A change request at any point re-enters at Stage 1.

## Status

- Done (branch `feature/foundation`): foundation + Phase 1 (Stages 0 and 1, Gate 1, dashboard), eval runner
  and answer keys (classifieds key is a draft awaiting senior review).
- Done (branch `feature/stage2-platform-decision`): Stage 2 platform decision agent, platform check, dashboard screen.
- Done (branch `feature/stage3-estimate`, stacked on Stage 2): Stage 3 estimator (tasks with min-likely-max hours,
  PERT totals and risk buffer computed in code, recommended additions estimated separately), estimate sheet
  (.xlsx), Gate 2 (three roles; blocked while platform or estimate checks fail).
- Done (branch `feature/client-approval-change-requests`, stacked on Stage 3): client decision after internal
  Gate 2 (opt-in additions become requirements, declined ones out of scope); change requests (text becomes input
  lines, change analyst adds/changes/removes requirements with stable ids, Gate 1 reopens, then only affected
  requirements are re-mapped and re-estimated).
- Done (branch `feature/llm-json-hardening`, stacked): JSON retry and shape coercion for every model call.
- Done (branch `feature/stage4-solution-design`, stacked): Stage 4 solution design (stacks from tech packs,
  components, data model, API, screens and flows), architecture doc with Mermaid diagrams, Gate 3.
- Done (branch `feature/stage5-skills-setup`, stacked): Stage 5 skill pack (company rules from tech packs kept,
  model only adds project rules, project context skill from the design, Claude Code SKILL.md layout).
- Done (branch `feature/stage6-internal-plan`, stacked): Stage 6 plan (tickets from the estimate, model dependencies
  validated and cycles broken, sprints scheduled by code, validation report, Jira CSV export, tech lead review non-blocking).
- Done (branch `feature/stage7-build`, stacked): Stage 7 build loop (developer agent per ticket, GuardedGit rules,
  local git host with real branches and recorded pull requests, human merge unblocks dependents, failed tickets
  retried explicitly, handover when agent-scope tickets are merged).
- Done (branch `feature/traceability-matrix`, stacked): traceability matrix (`traceability.py`, pure code): one row
  per requirement from input line to pull request, chain breaks flagged per stage that has run; .xlsx and .md.
- Done (branch `feature/stage8-qa-release`, stacked): Stage 8 (QA agent writes test cases, people record results;
  code security scan of develop; per-platform release checklist; release notes and test report), Gate 4, and
  'done by developers' for tickets outside the agents' scope.
- Done (branch `feature/stage9-handover`, stacked): Stage 9 handover pack (summary, maintenance guide with a
  model-written runbook, every deliverable in one zip) and client sign-off, blocked by traceability breaks.
  All ten stages now run end to end on the fake model.
- In progress (branch `feature/prompt-tuning-round1`): fixes from the first qwen2.5:7b runs (checklist needs a
  cited feature, platforms only if the client said them, analyst follow-up for unmapped lines, reviewer merge
  guard, thin briefs filled from the domain pack, dummy-payment wording) and Stage 7 fixes (only coding tickets
  go to the developer agent; one follow-up call for missing tests; local pull request diff on the dashboard).
- Done (same branch): runnable starter apps and run checks. Stage 7 first puts code-written starter apps on
  develop (`starters/<pack>/`, rendered by `build/starters.py`: FastAPI backend with dummy data, Next.js or Vite
  admin panel and website, one Expo app for Android and iOS), then tickets extend them. `orchestrator/apps.py`
  installs, tests, starts and stops them on a worktree of develop (`build/runner.py`), results in
  `project.run_checks`; "Run the apps" on the Build screen shows links and an Expo Go QR code.
- Next: re-run the eval and keep tuning prompts; GitHub host and
  Docker sandbox (Stage 7 and automated test runs in Stage 8); rate card for team plan, timeline and cost; proposal doc and
  PPT once the Prakash Infotech templates arrive.

## Decisions already made (do not re-ask)

| Topic | Decision |
| --- | --- |
| Language and framework | Python 3.11+, LangGraph, Streamlit dashboard |
| LLM | Claude for production; free local model (Ollama, qwen2.5) for development and demo. One model interface; switch with MODEL_PROVIDER in .env |
| Storage | JSON files for the demo (`state/store.py`); PostgreSQL later behind the same methods |
| Questions and approvals | Simple dashboard only (no Slack/email for now) |
| Gate approvers | Tech lead, delivery head AND sales must all approve every gate |
| Tickets | Jira. Tasks arrive as Jira tickets and are implemented from them |
| Source code | GitHub only: https://github.com/psspl-jackey/AI-SDLC-Agent |
| Templates | Prakash Infotech company templates for proposal docs, PPTs, reports (files still to be shared) |
| Estimation method | None exists today; estimator proposes task hours as min-likely-max ranges, reviewed at Gate 2 |
| Stage 7 build | Agents build the scaffold and first modules only; human developers take over |
| Payment and third-party integrations | Out of scope for now. Payment is built against a DUMMY gateway with static responses so the flow can be demoed |
| NDA | No NDA constraint for now; revisit when a client requires one |
| Skills library owners | Tech lead and delivery head |
| Past SOWs | None available; use sample inputs with planted gaps and answer keys (`samples/`) |
| Monthly LLM budget | Unknown; measure with the cost meter during the demo |
| Tech packs | v1 written by Claude Code (Flutter, React Native, Kotlin, Swift, React, Next.js, NestJS, FastAPI, Spring); tech lead to review and own |
| Sprint plan | `JIRA_PROJECT_KEY=SDLC` placeholder until the real key exists; 2-week sprints, 240 h capacity per sprint (placeholders, tech lead to set); tickets reach Jira by CSV import for now (API needs Jira URL and token) |
| Stage 7 build | Agents build tickets up to `BUILD_MAX_SPRINT` (default 1). Every agent write goes through `GuardedGit` (feature branches only, PRs into develop, Jira/ticket key in commits, requirement ids in PR body, no secrets or paths outside the repo). Local git host for the demo; GitHub host, coding agent choice (Claude Code headless vs local model) and Docker sandbox still to decide |
| Working without Jira | Everything runs locally: tickets keep local ids (T-001), code goes to the local git repo under `data/build/<project>/repo`, pull requests are recorded next to it and reviewed on the Build screen. Jira CSV export is optional |
| Estimate risk buffer | 15% default (`RISK_BUFFER_PCT` in .env), reviewed at Gate 2; placeholder until there is effort history |

## Rules that must hold in code

1. Ask-but-do-not-stop: questions are asked ONCE up front (adaptive intake questionnaire). Later
   questions never stop work: non-blocking -> assume, log assumption, continue; blocking -> only that
   item waits (gap stays OPEN with an assumption attached).
2. All gap analysis (SOW, NFR, domain checklist, competitor, review-mined, inferred) finishes BEFORE Gate 1.
3. Gate 1 coverage check is CODE, not LLM (`gaps/register.py::coverage_check`):
   every input line maps to a requirement or is marked not-a-requirement; every gap has a status;
   competitor/review gaps have evidence URL + research date; OPEN/ASSUMED gaps have an assumption;
   ANSWERED gaps link a real requirement.
4. Table stakes vs differentiator for competitor gaps is decided by code from competitor counts.
5. Market gaps never become requirements on their own: status RECOMMENDED, shown as separately
   estimated "Recommended additions"; the client opts in.
6. Everything the system infers is tagged "inferred" and enters the gap register as ASSUMED.
7. Every model call goes through `TracedLLM` (tracing + cost meter).
   Agents ask for JSON with `llm/json_call.py::complete_json(llm, system, prompt, SHAPE)`, never raw
   `parse_json`: it retries once on bad JSON and coerces small-model replies to the declared shape.
8. Web research: public pages only, respect robots rules, never copy content or design.

## Code map

- `src/sdlc_agent/llm/` model interface (Ollama, Anthropic)
- `src/sdlc_agent/state/` Project model and store
- `src/sdlc_agent/intake/` detect input, readers, brief, questionnaire
- `src/sdlc_agent/agents/` requirements_analyst, domain_research, reviewer, platform_decision, estimator, change_analyst, solution_design, skills_setup, planner, developer, qa, handover (run() is pure, apply() merges)
- `src/sdlc_agent/orchestrator/pipeline.py` Stage 0, Stage 1 LangGraph graph, Gate 1
- `src/sdlc_agent/build/git_host.py` GitHost interface, GuardedGit rules, Fake and Local hosts; `orchestrator/build.py` Stage 7 loop, `orchestrator/release.py` Stage 8, `orchestrator/handover.py` Stage 9
- `starters/` runnable app templates per tech pack (Flutter, native and Node backends have none yet);
  `build/starters.py` renders them, `build/runner.py` runs them, `orchestrator/apps.py` Stage 7 run checks
- `src/sdlc_agent/traceability.py` requirement -> ... -> pull request matrix (no model)
- `src/sdlc_agent/gaps/`, `questions/`, `tracing.py`, `exports.py`, `evals.py` (scores runs against `samples/*.answers.yaml`)
- `domain_packs/*.yaml`, `tech_packs/*.yaml` (stacks Stage 4 may choose), `skills/*.md`, `dashboard/app.py`, `samples/`, `tests/`

## Commands

- Setup: `python3 -m venv .venv && source .venv/bin/activate && pip install -e ".[dev]" && cp .env.example .env`
- Tests (no model needed, scripted FakeLLM): `pytest -q`
- Dashboard: `streamlit run dashboard/app.py` (needs `ollama serve` and the model pulled)
- Eval against answer keys: `python -m sdlc_agent.evals samples/*.answers.yaml` (uses the model in `.env`; reports in `data/evals/reports/`)

## Working rules for Claude Code

- Branches: `main` (stable), `develop` (integration), `feature/<JIRA-KEY>-short-name`. Never commit or push to `main` directly; open pull requests into `develop`.
- Commit messages start with the Jira key when there is one, e.g. `SDLC-12: add PDF page references`.
- Run `pytest -q` before every commit; add tests for new behaviour using the FakeLLM in `tests/conftest.py`.
- Keep agents' run() pure and apply() as the only writer, so agents can run in parallel.
- Never put API keys in code or commits; they live in `.env` (git-ignored).

## Open items

- Jira project key (for branch and commit names)
- Remaining sample inputs: full Word SOW (business tool) and a reference website link, with answer keys
- Free web search option for automatic competitor discovery (`SearchProvider` in `agents/domain_research.py`)
- Vision model for reading screenshots and wireframes
- Prakash Infotech template files for Phase 2
