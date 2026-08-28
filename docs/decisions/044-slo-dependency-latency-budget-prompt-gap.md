# 044 — `slo`/`dependency` never asked for `latency_overhead_budget_ms`

Status: **landed, NOT live-verified** (2026-08-28) — see Verification.
Same-day follow-up to `docs/decisions/042`/`043`, found while auditing
readiness before spending further API budget on another full real
`oah readiness` run against `mf-analyzer-web`.

## Context

`docs/decisions/042`'s real re-run confirmed `latency_budget_declared_per_point`
fails for `ops`, `slo`, and `dependency` alike, identically in both the v2
and v3 full-scale runs, and named the root cause "completely unknown" —
not investigated further at the time.

Direct inspection (no model call needed — a code/prompt-reading check,
free, the same kind of investigation `docs/decisions/041`/`043` already
used for their own root causes) found the cause is not one bug but two:

Commit `6e3c73a` ("Fix systemic S4 prompt gap: no SKILL.md ever asked for
`latency_overhead_budget_ms`", 2026-08-25) added the
instruction to all 9 lenses that existed *at that time*
(`generation-capture`, `pii-governance`, `cost`, `ops`, `retrieval`,
`feedback`, `realtime-multimodal`, `tracing`, `tools`). `slo` and
`dependency` were built two commits later that same day
(`docs/decisions/020`, `021`) and never received the equivalent
instruction — `skills/s4-slo/SKILL.md` and `skills/s4-dependency/SKILL.md`
never mention `latency_overhead_budget_ms` anywhere. This is a pure,
deterministic prompt gap: any model that follows either SKILL.md exactly
as written will omit the field on every real invocation, which is exactly
what both full-scale runs show.

`ops`'s own case is different and remains genuinely unexplained:
`skills/s4-ops/SKILL.md` *does* carry the instruction (added by the same
2026-08-25 commit) and the gate still failed at real full scale in both
v2 and v3. Not a prompt-completeness gap — something else, not
investigated in this pass.

## Decision

Added the same instruction sentence the other 9 lenses already carry —
"Also set `latency_overhead_budget_ms` on at least one signal per point —
S5 gates on it being declared per point, not per signal — a concrete
millisecond estimate for the overhead this lens's own capture adds to the
call path" — to `skills/s4-slo/SKILL.md` (into the existing "Every
`design_fragment` signal must satisfy S5's ordinary gates" sentence) and
`skills/s4-dependency/SKILL.md` (same location, before the existing
`context.yaml` PII-floor paragraph). Wording adapted to each lens's own
signal shape (SLO pointer/indicator capture; dependency edge-pointer
capture) rather than copied verbatim.

`grep -L "latency_overhead_budget_ms" skills/s4-*/SKILL.md` now returns
nothing — all 13 SKILL.md files (9 original + `pii-governance-route`,
`telemetry-cost`, `slo`, `dependency`) carry the instruction.

`ops`'s own unexplained full-scale failure was deliberately left alone —
its SKILL.md is already correct; guessing at a second fix without
evidence would be exactly the "defensive, not evidence-based" move this
ADR family has consistently avoided (`docs/decisions/042`'s own Decision
section states the same reasoning for not touching `ops`'s `maps_to`).

## Verification

**Not live-verified — a real, stated limitation, not a silent gap.**
This is a prose-only SKILL.md change; the full local suite (`pytest -q`,
762 tests) passes unchanged, which proves the edit didn't break anything
structural and nothing else regressed — it proves nothing about whether a
real model now reliably sets the field, the same caveat every prior
prompt-only fix in this ADR family (`039`–`043`) has carried until its
own live call. Deliberately not spending API budget on a live check
before this specific, cheaply-diagnosed gap was actually closed in code —
running the full 375/75-point live re-run before this fix would have
reconfirmed a failure that was already predictable for free.

The natural next step is the same one `docs/decisions/043` already
deferred: one full real `oah readiness` re-run against `mf-analyzer-web`
covering `ops`/`slo`'s coverage fix (`043`) and this fix together, rather
than another isolated small-batch probe — the isolated-batch pattern
already used twice this session for `ops`/`slo` risks under-testing the
same "id est correct at N=12, wrong at N=375" gap this whole ADR chain
keeps finding.

## Consequences

- `latency_budget_declared_per_point` should now hold for `slo` and
  `dependency` at real scale — a mechanism-level fix, not yet proven
  against real model output.
- `ops`'s own `latency_budget_declared_per_point` failure remains open,
  root cause unknown, not attempted here.
- Before this fix, any full-scale live re-run of `oah readiness` was
  certain to still return `remediate_before_release` on
  `latency_budget_declared_per_point` alone, regardless of whether
  `043`'s `ops`/`slo` coverage fix held at scale — spending API budget on
  such a run would have re-confirmed a known, freely-diagnosable gap
  rather than testing anything new.
