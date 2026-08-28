# 046 — Full 375/75-point live re-run confirms `043`/`044`; finds `ops`'s own self-inflicted S7 conflict

Status: **landed, mechanically verified** (2026-08-28). Same-day
follow-up to `docs/decisions/044`/`045`.

## Context

`docs/decisions/044`'s `slo`/`dependency` prompt fix and `045`'s
diagnosis of `ops`'s latency-budget failure and `telemetry-cost`'s
`pii_masked_above_tier` failure were both explicit that a real live
re-run at the original full 375-point/75-point scale — the scale that
first surfaced every failure in this ADR chain — was the one item
neither could substitute for. With explicit user go-ahead and a real
`ANTHROPIC_API_KEY`, that re-run was made: `oah readiness` against the
real `mf-analyzer-web` target, `--context context_v2.yaml --language
typescript --pack service --save-intermediates`.

## What the run found

**All three pending items from `044`/`045` confirmed, for real, at full
scale:**

- `every_surface_point_has_decision` passes on all 6 lens fragments
  (`tracing`, `ops`, `pii-governance`, `telemetry-cost`, `slo`,
  `dependency`) — `043`'s `ops`/`slo` coverage fix holds at the 375/75
  scale that originally produced 1/375 and ~9/75.
- `latency_budget_declared_per_point` passes on all 6 fragments —
  `044`'s `slo`/`dependency` prompt fix holds at scale, and `045`'s
  diagnosis (that `ops`'s own instance was a downstream consequence of
  the coverage bug, not a separate cause) is confirmed: with coverage
  fixed, the latency-budget gate has nothing left to fail on.
- `pii_masked_above_tier` passes on all 6 fragments — `045`'s diagnosis
  (the `telemetry-cost` reminder added in `042` targets exactly this
  failure shape) is confirmed. `evidence_position.confirmed` in the
  resulting readiness report states plainly: "S5 deterministic invariant
  gates pass on the current design."

**A new regression, same class as `042`, now with real evidence where
`042` had none:** `build_event_schema` failed again —
`oah.ops.release_id` designed at `sensitivity_tier='confidential'` by one
group of `ops` signals and `'internal'` by another. Inspecting the real
fragment: with `043`'s coverage fix landed, `ops` now actually covers
all four of the target's workflows (`chat`, `sql analysis`, `portfolio`,
and ungrouped `other`) instead of the 1-point sliver it produced before —
and correctly floors the direct-PII `chat` journey's signals to
`confidential` per `docs/decisions/040`'s PII floor, while the other
three journeys correctly stay `internal`. But all four signals in *each*
of `ops`'s four categories (`release_id`, `degradation_response`,
`rollback_target`, `incident_owner`) shared one unsuffixed
`maps_to.attribute` — checked directly: **all four categories carry the
same `{confidential, internal}` tier split**, not just `release_id`;
`build_event_schema` only ever reported the first one it reached.

`docs/decisions/042`'s own Decision section explicitly declined to give
`ops` this same Option B namespacing guidance at the time, reasoning
"this run's real data shows no evidence of the same same-attribute-two-
tiers collision actually happening for it. Adding it speculatively would
be exactly the 'defensive, not evidence-based' move this whole ADR family
has consistently avoided." That reasoning was correct given the evidence
available then — `ops` covered 1 point, so no cross-journey tier
variance could exist yet to collide. Fixing the coverage bug is exactly
what created the conditions for the collision to become real.

## Decision

`skills/s4-ops/SKILL.md` gained the same Option B namespacing paragraph
`tracing`/`telemetry-cost`/`dependency` already have, covering all four
of this lens's own attribute categories (not just `release_id`, since
all four share the same tier-variance shape): when a batch spans
journeys whose real `sensitivity_tier` differs, namespace the varying
attribute per journey (e.g. `oah.ops.release_id.chat`) instead of
sharing the unsuffixed name.

## Verification

**Verified mechanically, not by a sixth live model call** — the same
budget/scope tradeoff `042` made for `tracing`'s own fix, for the same
reason: this is a narrow, pattern-identical prompt clarification, and a
live call has already just run at real cost. The real `ops` fragment from
this run's own `intermediates_sonnet_v5.json` was hand-patched exactly
per the new rule (all four `chat`-journey, `confidential`-tier signals'
`maps_to.attribute` suffixed with `.chat`) and re-run through the real
`build_event_schema`: conflict resolved, 35 attributes produced where it
previously raised on the first one. 762 tests passing (prose-only
SKILL.md change).

## Consequences

- The `mf-analyzer-web` readiness verdict is still `remediate_before_release`,
  but for a genuinely different, non-S5 reason now: S9's dark-gap check
  (`oah/design/readiness_report.py`) reports 265 unaddressed p0/p1 `dark`
  gap_model entries — points S2's telemetry inventory found with zero
  existing instrumentation. This is **not a bug and not in scope for this
  ADR chain**: `dark` status comes entirely from S1-S3's deterministic
  discovery of the target's *actual, current* telemetry, independent of
  anything S4 designs; the check exists precisely so a clean S4/S5/S6
  design can't be mistaken for a release-ready product when the
  underlying code still has zero real telemetry at critical points. This
  is M3's own still-open DoD (`oah instrument` actually applied to a real
  target, `ROADMAP.md`), not a new finding.
- With the `ops` fix above landed, a seventh full-scale live re-run would
  be the next available confirmation step — not attempted here, same
  cost-proportionality reasoning as every prior "mechanical verification
  now, live re-confirmation later if warranted" step in this chain
  (`042`, `044`).
- This closes the loop `docs/decisions/039` opened: every S5 gate and
  every S7 event-schema conflict found across `039`-`046`'s real runs
  against `mf-analyzer-web` is now either fixed-and-confirmed-at-scale or
  fixed-and-mechanically-verified. The remaining `remediate_before_release`
  verdict reflects real, expected, out-of-scope work (S10 instrumentation
  not yet applied), not a design defect.
