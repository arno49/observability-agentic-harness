# 045 — `ops`'s "unexplained" latency-budget failure closed; `telemetry-cost`'s `pii_masked_above_tier` diagnosed

Status: **landed, diagnosis only — no code change** (2026-08-28). Same-day
follow-up to `docs/decisions/044`, done as free data analysis on the
already-saved `intermediates_sonnet_v3.json` before spending any further
API budget.

## `ops`'s `latency_budget_declared_per_point` failure: not a separate bug

`docs/decisions/042` named this "root cause completely unknown" and
`docs/decisions/044` treated it as a distinct, still-open mystery separate
from `slo`/`dependency`'s prompt gap (`ops`'s SKILL.md already carries the
`latency_overhead_budget_ms` instruction, so a missing-instruction
explanation didn't fit).

Direct inspection of `intermediates_sonnet_v3.json`'s `ops` design
fragment shows why: it contains exactly 4 signals, **all four scoped to
the single point `sp-0018`** — the fragment covers 1 of 375 points, not
374 with a latency gap and one without. Extracting the two gate findings'
own point-ID lists and diffing them confirms this exactly:
`every_surface_point_has_decision`'s 374 missing points and
`latency_budget_declared_per_point`'s 374 missing points are the **same
set, identically** (`ids13 == ids20` → `True`, empty symmetric
difference). A point with no `ops` signal at all obviously has no
`latency_overhead_budget_ms` declared on any signal either — the
instruction being present in the prompt is irrelevant to a point the
model never produced any signal for in the first place.

This is not a second bug: it is a direct, deterministic downstream
consequence of the exact coverage bug `docs/decisions/043` already found
and fixed (`ops`'s stale `llm_generation`-only framing). No code change
needed here. Whether it actually clears once `043`'s fix is exercised at
real full scale is exactly the still-open question `docs/decisions/043`
itself named as not yet re-run — this closes the "second unexplained
cause" concern, it does not substitute for that live re-run.

## `telemetry-cost`'s `pii_masked_above_tier` failure: diagnosis matches the already-landed fix

`docs/decisions/042`'s own text was deliberately hedged: the
`pii_masked: true`-reminder fix "was NOT proven to be the actual cause of
this specific run's failure," added "for consistency" alongside the
`tracing` fix in the same commit.

Direct inspection of the three failing signals named in
`intermediates_sonnet_v3.json`'s `gate_findings`
(`chat_client_call_sampling_rate_0_05_head_plus_tail_error_biased`,
`chat_client_call_sampling_rationale`, `chat_client_call_retention_rationale`)
shows all three share the exact shape the fix targets: each is
`sensitivity_tier: "confidential"` with no `pii_masked` key at all (not
`false` — entirely absent). That is precisely the gap
`skills/s4-telemetry-cost/SKILL.md`'s new reminder (landed in `06f4134`,
*after* this v3 run was generated) closes — "set `pii_masked: true` to
match the floored tier," mirroring the wording `ops`/`tracing` already
had before this run.

This raises confidence well past "plausible" — the failure isn't just
consistent with the fix in general terms, it matches the fix's exact
target shape on all three instances, with no other candidate explanation
visible in the fragment. It is still not proof: a prose reminder doesn't
guarantee a live model's compliance, the same caveat every prompt-only
fix in this ADR family carries until its own live call
(`docs/decisions/039`–`044`). No further code change made here.

## Consequences

- Of the three items this ADR was asked to close, two are resolved by
  data analysis alone, with no code change required (both already
  covered by fixes landed in `docs/decisions/042`/`043`):
  - `ops`'s latency-budget failure — explained, not a separate bug.
  - `telemetry-cost`'s `pii_masked_above_tier` failure — diagnosis now
    matches the already-landed fix's exact target shape.
- The third — confirming `043`'s `ops`/`slo` coverage fix (and
  `044`'s `slo`/`dependency` latency-budget fix) at the real full
  375-point/75-point scale — has no free substitute. Isolated batches
  (`12`-point `ops`, `6`-point `slo`) already proved the mechanism;
  only a real full-scale live run proves it holds at the scale that
  originally failed. Not attempted in this pass — requires a live
  `ANTHROPIC_API_KEY`-backed `oah readiness` run against the real
  target (`mf-analyzer-web`), real API spend, and explicit user
  go-ahead before running, consistent with every prior live run this
  session.
