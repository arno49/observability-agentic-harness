# 017 — E12 phase 2: the anti-redundancy gate

Status: landed. Advances E12 (`docs/decisions/011`, DoD (d)).

## Context

`docs/decisions/011`'s Finding 2 is the service pack's whole reason for
being narrower than the GenAI pack: HTTP semantic conventions are Stable
and zero-code auto-instrumentation already emits route, duration and
`error.type` signals with no source edit. A service pack that generated
DTOs wrapping HTTP handlers to re-emit those same signals would be
worse-and-later duplicating something that already exists for free. E12's
own DoD (d) names the enforcement mechanism directly: "every generated DTO
is checked against `auto_instrumentation_baseline` and one that only
re-emits an already-covered attribute is refused." `domains/service/pack.json`
(`docs/decisions/016`) already declares the baseline; nothing read it.

## What was built

- `oah/design/dto_generator.py`: `_baseline_covered_attributes(pack)` (a
  flat set of attribute names from the pack's own
  `auto_instrumentation_baseline.covered_signals`) and
  `_is_redundant_with_baseline(dto, baseline_attributes)` (true when every
  `expected_events[].required_attributes` entry across a DTO's *entire*
  event list is already in that set — a DTO with no attribute claim at all
  is never refused on that basis, and a DTO that adds even one genuinely
  new attribute alongside a covered one survives). `generate_dtos` now
  partitions the model's proposed DTOs into kept and refused before
  rollout-step assignment, so a refused DTO never gets a rollout step at
  all.
- `schemas/implementation_dto.schema.json`: new, additive `refused_dtos`
  array (`id`, `gap_id`, `reason: "redundant_with_auto_instrumentation"`),
  absent entirely (not an empty array) when a pack declares no baseline.
- `tests/test_service_pack.py`: a DTO whose only attribute is `http.route`
  is refused against the real service pack; a DTO adding a genuine
  `oah.*` attribute alongside `http.route` survives; the genai pack (no
  declared baseline) never refuses anything, by construction, confirmed
  directly against `_baseline_covered_attributes`.

## Decision

The check runs once, in `generate_dtos`, after schema validation and
before rollout-step assignment — not as a separate S5 gate. `auto_instrumentation_baseline`
is DTO-shaped data (attribute-level, not signal-level: a `design_fragment`'s
`signals[].maps_to.attribute` is the same namespace S8's DTOs reference
through `expected_events[].required_attributes`), and S5's gates run
*before* S8 exists at all — the redundancy question ("does this concrete
DTO duplicate something free") only has an answer once a DTO is proposed,
not at the signal-design stage a gate would check.

**Deliberately conservative, matching this project's `has_commercial_apm`/
`declared_undetected` honesty precedent**: a DTO is refused only when
*every* attribute it claims is baseline-covered — partial overlap survives
whole, not attribute-by-attribute pruned, since S8's own schema has no
concept of "partially generate this DTO." A future refinement could strip
just the redundant attribute from a DTO's `required_attributes` rather
than refusing the whole DTO; not attempted here, since no real DTO
generation against this pack has surfaced that shape yet, and building it
speculatively would be exactly the kind of unevidenced guess this project's
own registries/gates discipline refuses elsewhere.

## Consequences

- E12's DoD (d) is now real: verified against the actual pack, the actual
  DTO schema, and `generate_dtos`'s real code path — not just declared
  data.
- Zero behavior change for every existing caller: `_baseline_covered_attributes`
  returns an empty set for any pack that declares no baseline (every pack
  before the service pack), so the partition step is a no-op and
  `refused_dtos` never appears.
- E12's remaining shape is unchanged by this phase: `telemetry-cost`/`slo`/
  `dependency`, five new S1 registries, `docs/decisions/011`'s own new S5
  gates, S11 signal provenance, and a real corpus fixture (DoD (a)) are
  still fully unbuilt.
