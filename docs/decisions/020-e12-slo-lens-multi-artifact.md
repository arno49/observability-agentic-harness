# 020 — E12 phase 5: the slo lens and multi-artifact lens support

Status: landed. Advances E12 (`docs/decisions/011`).

## Context

E13's own decision record named this exact deferral: "`lenses[].emits`
ships in the manifest (forward-looking, for E12's slo lens) but
`oah/design/lens.py`'s `design_lens()` still returns a bare
`design_fragment` — extending its return contract to `{artifact_type:
parsed}` was scoped out as unnecessary risk with zero current consumer;
E12 does that when the slo lens actually needs a second artifact type."
`docs/decisions/011`'s own Finding 1 explains why a second artifact type
is unavoidable here: "An SLO specification is not expressible as a list of
event attributes: an indicator, a target, a window, alert tiers and a
budget policy are a different shape." This phase is where that deferred
work actually happens, driven by the first lens that genuinely needs it.

## What was built

- **Multi-artifact plumbing, added without touching `design_lens()`
  itself.** `design_lens()` already just validates the model's response
  against whatever `io/output.schema.json` the skill declares and returns
  it as-is — it never assumed a bare `design_fragment` shape in the first
  place, so no change was needed there. The real gap was in
  `oah/cli.py`'s `_design_all_lenses`, which assumed every lens's result
  IS a `design_fragment` directly. It now checks the loaded pack's own
  `lenses[].emits` for each lens (`_emits_for_pack`, new): a lens with
  exactly one emit type is handled exactly as before; a lens with more
  than one returns `{artifact_type: value}`, and `_design_all_lenses`
  unpacks `design_fragment` into the existing `fragments` list (so S5's
  `run_gates`/S7's `build_event_schema` need no change) while collecting
  every other key into a new `extra_artifacts` return value.
  `_design_all_lenses`'s signature changes from returning `fragments` to
  `(fragments, extra_artifacts)` — a real, mechanical change to all four
  call sites (`cmd_design`/`cmd_event_schema`/`cmd_dtos`/`cmd_readiness`),
  each verified to still pass its own existing tests unchanged.
- **`schemas/slo_spec.schema.json`** (new): indicator (name,
  good-event-definition, aggregation method — with no enum value that
  spells out averaging multiple precomputed percentiles, a real, common
  statistical error), objective (target, period, up-predicate,
  granularity, brownout classification — target constrained
  `exclusiveMaximum: 1`, so a 1.0 target is a schema violation, not just a
  gate finding), alert tiers (budget fraction, detection window, a
  required paired short window, required `short_window_rationale` prose,
  and a computed `burn_rate_multiplier`), and an error-budget policy
  (steps, each with an entry-criterion tier reference and a required exit
  criterion).
- **`oah/design/slo_gates.py`** (new, deliberately separate from
  `oah/design/gates.py`): seven gates, matching `docs/decisions/011`'s own
  new-gate list for this lens exactly — burn-rate recomputation (the real
  formula, verified against the ADR's own worked table: `budget_fraction ×
  (period_days × 24) ÷ detection_window_hours`), paired short-window
  validity + non-trivial rationale, policy-step exit criteria, policy
  entry-criterion tier references (no dangling references), objective
  completeness, target-not-1.0, and indicator aggregation-method validity.
  Reuses `gates.py`'s own `Finding` dataclass — same machine-readable
  contract, not a parallel one; `gates_passed()` already works generically
  across both gate sets' `Finding` lists.
- **`skills/s4-slo/`** (new): `SKILL.md` teaches the burn-rate formula
  with the ADR's own worked example reproduced exactly (2%/1h→14.4,
  5%/6h→6, 10%/1d→3, 10%/3d→1 at a 30-day period), and is explicit that no
  formula is supplied for the short-window ratio itself — the ADR's own
  finding that this specific ratio has no derivation in any reviewed
  source, so the skill requires stated rationale instead of a copied
  constant. `io/output.schema.json` is a wrapper object
  (`{design_fragment, slo_spec}`, both required) — the one skill in this
  project whose output isn't a bare `design_fragment`.
- `oah/design/lens.py`: `design_slo`, documented as the one lens whose
  return value isn't a bare fragment.
- `domains/service/pack.json`: `slo` lens entry, `target_kinds:
  ["http_server_route", "declarative_route"]` (an SLO covers a critical
  business journey, and the journeys are the routes — `docs/decisions/011`),
  `emits: ["design_fragment", "slo_spec"]`, no `reused_from` (new, not
  reused or adapted).
- Real tests: `tests/test_slo_gates.py` (11, including the ADR's own
  worked table recomputed and gate-verified for all four rows),
  `tests/test_slo_lens.py` (6, the real `design_slo` function against real
  `SKILL.md`, both halves separately schema-validated and gate-checked),
  `tests/test_service_pack.py` extended for the real `_design_all_lenses`
  unpacking behavior against the real 5-lens pack.

## Decision

**`slo_spec` is not consumed by S7/S8/S9 in this phase.** `cmd_design`
surfaces it under a new `extra_artifacts` output key — the one place a
human/reviewer sees it — but `build_event_schema`/`generate_dtos`/
`build_readiness_report` remain entirely unaware `slo_spec` exists.
architecture.md's own `rollout_plan.md`/`runbook.md` generation (where an
SLO's error-budget policy would naturally feed a runbook's escalation
steps) isn't built yet regardless, so there is no real consumer to wire
this into today; wiring it in ahead of that would be speculative.

**`route_is_templated`/`cardinality_guard`/`critical_dependency_extra_nine`
are NOT part of this phase**, despite appearing in `docs/decisions/011`'s
same gate list. The first is arguably `telemetry-cost`'s territory (it
already reasons about `has_path_parameter`); the second is squarely the
still-unbuilt `dependency` lens's own gate. Batching them in here would
blur three independently-scoped pieces of domain judgment into one
change, the same reasoning that kept `telemetry-cost` and `slo` in
separate phases.

## Consequences

- Five of E12's six lenses are now real: three reused, one adapted, one
  new. Only `dependency` remains — the last lens, needing its own new
  domain content (edge criticality, the extra-nine rule, budget split
  between own and dependency failures) and, per the paragraph above, the
  two gates this phase deliberately left for it.
- The multi-artifact plumbing is real, general infrastructure, not
  slo-specific — any future lens needing a second artifact type (the
  `dependency` lens's own `dependency_model`, already a valid `emits`
  enum value per `schemas/domain_pack.schema.json`) inherits this
  mechanism for free.
- Still unbuilt: the `dependency` lens, four more S1 registries
  (`db_query`/`queue_*`/`scheduled_job`), the two gates named above, S11
  signal provenance, and a real corpus fixture (DoD (a)).
