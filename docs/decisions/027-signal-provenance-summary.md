# 027 — Signal provenance: a report-level summary

Status: landed. Advances S11 (`docs/decisions/011`, `docs/decisions/025`'s own named follow-up).

## Context

`docs/decisions/025` landed per-DTO provenance (`event_assertions[].provenance`)
but deliberately deferred "bubbling provenance into `ladder_rung`/`verdict`
itself" as a separate follow-up. Re-reading `docs/decisions/011`'s own
framing on returning to it: "provenance answers by whose instrumentation"
is posed as a question the report should be able to answer, not as a new
gating threshold alongside `ladder_rung`/`environment`. That reframing
settled the scope: a report-level **summary**, not a change to the
promotion rule in `oah/validate/verdict.py`.

## What was built

- `oah/validate/event_assertion.py`'s `summarize_provenance(*event_assertion_lists)`:
  counts observations (not distinct DTOs — matching the per-DTO field's
  own non-exclusive shape) across one or more `event_assertions` lists.
  `cmd_validate` calls it with **both** the top-level `--dynamic` list and
  `live_execution`'s own `--live` list (whichever ran), so a combined run
  gets one real, combined answer instead of two separate, uncombined
  numbers a reader would have to add up themselves.
- `schemas/validation_report.schema.json`: new required top-level
  `signal_provenance` field (`{auto_instrumentation, harness_instrumented,
  unknown}`, all-zero when nothing was ever observed).
- `oah/cli.py`'s `cmd_validate`: computes and includes it in every report,
  plus a stderr summary line matching the existing style for
  `regression_gate`/`event_assertions`/etc.
- Real tests: `summarize_provenance`'s own unit tests (zero case, single
  list, combining two lists, a DTO counted toward both categories) and a
  real-Docker assertion added to the existing R1-promotion end-to-end test
  — verified by actually running it, not just predicted: one `unknown`
  from `--dynamic`'s own capture mechanism (structurally can't carry
  `instrumentation_scope`) plus one `harness_instrumented` from `--live`'s
  real OTLP-JSON capture of the same tracer span, in one real combined
  `oah validate --dynamic --live --baseline` invocation.

## Decision

**Not wired into `compute_ladder_verdict`'s promotion rule.** A run's
`ladder_rung`/`verdict` still depend only on whether each DTO's evidence
was *observed*, never on *whose* instrumentation produced it — matching
`docs/decisions/011`'s own framing of provenance as an informational
answer, not a gate. Whether provenance should ever become gating (e.g. "a
DTO can't count toward R2 if its only evidence is auto-instrumentation,
since that was never OAH's own edit to begin with") is a real, separate
design question, not decided here — this phase closes the "answer the
question" half of `docs/decisions/011`'s own ask, not the "should this
threshold gate promotion" half, which nothing in the ADR's own text
actually asked for.

## Consequences

- `docs/decisions/011`'s own S11 addition is now fully landed: a
  validation report can state, per DTO and in aggregate, whether OAH's own
  instrumentation work was load-bearing.
- E12/S11's remaining real gaps: two queue registries (`amqplib`'s
  multi-hop resolution chain), a JS/TS-side empirical verification of the
  `@opentelemetry/instrumentation-` scope-name convention (grounded in the
  same OTel spec pattern as the verified Python case, not independently
  spiked), and a real vendored-corpus fixture (E7's own territory, DoD
  (a)'s stronger form).
