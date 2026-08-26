# Observability Agentic Harness (OAH) — Agentic Observability Pipeline

> **Status: pre-alpha.** S1–S9 (surface mapping through the production readiness
> report), S10 (instrument, both `report-only` and `fix` modes), and S11's `R4`
> slice (static validation) are implemented and tested — see
> [Installation](#installation) below to run them. S10 covers 4 of
> `implementation_dto.schema.json`'s 13 change types; `fix` mode requires a recorded
> S9 `ready`/`ready_with_conditions` decision and commits one DTO at a time with
> automatic rollback on any failure. S11's `R1`–`R3` (running the product, real OTLP
> capture, the agentic audit panel) are not built yet — `R4` never claims more than
> "this attribute name appears in the code." Follow [ROADMAP.md](ROADMAP.md) for
> progress.

OAH is an agentic harness that **builds LLM observability into an existing product**
(or produces observability requirements for a product being designed). Given access to
a repository, it runs a multi-stage pipeline: it maps every LLM call site, retrieval
step, and tool invocation; inventories existing telemetry; designs a target
observability architecture; produces an implementation plan; then — in fix mode —
generates and applies the instrumentation code and **validates that telemetry actually
flows** by exercising the product and checking emitted events against a versioned
schema.

OAH ships two co-equal deliverables:

1. **Working instrumentation** — code, event schema, collector config, and a
   validated Trace Completeness Rate for the target product.
2. **A production readiness decision** — a structured five-question readiness
   report ([schema](schemas/readiness_report.schema.json)) ending in one of six
   evidence-led recommendations: *ready / ready with conditions / remediate before
   release / pause and redesign / escalate for review / rollback or pause
   expansion* — with the epistemic position stated (confirmed vs. assumed vs.
   unknown), scope exclusions, named owners, and the evidence that would change
   the decision. The gate never advances on confidence, urgency, or a successful
   demo alone.

The two reinforce each other: the readiness decision is only as good as the
signals behind it, and the installed signals are designed backwards from the
decisions they must support — every signal names the decision it serves and the
owner who acts, or it is not built (the anti-metric-hoarding gate).

## Inspiration & credit

The architecture of this project is directly inspired by
[**Visa Vulnerability Agentic Harness (VVAH)**](https://github.com/visa/visa-vulnerability-agentic-harness) —
Visa's open-source agentic SAST pipeline built on learnings from Anthropic's Project
Glasswing. We adopt its core design pattern and adapt it from vulnerability management
to observability engineering:

| VVAH pattern | OAH adaptation |
|---|---|
| Threat modeling before analysis | Observability surface mapping & gap modeling before design |
| Multi-phase pipeline of composable, versioned skills | Same — each LLM-driven stage is an independently testable skill |
| Deterministic controls + frontier-model reasoning | Deterministic AST/code scanning + LLM reasoning at each phase |
| Structured artifacts (DTOs, SARIF) between stages | Structured artifacts (surface map, gap model, implementation DTOs) |
| Remediation applies code changes, then adversarial validation panel | Instrumentation applies code changes, then dynamic validation: run the product, intercept telemetry, verify against schema |
| Primary metric: Mean Time to Adapt (MTTA) | Primary metric: **Trace Completeness Rate (TCR)** — share of user requests reconstructable end-to-end from telemetry with no gaps |

We are not affiliated with Visa. VVAH is licensed under Apache-2.0; this project is an
independent implementation of the pattern in a different domain and is also released
under Apache-2.0.

## Why

For LLM products, the dominant failure class is not "the call failed" but "the call
succeeded and the output was bad": hallucination, irrelevant retrieval, silent context
truncation, instruction bypass. Classic APM sees green dashboards while the product
degrades. Observability for LLM systems therefore needs a domain model of its own —
traces, generations, retrieval spans, tool spans, feedback events, eval datasets —
plus governance over the telemetry itself (prompts and outputs are sensitive data).

The pipeline itself doesn't know it's about LLMs, though: S1–S3's mapping/gap-model
mechanics, the S4 ops lens (release identifiers, alert plan, decision menu), S5's
invariant gates, S7's runbook/roll-up structure, S8–S9's DTO and readiness-report
shapes, and S11's TCR/validation-ladder concept are domain-agnostic SRE engineering.
What's LLM-specific is concentrated in [docs/event-model.md](docs/event-model.md)
(the Generation/Retrieval entities S3 diffs against) and three of S4's eight lenses
(generation-capture, retrieval, realtime-multimodal) — call it the **GenAI domain
pack** the harness ships with. That's a scope choice, not an architectural limit:
LLM observability is where OTel semantic conventions and APM tooling are least
mature, so it's where a gap-modeling harness adds the most value first.

Retrofitting this by hand into an existing codebase is slow, inconsistent, and usually
stalls after the first dashboard. OAH turns it into a repeatable, reviewable,
agent-executed pipeline with human gates.

## Pipeline (4 phases, 11 stages)

| Phase | Stages | Purpose |
|---|---|---|
| **1 — Discovery & Modeling** | S1–S3 | Map the observability surface (LLM/retrieval/tool call sites), inventory existing telemetry, build a prioritized gap model with owner context |
| **2 — Design & Verification** | S4–S6 | Design instrumentation per lens (tracing, generation capture, retrieval, tools, feedback, PII/governance, cost); deterministic invariant gates; adversarial design review panel |
| **3 — Synthesis & Planning** | S7–S9 | Emit architecture doc, versioned event schema, rollout plan + runbook (ownership matrix, alert plan, decision menu), per-change implementation DTOs, and the production readiness report — the human gate with a six-way recommendation |
| **4 — Implementation & Validation** | S10–S11 | Apply instrumentation to source (agentic, per-change commits); dynamically validate — run the product, intercept emitted events, compute actual TCR and latency overhead; adversarial audit panel |

Detailed stage-by-stage description: [docs/architecture.md](docs/architecture.md).
Target telemetry domain model: [docs/event-model.md](docs/event-model.md).

## Installation

### From PyPI

```bash
pip install oah
oah doctor .
```

`doctor`, `estimate`, `map --no-disambiguate`, `inventory`, `gaps`, and `interview`
work out of the box — no LLM credential, no extra dependency. `map`'s
disambiguation pass and `design`/`event-schema`/`dtos`/`readiness` call an LLM via
[LiteLLM](https://www.litellm.ai/), whose own dependency tree (openai, boto3,
tiktoken, huggingface-hub, aiohttp, pydantic, ...) is sizeable enough that it's an
opt-in extra, not a default install:

```bash
pip install "oah[llm]"
export ANTHROPIC_API_KEY=...        # or another LiteLLM-supported provider's credential
```

Calling an LLM-driven command without the extra installed fails with a clean
`pip install 'oah[llm]'` message, not a raw import error.

### Local development (venv)

```bash
git clone https://github.com/arno49/observability-agentic-harness.git
cd observability-agentic-harness
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev]"            # dev pulls in [llm] too, so the full test suite runs

oah doctor .                       # sanity check
python -m pytest tests/ -q         # run the test suite
```

`pip install -e ".[dev]"` is an editable install: changes to `oah/` take effect
immediately without reinstalling. If you only want to run the CLI's deterministic
commands, `pip install -e .` alone is enough; add `[llm]` for the LLM-driven ones.

S1–S9 need Python ≥ 3.10 — see [Requirements](#requirements-planned) below for what
each stage needs beyond that.

## CLI

Implemented today (S1–S9, S10 — both modes, S11's R4 slice, E9's backend configs):

```
oah doctor <target>                              # check credentials, backends, repo access
oah estimate <target>                            # scope & cost estimate — spends nothing
oah map <target> [-o out.json] [--no-disambiguate] [--model MODEL]  # S1: surface map (standalone audit)
oah inventory <target> [-o out.json]              # S2: existing telemetry inventory
oah interview <target> [-o context.yaml]          # S3: interactive owner interview
oah gaps <target> [--context context.yaml] [-o out.json]        # S3: gap model
oah design <target> [--context context.yaml] [-o out.json] [--model MODEL]      # S4 lenses + S5 gates + S6 panel
oah event-schema <target> [--context context.yaml] [-o out.json] [--model MODEL]  # S7: event schema
oah dtos <target> [--context context.yaml] [-o out.json] [--model MODEL]          # S8: implementation DTOs
oah readiness <target> [--context context.yaml] [-o out.json] [--model MODEL]     # S9: readiness report
oah instrument <target> --dtos implementation_dto.json [-o out.json] [--run-id ID]        # S10 report-only
oah instrument <target> --dtos implementation_dto.json --mode fix --readiness readiness_report.json  # S10 fix
oah validate <target> --dtos implementation_dto.json --instrument-report instrument_report.json [-o out.json] [--dynamic] [--live --start-command CMD --port N --requests requests.json [--event-schema event_schema.json] [--setup-script SCRIPT]]  # S11, R4 always + real R2 with --dynamic + R1 mechanism with --live
oah backend-config <target> --backend {otel-only,langfuse} [-o output_dir]  # E9: collector config
```

`--no-disambiguate` on `map`, plus `doctor`/`estimate`/`inventory`/`interview`/`gaps`/`validate`/`backend-config`,
need neither the `[llm]`/`[agent]` extras nor an API credential — `validate`'s R4
slice is pure static file reads, no LLM or agent call at all. `validate --dynamic`
needs no LLM/agent credential either, but does need a real, reachable Docker
daemon — it runs the target's own test suite inside E6 R2's isolated sandbox
(`oah/validate/sandbox.py`) as a regression gate; without Docker it degrades
to a reported `regression_gate.status: "skipped"`, never a crash. `design`,
`event-schema`, `dtos`, and `readiness` (and `map` without `--no-disambiguate`) call
the S4 lens skills and need `[llm]` — see [Installation](#installation) above.
`instrument` needs the separate `[agent]` extra instead (Claude Agent SDK,
Anthropic-only — see [Choosing a model / provider](#choosing-a-model--provider)
below) and covers only 4 of `implementation_dto.schema.json`'s 13 `change.type`
values; an unsupported type is reported `status: "unsupported"` per DTO, never
silently skipped.

`--mode report-only` (the default) proposes a diff (or a stated refusal, matching a
DTO whose anchor doesn't match the real file) for each DTO — **never writes to the
target repo**. `--mode fix` writes and creates one git commit per successfully
verified DTO, and requires two things report-only doesn't: `--readiness
<readiness_report.json>` from `oah readiness`, whose `recommendation.decision` must
be `ready` or `ready_with_conditions` (architecture.md's own gate — fix mode refuses
to run otherwise), and a **clean git working tree** in the target repo (a failed
DTO's rollback restores its file to `HEAD`, which would discard your own uncommitted
changes if the tree wasn't already clean). Any failure past verification —
syntax-invalid agent output, a rejected `git commit` — rolls back that one DTO
cleanly and is recorded as `status: "failed"`, never a half-applied file.

`oah validate` is [`docs/validation.md`](docs/validation.md)'s degradation ladder,
**R4 only**: for each DTO `oah instrument --mode fix` actually applied, does
`change.file` contain every expected attribute name at or after the DTO's own
anchor line? A code-level presence check, nothing more — it never runs the target
product on its own, so `ladder_rung` is fixed at `"R4"` (R4's own stated ceiling —
`--dynamic` below doesn't change this, see why). `--dynamic` additionally wires
E6 R2's sandbox mechanism into `docs/validation.md`'s own **deterministic-layer
regression gate** and, now, **real per-DTO event-emission assertion** — both over
one real sandboxed run, not two. The regression gate: the target's real test suite
runs, network-isolated, inside a throwaway Docker container; a real test failure
sets `verdict: "validation_failed"` (real ladder vocabulary the schema never
emitted before this), reported under `regression_gate`
(`status`: `not_attempted`/`skipped`/`passed`/`failed`, plus `reason`). Event
assertion: `skills/s10-instrumenter/SKILL.md` now names a concrete telemetry API
(`opentelemetry.trace`), so the sandbox additionally bootstraps a real
OpenTelemetry capture pipeline (`opentelemetry-instrument` +
`OTEL_TRACES_EXPORTER=console`) and, per DTO, checks whether a single real
captured span actually had every one of that DTO's `expected_events[].required_attributes`
together — reported under `event_assertions`
(`status`: `not_attempted`/`skipped`/`observed`/`not_observed`, plus `reason`).
Alongside these two, a **static trace-ID-propagation check** runs unconditionally
(no `--dynamic` needed, same as the R4 static check) for `propagate_context`
DTOs specifically: it classifies the async/queue boundary shape from
`change.description`'s free text and looks for that shape's expected
propagation code (`opentelemetry.context`'s `get_current()`/`attach()` for a
thread-pool boundary, `opentelemetry.propagate`'s `inject()`/`extract()` for a
Celery/queue boundary crossing a real wire, or nothing at all for
`asyncio.create_task`, which already propagates via Python's own `contextvars`)
— reported under `propagation_checks` (`status`:
`not_applicable`/`skipped`/`present`/`absent`, plus `reason`); an
unclassifiable description is honestly `skipped`, never guessed.

Together these are **real R2, both halves** — `docs/validation.md`'s ladder
table defines R2 as event-emission assertion *and* propagation check together,
and `oah/validate/verdict.py`'s `compute_ladder_verdict` is the one place that
decides whether a run actually earned it: `ladder_rung: "R2"` /
`verdict: "validated"` only when `--dynamic` ran, the regression gate passed,
there's at least one DTO S10 actually applied, and every one of those DTOs'
relevant checks came back positive. Short of that, `ladder_rung` stays `"R4"`
— a real regression-gate failure still forces `validation_failed` regardless of
the rest.

`--live` additionally wires E6 R1's execution mechanism in: starts the target
as a real long-running service (`--start-command`, `--port`) alongside a real
local OTel Collector on an internet-isolated Docker network, drives each
`{"method", "path"}` entry in `--requests`' JSON file against it, and reports
real captured requests/latency (`latency_p50_ms`/`latency_p95_ms`, computed
from that run's own raw samples) plus per-DTO event assertions under
`live_execution`. With `--event-schema`, captured spans' attribute names are
also checked against its declared list for unknown attributes. Also reports
real **TCR** — `docs/architecture.md`'s own primary metric: the share of
captured traces (spans grouped by `trace_id`) reconstructable end-to-end
with no missing spans (no span's parent points at one that was never
captured) — under `live_execution.tcr`, computed directly from that run's
own captured spans. `--baseline` (on top of `--live`) additionally runs the
target's real *pre-instrumentation* code — a real `git worktree` at
`--instrument-report`'s own `repo_git_sha`, never touching your actual
working tree — through the same `--start-command`/`--port`/`--requests`, and
reports the real measured latency overhead against each applied DTO's
declared `estimated_overhead_ms` budget under
`live_execution.overhead_vs_budget` (`overhead_p50_ms`/`overhead_p95_ms` are
the real signed delta between the two runs, never clamped to zero; the
budget is `null`/incomplete rather than silently `0` if any applied DTO
never declared an estimate). Doubles the live-run cost/time — opt-in, not a
default.

**`ladder_rung: "R1"` is now reachable** — `compute_ladder_verdict`
promotes past R2 to `"R1"` (still `verdict: "validated"`) when every one of
R2's own requirements holds *and* `--live` succeeded with a real
`live_execution.tcr.tcr` of exactly `1.0` (every captured trace complete,
none partial) *and* `--baseline` ran with `overhead_vs_budget.within_budget`
`true`. This is the first time `oah validate` has been able to report R1
at all — proven end to end with `--dynamic --live --baseline` combined in
one real invocation
(`tests/test_cli_validate_r1_promotion.py`). R3 (generated smoke) and the
agentic audit panel aren't built — see [Requirements](#requirements-planned)
and `ROADMAP.md`'s E6 entry.

`oah backend-config` generates a real `otel-collector-config.yaml` for either
`otel-only` (a vendor-neutral floor, exports to the collector's own `debug`
exporter) or `langfuse` (self-hosted Langfuse accepts OTLP directly over HTTP —
verified against Langfuse's own docs, not assumed). Fully deterministic, no
LLM/agent call at all. `--backend` is a **manual choice today** — constraint-driven
selection from `context.yaml` (`architecture.md`'s S7) needs S7's LLM-driven
`architecture.md`-prose synthesis, which isn't built yet (`oah event-schema` is
S7's only built piece, and it's the deterministic merge only). For `langfuse`,
the command also points you at Langfuse's own `docker-compose.yml` — deliberately
not vendored here, since Langfuse maintains that file themselves and a local copy
would drift.

`oah map` is intentionally a standalone deliverable: a one-shot observability audit of
a codebase has value even if you never proceed to instrumentation.

**Self-telemetry (dogfooding, E10):** every real LLM/Agent-SDK call `oah` itself makes
(S1 disambiguation, S4 lens design, S6 panel review, S8 DTO generation, S10
instrumentation) is wrapped in a real `opentelemetry-sdk` span — the same
`gen_ai.*`/`oah.*` attribute shape `docs/event-model.md` defines for the products
`oah` instruments — appended to `.oah/traces/oah.jsonl` (already gitignored). A
failed call's exception is recorded on its span, so a failure in any of those five
calls is reconstructable — which stage, which lens, which model, what broke — from
that file alone.

### Choosing a model / provider

Every LLM-driven command takes `--model`, a [LiteLLM model
string](https://docs.litellm.ai/docs/providers) — any provider LiteLLM supports
works, not just Anthropic. Credentials/endpoints are each provider's own env vars,
read by LiteLLM itself, not by `oah`:

```bash
# Default -- Anthropic, claude-sonnet-5
export ANTHROPIC_API_KEY=...
oah design ./product

# A different Anthropic-compatible or third-party cloud model
export OPENAI_API_KEY=...
oah design ./product --model openai/gpt-4o

# A local model via Ollama -- no API key, just a reachable endpoint
ollama pull llama3
oah design ./product --model ollama/llama3
# non-default OLLAMA_API_BASE (default is http://localhost:11434):
export OLLAMA_API_BASE=http://localhost:11434
```

`--model` is only pre-flight-checked for credentials when it's the default
(`claude-sonnet-5`) — `ANTHROPIC_API_KEY` isn't demanded for a call that was never
going to use Anthropic. Point any other model at a bad credential or unreachable
endpoint and that provider's own error surfaces from the live call, not a
misleading "ANTHROPIC_API_KEY is not set."

`oah instrument`'s `--model` is a different axis, not a LiteLLM string:
`architecture.md` pins S10 to the Claude Agent SDK specifically (file-mutation/
agent tooling), so it's Anthropic-only — pass a Claude model name/alias if you
want something other than the default, not a `provider/model` string.

Planned, not yet built (the remaining 9 DTO change types; S11's R1–R3, OTLP capture,
and agentic panel):

```
oah scan --repo ./product           # full run; --stop-after s9 for analysis-only
oah resume <run_id>                 # continue a crashed or session-limit-terminated run
                                     # from its last completed unit of work
oah check-drift --repo ./product    # cheap staleness check against DTOs' retest_triggers,
                                     # no full pipeline re-run
```

> ⚠️ Following VVAH's convention and warning: `oah instrument --mode fix` **edits
> source files in the target repo** — one git commit per DTO, with automatic
> rollback on any failure. `--mode report-only` (the default) is the non-mutating
> path; use it first. `oah scan --stop-after s9` (planned) will be the equivalent
> non-mutating path for a full pipeline run.

## Design principles

1. **Model before you design.** The gap model (S3) focuses all downstream work, the
   same way VVAH's threat model focuses vulnerability hunting.
2. **Skills, not a monolith.** Every LLM stage is a versioned skill with a declared
   input/output schema, testable in isolation against a reference corpus
   ([docs/SKILLS.md](docs/SKILLS.md)).
3. **Deterministic where possible, LLM where necessary.** AST scanning finds call
   sites; the LLM resolves ambiguity and designs. Invariant gates (S5) are pure code.
4. **OpenTelemetry as the transport floor.** Generated instrumentation targets OTel
   GenAI semantic conventions regardless of chosen backend, insuring the client
   against vendor lock-in. Opinionated backend targets (self-hosted Langfuse,
   OTel-only, managed) are selected by constraints, not fashion.
5. **Never claim more validation than performed.** S11 has an explicit degradation
   ladder (full dynamic → unit-level → generated smoke → `needs_review`);
   see [docs/validation.md](docs/validation.md).
6. **Telemetry is sensitive data.** PII masking, role-scoped access to trace content,
   and retention policy are first-class requirements, not add-ons
   ([docs/event-model.md](docs/event-model.md), [docs/security.md](docs/security.md)).
7. **Signals exist for decisions.** A health check says the service is reachable —
   not that users receive correct, approved, region- and role-appropriate, safely
   escalated answers. Every designed signal names the decision it supports and the
   role that acts; alerts no one owns are not created; evidence is judged by
   coverage class, not test count.
8. **Dogfooding.** Every OAH run emits a trace of its own stages in the very schema it
   installs for clients.
9. **Language and modality are plugins, not the core.** S1's registry and the S4
   design lenses are architected so a new source language (TypeScript, Java, ...)
   or a new call-site modality (voice, image) is an additive extension, not a
   pipeline rewrite — Python and text-first are the first concrete targets because
   a pilot needs one deep example, not because the architecture assumes them.

## Repository layout

```
docs/          architecture, event model, skills system, validation ladder, security
schemas/       JSON Schemas for inter-stage artifacts (the contract backbone)
skills/        skill drafts (SKILL.md per stage lens)
corpus/        reference repositories & eval fixtures for skill testing (planned)
.github/       CI, incl. a skills-bundling Action — debug tooling, not the
               pipeline itself; see docs/skills-bundle.md
ROADMAP.md     milestones, epics, spikes
```

## Requirements (planned)

- Python ≥ 3.10 (S1–S9, implemented today)
- `pip install oah` alone is enough for `doctor`, `estimate`, `map --no-disambiguate`,
  `inventory`, `gaps`, and `interview` — fully deterministic, no LLM credential.
- `pip install "oah[llm]"` plus an `ANTHROPIC_API_KEY` (or another provider
  [LiteLLM](https://www.litellm.ai/) supports) for `map`'s disambiguation pass and
  S4's lens skills (`design`, `event-schema`, `dtos`, `readiness`) — any provider or
  a local model (Ollama/vLLM) works via LiteLLM's abstraction layer, light-tier
  defaults for high-volume stages. Enterprise deployments behind a private gateway
  supported via base-URL override + mTLS.
- `pip install "oah[agent]"` plus an Anthropic credential for `oah instrument` (S10,
  both `report-only` and `fix`) — a separate axis from `[llm]`: the Claude Agent SDK
  specifically, not LiteLLM-routed, mirroring VVAH's Anthropic-only remediation
  constraint. `oah validate`'s `R4` slice needs neither extra (pure static file
  reads); `R1`–`R3`, when they land, will. `fix` mode additionally needs a
  git repository with a clean working tree in the target, and a `readiness_report.json`
  recommending `ready` or `ready_with_conditions`.

## Limitations (read before you trust output)

- **LLM-generated, non-deterministic.** Designs and code changes are candidates
  requiring human review at the S9 gate and at every S10 commit.
- **Dynamic validation depends on the target's runnability.** If the product cannot be
  exercised (no tests, no compose, no smoke path), the best achievable verdict is
  `needs_review` — never `validated`.
- **Elevated privilege.** The harness reads source code that may contain prompts,
  keys, and data samples, and in fix mode edits it. Run only against repositories you
  own or are authorized to modify. See [docs/security.md](docs/security.md).
- **No accuracy numbers yet.** Skill precision/recall against the reference corpus
  will be published as the corpus lands (Epic E7).

## License

Apache License 2.0 — see [LICENSE](LICENSE) and [NOTICE](NOTICE).
