# 040 — Deterministic PII sensitivity-tier floor + namespaced attributes (Option B)

Status: **landed** (2026-08-28), same-day follow-up to `docs/decisions/039`.

## Context

Discussing `docs/decisions/039`'s own "journey-first S4 batching" proposal
found it was actually two independent ideas bundled under one name:

1. **Batching mechanism** — partitioning S4's LLM calls by journey instead
   of one flat batch per lens. A real, separate, larger question (cost —
   more calls; a new attribute-naming-consistency risk across batches;
   orphan-point handling) with no evidence yet that today's flat batches
   are actually causing quality problems at scale. Left as an open,
   not-yet-agreed proposal, not touched here.
2. **Deterministic `sensitivity_tier` from `context.yaml`'s `pii_presence`**
   — the piece that actually targets the original S7 conflict this whole
   investigation started from (`docs/decisions/039`'s own Context section:
   `oah.telemetry_cost.cardinality_risk` assigned `confidential` for the
   real-PII `chat` journey and `internal` elsewhere).

Working through (2), a further correction surfaced: a **floor** on
`sensitivity_tier` (never let a signal go below some minimum for a
direct-PII workflow) does not by itself prevent the original conflict.
A floor only stops under-classification; it does nothing to stop the
*same* attribute name from legitimately landing at two different
floor-compliant tiers across two different journeys — which is exactly
how the original conflict happened. Closing that requires a second,
independent mechanism: teaching the affected lens to give each journey's
variant a distinct attribute name when the tier genuinely differs
(**Option B**, already named and deferred in `docs/decisions/039`'s own
Deferred section).

Decision, made by explicit user choice after this correction was raised:
build both together, since neither alone completes the picture.

## Decision

### 1. `find_workflow` made public

`oah/discovery/gap_model.py`'s `_find_workflow(workflow_hint, context)`
(exact stripped/lowered match against `context.yaml`'s workflow names)
renamed to `find_workflow` — the identical lookup S5's new gate needs, not
a second implementation of the same match rule. Its one internal call
site updated; comments in `oah/interview.py`, `oah/discovery/typescript_adapter.py`,
and `tests/test_interview.py` updated to the new name. Historical ADRs
(`docs/decisions/034`) and `ROADMAP.md`'s own dated narrative entries were
left referencing the old name deliberately — they are a record of what
was true when written, not live documentation.

### 2. `check_sensitivity_tier_meets_pii_floor` (S5 gate)

`oah/design/gates.py`: a workflow `context.yaml` records as
`pii_presence: "direct"` gets a deterministic floor of `confidential` on
every signal covering one of its points. Mirrors the exact asymmetry
`gap_model.py`'s own gap-priority weighting already uses — only `"direct"`
triggers special deterministic treatment; `"indirect"`/`"none"` leave the
model's own judgment completely unconstrained, deliberately, since those
categories are lower-confidence and a blanket floor there would more
often overclassify a genuinely non-PII signal than catch a real gap.

A **floor, not an assignment**: the gate checks `tier >= floor`, never
sets the tier itself — a lens can still choose `restricted` if it judges
that's warranted. No-op when `context` is `None` (no interview has run)
or a signal's covered points don't resolve to a known workflow — same
degrade-gracefully precedent every other context-optional gate already
follows.

New gate inputs: `point_workflow_hints` (a `{point_id: workflow_hint}`
map) and `context`, both threaded through `run_gates()`'s new keyword
arguments and both of `oah/cli.py`'s call sites (`cmd_design`,
`cmd_readiness`), built once per command from `surface_map["points"]`.

**Explicitly does not prevent the original S7 collision by itself** — see
Option B below, which is the mechanism that actually does.

### 3. Option B: namespaced attribute names (SKILL.md guidance)

`skills/s4-telemetry-cost/SKILL.md` — the lens where the real conflict
was observed — gained explicit instruction: if the same
`oah.telemetry_cost.*` attribute name would otherwise cover two
journeys' points at genuinely different tiers, give each journey's
variant a distinct, workflow-suffixed name (e.g.
`oah.telemetry_cost.cardinality_risk.chat`) instead of one shared name at
disagreeing tiers. No schema change needed — `maps_to.attribute` was
already an unconstrained string using dot-separated namespacing by
convention. Explicitly scoped to *only* split the name when the tier
genuinely differs for a real reason, not defensively.

Rollout scope: `telemetry-cost` only, the lens with real, confirmed
evidence of this problem — matching this whole ADR-family's own "targeted,
not blanket" precedent (`docs/decisions/039`'s own Phase B rollout used
the identical reasoning). `ops`, `slo`, `dependency`, and the genai-pack
lenses are not touched; if this pattern is later observed there too, that
is real, separate evidence to act on, not guessed at now.

## Verification

Real Sonnet call against the same 2 real `mf-analyzer-web` points used to
verify `docs/decisions/039` Phase B, this time with a constructed
`context.yaml` giving each point's own workflow a different `pii_presence`
(`"ai prompt context"`: `direct`; `"ai prompts"`: `none`) — checked both
mechanisms together in one call, first attempt, no bug found this time:

- `sp-0001` (the direct-PII `"ai prompt context"` workflow):
  `oah.telemetry_cost.cardinality_risk.ai_prompt_context` at
  `sensitivity_tier: confidential` — floor met, and the model namespaced
  the attribute on its own initiative, per the new SKILL.md guidance.
- `sp-0002` (the `"none"`-PII `"ai prompts"` workflow):
  `oah.telemetry_cost.cardinality_risk` (unsuffixed) at
  `sensitivity_tier: internal`.
- `check_sensitivity_tier_meets_pii_floor` on the resulting fragment:
  `passed=True`.

The two signals now carry genuinely different attribute names
(`....cardinality_risk.ai_prompt_context` vs `....cardinality_risk`) —
exactly the split that would have prevented `docs/decisions/039`'s own
original motivating S7 conflict had it existed at the time.

## Consequences

- A direct-PII workflow's signals can no longer be silently
  under-classified below `confidential` — a real, deterministic
  compliance floor that didn't exist before, closing a gap
  `docs/decisions/039`'s own Deferred section named but didn't build.
- The original class of S7 conflict (same attribute name, two
  floor-compliant but disagreeing tiers) is now addressed for
  `telemetry-cost` specifically, via prompt guidance rather than a
  structural guarantee — this remains probabilistic, not gate-enforced;
  there is no deterministic way to *require* correct namespacing without
  re-deriving the same judgment call the namespacing decision itself is.
- Real, named, not addressed here: the batching-mechanism half of the
  original proposal remains a distinct, larger, not-yet-agreed question.

## Addendum (2026-08-28, same day) — `dependency` had the identical bug, found for real

Preparing for a full-scale readiness re-verification, the pilot run's
already-collected `--save-intermediates` output
(`docs/decisions/038`) was analyzed (plain code, no new model calls):
grouping every captured fragment's signals by `maps_to.attribute` and
checking whether each attribute's covered points spanned journeys with
disagreeing `sensitivity_tier`. Result: `telemetry-cost` had it on all
six of its own attributes (confirming the fix above was necessary, not
overbuilt); `dependency`'s `oah.dependency.edge_name` had the identical
pattern (`direct`-PII `chat` journey at `confidential`, an `indirect`-PII
journey at `internal`, same shared name); `tracing`'s
`oah.tracing.propagation_risk` spans both PII levels but never actually
disagrees on tier (no real risk); `pii-governance`/`slo` showed no
cross-journey signal in this run's own data at all.

`dependency`'s own conflict never surfaced in the original run's S7
error — `build_event_schema` raises on the *first* conflict it finds and
`telemetry-cost` came first in fragment order, silently masking this
second, identical bug.

`skills/s4-dependency/SKILL.md` gained the same Option B guidance
`telemetry-cost` already has, scoped to its one real pointer signal
(`oah.dependency.edge_name`). `pii-governance` and `slo` were left
untouched — no evidence from real data that they need it, matching this
whole ADR-family's "targeted, not blanket, evidence before building"
precedent.

## Second addendum (2026-08-28, same day) — step 3: full 375-point re-run

Per the 1→2→3 diagnostic plan agreed with the user (1: isolated `ops`
probe; 2: free analysis of already-collected data; 3: full real
`oah readiness` re-run against `mf-analyzer-web`, same target/pack/context
as the original pilot), step 3 ran to completion. Findings, sorted by
what they mean:

**A real regression in this same ADR's own Phase D, found and fixed.**
`build_event_schema` raised a false-positive `EventSchemaConflictError`
that blocked S7 (and therefore S8) for the entire run: three
`telemetry-cost` signals legitimately shared one unnamespaced attribute
(`sensitivity_tier` genuinely agreed across them, so Option B correctly
did not split the name) but had different `health_thresholds[].rationale`
text — free prose grounded in each signal's own distinct points
(`"portfolio CRUD calls..."` vs `"57 axios call sites..."`), never meant
to be byte-identical. The Phase D equality check compared the raw
threshold list, rationale included. Fixed: `_health_thresholds_signature`
now compares only `(state, condition, basis)` per tier, ignoring
`rationale`; `basis` disagreement (`assumed` vs `confirmed`) still raises,
since that's a real factual claim, not prose. Verified against the
actual real fragments that triggered the bug: `build_event_schema` now
succeeds (21 attributes) where it previously raised. 2 new regression
tests.

**The `sensitivity_tier_meets_pii_floor` gate worked exactly as
designed** — caught real under-classification in `tracing` (one signal)
and `ops` (four signals) covering the `chat` direct-PII journey, still at
`internal`. Both lenses never received the SKILL.md floor reminder
(only `telemetry-cost`/`ops`'s Option B guidance was added, and — checked
now — `ops` never actually got the PII-floor *reminder* paragraph, only
`telemetry-cost` did). This is the gate doing its real job (blocking a
genuine gap), not a false positive — but means more lenses will keep
failing this gate on real direct-PII data until they get the same
reminder text, a real, named follow-up not done here.

**A new `pii_masked_above_tier` failure, directly attributable to this
ADR's own floor mechanism**: `dependency`'s `oah.dependency.edge_name`
correctly reached `confidential` for the direct-PII `chat` edge (the
floor working) but omitted `pii_masked: true` (a separate, pre-existing
S5 gate). Fixed same day: `skills/s4-dependency/SKILL.md` gained a
reminder to set `pii_masked: true` whenever the floor pushes tier to
confidential/restricted.

**Two `consistency_assertions_referential_integrity` failures — checked
and confirmed pre-existing, not caused by tonight's work.** The exact
same failure mode (a fragment's `consistency_assertions[].fields_involved`
naming `maps_to.attribute` values instead of real `signal.name` values)
already existed in the original pre-`docs/decisions/039` pilot run
(`telemetry-cost`'s own assertion failed identically then). Not
investigated further here — a real, standing S4 gap, named, not fixed in
this pass.

**`pii-governance` still fails with `signals: [] should be non-empty`**,
the same failure class `ops` had in the original run. An isolated 2-point
probe (step 1) found `ops` does **not** actually refuse on a kind
mismatch — it designed 8 sensible signals despite its SKILL.md's
`llm_generation`-only framing. `ops` itself succeeded on this real 375-point
run. `pii-governance`'s own failure (a much smaller ~75-point batch) is
therefore not simply a batch-size story either — root cause still
unknown, not investigated further this pass.

**Bottom line**: the original motivating problem (the S7 cross-journey
tier collision) is fixed and holds at real scale — `build_event_schema`
succeeds end to end on the full real run once the Phase D regression
above is fixed. The overall `oah readiness` verdict is still
`remediate_before_release` — for different, mostly pre-existing or
narrower reasons than the original run, not the original conflict. S4 is
not "fully ready" — several real, named, mostly pre-existing gaps remain
(`pii-governance`'s empty-signals bug, the assertion-naming pattern, the
floor reminder not yet in every lens, `tracing`'s narrow-by-design scope
vs. a cross-cutting gate expecting full point coverage).
