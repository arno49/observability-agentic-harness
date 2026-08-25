# Validation (S11)

The hard difference from VVAH's domain: a vulnerability can be confirmed statically,
but working telemetry only dynamically — the product must run and emit. S11 is
therefore built around an explicit **degradation ladder**, and the verdict always
states which rung was achieved. The harness never claims more validation than it
performed.

## The ladder

| Rung | Precondition in target repo | What we do | Best achievable verdict |
|---|---|---|---|
| **R1 — Full dynamic** | Runnable product (compose / e2e / dev server) | Run product, drive synthetic traffic over the critical workflows, intercept events via local OTLP collector, diff against `event_schema.json`, compute **actual TCR** and latency overhead vs. budget | `validated` |
| **R2 — Unit-level** | Unit tests only | Assert event emission at unit level per DTO's expected-events; static check of trace-ID propagation across async boundaries | `validated` (annotated R2) |
| **R3 — Generated smoke** | Nothing runnable | Instrumenter generates a minimal smoke scenario; if it runs → treat as R1-lite. When the ops lens installed a persistent post-deploy smoke test (DTO type `add_smoke_test`), S11 reuses it — the validation scenario and the product's ongoing deploy check are the same artifact | `needs_review` unless smoke covers all critical workflows |
| **R4 — Static only** | Smoke generation failed | Schema conformance of code-level emission points only | `needs_review`, never `validated` |

## Deterministic layer (runs first, always)

1. Target's own test suite — instrumentation must not break the product
   (regression gate; hard fail → `validation_failed`).
2. Event capture — local OTLP collector as interception point; every captured event
   validated against the versioned schema; unknown fields and missing invariants
   (orphan generations, missing release identifiers or ownership attributes) are
   failures.
3. Metrics — TCR per workflow; behavioral rates observable end-to-end (fallback
   with reason, clarification, escalation, restricted-attempt handling — and
   sliceable by region/role); p50/p95 latency overhead vs. declared budget;
   telemetry fail-open check (kill the collector mid-traffic → product must not
   degrade).

## Agentic panel (runs on R1–R3 evidence)

- **telemetry-auditor** — is handed a captured trace and must reconstruct the request
  end-to-end from telemetry alone, answering the nine support questions from
  [event-model.md](event-model.md) (which request, which release, what status,
  what category, which dependency, where the latency, isolated or widespread,
  what evidence for the decision, was sensitive data excluded); any unanswerable
  question = coverage gap finding.
- **privacy-auditor** — hunts for PII/secrets in *real emitted events* (not the
  design); any hit is a blocking finding.
- **cross-service-analyzer** *(optional)* — for multi-repo products, verifies trace
  continuity across service boundaries.
- **tabletop walkthrough** *(when corpus fixtures exist)* — the panel replays an
  incident scenario against the installed signals and runbook; passing means the
  correct response path (per the fixture's labeled stronger response) is reachable
  from telemetry alone.

The panel is read-only: it reads the repo and captured events, writes only its own
findings, applies no patches.

## Verdicts

`validated` / `validation_failed` / `needs_review` — VVAH vocabulary — always with:
ladder rung, TCR achieved, overhead measured, panel findings by category, and
**environment** — which environment (sandbox / staging / production-shadow /
production) the evidence came from, and whether that environment claim is
self-reported or corroborated against IaC/CI config (SP9 decides the mechanism and
exact data model). Ladder rung answers "how much did we actually run"; environment
answers "against what" — the two are independent axes, and a report collapsing them
into one line hides exactly the "staging proved this" vs. "production proved this"
distinction that matters most to a reader deciding whether to trust the verdict.
Re-runs are idempotent.

## Staleness

A `validated` verdict is a statement about the repo at the git SHA it ran against,
not a durable property of the product. `oah check-drift` compares the current repo
state to each DTO's `retest_triggers` (files/config keys named at DTO-generation
time, S8) and flags which recorded verdicts are stale — without re-running S11. It
is deliberately cheap and non-agentic: a yes/no staleness flag per DTO, not a new
verdict. A flagged DTO's evidence should be treated as `needs_review` until S11
re-runs, even though its stored verdict still reads `validated`.
