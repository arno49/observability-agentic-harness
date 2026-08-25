# Pipeline architecture

Four phases, eleven stages. Deterministic stages are pure code; LLM stages are
versioned skills (see [SKILLS.md](SKILLS.md)). Every stage consumes and produces
artifacts validated against `schemas/` at the boundary — a stage never receives free
text from a previous stage. Checkpoints live in a SQLite state DB outside the target
repo; runs are resumable and idempotent.

## Phase 1 — Discovery & Modeling

### S1 — Observability surface mapping *(deterministic + LLM disambiguation)*
Walk the target repo with AST parsing and a signature registry (Anthropic/OpenAI
SDKs, LangChain, LlamaIndex, raw HTTP to known LLM endpoints, vector DB clients,
tool/agent frameworks, queue producers/consumers on paths between them, and
`realtime_session` sites — persistent duplex connections such as a WebRTC/WebSocket/
SIP voice session, structurally distinct from a single request/response call).
The AST layer and signature registry sit behind a per-language adapter interface
(SP10) so Python ships first without hard-coding Python-only assumptions into the
pipeline core — TypeScript/Node and Java (E11) plug into the same interface.
Ambiguous sites (dynamic dispatch, homemade wrappers) go to an LLM disambiguation
pass with the surrounding code as context. **Output:** `surface_map.json` — every
LLM, retrieval, tool, queue, and realtime-session touchpoint with file/line,
framework, sync/async nature, and confidence.

### S2 — Existing telemetry inventory *(deterministic + LLM)*
Find what already exists: loggers and their call sites, metrics libraries, existing
OTel/vendor SDK usage, correlation-ID mechanics, error handling that swallows or
surfaces failures. **Output:** `telemetry_inventory.json`.

### S3 — Gap model & strategy *(skill: gap-modeler; interactive)*
Join S1 × S2 against the reference domain model ([event-model.md](event-model.md)).
For every surface point, decide: covered / partially covered / dark. The stage also
generates an **owner interview** — questions about workflow criticality, PII
presence, data-egress constraints, review workflows, plus a **data & governance
map**: what data the product receives / retrieves / returns / logs across the full
workflow ("internal-only" is not "low-risk by default"); the **source inventory**
with approval status per region and use case, restricted sources and their
approved handling path; **trust boundaries** — which caller-asserted context
(role, region) is verified server-side vs. trusted; and the **declared tool/action
boundary** for the current release. Answers are recorded as `context.yaml` and
weight prioritization. The skill also flags any place the target product treats a
model-generated confidence/certainty field (e.g. `confidence_note`) as if it were
calibrated — routing on it without a deterministic rule, evaluator, or human behind
it is a gap, not coverage (see the confidence-field invariant in
[event-model.md](event-model.md)). **Output:** `gap_model.json` (prioritized),
`context.yaml`.

## Phase 2 — Design & Verification

### S4 — Design by lens *(skills, one per lens)*
Specialized skills each design their slice for this specific stack:

- **tracing** — trace-ID propagation end-to-end, including async boundaries, queues,
  and retries (the hardest lens; see SP2 pattern catalog);
- **generation-capture** — prompt/completion capture, model+prompt versioning,
  parameters, token & cost accounting including cache read/write and reasoning
  tokens as their own line items where the provider bills them separately
  (`gen_ai.usage.cache_read.input_tokens` / `cache_write.input_tokens` /
  `reasoning.output_tokens`, per SP6), **time-to-first-token**
  alongside total generation latency for streaming calls; and whether
  user-supplied data is captured in a field structurally separate from system
  instructions — the design-time mitigation the prompt-injection guardrail
  (see event-model.md) is the runtime backstop for;
- **retrieval** — retrieved sources, scores, the critical "what actually made it
  into the context window vs. was truncated" signal, and **permission-aware
  retrieval visibility**: per-source governance status against the inventory from
  `context.yaml`, region-conditional handling, restricted-source exclusion or
  gating made observable;
- **tools** — tool/agent invocations: arguments, results, durations, and cascade
  shape captured **per branch**, not only as a cascade-level aggregate — a fan-out
  of parallel calls compounds a small per-call tail-latency chance fast (a 1%
  per-call tail at 100-way fan-out puts most requests through at least one slow
  call), so an aggregate duration alone hides exactly the risk fan-out creates;
- **feedback** — user feedback and reviewer verdicts bound to trace IDs; verdict
  taxonomy (categorized, not free-text);
- **pii-governance** — masking at ingestion, role-scoped content access, retention
  matrix, deletion-by-subject;
- **cost** — per-call cost attribution, spend thresholds with a named acting role,
  quota/rate-limit headroom capture (provider rate-limit headers on generation
  spans), throttling/queueing hooks;
- **realtime & multimodal** — turn-taking and interruption latency for live voice,
  transcription/recognition error rate, fallback/handoff across channels when a
  modality isn't working for the user, and media-specific governance: consent,
  access/storage/retention for captured media, what derived artifacts (transcripts,
  embeddings) must never reach logs. On the `surface_map.json` side this lens is
  the consumer of `realtime_session` points; on the event side it's the consumer
  of the Generation entity's `modality` attribute. Present on the lens roster from
  the start (not deferred) so the event model stays modality-neutral even while
  the first registries are text-only;
- **ops (production readiness)** — release identifiers stamped on every event
  (prompt, model config, tool setup, retrieval config, deployment package — "we see
  a problem but don't know what changed" must be impossible); a **persistent
  post-deploy smoke test** installed into the client product (alive, reachable,
  one golden path per critical workflow) — distinct from S11's one-off validation;
  **degradation visibility** — graceful-degradation responses (e.g. safe "cannot
  answer from approved sources" instead of invention) emitted as first-class
  events, so silent-failure and unsafe-fallback rates are measurable; **rollback
  observability** — every rollback-capable surface (prompt version, model config,
  retrieval index, deployment) is identifiable in telemetry, so "roll back to the
  last known-good" has an evidence trail; a **disablement plan** distinct from
  rollback — the ability to switch off or limit the workflow (kill switch, scope
  narrowing to a region/role segment) even when there is nothing safe to roll
  back to; **incident-response route** — ownership
  attribute on every workflow's telemetry, alert routing to named first responders,
  escalation events recorded with outcome; **alert plan** — the standard catalog
  (availability, latency, error-rate, quota, cost/consumption, dependency,
  safety/quality), each category either a user-facing symptom or one of the narrow
  legitimate exceptions — a resource approaching exhaustion (quota, cost/consumption)
  before any symptom is visible yet — never an enumerated internal failure cause
  with no symptom and no exhaustion story behind it; alerting on every possible
  failure mode individually is exactly the noise the anti-metric-hoarding gate
  below exists to keep out — where every
  alert declares a trigger condition stated as a target and measurement window per
  critical workflow (a reliability budget, not a bare threshold pulled from
  nowhere), so "pause expansion" or "roll back" in the S7 decision menu fires when
  that budget is spent, priority, first responder, escalation path, and decision
  owner. Rule mirroring the S5 signal-gate: an alert no one owns, or whose signal
  only matters in periodic review, is not created — low-value alerts bury the ones
  that matter.

**Output:** per-lens design fragments (structured), merged into a draft design.

### S5 — Deterministic invariant gates *(pure code)*
No LLM. Checks include: every S1 surface point has a design decision; event fields
map to OTel GenAI semantic conventions or declared `oah.*` extensions; every schema
field carries a data-sensitivity tier and no field is allowed to carry unmasked PII
above its declared tier; declared cross-field consistency assertions (e.g. a
restricted-access response cannot carry `needs_review: false`) are present wherever
a structured output has more than one field whose values can contradict each other;
latency-overhead budget is declared per call path; telemetry failure mode is
declared fail-open (telemetry loss must never break the product); **a decision-menu
step that pauses, freezes, or throttles (S7) never ships without a paired
resumption condition** — a freeze with no stated way back is rejected the same way
an alert with no owner is; **every designed signal names at least one decision it
supports and the role that acts**
(anti-metric-hoarding gate — see the signals→decisions matrix in
[event-model.md](event-model.md)). A failed gate blocks progression with a machine-readable reason.

### S6 — Adversarial design review *(agentic panel)*
Personas score the design against weighted gates, VVAH-style:
- **SRE** — collector failure modes, backpressure, cardinality, overhead;
- **security reviewer** — prompts/outputs as sensitive data, access model, injection
  surface of the telemetry path itself; **data-flow review**: caller-asserted
  context trusted without verification, retrieval reachable beyond the approved
  inventory, tool actions beyond the declared boundary, and staging success
  presented as evidence of production-ready secrets/configuration;
- **cost skeptic** — storage & egress economics at target traffic, sampling policy
  sized from measured trace-duration percentiles (a collector's decision-wait set
  above the traffic's actual p99 trace duration, not a default copied from a
  different service's traffic shape) — and flagged if the design assumes per-span
  sampling decisions when the backend requires whole-trace tail sampling, which
  forces every span of a trace onto the same collector instance and adds a
  load-balancing tier, not just a config knob.

Findings are categorized verdicts, not prose. Design iterates S4→S6 until pass.

## Phase 3 — Synthesis & Planning

### S7 — Architecture & schema emission *(skill: synthesizer)*
Emit `architecture.md` (target design incl. backend selection justified against
`context.yaml` constraints — OTel-only / self-hosted Langfuse / managed),
`event_schema.json` (versioned; OTel GenAI + extensions), and `rollout_plan.md`
ordered by workflow criticality: first workflow = most critical one, tracing +
generation capture first, feedback loop second, auto-scoring third. Schema
versioning follows OTel's own discipline rather than an invented one: an `oah.*`
extension attribute is Development or Stable (nothing in between), a breaking
rename ships alongside the old name for a stated dual-emission window before the
old name is dropped, and consumers pin to a schema version instead of assuming
latest. One gap this inherits, not solves: `gen_ai.*` itself publishes no
schema-version marker to pin to, and every `gen_ai.*` attribute currently sits
at Development stability, not just some
(see [SP6's decision record](decisions/001-sp6-otel-genai-semconv-maturity.md))
— so `oah.*` extensions carry the version discipline the GenAI layer doesn't yet provide for
itself. Also emit
`runbook.md` — the incident-response route for the installed observability: per
workflow, an **ownership matrix** (service owner, first responder, escalation
owner, release owner, rollback owner, documentation owner), issue-review cadence,
documentation location, evidence to pull per alert (which dashboards/queries), and
the decision menu (continue / pause expansion / cap or throttle / remediate /
degrade / roll back / escalate) with rollback targets identified by release
identifiers. When the trigger is budget exhaustion specifically, the ladder
follows one of two shapes, chosen per workflow rather than invented per DTO:
**burn-rate** (how fast the budget is being spent — e.g. page when 10% of a
week's budget burns in an hour) or **cumulative-consumption** (how much of the
window's budget is gone — e.g. warn at 75%, freeze at 90% over 30 days). Either
shape, a freeze/pause step is never emitted without a paired resumption condition
(budget back under a stated floor and alerts clear) — see S5's matching gate.
Each ownership row binds to evidence ("if cost exceeds pilot range,
X reviews spend evidence and decides on limits") — the aim is a clear decision
path for the most important signals, not an ownership matrix for every possible
issue. Dashboards and alerts are specified as one roll-up per critical workflow,
not authored as two independent views: S4's alert-plan catalog (availability,
latency, error-rate, quota, cost, dependency, safety/quality) is the technical
layer; the ops lens's golden-path smoke checks are the functional layer directly
above it; both roll up into a single per-workflow status. An on-call engineer
paged by an alert and a stakeholder reading a dashboard are then reading the same
tree at different depths, so a signal added at the technical layer is visible at
every layer above it by construction, instead of requiring someone to remember to
also wire it into a separately-maintained dashboard. What S7 fixes is the roll-up
structure — which signals feed which layer — not a set of pre-built charts: a
curated dashboard goes stale the moment a workflow's shape changes faster than
someone maintains it, so the roll-up is built to be queried ad hoc as well as
viewed pre-assembled.

The runbook also names a **drill cadence** — the corpus tabletop
walkthrough (`docs/validation.md`) and a fail-open check (kill the collector
mid-traffic) rerun on a schedule, not only once at S11 and not only when a
retest trigger fires, since an untested runbook is a document, not a
capability. And it names a **post-incident retrospective process**: every
resolved escalation with a `preventative_action` (event-model.md) is reviewed
against the current gap model and eval dataset within a stated window, so
closing an incident operationally and feeding it back into the design are the
same habit, not two unrelated processes that happen to share a data source.

### S8 — Implementation DTOs *(skill: dto-generator)*
Each rollout step decomposes into `implementation_dto.json` entries: target file and
insertion point, instrumentation type, code-shape preconditions, and — crucially —
**expected emitted events**, which is what makes S11 verification possible. Expected
events may include **cross-field consistency assertions** (not just field presence)
— e.g. "if `access_result == restricted` then `source_ids == []` and `needs_review
== true`" — so S11 catches a schema-valid-but-incoherent response the same way it
catches a missing field. Every DTO links back to a gap-model entry and a surface-map
point.

### S9 — Production readiness report *(deterministic assembly)*
The human gate artifact, structured as a five-question readiness checklist
(Markdown + machine-readable JSON per `schemas/readiness_report.schema.json`):

1. **What are we deploying, and where will it run?** — workflow, intended
   users/systems, environment & exposure, runtime/secrets approach, and the
   data/access/dependency/rate-limit assumptions that affect readiness.
2. **What evidence shows the release is ready to move?** — release identifier set,
   health/smoke/controlled-failure evidence, approval/release/rollback owners, and
   evidence still missing.
3. **How will the team know what is happening after release?** — key signals (each
   naming its decision), correlation IDs and rate-limit headers, alert triggers,
   and named sensitive-data classes that must not be logged.
4. **What happens if it fails or degrades?** — top failure modes with default
   response actions, retry/degradation/fallback behavior, incident route,
   rollback/pause criteria.
5. **What is the recommendation?** — one of **ready / ready with conditions /
   remediate before release / pause and redesign / escalate for review / rollback
   or pause expansion**, with rationale, top blocker, next-action owner, and —
   keeping the decision falsifiable — *the evidence that would change it*.
   *Pause-and-redesign* (the design itself is unfit for the workflow) and
   *escalate-for-review* (the risk exceeds the working team's authority) are
   deliberately distinct diagnoses: gaps that are fixable evidence problems point
   to *remediate*, not to either.

Every section ends with its open blocker or next validation step. The Markdown
half narrates the same content in seven sections: customer situation /
recommendation / **evidence position (confirmed vs. assumed vs. unknown)** /
readiness gaps / **scope and exclusions** (what stays out of the first release
unless separately approved — evidence-led, not ambition-led) / owners and next
action / decision-change evidence in both directions (what would upgrade the
decision, what would force escalation). The report is short, specific, and
decision-ready — evidence a reviewer needs, not an inventory of every operational
detail. Two standing rules: the gate never advances on confidence, urgency, or a
successful demo alone; and the recommendation must be **deployment-safe** — clear
about what the product can do, what it cannot yet prove, and what must happen
before users are exposed to risk. The release recommendation is a decision layer above
S11's technical verdict (`validated`/`validation_failed`/`needs_review`): a
technically `validated` run can still be `ready_with_conditions`, and post-release
evidence can turn any prior decision into `rollback_or_pause_expansion`. **Fix
mode does not proceed without a recorded decision of `ready` or
`ready_with_conditions` (with conditions logged).**

## Phase 4 — Implementation & Validation

### S10 — Instrument *(agentic; Claude Agent SDK)*
Apply DTOs: insert SDK calls/decorators, wire collector config, generate
docker-compose for self-hosted backends. One commit (or PR) per DTO. Modes:
`report-only` (diffs only) / `fix` (applies). Failed application → clean rollback +
recorded failure, never a silent skip. ⚠️ Fix mode edits source in the target repo.

### S11 — Validate *(deterministic layer + agentic panel)*
**Deterministic:** run the target's own test suite (regression check); exercise the
product per the validation ladder ([validation.md](validation.md)); intercept emitted
events via a local OTLP collector; validate every event against `event_schema.json`;
compute **actual Trace Completeness Rate** and latency overhead vs. budget.

**Agentic panel:** *telemetry auditor* ("take trace X, reconstruct the incident from
telemetry alone"), *privacy auditor* ("find PII in real emitted events"), optional
*cross-service analyzer* for multi-repo products.

**Verdicts:** `validated` / `validation_failed` / `needs_review`, always annotated
with the ladder rung achieved.

## Cross-cutting

- **Run manifest.** Every run writes `run_manifest.json`: tool version, model roles,
  config hash, target git SHA, timing, per-stage cost, and — once produced —
  **environment** (per SP9's provenance model: self-reported vs. IaC-corroborated),
  since a verdict must be readable without cross-referencing a separate document to
  know what it's evidence *of*.
- **Checkpointing.** Sub-stage, not just stage-boundary: S10 checkpoints per applied
  DTO, S11 per completed scenario. `oah resume <run_id>` continues from the last
  completed unit of work whether the run stopped because it crashed or because it
  hit a token/session budget wall — the two cases are indistinguishable to resume
  logic and must both "just continue."
- **Budgets.** Per-stage `max_budget_usd`; `oah estimate` predicts before spending.
- **Model backend abstraction (LiteLLM).** The harness talks to models through
  [LiteLLM](https://www.litellm.ai/), so every stage's model is a config role
  resolvable to any provider — Anthropic, OpenAI-compatible, or local
  (Ollama/vLLM) — mirroring VVAH's vendor-neutral layer without building one.
  High-volume/low-judgment stages (S1 disambiguation, S2 inventory) default to a
  light tier (Haiku-class or local for zero-egress deployments); design and panel
  stages (S4, S6) default to a frontier model. **Exception, VVAH-style:** the
  agentic stages S10 (instrumenter) and S11 (validation panel) require the Claude
  Agent SDK's file-mutation and agent tooling and are Anthropic-pinned; a
  non-Anthropic role there is refused rather than degraded silently. SP8 validates
  where the light tier holds quality before it becomes a default.
- **Self-telemetry.** The harness emits traces of its own stages in the same event
  schema it installs (dogfooding, and the best product demo).
- **Primary metric.** TCR — share of exercised user requests reconstructable
  end-to-end with no missing spans. Reported per run and per workflow.
