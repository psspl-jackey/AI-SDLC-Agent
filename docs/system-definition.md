# AI SDLC Agent: System Definition

Nov 4, 2026 · Jackey Kabra
Exported from the team doc ("AI SDLC Agent System Definition.pdf", 23 pages). The end-to-end flow
diagram (PDF pages 5-6) is not reproduced here; the stage table below carries the same content.
Decisions made after this export live in `CLAUDE.md`.

## Purpose

We are building an AI agent system that takes a client's requirement in any form, from a full Scope
of Work (SOW) to a one-line idea or a website link, and carries it through to a working project:
validation, platform decision, estimation, detailed proposal, architecture, internal planning, and
development. It runs as a team of specialist AI agents coordinated by one orchestrator, with humans
approving the decisions that carry business risk.

**Out of scope for now:** real payment and third-party integrations. Where a project needs payment,
it is built against a dummy gateway with static responses, so the full payment flow works and can be
demoed; real integrations come back in a later phase.

The goal is to cut the time from "SOW received" to "approved proposal" and "first working build"
while keeping quality consistent across projects. The system is stack-agnostic: it chooses Python,
Java, Node.js, Kotlin, Swift, Flutter or others per project, based on the requirements.

**Any domain, any technology.** The flow and the agents stay the same for every project, whether
classifieds, e-commerce, fintech, healthcare or business tools. Per-project knowledge comes from
plug-in packs: **domain packs** hold feature checklists, user flows, NFRs and compliance rules per
category and region; **tech packs** hold architecture, conventions, security and testing rules per
stack (Flutter, Swift, Kotlin, React, Node.js, Python, Java and others). A new domain means a new
pack, not new agents, and every finished project improves its packs.

This document is the team's shared definition. At the time of writing nothing was built; it
describes what we will build and the decisions still open.

## The flow as proposed

The original idea has eight stages, run in order:

1. Upload the scope documentation (SOW).
2. Validate requirements and feasibility.
3. Decide which platforms are needed: web app, mobile app, backend, or others.
4. Estimate and write a detailed proposal: modules, features and tasks.
5. Plan the base structure and choose the programming language per platform.
6. Create development skills per platform: architecture, codebase, security, test cases and more.
7. Make an internal plan and validate it.
8. Start building the project.

Two rules run across all stages: reports, documentation and PPTs are shared as they are produced, and
when anything is unclear the system asks the user for confirmation without stopping the work.

## Gaps found and how we close them

The flow covers the main path well but stops at "start building" and has no way back when something
changes. Fourteen gaps, most important first:

| # | Gap | Why it matters | How we close it |
| --- | --- | --- | --- |
| 1 | No approval gates | "Never stop" is risky for estimates, pricing and architecture: a wrong guess compounds through every later stage | Split questions into blocking and non-blocking; 4 hard gates where a human must approve (see the ask-but-do-not-stop rule) |
| 2 | No assumption log | When the agent continues without an answer, it is guessing; nobody can see which guesses were made | Every unanswered question becomes a logged assumption, revisited when the answer arrives |
| 3 | No client clarification step | SOWs are almost always incomplete or ambiguous | Stage 2 outputs a client question list; answers feed back into the requirements |
| 4 | Non-functional requirements missing | Performance, security, compliance (GDPR, HIPAA, PCI), scale, offline support, accessibility, languages change cost and architecture | Explicit NFR checklist in validation |
| 5 | No UI/UX design stage | Developers cannot build screens nobody designed; mobile especially | Add a design stage: user flows, wireframes, design system, before build |
| 6 | Estimation lacks team, timeline, cost | Effort hours alone do not make a proposal | Add resource plan, timeline, cost and risk buffer; calibrate against past projects |
| 7 | Build is the last step | Testing, code review, CI/CD, deployment, App Store and Play Store release, handover are missing | Extend the flow: build, QA, release, handover |
| 8 | No change-request path | Scope changes mid-project are normal | Change request re-enters at validation and re-estimates only the affected modules |
| 9 | No traceability | Cannot prove every SOW line was delivered | Requirement IDs carried through module, task, code and test |
| 10 | Third-party integrations (deferred) | Real payment and third-party integrations are out of scope for the first version; payment uses a dummy gateway with static responses | Add an integration inventory to validation when they come back in scope |
| 11 | Greenfield vs existing system | Extending an existing codebase is a different job from a new one | Ask at intake; if existing, add a codebase analysis step |
| 12 | Client data confidentiality | SOWs are under NDA; data goes to an LLM provider | Data policy: which provider, retention settings, what can be uploaded |
| 13 | No quality checks on agent output | An agent can produce a confident but wrong proposal | Evals, reviewer agent, tracing (see architecture) |
| 14 | Skills are per-project in the flow | Rebuilding architecture and security standards every project wastes effort and loses consistency | Skills become a reusable company library; each project selects and tailors them |

## End-to-end flow

Work moves down the stages and stops only at the four gates; the question queue, assumption log,
tracing and reviewer run in parallel the whole time. A change request loops back to Stage 1 rather
than patching later stages directly.

## Stage-by-stage definition

The revised flow has 10 stages and 4 hard approval gates. Each stage has a clear input, a clear
output, and an owner agent, so it can be built and tested on its own.

| Stage | Input | What the agents do | Output | Human gate |
| --- | --- | --- | --- | --- |
| 0. Intake | Any input: one-line idea, website or app link, Word, PDF, Excel, images, notes | Detect input type; read files or crawl links; build one normalized project brief; score completeness; ask one adaptive intake questionnaire up front | Normalized project brief with completeness score, intake answers, loaded domain pack | None |
| 1. Requirements and feasibility | Parsed SOW | Extract requirements with IDs; find gaps, conflicts, NFRs; judge technical and timeline feasibility; research same-category apps and competitors; build the gap register and run the coverage check | Requirements doc, competitor feature matrix, gap register, client question list, risk and assumption log | **Gate 1:** requirements and complete gap register approved |
| 2. Platform decision | Approved requirements | Map requirements to platforms: web, iOS, Android, cross-platform, backend, admin panel, others | Platform matrix with reasons | None (reviewed at Gate 2) |
| 3. Estimation and proposal | Requirements + platforms | Break into modules, features, tasks; estimate effort per task; build team plan, timeline, cost, risk buffer | Detailed proposal doc, estimate sheet, proposal PPT | **Gate 2:** proposal approved internally, then by client |
| 4. Solution design | Approved proposal | Choose stack per platform; design architecture, data model, APIs; UX flows and wireframes | Architecture doc, stack decision record, wireframes | **Gate 3:** architecture approved |
| 5. Skills setup | Architecture + stack | Select skills from the company library (architecture, codebase conventions, security, testing, CI/CD) and tailor them | Project skill pack | None |
| 6. Internal plan and validation | All of the above | Sprint plan, task breakdown with dependencies; reviewer agent checks every requirement ID maps to tasks | Sprint plan, Jira tickets, validation report | Tech lead review (non-blocking) |
| 7. Build | Plan + skills | Pick up tasks from Jira tickets; scaffold the base project and build the first modules: code, unit tests, self-review, pull request; human developers take over the rest | Code in Git, pull requests, progress reports | Human code review on each pull request |
| 8. QA and release | Built modules | Integration and end-to-end tests, security scan, build pipelines, store submission prep | Test report, release build, release notes | **Gate 4:** release approved |
| 9. Handover | Released project | Final documentation, traceability report, maintenance guide | Handover pack | Client sign-off |

A change request at any point re-enters at Stage 1, and only the affected modules are re-estimated
and re-planned.

## Stage 0 in detail: any input, one understanding

Clients send requirements in very different forms. The intake agent turns whatever arrives into one
**normalized project brief**, so every later stage always works from the same structure.

**Normalized project brief:** project goal, domain and region, target users, intent (new product,
rebuild of an existing one, or "like this reference"), platforms if stated, features, NFRs,
constraints, references, and a source for every item: file and page, URL, or "inferred".

| Input type | Example | How the intake agent handles it |
| --- | --- | --- |
| One-line idea | "Build an app like OLX for Gujarat" | Classify domain and region; fill the brief from the domain pack and competitor research; tag everything inferred |
| Website or web app link | Client's current site, or a reference site | Crawl public pages; list pages, features and user flows; capture screenshots; ask once whether it is a rebuild or a reference |
| App store link | Client's existing app or a reference app | Read listing, screenshots, release notes and reviews |
| Word, PDF, Excel | Full SOW, feature list, RFP | Extract text, tables and images; keep page references for traceability |
| Images and screenshots | Sketches, wireframes, competitor screens | Read screens and flows from the images |
| Notes or email text | Pasted meeting notes | Extract requirements and open points |
| Mixed | A doc plus links plus images | Handle each, merge into one brief, flag conflicts between sources |

### Completeness score

| Level | Typical input | What changes |
| --- | --- | --- |
| Rich | Full SOW | Most items extracted from the source; few questions |
| Partial | Short brief, feature list, website link | More inferred from domain packs and competitors; a moderate questionnaire |
| Thin | One line | Most of the brief inferred; the longest questionnaire; Gate 1 review focuses on inferred items |

The thinner the input, the more the system decides on its own. Every inferred item is tagged
"inferred" and enters the gap register with status *assumed*, so the human at Gate 1 sees exactly
what came from the client and what the system decided.

The adaptive questionnaire is asked once, up front, and skips anything the input already answers.
Website crawling covers public pages only, respects each site's terms, and is used to understand
features, never to copy content or design.

## Stage 1 in detail: all gap analysis finishes before Gate 1

Gate 1 opens only when every gap from every source sits in one gap register with a status. Nothing
found in Stage 1 can be silently dropped, because a code check, not the LLM, confirms coverage.

**Agents in Stage 1:** 4 agents plus the orchestrator.

| Agent | Job in Stage 1 |
| --- | --- |
| Requirements analyst | Extract requirements with IDs; find SOW gaps (missing, vague, conflicting) and NFR gaps; judge feasibility |
| Domain and market research agent | Classify domain and region; compare SOW against the domain pack; research competitors; mine user reviews |
| Reviewer agent | Check each gap is real, clear, not duplicated, and that every competitor claim has a working source link |
| Document agent | Produce the requirements doc, competitor feature matrix, gap register and client question list |
| Orchestrator | Runs the steps below, enforces the coverage check, opens Gate 1 |

### Sequence

1. Classify domain, sub-type, users and region from the SOW and intake answers; load the matching
   domain pack.
2. In parallel: the analyst extracts requirements and SOW gaps; the research agent compares the SOW
   to the domain pack checklist.
3. Research agent finds competitors: names from intake first, then top apps in that category and
   region from web and app-store data.
4. Research agent builds a feature matrix from public sources (store listings, websites, help docs,
   release notes, reviews), each feature with a source link and research date.
5. Every missing feature is bucketed: table stakes, differentiator, already in SOW, or not relevant.
6. All gaps go into the gap register with an ID and source tag.
7. Reviewer agent validates the register; a code check confirms coverage; Gate 1 opens.

### Where gaps come from

| Source | Found by | Example (classifieds app) |
| --- | --- | --- |
| SOW gap | Requirements analyst | "Users can search" with no filters defined |
| NFR gap | Requirements analyst | No performance or offline targets |
| Domain checklist gap | Research agent vs domain pack | No report-ad or moderation flow |
| Competitor gap, table stakes | Research agent | No buyer-seller chat, which all top apps have |
| Competitor gap, differentiator | Research agent | No seller verification badge |
| Review-mined opportunity | Research agent | Competitor reviews complain about fake listings |

**Gap register fields:** ID (GAP-001), source, description, evidence link, bucket, status, linked
requirement ID, date found. Status is one of: **answered** (became a requirement), **assumed** (in
assumption log), **out of scope** (in exclusions), **recommended addition** (market gap offered to
the client), or **open** (waiting on the client, with an assumption attached so work continues).

### Gate 1 exit criteria

- Every SOW line maps to a requirement ID or is marked as not a requirement (code check)
- Every gap has an ID, source and status; no empty status (code check)
- Every competitor claim has a source link and research date (code check)
- Every open gap has an assumption attached (code check)
- Tech lead, delivery head and sales approve the competitor list, the buckets and the register (human)

Market gaps never become requirements on their own: they reach the proposal as a separately
estimated "Recommended additions" section, and the client opts in. Research uses public information
only, for feature comparison, never to copy designs or content.

## Agent architecture

One orchestrator agent owns the project state and hands each stage to a specialist agent. A separate
reviewer agent checks every major output before it reaches a human gate. This is the
orchestrator-worker pattern with an evaluator on top.

| Agent | Responsible for | Main tools |
| --- | --- | --- |
| Orchestrator | Runs the flow, tracks stage status, routes questions, enforces gates | Project state store, question queue, notifications |
| Intake agent | Turning any input into one normalized project brief; adaptive intake questionnaire | File readers (PDF, Word, Excel, images), web crawler, app-store lookup |
| Requirements analyst | Requirement extraction, SOW and NFR gaps, feasibility, client questions | Requirement store, gap register, checklist skill |
| Domain and market research agent | Domain classification, domain-pack comparison, competitor feature matrix, review mining | Web search, web fetch, app-store data, domain packs |
| Solution architect | Platform decision, stack choice, architecture, data model, APIs | Tech packs, past-project knowledge base |
| Estimator | Module and task breakdown, effort, team, timeline, cost | Estimation history, rate card, spreadsheet writer |
| Document agent | Proposal doc, PPT, reports in Prakash Infotech templates | Doc, PPT and spreadsheet generators |
| Planner | Sprints, tickets, dependencies | Jira for tickets, GitHub for source code |
| Developer agents (one per platform) | Code, unit tests, pull requests | Code execution sandbox, Git, tech packs |
| QA agent | Integration tests, security scans, test reports | Test runners, scanners, CI |
| Reviewer agent | Checks outputs against requirements and packs; validates gaps and sources; scores quality | Evals, traceability matrix, coverage check |

How the 10 agent engineering concepts show up in this system:

| Concept | Where it applies here |
| --- | --- |
| Harness engineering | The runtime that hosts every agent: prompts, tool wiring, retries, sandbox |
| Loop engineering | Each agent's think, act, check loop, with step limits and a stop condition per stage |
| Context engineering | Each agent gets only its stage inputs plus the relevant requirement IDs, not the whole project history |
| Tool design | Small, well-described tools: `read_sow`, `save_requirement`, `ask_user`, `create_ticket`, `open_pull_request` |
| Human-in-the-loop design | 4 hard gates plus the non-blocking question queue |
| Memory architecture | Short-term: current stage context. Long-term: requirement store, gap register, decision log, past-project estimates, domain packs, tech packs |
| Orchestration patterns | Orchestrator-worker for stages; parallel developer agents per platform; evaluator-optimizer with the reviewer |
| Guardrails and permissions | Read-only access until Stage 7; no push to main branch; no client-facing send without approval; NDA data rules |
| Evals for agents | Test set of past SOWs with known good requirements and estimates; score each agent against it |
| Observability and tracing | Every agent step, tool call, cost and decision logged and replayable per project |

## The ask-but-do-not-stop rule

The agent never sits idle waiting for an answer, but it also never crosses a hard gate on a guess.
Every question is classified when it is raised:

- **Non-blocking question:** the agent picks the most reasonable answer, writes it to the assumption
  log, sends the question to the user, and keeps working. Example: "Should the app support dark
  mode?" Assume yes, continue.
- **Blocking question:** the agent pauses only the affected item and works on everything else in
  parallel. Example: "Is multi-language support in scope?" Pause localization work, continue the rest.
- **Gate decision:** the stage output is complete and waits for approval; the agent prepares the next
  stage's groundwork meanwhile but does not commit to it.

When an answer arrives, the orchestrator finds every output built on the related assumption and
re-runs only those parts. Unanswered questions are re-sent as a daily digest, not one message each,
so the user is not flooded.

Questions are front-loaded. The Stage 0 intake questionnaire collects everything every project
needs, so later questions are only ones the SOW itself raises, and those never stop the work.

All questions and approvals go to the dashboard. Every gate is approved by the tech lead, the
delivery head and sales.

## Deliverables

Every deliverable uses the company template and is shared as soon as it is produced, not at the end.

| Deliverable | Produced at | Format | Audience |
| --- | --- | --- | --- |
| Intake answers | Stage 0 | Form | Internal |
| Requirements document with IDs | Stage 1 | Doc | Internal, client |
| Competitor feature matrix with sources | Stage 1 | Sheet | Internal, client |
| Gap register | Stage 1, updated throughout | Sheet | Internal |
| Client question list | Stage 1, updated throughout | Doc or sheet | Client |
| Risk and assumption log | Stage 1, updated throughout | Sheet | Internal |
| Platform matrix | Stage 2 | Doc section | Internal, client |
| Detailed proposal: modules, features, tasks, assumptions and exclusions | Stage 3 | Doc | Client |
| Recommended additions from market gaps, separately estimated | Stage 3 | Proposal section | Client |
| Estimate sheet: effort, team, timeline, cost | Stage 3 | Spreadsheet | Internal, client summary |
| Proposal presentation | Stage 3 | PPT | Client |
| Architecture document and stack decision record | Stage 4 | Doc with diagrams | Internal |
| Wireframes and user flows | Stage 4 | Design files | Internal, client |
| Project skill pack | Stage 5 | Skill files | Agents, developers |
| Sprint plan and tickets | Stage 6 | Jira | Internal |
| Weekly progress report | Stage 7 onward | Doc or PPT | Internal, client |
| Test and security report | Stage 8 | Doc | Internal, client |
| Traceability matrix | Stage 9 | Sheet | Client |
| Handover and maintenance guide | Stage 9 | Doc | Client |

## Build approach and tech options

The agent system itself should be built in Python or TypeScript, where agent frameworks are most
mature. This is separate from the stack it chooses for client projects, which stays open.

| Layer | Options to evaluate | Notes |
| --- | --- | --- |
| Agent framework | Claude Agent SDK, LangGraph, OpenAI Agents SDK, CrewAI | LangGraph suits an explicit stage graph with gates; Claude Agent SDK suits skills and coding agents |
| Coding agent for Stage 7 | Claude Code (headless), or developer agents built on the chosen SDK | Runs in a sandbox, opens pull requests, never pushes to main |
| Project state | PostgreSQL | Stages, requirements, assumptions, gate decisions |
| Knowledge and memory | Vector store (pgvector or similar) + file store | Past SOWs, past estimates, skills library |
| Document output | Doc, PPT and spreadsheet generators with company templates | Reuse existing templates |
| Integrations | Jira (tickets and tasks), GitHub (source code only), dashboard notifications | Through tools or MCP connectors |
| Tracing and evals | Langfuse, LangSmith, or OpenTelemetry-based | Needed from day one, not later |
| Interface | Simple web dashboard: upload SOW, see stage status, answer questions, approve gates | Can start as Slack-only |

Recommended start: one framework, one LLM provider, PostgreSQL, tracing from the first commit. Add
more only when a stage proves it needs it.

## What it costs to run (demo vs production)

The 10 agents are not 10 separate products or licences. They are the same LLM called with different
instructions and tools, so cost depends on how much text goes in and out (tokens), not on the number
of agents.

| Part | Free for a demo? | Notes |
| --- | --- | --- |
| Agent frameworks (LangGraph, CrewAI, Claude Agent SDK, OpenAI Agents SDK) | Yes | Open-source libraries |
| LLM calls from hosted providers (Claude, GPT, Gemini) | No, pay per use | Some providers offer trial credits or limited free tiers; terms change, check before relying on them |
| Local open models (Llama, Qwen, Mistral via Ollama) | Yes | Runs on our own machine; weaker at long documents and estimation, fine for testing the flow |
| Tracing (Langfuse self-hosted) | Yes | Hosted plans cost money |
| PostgreSQL, pgvector | Yes | Self-hosted |
| GitHub | Free plans for small teams | Enough for a demo |

**Decision:** develop and demo on a free local model; use a small Claude budget only if local quality
is not good enough. A demo on 2-3 SOWs should cost little, but we will measure it from the tracing
data rather than guess.

## Phased rollout

Build the front half first: SOW to approved proposal is where the time saving is largest and the risk
is lowest, because a human reviews everything before it leaves the company.

1. **Phase 1 - SOW to requirements (Stages 0-1).** Upload a SOW, get a requirements doc, gap list and
   client questions. Test on 5-10 past SOWs where we know the right answer.
2. **Phase 2 - Proposal engine (Stages 2-3).** Platform matrix, module and task breakdown, estimate
   sheet, proposal doc and PPT. Compare its estimates against what past projects actually took.
3. **Phase 3 - Design and planning (Stages 4-6).** Architecture, stack decisions, skills library,
   sprint plan and tickets.
4. **Phase 4 - Build and release (Stages 7-9).** Coding agents per platform, QA agent, release
   support. Start with one platform, likely mobile, since that is our strongest area.

Each phase ships with its own evals and tracing before the next one starts.

## Implementation plan for the agent system

This is the build list for the agent itself, including the pieces the stage flow does not show but
every stage depends on.

### Foundation (before Phase 1)

- Pick the agent framework; set up repo, environments, secrets handling
- One model interface, so switching between the local model and Claude is a config change
- Project state model: project, stage, requirement, gap, assumption, question, gate decision
- Orchestrator skeleton: stage graph, status tracking, retry and failure handling
- Question queue with blocking and non-blocking types
- Simple dashboard v1 (see Demo setup)
- Tracing on every LLM and tool call from the first commit
- Prompt and skill versioning, so a change can be compared and rolled back
- Basic access control: who can upload, answer, approve
- Cost meter per project

### Phase 1 - SOW to requirements

- Adaptive intake questionnaire and normalized project brief with completeness score
- Input handlers: one-line text, website and app links (crawler), PDF, Word, Excel, images
- Requirements analyst agent with an NFR checklist skill
- Domain and market research agent: web search, app-store data, review mining, source links on every claim
- First 2-3 domain packs, starting with the domains we get most SOWs for
- Gap register and the code-based coverage check for Gate 1
- Requirements doc, competitor feature matrix and client question list output
- Gate 1 approval screen or message
- Eval set: 3-5 sample SOWs with planted gaps and an answer key (see Demo setup)

### Phase 2 - Proposal engine

- Platform decision agent and matrix
- Estimator agent: module, feature, task breakdown with effort ranges
- Document agent: proposal doc, estimate sheet, PPT in company templates
- Reviewer agent checks every requirement ID appears in the proposal
- Gate 2 approval; eval estimates against actual effort of past projects

### Phase 3 - Design and planning

- Skills library v1: architecture, codebase conventions, security, testing per platform
- Solution architect agent and stack decision record
- Planner agent: sprints and tickets; Gate 3 approval

### Phase 4 - Build and release

- Sandbox for code execution; Git access limited to branches and pull requests
- Developer agent for one platform first (mobile), then others
- QA agent: tests and security scan; Gate 4 approval
- Handover pack and traceability matrix

### Change-request path (after Phase 2)

- Re-enter at Stage 1, find affected requirement IDs, re-estimate and re-plan only those

## Demo setup

**Model.** Claude runs only as a hosted API and cannot run on our own machines, so the demo is built
in two steps. First, develop and run the whole flow on a free local open model through Ollama.
Second, if output quality on long SOWs, gap finding or estimates is not good enough, switch the same
code to Claude through the model interface and use a small budget, tracked by the cost meter. Because
the demo uses only sample SOWs, no client data leaves the company.

**Test SOWs.** We have no past SOWs ready, so we write our own:

- 3-5 sample inputs in different domains and different forms: a full Word SOW, a short PDF brief, a
  one-line idea, and a reference website link.
- Each one has gaps planted on purpose: missing NFRs, vague features, a conflicting requirement, and
  a few table-stakes features left out.
- Each one has an answer key: the planted gaps and the requirements a senior person would extract.
- The eval measures how many planted gaps the agents find and how many false gaps they raise.

For estimates, there is no actual effort data yet, so 1-2 senior people estimate the sample SOWs once
and we compare. From now on, record actual effort on every new project to build real data.

**Dashboard v1.** One simple web app for everything the user touches:

| Screen | What it does |
| --- | --- |
| New project | Upload SOW and fill the intake questionnaire |
| Project overview | Stage status and a feed of what each agent is doing |
| Questions inbox | Blocking and non-blocking questions, answered inline |
| Gate approvals | Review stage outputs; approve or reject with a comment |
| Gap register | Every gap with source, bucket, status and evidence link |
| Deliverables | Download docs, sheets and PPTs |
| Trace and cost | Agent steps, tool calls and running cost per project |

Streamlit is the fastest option if the team builds in Python; React or Next.js is better if the
dashboard will grow into the real product.

## Open questions for the team (answered)

### Needed before the foundation work

- **LLM provider:** Claude for production
- **Demo budget:** fully free first, on a local model; a small Claude budget only if local quality is not good enough
- **Past SOWs:** none ready; we create 3-5 sample inputs instead (see Demo setup)
- **Questions and approvals:** simple dashboard
- **NDAs:** no NDA constraint for now; revisit when a client requires one
- **Input format:** not fixed; can be a one-line idea, a website link, a Word file or anything else, so the system builds its own understanding (see Stage 0 in detail)

### Answered later, by the phase that needs them

- **Gate approvers:** tech lead, delivery head and sales approve every gate
- **Estimation method:** none today; the estimator proposes task hours as min-likely-max ranges, and the gate approvers review them at Gate 2
- **Templates:** Prakash Infotech company templates for proposal docs, PPTs and reports; the template files need to be shared with the team
- **Ticketing and Git:** GitHub for source code only (repo: https://github.com/psspl-jackey/AI-SDLC-Agent); Jira for tickets, and agents implement tasks from Jira tickets
- **Skills library owners:** tech lead and delivery head
- **Stage 7:** not the full project; agents build the scaffold and first modules, then human developers take over
- **Monthly LLM budget per project:** unknown; measure it with the cost meter during the demo, then decide
- **Payment and third-party integrations:** later; for now payment uses a dummy gateway with static responses, so the payment flow can still be shown end to end
