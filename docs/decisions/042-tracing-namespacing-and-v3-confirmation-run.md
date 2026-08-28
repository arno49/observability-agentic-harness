# 042 — Full real re-run confirms the fixes; a new self-inflicted tracing conflict found and fixed

Status: **landed** (2026-08-28), same-day follow-up to `docs/decisions/039`,
`040`, and `041`.

## Context

With `docs/decisions/041`'s `pii-governance` fix landed and CI green, the
natural next question was whether `oah readiness` actually behaves
differently now on the real target this whole investigation started
from. A fourth full real `oah readiness` run against `mf-analyzer-web`
(service pack, same `context_v2.yaml`, `--save-intermediates`) was run —
explicit user choice, made aware this was real API spend on top of three
prior full/large runs this session.

## What the run found

**Confirmed fixed, holding at real scale:**

- `pii-governance` no longer fails. Its fragment covers all 75
  `http_server_route`/`declarative_route`/`db_query` points with 12
  signals (sensible grouping — e.g. many structurally-identical public
  routes sharing one governance judgment — not the brute-force
  one-signal-per-point shape an earlier isolated probe produced), and
  every S5 gate on it passes.
- `consistency_assertions_referential_integrity` no longer fails anywhere
  in this run.
- `sensitivity_tier_meets_pii_floor` no longer fails anywhere in this
  run — the `ops`/`tracing` reminder additions (`docs/decisions/040`
  Third addendum) are holding.

**A new regression, self-inflicted and directly traceable:** `build_event_schema`
raised again — `attribute 'oah.tracing.propagation_risk' designed at
sensitivity_tier='internal' by ['tracing'] but tier='confidential' by
lens='tracing'`. Inspecting the real fragment: `tracing` correctly
floored its `chat`-workflow signal to `confidential` (the PII-floor
reminder added in `docs/decisions/040` working exactly as intended) and
gave that signal a distinct `name`
(`propagation_risk_automatic_same_process_async_chat_direct_pii`) — but
`maps_to.attribute` stayed the shared, unsuffixed
`oah.tracing.propagation_risk` on all three of the fragment's own
signals. S7 merges by `maps_to.attribute`, not by `name` — splitting the
name alone does nothing to prevent the conflict.

This is the exact class of bug `docs/decisions/040`'s Option B mechanism
exists to prevent, and it is directly attributable to that same ADR's own
work: adding the PII-floor reminder to `tracing`'s SKILL.md (Third
addendum) enabled the model to correctly float a signal to `confidential`
for the first time, but `tracing`'s SKILL.md was never given the
matching Option B namespacing guidance `telemetry-cost`/`dependency`
already have — and `tracing`'s own `maps_to` line went further, stating
the attribute as a single fixed literal
(`oah_extension + oah.tracing.propagation_risk`), giving the model no
indication it could ever vary. Fixing under-classification without also
fixing the resulting name collision was foreseeable in hindsight; it
wasn't caught at the time because the Third addendum's own fix was
verified against isolated single-point probes, never a batch spanning
both a direct-PII and a non-direct-PII group for the same lens.

**Confirmed pre-existing, NOT caused by anything this session touched** —
checked directly against `intermediates_sonnet_v2.json` (the run from
before today's `ops`/`tracing` SKILL.md edits):

- `every_surface_point_has_decision` fails for `ops` (4 signals, only 1
  of 375 points covered) and `slo` (2 signals, only ~9 of 75 points
  covered) in both v2 and v3, identically. `ops`'s coverage was already
  exactly 1/375 before any of today's edits.
- `latency_budget_declared_per_point` fails for `ops`, `slo`, and
  `dependency` in both v2 and v3. `dependency`'s specific failure list is
  the same shape in both runs.
- `telemetry-cost`'s new `pii_masked_above_tier` failure (three
  `chat_client_call_*` signals at confidential/restricted tier without
  `pii_masked: true`) was NOT present in v2 — plausibly ordinary model
  sampling variance rather than a new SKILL.md gap, but a real, findable
  inconsistency was still worth closing while looking: `telemetry-cost`'s
  own PII-floor paragraph (written in `docs/decisions/040`'s original
  Phase D) never said to set `pii_masked: true` to match the floored
  tier, unlike the newer `ops`/`tracing` paragraphs added in the Third
  addendum, which do. Fixed for consistency, not proven to be the actual
  cause of this specific run's failure.

None of the pre-existing items above were investigated further this
pass — real, named, standing gaps, not attempted here.

## Decision

1. `skills/s4-tracing/SKILL.md`: `maps_to` now states the attribute may
   be `oah.tracing.propagation_risk` "or a `.`-suffixed variant of it",
   and gained the same Option B namespacing paragraph
   `telemetry-cost`/`dependency` already have, adapted to tracing's own
   single-attribute shape — explicit that splitting `name` alone is not
   enough, `maps_to.attribute` itself must be suffixed for the tier that
   genuinely differs.
2. `skills/s4-telemetry-cost/SKILL.md`: PII-floor paragraph now also says
   `pii_masked: true` must be set to match the floored tier, mirroring
   `ops`/`tracing`'s own wording.
3. `ops` was deliberately NOT given Option B namespacing guidance in
   this pass — its `maps_to` already varies across several concrete
   attribute names (`oah.ops.release_id`, `oah.ops.degradation_response`,
   etc.), and this run's real data shows no evidence of the same
   same-attribute-two-tiers collision actually happening for it. Adding
   it speculatively would be exactly the "defensive, not evidence-based"
   move this whole ADR family has consistently avoided.

## Verification

The tracing fix is verified **mechanically, not by a new live model
call** — a real budget/scope tradeoff, stated plainly rather than
overclaimed: the exact real fragment that triggered the conflict was
hand-patched (only `maps_to.attribute` suffixed to
`oah.tracing.propagation_risk.chat` on the direct-PII signal, matching
exactly what the new SKILL.md rule instructs) and re-run through the real
`build_event_schema` — conflict resolved, 26 attributes produced where it
previously raised. This proves the *mechanism* works, the same one
already proven twice for `telemetry-cost`/`dependency`; it does not
re-prove that a real model reliably *follows* the new prompt wording,
which would need another live call. Given three isolated/full real calls
already ran this session, a fourth was judged not worth the additional
cost for a narrow, pattern-identical prompt clarification.

Full non-Docker suite passing after these prose-only SKILL.md changes
(no new test surface — these are wording fixes, not new logic; the
`build_event_schema` mechanism itself already has direct-fragment
regression tests from `docs/decisions/040`).

## Consequences

- The `mf-analyzer-web` re-run's overall `oah readiness` verdict is still
  `remediate_before_release`, now for a shorter, more precisely named
  list: `every_surface_point_has_decision` and
  `latency_budget_declared_per_point` (both pre-existing, `ops`/`slo`/
  `dependency`), `pii_masked_above_tier` (telemetry-cost, one instance).
  The S7 event-schema conflict that motivated this entire investigation
  (`docs/decisions/039`) is fixed and does not recur once the tracing fix
  above is applied.
- `ops`'s and `slo`'s near-total lack of per-point coverage (1/375 and
  ~9/75) is the single largest real gap left, and — unlike everything
  fixed across `docs/decisions/039`–`042` — its root cause is still
  completely unknown: not attributable to any change made this session,
  not yet investigated at all. This is the natural next real question if
  S4 work continues, separate from and larger than any of the fixes in
  this ADR family so far.
