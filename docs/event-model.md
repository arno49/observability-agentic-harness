# Target event model

This is the reference domain model OAH installs into client products. It is the
yardstick S3 measures gaps against and the schema S11 validates real events against.
Transport floor: OpenTelemetry, using GenAI semantic conventions (`gen_ai.*`) where
they exist and `oah.*` extension attributes where they do not (SP6 maintains the
mapping).

## Entities

**Trace** — the full path of one user request through all components. Carries the
**release identifier set**: prompt version, model id, config hash, tool-setup
version, retrieval-config version, and deployment package id — so any incident is
reproducible and "we see a problem but don't know what changed" is impossible.
Every trace also carries an **ownership attribute** (workflow → owning team/person)
so alerts route to a named first responder, not a shared void. Trace metadata is
never sampled away; content payloads may be tier-stored (see governance).

**Span** — one stage inside a trace: retrieval, generation, tool call, guardrail
check, human review, queue hop. Spans carry stage-local latency and status including
*partial* outcomes (stream aborts, truncations).

**Generation** — specialized span for an LLM call: prompt reference (versioned, not
inline duplicated), parameters, token counts, cost, cache-hit flag, finish reason,
and refusal/guardrail outcomes. Carries **`input_modality`/`output_modality`**
(`text` / `audio` / `image` / `structured`, extensible) so a call that takes voice
input or returns an image is the same entity as a text call, not a special case —
this is what lets the `lens-realtime-multimodal` design lens (see architecture.md
S4) reuse the whole trace/span model instead of forking it, even though the first
concrete registries only ever populate `text`. Carries a **`response_path`**
classification —
`answer` / `clarify` / `refuse_safe_complete` / `escalate` / `structured_failure` —
naming which of the designed response paths this generation actually took, so
behavior rates (fallback, clarification, refusal, escalation) are computable
directly from spans instead of reconstructed from free-text output after the fact.

**Retrieval span** — query, retrieved source IDs with scores, the
made-it-into-context vs. truncated distinction (silent truncation is a top hidden
degradation cause), and **per-source governance status**: whether each source used
was approved for this user, role, region, and use case at request time (approved /
pending / restricted / region-mismatch, with inventory version). "A document
exists" is not "the API may use it" — an answer served from an unapproved,
restricted, or region-inappropriate source must be a detectable event, not a
post-hoc investigation.

**Tool span** — tool name, arguments, result, duration, downstream error class,
and the **declared action boundary**: which external effects this release is
allowed to have (e.g. read-only pilot: no ticket creation, no record updates, no
outbound messages). A tool action outside the declared boundary is an alertable
event in its own right, regardless of whether it succeeded.

**Guardrail span** — a single pre- or post-generation check, structured the same
way as the S7 alert plan so a check is never just a pass/fail with no accountable
owner: **boundary** (what it controls), **trigger** (the condition that activates
it), **check location** (before generation / after generation / before action /
before display), **expected behavior** (continue / clarify / refuse / retry /
block / escalate), **evidence captured**, and **owner**. A guardrail's job is not
"did every required field come back" but whether the fields are *mutually
consistent* — e.g. a response about a restricted dataset with an empty
`source_ids` and `needs_review: false` is a guardrail failure even though every
required field is present and schema-valid.

**Feedback event** — user report or reviewer verdict bound to a trace ID. Verdicts
use a fixed taxonomy (hallucination / irrelevant-retrieval / refusal-error /
format-error / other) — free-text-only feedback is a gap, not coverage.

**Session** — chain of traces for one dialog/task.

**Degradation event** — the product chose a limited safe response instead of the
full path (retrieval source down → "cannot answer from approved sources" rather
than invention; approved regional source missing or pending → fallback or human
routing instead of answering from the wrong region's version). Recorded with cause
and fallback taken. This makes graceful
degradation *measurable*: silent-failure rate and unsafe-fallback rate become
metrics instead of anecdotes.

**Escalation event** — a human was pulled in: review flag raised, incident
escalated, pause/rollback decision taken. Carries who, why (category), and outcome
(confirmed / dismissed / rolled back), closing the loop the runbook defines.

**Dataset item** — a trace promoted into an eval set, tagged with a **case
class**: common / ambiguous (expected: clarification) / restricted (expected:
refusal or escalation) / regional / role-specific / missing-source /
outdated-source / conflicting-source / high-risk / action-boundary. Coverage is
judged per class, never by raw test count — passing happy-path cases proves
progress, not readiness. This link is what turns observability from a log
warehouse into a quality flywheel: bad traces become regression tests for the
next prompt/model version, and each promoted trace fills a named coverage class.

## Error taxonomy

Every failure event carries a category from a fixed vocabulary, grouped by nature:

- **input/context:** missing input, missing approved context, source unavailable,
  context overflow & truncation, stale index;
- **execution:** authentication failure (identity not proven) vs. authorization
  failure (identity proven, access not allowed) — distinct categories with
  distinct responses; malformed structured output (+ retry outcome);
  tool/downstream failure (incl. cascade/partial); latency/timeout; rate
  limit/quota;
- **quality/governance:** confirmed hallucination, wrongful refusal, irrelevant
  retrieval with green status, **answer served from an unapproved, restricted, or
  region-inappropriate source**, tool action outside the declared boundary,
  prompt-injection attempt & outcome, eval regression, drift;
- **feedback:** user-reported incorrect output, reviewer rejection (categorized).

Severity is assigned per category, not left to the emitter. Each category also
carries a **default response action** chosen at design time from: bounded retry
(exponential backoff + jitter, capped attempts, never for non-retryable
categories — failed attempts still consume rate limits), fallback to an approved
alternate path, graceful degradation, escalation to owner, rollback, pause
rollout, or user/stakeholder communication. This mapping is the design-level
answer to "what can go wrong and what should happen when it does", and it guards
both unsafe extremes: ignoring failures because the service is still technically
reachable, and treating every failure as a full emergency.

## Governance requirements (first-class, not add-ons)

**Data sensitivity classification.** Every field a designed signal might carry is
classified into one of five tiers, and the tier — not the field's apparent
harmlessness — drives masking, access, and retention design:

| Tier | Examples |
|---|---|
| Public | Content already approved for public use |
| Internal | Business information for internal users |
| Customer-confidential | Records, correspondence, documents tied to a specific customer |
| Personal / regulated | Personal, protected, or regulated data |
| Secrets / credentials | API keys, passwords, tokens, certificates |

**Rule under uncertainty:** classify at the highest tier reasonably applicable
until a responsible owner confirms otherwise — never guess down. `lens-pii-governance`
designs masking/access/retention per tier; the S5 gate checks every schema field
against its declared tier.

1. **PII masking at ingestion** — before storage, not at query time. The
   exclusion list goes beyond personal data: customer confidential content,
   access tokens/credentials, **internal system prompts and hidden instructions**
   (log prompt *references and versions*, never bodies, outside permissioned
   tiers), **raw tool outputs containing sensitive data**, and full source
   documents that don't need to live in logs. More logging is not better: excess
   capture raises noise, cost, privacy risk, and review burden. A reference
   allow/deny pair anchors the design: **safe** — `request_id, caller_id,
   environment, action, approval_status, status_code, latency_ms, timestamp`;
   **unsafe** — raw prompt body, `api_key`, customer email address, generated
   customer-facing text. The privacy-auditor panel (S11) is graded against this
   pair on real emitted events, not the design.
2. **Role-scoped access** — metadata visible broadly; prompt/output content by
   permission; content reads are themselves audited.
3. **Retention matrix** — separate clocks for metadata (long) and content (short);
   full content kept for all failures and negative feedback, sampled for successes.
4. **Deletion by subject** — user-ID-keyed erasure across trace content.
5. **Fail-open telemetry** — loss of telemetry must never degrade or break the
   product path (fire-and-forget with local buffering).

## Signals → decisions

The model above defines *what* is recorded; this section defines *why*. Every
signal OAH designs must name at least one operational decision it supports and the
role that acts — a signal supporting no decision is rejected at the S5 gate
(anti-metric-hoarding rule: the goal is not to collect every possible metric, but
the evidence needed to decide whether the product is healthy, usable, reliable,
affordable, and safe for its workflow).

| Signal class | Shows | Supports deciding |
|---|---|---|
| **Health & availability** | Service reachable, responding, available when intended users need it (continuous health check + the installed post-deploy smoke test) | continue / investigate outage / block release / escalate availability risk |
| **Latency & dependency timing** | Whether slowness comes from the API layer, model, retrieval, tool, or downstream — per-stage span timing makes the decomposition free | investigate source of slowness / tune / review scaling / degrade gracefully / pause expansion / roll back |
| **Usage, throughput & quota pressure** | Traffic volume vs. expectations; headroom against provider rate limits and quotas — generation spans capture provider rate-limit response headers (`anthropic-ratelimit-*`; `x-ratelimit-*` on OpenAI-compatible backends incl. LiteLLM-proxied local ones; exact header sets validated against current provider docs at design time, not hardcoded) | adjust rollout / review quota needs / plan capacity / add throttling or queueing / revisit rate-limit assumptions |
| **Cost & consumption** | Whether usage creates expected consumption; whether the chosen model/capability/retrieval pattern still fits the operating plan; spend vs. declared thresholds. Primary metric is **cost per successful task** — including retries, extra calls, and reviewer correction — not nominal per-call price, which understates cost on any workflow with a non-trivial retry or correction rate | continue / cap usage / set usage limits / add release conditions / investigate cost drivers / review model choice — each spend threshold names **who acts** when approached |
| **Retrieval & dependency reliability** | Source/model/tool/downstream failing, unavailable, slow, permission-blocked, or incomplete | remediate source or permission / fall back / degrade gracefully / escalate to owner / pause expansion / roll back |
| **Error behavior & release traceability** | Error rate vs. baseline; whether errors rose after a release; which release identifier produced the behavior | investigate / remediate / pause expansion / roll back / review release / preserve auditability |
| **Behavior & guardrail signals** | Fallback rate *with reason*, clarification rate, escalation/human-handoff rate, restricted-topic attempt rate with handling outcome — and error patterns **segmented by region, role, and restricted-attempt**, since a systematic failure for one user group is invisible in aggregate rates | tune guardrails / expand or narrow scope / escalate to policy owners / pause expansion for an affected segment — a health check says the service is reachable, not that users receive correct, approved, region- and role-appropriate, safely escalated answers |

The runbook (S7) binds each row to the workflow's owner and escalation path, so
the decision menu — continue / pause expansion / cap or throttle / remediate /
degrade / roll back / escalate — is never abstract.

## Support questions (telemetry acceptance rubric)

Installed telemetry must answer, for any incident, without code archaeology:
which request failed; which release identifier set was running; what status was
returned; what error category occurred; did the model / tool / retrieval source /
downstream dependency succeed; where did latency appear; was the issue isolated or
widespread; what evidence supports release, rollback, or remediation; and was
sensitive data excluded from the record. The S11 telemetry-auditor uses these nine
questions verbatim as its reconstruction rubric.

**Request summary record.** Besides full traces, each request emits one compact
summary record — the support-facing rollup: request IDs, environment (tagged with
its provenance — self-reported vs. IaC-corroborated, per SP9 — so "staging" in a
record is never silently taken on faith), caller, release identifiers, action,
status, per-dependency statuses (model / retrieval / tool / downstream, incl.
`not_used`), latency, error category, rate-limit headroom, and a
`sensitive_content_logged` self-attestation flag (asserted `false` by construction;
the S11 privacy-auditor treats a `true` or a wrong `false` as a blocking finding).
Support works from summaries; full traces are opened by permission when a summary
isn't enough.

**Dual request-ID correlation.** Generation spans record both the
provider-generated request id (e.g. Anthropic's `request-id` response header) and
an application-supplied client request id sent with the call — so timeouts and
network failures are correlatable even when no response header ever arrives. The
client id lives in the trace; the provider id links the trace to provider-side
logs and support tickets.

## Invariants (enforced by S5 gates and S11 validation)

- Every LLM call belongs to a trace; no orphan generations.
- Every trace carries the release identifier set and an ownership attribute.
- Every feedback event resolves to a trace ID.
- Every error event carries a taxonomy category.
- Every fallback path emits a degradation event — degrading silently is itself a
  defect the telemetry must expose.
- Every retrieval span records the governance status of each source used; every
  tool span records conformance to the declared action boundary.
- Caller-asserted context (role, region, tenant) is recorded with its provenance —
  whether the API verified it or trusted the calling application. Authentication
  of the caller alone does not prove authorization of the request.
- No schema field may contain unmasked PII.
- Structured output fields must be internally consistent, not merely
  schema-valid — a DTO (S8) may declare cross-field assertions (e.g. `access_result
  == "restricted"` implies `source_ids == []` and `needs_review == true`), and
  a field-presence check that ignores such assertions is not a passing check.
- A model-generated confidence/certainty field (e.g. a `confidence_note`) is
  explanatory text, not a calibrated probability, and must never be the sole
  basis for a low-confidence trigger, a review gate, or a decision signal. If
  the target product treats one as calibrated, that is a gap-model finding
  (S3), not coverage — the trigger needs a deterministic rule, an evaluator, or
  a human in the loop behind it.
