# 039 — Generalized per-signal health thresholds (`health_thresholds`)

Status: **designed, not yet built**. Decomposed into phases below;
none landed yet.

## Context

The real Sonnet `readiness` run against `mf-analyzer-web` (375 real
surface points, `docs/decisions/032`-`038`'s own pilot) produced a real
`remediate_before_release` verdict whose rationale, read closely, surfaced
two distinct problems, not one:

1. `ops` lens design failed outright (`signals: [] should be non-empty`)
   — a clean schema rejection, not a reliability concern.
2. S7's event-schema merge failed:
   `attribute 'oah.telemetry_cost.cardinality_risk' designed at
   sensitivity_tier='confidential' by ['telemetry-cost'] but
   tier='internal' by lens='telemetry-cost'`. Read against the actual
   per-journey design fragments (`--save-intermediates`,
   `docs/decisions/038`), the model's own two assignments were each
   individually correct: the `chat` journey handles real PII and the
   others don't, so a single flat attribute name legitimately deserves two
   different tiers depending on which journey emitted it. `build_event_schema`
   (`oah/design/event_schema.py`) enforces one global tier per attribute
   name — a real, deliberate invariant (S7 "raised as a real error, not
   merged by picking one arbitrarily") — so a content-correct per-journey
   judgment call reads as a lens contradicting itself. The earlier draft
   of the published pilot report used exactly that "lens contradicted
   itself" framing; it overstates a schema-merge limitation as a model
   reliability problem and should be corrected wherever this report
   language still appears.

Discussing fixes for (2) surfaced a separate, standing gap named while
reading `schemas/design_fragment.schema.json`'s signal object end to end:
every field a signal can carry (`sensitivity_tier`, `pii_masked`,
`supports_decision`, `acting_role`, `latency_overhead_budget_ms`,
`cardinality_guard`) describes what the signal *is*. None describe what a
*healthy value looks like* — whether the number or state this signal
carries at runtime is fine, degraded, or actionable. The one place that
concept exists at all is `slo_spec.alert_tiers` (`schemas/slo_spec.schema.json`),
and it's confined to the `slo` lens's own separate artifact, not available
to any other lens's signals.

The user asked, in these words, to generalize that concept: "распространить
что-то вроде SLO-tiers на КАЖДЫЙ сигнал в любом lens'е" (spread something
like SLO-tiers onto every signal in any lens) — this ADR is that design,
reached after discussing and rejecting a literal copy of SLO's own shape
(see Options).

## Options considered

**A. Auto-resolve S7 tier conflicts to the more restrictive tier.**
Mechanical, ships fastest, fixes symptom (2) alone. Rejected as the sole
fix: it silently discards the real information that a per-journey split
carries (a reader never learns `chat` is the confidential one), which is
exactly the "picked one arbitrarily" outcome `build_event_schema`'s own
docstring already refuses to do for `sensitivity_tier`.

**B. SKILL.md prompt nudge toward namespaced attribute names when
sensitivity varies by point group** (e.g. `oah.telemetry_cost.cardinality_risk.chat`
vs. `...default`). Real, cheap, and still useful independent of anything
else in this ADR — recommended as a near-term complement, not a
replacement, since it only helps `sensitivity_tier`-style conflicts, not
the missing health-threshold concept.

**C. Copy `slo_spec.alert_tiers`'s exact shape onto every signal.**
Rejected on inspection: `alert_tiers` is a specific mathematical model —
multi-window error-budget burn rate — that presumes a ratio-based
indicator with a `target`/`period_days` objective. Most signals in other
lenses aren't that shape at all: `cardinality_risk` is categorical
(`high`/`medium`/`low`), a PII-masking flag is binary compliant/
non-compliant, a `tool_call` dispatch-site signal may have no runtime
"value" to threshold at all. Forcing `budget_fraction`/`burn_rate_multiplier`
onto a categorical signal would be uninterpretable, not just unused.

**D. Extract the common pattern (chosen).** SLO's `alert_tiers` and a
generic health classification share one real idea — a named severity
state, a trigger condition, and a stated reason — without sharing SLO's
own burn-rate math. Factor that shared idea into a new, smaller, optional
field any signal may carry; leave `slo_spec.alert_tiers` exactly as it is,
since ratio-based SLI burn-rate accounting is a real, more rigorous model
that only fits a real subset of signals.

## Decision

### 1. New optional signal field: `health_thresholds`

`schemas/design_fragment.schema.json`, signal object, alongside
`cardinality_guard` (same "optional, only when a lens has something real
to say" precedent):

```json
"health_thresholds": {
  "type": "array",
  "minItems": 1,
  "maxItems": 3,
  "description": "Optional. Only for signals that represent a genuinely measurable, classifiable runtime condition -- a latency, an error rate, a cardinality category, a compliance state. A signal with no meaningful 'healthy vs. not' reading (e.g. a tool-dispatch marker) should omit this field entirely, not fill it in with placeholder states.",
  "items": {
    "type": "object",
    "required": ["state", "condition", "basis", "rationale"],
    "additionalProperties": false,
    "properties": {
      "state": { "enum": ["green", "amber", "red"] },
      "condition": {
        "type": "string",
        "description": "The actual trigger, numeric or categorical -- e.g. 'p99_latency_ms > 500' or 'cardinality_risk == high'. Free text, not a formula language -- same precedent as slo_spec's own short_window_rationale (docs/decisions/011 Finding 3: no safe generic derivation exists, state the real reason instead of inventing a syntax to half-enforce it)."
      },
      "basis": {
        "enum": ["confirmed", "assumed"],
        "description": "Reuses readiness_report.schema.json's own evidence_position vocabulary rather than inventing a second one. A signal designed at S4 has no live run to draw on by pipeline construction (S10/S11 haven't happened yet) -- 'confirmed' is real vocabulary reserved for a future recalibration mechanism, not built by this ADR (see Deferred). No gate currently blocks a lens from mistakenly asserting 'confirmed' at S4 time -- a named, deliberate gap, not a silent one (see Consequences)."
      },
      "rationale": { "type": "string" }
    }
  }
}
```

No `additionalProperties` widening elsewhere; the SLO lens's own
`alert_tiers` shape is untouched.

### 2. New S5 gate: `check_health_thresholds_well_formed`

`oah/design/gates.py`, joining the domain-neutral `ALL_GATES` list
(same precedent as `check_route_is_templated`, `docs/decisions/026`) —
fragment-only, no `surface_map_point_ids`/`pack` argument needed:

- No two entries in one signal's `health_thresholds` share a `state`
  (ambiguous — which one wins at runtime).
- If `health_thresholds` is present at all, exactly one entry must have
  `state: "red"` — mirrors `check_decision_menu_resumption_paired`'s
  "a declared mechanism must be complete" precedent: a threshold set that
  never names the unhealthy state is not a threshold, it's decoration.
  `amber`/`green` remain optional — a binary compliance signal may
  legitimately declare only `red` (non-compliant) with no meaningful
  middle state.
- Every entry's `condition` and `rationale` pass the same `_non_trivial`
  check every other free-text field in this module already uses.

**Structural validity is deterministic; the threshold values themselves
are not** — same division of labor SLO's own gates already draw:
`slo_gates.py`'s `check_burn_rate_matches_declared_inputs` verifies the
*math* is internally consistent, never whether `0.999` was the *right*
target. This gate verifies a threshold set is *well-formed*, never
whether `500ms` is actually where `p99_latency_ms` should turn red — that
judgment stays the lens's.

### 3. SKILL.md rollout — targeted, not blanket

Only lenses whose signals are plausibly metric-shaped gain instructions
to consider `health_thresholds`: `slo` (non-`alert_tiers` signals it
already emits), `telemetry-cost` (`cardinality_risk` is the exact signal
that motivated this ADR), `ops`, `dependency` (edge latency/error rate —
`docs/decisions/011`'s own "extra-nine rule" language already implies a
threshold concept that has never had a field to land in). `tracing`,
`pii-governance`, and the genai-pack lenses whose signals are mostly
presence/absence or structural are told explicitly to omit the field
unless a genuine metric-shaped signal appears — matching this ADR's own
"only when real, not filled in as decoration" framing, not a mechanical
rollout to all nine-plus lenses at once.

### 4. S9 surfacing

`oah/design/readiness_report.py` rolls up any signal carrying
`health_thresholds` the same way it already rolls up gate findings —
visible in the assembled report, `basis: "assumed"` flagged with the same
"estimated, not measured" honesty treatment `evidence_position` already
gets, not buried in `--save-intermediates`-only output.

## Deferred (named, not silently dropped)

- **A post-S11 recalibration mechanism** that could someday promote a
  threshold's `basis` from `assumed` to `confirmed` against real captured
  data — not designed here. `basis: "confirmed"` exists in the enum today
  purely so the field doesn't need a breaking schema change when that
  mechanism is eventually built.
- **A gate blocking a lens from asserting `basis: "confirmed"` at S4
  time** (when it is, by pipeline construction, never true) — a real,
  buildable, small addition, deliberately left out of this phase's scope
  rather than added speculatively before any lens has actually been
  observed doing this.
- **S7 merge policy when two lenses design the same `maps_to.attribute`
  with *different* `health_thresholds`.** `sensitivity_tier` mismatches
  hard-fail today (S7's own stated invariant); whether a threshold
  mismatch deserves the same treatment, or is legitimately advisory and
  allowed to differ per lens, is an open judgment call — not decided by
  this ADR.
- **Option B** (namespaced attribute names for genuinely per-journey
  `sensitivity_tier` splits) — a real, independent, smaller fix for the
  original S7 conflict this ADR was prompted by investigating; not
  implemented here, still worth its own small phase.
- **Journey-first S4 batching** (grouping S1 points by `workflow_hint`/
  `context.yaml` workflow before calling lenses, and deriving
  `sensitivity_tier` deterministically from `context.yaml.pii_presence`
  per workflow instead of leaving it to free LLM judgment) — discussed in
  the same architecture conversation as this ADR, structurally related
  (it would reduce how often the S7 conflict this ADR responds to even
  arises), but a separate, larger, not-yet-agreed proposal. Tracked
  separately, not folded into this ADR's scope.

## Consequences

- Every signal in every lens/pack now has a real, optional place to
  declare what "unhealthy" looks like — the concept `slo_spec.alert_tiers`
  pioneered stops being SLO-exclusive, without forcing burn-rate math onto
  signals that were never ratio-based to begin with.
- `slo_spec.alert_tiers` itself is untouched — no migration, no dual
  vocabulary collision; a reader who already understands SLO tiers reads
  `health_thresholds` as "the same idea, generalized," not a competing
  concept.
- Real, honestly-scoped gap: nothing in this design (or its Phase A/B
  slice) stops a lens from asserting `basis: "confirmed"` when nothing has
  actually been measured — deferred deliberately rather than guessed at.
- Does not fix the original `mf-analyzer-web` S7 `sensitivity_tier`
  conflict by itself — Option B or A would; this ADR treats the
  `health_thresholds` gap as a separate, structurally related finding from
  the same investigation, not a fix for the same bug.
