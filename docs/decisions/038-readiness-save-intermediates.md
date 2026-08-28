# 038 — `oah readiness` gains `--save-intermediates`

Status: landed. Closes a gap found while explaining a real
`remediate_before_release` verdict to a non-expert reader.

## Context

`docs/decisions/032`-`036`'s own pilot produced a real
`remediate_before_release` verdict on `mf-analyzer-web`'s 375 real
surface points, via `oah readiness --model ollama/gemma4:latest`. Asked to
explain it in plain language, the honest answer was: only an aggregate
was available — `readiness_report.json`'s own `recommendation.rationale`
names each failed gate and how many times it fired (`5×
every_surface_point_has_decision`, `3× no_phantom_surface_points`, ...),
but not *which* surface point, *which* lens's fragment, or the gate's own
real `reason` string (which names the actual offending point IDs —
`check_every_surface_point_has_decision`'s own code produces `f"{len(missing)}
surface point(s) have no design decision in this fragment: {missing}"`,
a real, specific, useful message that never reached the final report).

Root cause, found by reading `cmd_readiness` (`oah/cli.py`), not assumed:
it computes `fragments`, `gate_findings`, `panel_verdicts`, `event_schema`,
and `dtos` — the full S4-S8 output — entirely in local variables, passes
them into `build_readiness_report` for S9's own aggregate assembly, and
then lets every one of those local variables go out of scope when the
function returns. The detail was never persisted anywhere; `oah design
-o` already writes this same detail for its own scope (S4-S6 only), but
`oah readiness` runs the identical computation one layer further (through
S7/S8 too) and had no equivalent.

## What was built

`oah readiness` gained `--save-intermediates PATH`: when given, writes
`{design_fragments, gate_findings, panel_verdicts, event_schema, dtos}` —
exactly the data already computed inside `cmd_readiness`, zero additional
model calls — to that path, alongside the normal `readiness_report.json`
output. `fragments` (previously only ever assigned inside the `if
surface_map["points"]:` branch) is now pre-initialized to `[]` before that
branch, matching the existing pattern `gate_findings`/`panel_verdicts`/
`event_schema`/`dtos` already used, so the flag is safe on a 0-point run
too.

## Decision

**Opt-in, not automatic.** The full intermediate payload is large (every
lens's every signal, every gate finding, every persona's every finding) —
writing it unconditionally would bloat every `oah readiness` invocation's
own output for a detail most callers don't need. A flag matches
`oah map`'s own `--no-disambiguate`/`-o` precedent: available, not
default.

**No new schema.** This is a diagnostic/debugging artifact assembled from
already-independently-validated pieces (`design_fragment`, `gate finding`,
`panel_verdict` schemas each already apply during S4-S6), not a new
first-class OAH artifact type — defining a fifth schema for the bag that
holds them would be real, unjustified ceremony for what's fundamentally a
dump of existing local variables.

## Consequences

- A `remediate_before_release` (or any other) verdict can now be
  explained down to the specific surface point and the specific gate
  `reason` string that triggered it, not just a gate name and a count.
- Real cost: the file can be large on a real-scale run (375 points, 9
  lenses) — not compressed or paginated, a real, minor, named limitation,
  not addressed here.
- `oah design`'s own `-o` output remains the only source of S4-S6 detail
  for a `design`-only invocation; this flag is `readiness`-specific,
  matching where the gap was actually found.
