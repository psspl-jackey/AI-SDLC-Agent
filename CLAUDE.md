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
- Next: pull a model and run the eval to tune prompts; then Stage 3 (estimator, proposal) and Gate 2.

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
8. Web research: public pages only, respect robots rules, never copy content or design.

## Code map

- `src/sdlc_agent/llm/` model interface (Ollama, Anthropic)
- `src/sdlc_agent/state/` Project model and store
- `src/sdlc_agent/intake/` detect input, readers, brief, questionnaire
- `src/sdlc_agent/agents/` requirements_analyst, domain_research, reviewer, platform_decision (run() is pure, apply() merges)
- `src/sdlc_agent/orchestrator/pipeline.py` Stage 0, Stage 1 LangGraph graph, Gate 1
- `src/sdlc_agent/gaps/`, `questions/`, `tracing.py`, `exports.py`, `evals.py` (scores runs against `samples/*.answers.yaml`)
- `domain_packs/*.yaml`, `skills/*.md`, `dashboard/app.py`, `samples/`, `tests/`

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
