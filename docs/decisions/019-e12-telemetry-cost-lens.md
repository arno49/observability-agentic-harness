# 019 — E12 phase 4: the telemetry-cost lens

Status: landed. Advances E12 (`docs/decisions/011`).

## Context

`docs/decisions/011`'s own lens list names six for the service pack: three
reused unchanged (`tracing`, `ops`, `pii-governance`, landed in
`docs/decisions/016`), one adapted (`telemetry-cost`, from genai's `cost`
lens — "token accounting becomes cardinality, sampling and retention
accounting"), and two new (`slo`, `dependency`). This phase builds the
adapted one — the smallest of the three remaining, since "adapted" means
starting from `cost`'s own real structure (per-signal attribution,
thresholds with a named owner, budget-exhaustion hooks) rather than
inventing a lens shape from nothing the way `slo`/`dependency` still need.

## What was built

- `skills/s4-telemetry-cost/` (`SKILL.md` + `io/{input,output}.schema.json`),
  a new skill, not a copy of `s4-cost` with strings replaced. Reframes the
  same four-part structure (attribution → thresholds → headroom → hooks)
  around what actually drives an ordinary service's telemetry bill:
  - **Cardinality risk**, with a driver named from real S1 data already
    available: a route point's own `has_path_parameter` field
    (`docs/decisions/013`/`018`) directly informs the risk call, not a
    guess — a parameterized route is `high` unless the point already shows
    the receiver templates the segment.
  - **Sampling rate + rationale**, workflow-criticality-aware via
    `context.yaml` the same way `cost`'s thresholds are, but explicitly
    steering toward tail-based/error-biased sampling for high-cardinality
    error-relevant points rather than a flat rate that would systematically
    miss the failures that matter.
  - **Retention tiering**, a real axis `cost` never needed (LLM usage
    counts don't have a retention-cost tradeoff the way raw span/log
    volume does).
  - **Budget-exhaustion hooks**, structurally identical to `cost`'s own
    throttle-step requirement (S5's pause/freeze/throttle-needs-a-
    resumption-condition gate applies unchanged).
- Cross-cutting (`target_kinds: null`), unlike `cost` (`llm_generation`
  only) — cardinality/sampling/retention cost applies to any point kind
  that emits telemetry, not one SDK's call sites. `design_telemetry_cost`
  in `oah/design/lens.py` is a pure pass-through, matching every other
  lens's contract since `docs/decisions/016`'s own fix.
- `domains/service/pack.json`: new `telemetry-cost` lens entry, no
  `reused_from` (adapted, not reused — the one honest way this pack's own
  manifest already distinguishes the two).
- `tests/test_telemetry_cost_lens.py` (9 tests, mirroring
  `test_cost_lens.py`'s own structure) plus `tests/test_service_pack.py`
  extended: the real `design_telemetry_cost` function, real `SKILL.md`,
  real schema validation, real S5 gates, run end to end against real
  service-domain points alongside the three reused lenses.

## Decision

Scoped to exactly this one lens, not batched with `slo`/`dependency` —
those two are new, not adapted, and each needs real domain-content
research (`docs/decisions/011`'s own burn-rate derivation for `slo`, a
dependency-criticality/extra-nine rule for `dependency`) that doesn't
share a starting point with this phase's work the way `telemetry-cost`
shared one with `cost`. Landing them together would blur three
independently-reviewable pieces of domain judgment into one change.

**No new S5 gates in this phase.** `docs/decisions/011`'s own new-gate
list (burn-rate recomputation, alert-tier/window pairing, policy exit
criteria) is entirely `slo`-shaped; `telemetry-cost`'s signals satisfy the
existing ten domain-neutral gates unchanged (proven by the real
`run_gates` call in this phase's own tests), the same way `cost` always
did.

## Consequences

- Four of E12's six lenses are now real: three reused, one adapted. `slo`
  and `dependency` remain the two genuinely new ones, plus four more S1
  registries (`db_query`/`queue_*`/`scheduled_job`), `docs/decisions/011`'s
  own new S5 gates (now clearly `slo`/`dependency`-gated, not
  cross-cutting), S11 signal provenance, and a real corpus fixture
  (DoD (a)) — all still unbuilt.
- The `has_path_parameter`-driven cardinality-risk reasoning is the first
  real place a signal this pipeline designs is directly informed by an S1
  structural fact (not just point kind/file/line) — a pattern the future
  `slo`/`dependency` lenses can reuse for their own S1-derived inputs
  (e.g. a dependency edge's own call shape) rather than inventing a new
  one.
