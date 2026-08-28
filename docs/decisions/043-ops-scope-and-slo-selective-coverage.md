# 043 — `ops`'s stale llm_generation framing and `slo`'s coverage-vs-gate mismatch

Status: **landed, NOT live-verified** (2026-08-28) — see Verification.
Same-day follow-up to `docs/decisions/042`.

## Context

`docs/decisions/042`'s real re-run left `ops` (1 of 375 points covered)
and `slo` (~9 of 75) as the single largest remaining named gap — real,
severe under-coverage, root cause explicitly unknown at the time.

Direct inspection of both skills' own SKILL.md files (no model call
needed — this is a code/prompt-reading investigation, free) found two
different, unrelated root causes:

**`ops`**: `skills/s4-ops/SKILL.md`'s frontmatter, opening paragraph,
`## Input`, and `## Task` sections all stated, verbatim, "Use for every
surface_map.json point of kind llm_generation" / "You design ... for
`llm_generation` surface points" / "For each `llm_generation` point,
design...". This was correct under the genai pack (`target_kinds:
["llm_generation"]`) but has been **false** under the service pack ever
since `docs/decisions/016` made `ops` cross-cutting there
(`target_kinds: null` — every point, any kind). This is the exact same
root-cause *class* `docs/decisions/041` found for `pii-governance` — a
skill's own prompt claiming a narrower scope than the pack that loads it
actually assigns — just a softer failure mode: `pii-governance`'s prompt
made "govern LLM content" the model's entire task, which had no valid
referent at all for route/query points and produced empty/hallucinated
output; `ops`'s four signal categories (release id, degradation
visibility, rollback target, incident owner) are properties of *any* call
site regardless of kind, so the model could still design something
sensible — it just silently under-applied itself to the ~1 point it
judged most obviously in-scope and left the rest uncovered, rather than
refusing outright. `tracing`'s own SKILL.md, by contrast, has always
correctly stated its cross-cutting scope ("your input batch is not
filtered to one surface_map kind") — which is exactly why `tracing`
achieves full coverage and `ops` didn't, despite both being
`reused_from: "genai"`.

**`slo`**: a genuinely different cause, not a copy of the above.
`skills/s4-slo/SKILL.md`'s own `## Input` section already correctly and
*deliberately* states: "a route belonging to a `p0`/`critical` workflow
gets [an SLO]; a route with no known-critical workflow is real service
surface, but SLO effort concentrates on the journeys that matter first,
not every route uniformly." This is intentional, documented selectivity
matching `docs/decisions/011`'s own architecture — not a bug in what the
model was told to do. The mismatch is structural: S5's
`every_surface_point_has_decision` gate (`oah/design/gates.py`) is
unconditional — `missing = surface_map_point_ids - covered_points`, no
per-lens exception — so a lens explicitly designed to skip most of its
batch will always fail this gate, regardless of whether skipping was the
right call. `docs/decisions/040`'s own "Bottom line" section had already
named a version of this ("`tracing`'s narrow-by-design scope vs. a
cross-cutting gate expecting full point coverage") without identifying
which lens or gate it actually meant; checked directly against real data,
`tracing` itself has no such conflict (it achieves full coverage by
grouping broadly) — the real instance is `slo`, not `tracing`.

## Decision

**`ops`**: `skills/s4-ops/SKILL.md` corrected throughout (frontmatter,
opening paragraph, `## Input`, `## Task`) to state the batch may be
`llm_generation`-only (genai) or cross-cutting/any-kind (service),
mirroring `tracing`'s own honest framing, and explicitly instructing
"design for every point in the batch, whatever kind it is" — with a
direct callout that none of the four signal categories are
LLM-generation-specific, so a non-`llm_generation` batch is not a signal
to cover fewer points.

**`slo`**: `skills/s4-slo/SKILL.md`'s `### 5. The design_fragment half`
section gained an explicit rule: every point in the batch needs a
`design_fragment` signal, *including* the ones that correctly don't get a
real SLO — an honest placeholder pointer signal (e.g.
`oah.slo.no_objective_designed`) naming why (not a known-critical
workflow), rather than silence. This preserves the lens's own real
architectural decision (concentrate SLO *effort* on `p0`/`critical`
journeys) while satisfying the gate's own honest-coverage requirement —
matching the same "explicit non-decision, not silence" pattern already
used elsewhere in this codebase (e.g. the isolated `pii-governance`
2-point probe from `docs/decisions/041`'s own investigation, which
self-corrected to an honest `no_applicable_llm_generation_points_in_batch`
signal rather than staying silent).

Deliberately not attempted: a gate-level exception for `slo` (e.g.
"skip `every_surface_point_has_decision` for this one lens") — that would
weaken a real, generally-correct invariant for every other lens to
accommodate one lens's own scope, the same "targeted, don't weaken the
general case" reasoning this whole ADR family has used throughout.

## Verification

**Not live-verified — a real, stated limitation, not a silent gap.**
Both fixes are grounded in a confirmed mechanism (`ops`'s prompt directly
contradicted the pack's own point-kind assignment; `slo`'s own SKILL.md
already explains its selectivity, and the gate's source directly confirms
zero exceptions) and follow patterns already proven twice this session
(`docs/decisions/041`'s "explicit non-decision" signal;
`docs/decisions/039`/`040`'s "correct the framing, verify with a real
call" sequence) — but the actual verification step, a live Sonnet call
against a mixed-kind batch for `ops` and a mixed-criticality batch for
`slo`, could not run: the Anthropic account's API credit balance was
exhausted mid-session (`litellm.BadRequestError: ... "Your credit balance
is too low to access the Anthropic API"`), a hard external stop, not a
cost-tradeoff choice. Local, non-API test suite (762 tests) still passes
after both changes — proves the prose edits didn't break anything
structural, proves nothing about whether a real model now covers every
point.

This is a real limitation to close as a first step whenever API access is
restored, before treating either fix as confirmed the way `docs/decisions/041`'s
and `042`'s fixes are.

## Consequences

- If both fixes hold under a real call, `ops` and `slo` stop being the
  largest named gap in this ADR family's own investigation, and
  `remediate_before_release` on `mf-analyzer-web` would very plausibly
  clear its two largest current blockers
  (`every_surface_point_has_decision`, most of
  `latency_budget_declared_per_point`) — not proven here, a real next
  step once credits are available.
- `pii_masked_above_tier` on `telemetry-cost` (one instance,
  `docs/decisions/042`) remains the one other named, unresolved item.
- The underlying pattern this ADR closes out (a genai-authored SKILL.md's
  prose silently assuming genai's own scope, even after `target_kinds`
  itself was made pack-driven) has now been found and fixed three times
  this session, in three different lenses (`pii-governance`, `ops`, and
  — differently shaped — `slo`). No fourth lens has been checked; not
  claimed clean, just not yet investigated.
