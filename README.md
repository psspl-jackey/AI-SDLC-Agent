# AI SDLC Agent

An AI agent system that takes a client requirement in any form (full SOW, short brief, one-line idea,
website or app-store link) and carries it through requirements, gap analysis, proposal, design,
planning and build, with human approval gates.

This branch delivers the **foundation and Phase 1**: any input in, a gap-checked set of requirements
out, approved at Gate 1 by the tech lead, delivery head and sales.

The full system definition is the team doc "AI SDLC Agent: System Definition".

## What works today

| Part | Status |
| --- | --- |
| Stage 0 intake: text, links, PDF, Word, Excel, CSV, Markdown | Working |
| Normalized project brief with a source on every item | Working |
| Completeness score (rich, partial, thin) and adaptive questionnaire, asked once | Working |
| Requirements analyst: requirements with IDs, SOW and NFR gaps, client questions | Working |
| Domain and market research: domain-pack gaps, compliance prompts, competitor features, review complaints | Working (competitors from links you give) |
| Reviewer: duplicate gaps, unclear wording, dead evidence links | Working |
| Gap register and code-based Gate 1 coverage check | Working |
| Ask-but-do-not-stop question queue with an assumption log | Working |
| Gate 1 approval by all three roles | Working |
| Dashboard: new project, overview, questions, requirements, gaps, Gate 1, deliverables, trace and cost | Working |
| Tracing and cost meter on every model call | Working |
| Reading images and screenshots | Not yet (needs a vision model) |
| Automatic competitor discovery by web search | Not yet (search provider not chosen) |
| Stage 2 platform decision: platform matrix with reasons, code-enforced platform check | Working |
| Stage 3 estimate: tasks with min-likely-max hours, totals and risk buffer in code, recommended additions separate, .xlsx sheet | Working (hours only; cost needs a rate card) |
| Gate 2 approval by all three roles, blocked while checks fail | Working |
| Client decision: approve or reject, opt into recommended additions | Working |
| Change requests: re-enter at Stage 1, re-estimate only affected requirements | Working |
| Proposal doc and PPT in company templates | Waiting for template files |
| Stage 4 solution design: stacks from tech packs, components, data model, API, screens and flows; architecture doc with diagrams | Working (wireframes as screen lists, not drawings) |
| Gate 3 approval by all three roles, blocked while the design check fails | Working |
| Stage 5 skills setup: project skill pack from tech packs, tailored rules added, Claude Code SKILL.md layout | Working |
| Stage 6 internal plan: tickets, dependencies, sprints, validation report, Jira CSV, tech lead review | Working (Jira by CSV import; placeholder key SDLC) |
| Stage 7 build: developer agent per ticket, guarded git (feature branches, PRs into develop, secret scan), human merge per PR | Working on a local git host (GitHub host, sandbox and coding agent choice pending) |
| Stages 8 and 9 | Later phases |

## Setup (macOS)

You need Python 3.11 or newer and, for the free local model, [Ollama](https://ollama.com).

```bash
cd /Users/jackeykabra/AI-SDLC-Agent
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
```

### Model: free local (default)

```bash
brew install ollama        # or download from ollama.com
ollama serve               # leave running in its own terminal
ollama pull qwen2.5:14b    # about 9 GB; needs roughly 16 GB+ RAM
```

On a machine with less memory, use `qwen2.5:7b` and set `OLLAMA_MODEL=qwen2.5:7b` in `.env`.
Smaller models finish faster but find fewer gaps.

### Model: Claude (when local quality is not enough)

In `.env` set `MODEL_PROVIDER=anthropic`, add `ANTHROPIC_API_KEY`, and set `COST_INPUT_PER_MTOK` and
`COST_OUTPUT_PER_MTOK` from the current Anthropic price list so the cost meter is accurate.
No code changes are needed.

## Run

```bash
streamlit run dashboard/app.py
```

Open the link it prints, create a project, add an input (try `samples/one_line_classifieds.txt`),
answer the short questionnaire, and wait for Stage 1. Add 2 to 3 competitor links in the
questionnaire to get competitor gaps.

## Test

```bash
pytest -q
```

The tests use a scripted fake model, so they run without Ollama or Claude. GitHub Actions runs them
on every push and pull request.

## Eval: score the agents against the answer keys

```bash
python -m sdlc_agent.evals samples/*.answers.yaml
```

Runs Stage 0 and Stage 1 on each sample with the model set in `.env`, answers the intake form from the
key, and prints planted gaps found, expected requirements found, and gaps not in the key. Matching is
plain code (keywords in the key), so scores are comparable across models and prompt changes. Full
reports go to `data/evals/reports/`; eval projects stay out of the dashboard's project list.

## Project structure

```
src/sdlc_agent/
  config.py              settings from .env
  llm/                   one model interface: Ollama or Claude
  state/                 project state model and store (JSON files for the demo)
  intake/                Stage 0: detect input, read it, build the brief, questionnaire
  agents/                requirements analyst, domain and market research, reviewer
  gaps/                  gap register and the Gate 1 coverage check
  questions/             question queue and assumption log
  orchestrator/          LangGraph Stage 1 graph and Gate 1 decisions
  build/                 Stage 7 git hosts and the GuardedGit rules
  tracing.py             per-project trace and cost meter
  exports.py             requirements doc, gap register, competitor matrix, questions
  evals.py               score Stage 0-1 output against sample answer keys
domain_packs/            feature checklists and compliance prompts per domain
tech_packs/              stacks Stage 4 may choose, with architecture, security and testing rules
skills/                  reusable instructions for agents (NFR checklist)
dashboard/               Streamlit dashboard
samples/                 sample inputs and answer keys for the eval set
tests/                   unit, pipeline and dashboard tests
```

## Working with Jira and GitHub

- Tasks come from Jira tickets. GitHub holds the source code only.
- Branches: `main` (stable), `develop` (integration), `feature/<JIRA-KEY>-short-name` for each ticket.
- Open a pull request into `develop`; merge `develop` into `main` for a release. Nobody pushes to `main` directly.
- Put the Jira key in the commit message, for example `SDLC-12: add PDF page references`.

## Next steps

1. Write the remaining sample inputs and answer keys (see `samples/README.md`).
2. Run the eval on the local model (`python -m sdlc_agent.evals samples/*.answers.yaml`) and tune prompts.
3. Choose a free search option for automatic competitor discovery and plug it into `SearchProvider`.
4. Add a vision-capable model for screenshots and wireframes.
5. Phase 2: rate card (team, timeline, cost), proposal doc and PPT in Prakash Infotech templates, client approval.
