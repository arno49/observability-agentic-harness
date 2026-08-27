# 025 — S11 signal provenance

Status: landed. Advances E6/S11 (`docs/decisions/011`'s own named addition).

## Context

`docs/decisions/011`: "S11 needs one addition, not a redesign... What must
be added is **signal provenance** on the verdict — whether the evidence
came from auto-instrumentation or from code this harness edited. Ladder
rung answers how much was run; environment answers against what;
provenance answers by whose instrumentation, and collapsing it into the
others hides whether OAH's own changes were load-bearing." Unlike E12's
own registries, this is core validation infrastructure, not domain-pack
data — it applies to every pack's DTOs, not just the service pack's.

## What was verified before building

A real, live local capture (Python OTel SDK, both an
`opentelemetry-instrumentation-flask`-instrumented route and a manual
`tracer = trace.get_tracer(__name__)` span in the same process — the
exact pattern `skills/s10-instrumenter/SKILL.md` teaches), inspecting each
span's own `instrumentation_scope.name` directly (not the export format,
after the first attempt via `ConsoleSpanExporter`'s pretty-printed text
turned out not to expose this field at all — a real, structural limit of
that specific exporter's own text format, found empirically, not assumed):

- An auto-instrumented span's `instrumentation_scope.name` is the
  **instrumenting library's own name** — confirmed
  `"opentelemetry.instrumentation.flask"`.
- A manually-created span's `instrumentation_scope.name` is the **calling
  code's own module name** — confirmed `"__main__"` in the local spike,
  and (traced through real Docker test fixtures already in this repo)
  `"app"`/module-name-shaped in general, never an
  `opentelemetry.instrumentation.*`-prefixed string.

This gives a real, checkable classification rule — not a guess.

## What was built

- `oah/validate/live_sandbox.py`'s `_parse_span_file`: each parsed span
  gains an `instrumentation_scope` field, read from OTLP-JSON's own
  `scopeSpans[].scope.name` (a stable, spec-defined field the file
  exporter already writes; the SDK-internal value was verified directly,
  this specific JSON serialization of it was not independently
  re-verified against a live collector capture in this phase — named
  honestly in the module's own docstring).
- `oah/validate/event_assertion.py`: `_classify_provenance` (prefix match
  against `opentelemetry.instrumentation.` and `@opentelemetry/instrumentation-`
  → `auto_instrumentation`; present but unmatched → `harness_instrumented`;
  absent → `unknown`, never guessed). `check_dto_dynamic` now returns a
  `provenance` list (deduplicated, sorted) alongside `status`, populated
  only when `status == "observed"`.
- `schemas/validation_report.schema.json`: `provenance` added to both
  `event_assertions[]` (`--dynamic`) and `live_execution.event_assertions[]`
  (`--live`) item schemas.
- Real tests: `_classify_provenance`'s own unit tests (both real prefix
  shapes, the unknown case, deduplication across multiple matching spans),
  `_parse_span_file`'s new field extraction (Docker-free, synthetic
  OTLP-JSON), and three real-Docker end-to-end assertions updated with
  their now-correctly-predicted values, verified by actually running them
  (not just editing and trusting): `--dynamic`'s own path reports
  `["unknown"]` (confirmed for real — the console-exporter capture
  mechanism structurally can't carry this field); `--live`'s path reports
  `["harness_instrumented"]` for the existing test fixture's own manual
  span (confirmed for real).

## Decision

**A real, honest asymmetry between `--dynamic` and `--live`, not
smoothed over.** `--dynamic`'s event-assertion capture
(`oah/validate/pytest_runner.py`, scraping `ConsoleSpanExporter`'s
pretty-printed text) never carries `instrumentation_scope` in its own
printed format — confirmed empirically, not assumed. Every `--dynamic`
observation therefore reports `provenance: ["unknown"]` by construction,
which is not a bug to route around; it is what that capture mechanism can
actually support. `--live`'s OTLP-JSON capture is the one path where
provenance is genuinely informative today.

**Scoped to the per-DTO event-assertion result, not bubbled into
`ladder_rung`/`verdict`.** The ADR's own text asks for provenance "on the
verdict," which could mean a new top-level field summarizing provenance
across all DTOs, feeding `compute_ladder_verdict`'s own promotion logic.
Not attempted here — this phase lands the real, per-observation data first
(the harder, verification-heavy half); folding it into the promotion rule
is a separate, smaller follow-up now that the underlying data exists.

## Consequences

- For the first time, a validation report can honestly distinguish "this
  event showed up because zero-code auto-instrumentation already provides
  it" from "this event showed up because S10's own edit was load-bearing"
  — directly answering the question `docs/decisions/011` named.
- A real, structural asymmetry is now documented rather than silently
  inconsistent: `--live` runs can give a meaningful provenance answer,
  `--dynamic`-only runs cannot, by construction of their respective
  capture mechanisms.
- Not yet done: bubbling provenance into `ladder_rung`/`verdict` itself; a
  JS/TS-side empirical verification of the `@opentelemetry/instrumentation-`
  prefix (grounded in the same OTel spec convention as the Python case,
  not independently spiked against a live JS capture in this phase).
