# 034 — TypeScript gets `workflow_hint`, and `oah interview` surfaces it

Status: landed. Closes a gap named while assessing E12 phase 10/S2
(`docs/decisions/032`/`033`'s own retrospective).

## Context

Running `oah gaps --context context.yaml` against a real TypeScript target
repo (the same `mf-analyzer-web` pilot `docs/decisions/032`/`033` used, a
real EPAM app) produced NO change in priority at all, despite a real,
carefully-built `context.yaml` from a completed `oah interview` naming
seven real workflows with real criticality/PII answers. Root cause, found
by checking, not assumed: `workflow_hint` — the field `gap_model.py`'s
`_find_workflow` matches against a `context.yaml` workflow name to weight
priority — is populated **only** by S1's LLM disambiguation pass
(`skills/s1-surface-mapper/SKILL.md` step 4, wired into
`python_adapter.py:584`). The TypeScript adapter has never had an
LLM-disambiguation counterpart (E11-TS's own stated scope boundary,
`docs/decisions/014`), so `workflow_hint` was never set on a single
TypeScript surface point — `oah gaps --context` has been a **structural
no-op for every TS/JS target**, not a bug in any one interview's answers.

A second, independent finding surfaced while fixing the first: even with
`workflow_hint` populated, `_find_workflow` requires an **exact**
(stripped/lowercased) string match against a `context.yaml` workflow
name — and `cmd_interview`/`run_interview` never showed the interviewee
what hints existed anywhere, for *either* language. The owner has always
been typing workflow names blind, with no way to know what string would
actually connect to anything. This is a real, independent gap, not
specific to TypeScript.

## What was built

**Deterministic `workflow_hint` for TypeScript**
(`oah/discovery/typescript_adapter.py`, `_infer_workflow_hint`): this
adapter has no LLM to make a judgment call the way Python's disambiguation
skill does, but that skill's own stated source signal — "best-effort
product workflow name inferred from module/route/symbol names" — is
exactly what's statically available here too, no model call needed. A
route's own static path segments win when present (e.g.
`/portfolios/:id/sql-analysis` → `"portfolios sql-analysis"`, dynamic
`:param` segments dropped); otherwise the defining file's own module name,
camelCase-split with a common suffix (`Service`/`Api`/`Client`/
`Controller`/`Store`/`Repository`) stripped (e.g. `portfolioService.ts` →
`"portfolio"`, `sqlMetadataService.ts` → `"sql metadata"`). Wired into all
four point-emission sites in `_walk` (registry-driven receiver points, the
route-object-array pass, the JSX `<Route>` pass, and the bare-`fetch()`
pass) — every TypeScript point now carries a `workflow_hint`, verified on
the real target repo: 375/375.

**`oah interview` surfaces S1's own hints before asking for workflow
names** (`oah/interview.py`, `oah/cli.py`): `run_interview`/
`_run_interview_body` gained an optional `surface_map` parameter
(default `None` — byte-identical to every prior caller); when given, a new
`_workflow_hint_counts` helper prints the distinct `workflow_hint` values
found, most-frequent first, with point counts, before the "how many
workflows" question — e.g. `'sql analysis' (57 points)`,
`'portfolio' (47 points)`. `oah interview` gained a `--surface-map` flag
(an already-built `surface_map.json`, e.g. from `oah map -o`) that loads
and forwards it. This closes the loop for *either* language, not just
TypeScript — Python's LLM-produced hints were exactly as invisible to the
interviewee before this.

## Verified end to end

Ran the real pipeline against the motivating repo: `oah map` (workflow_hint
now on all 375 points) → `oah interview --surface-map surface_map.json`
(hint banner shown; three workflows named to match three of the printed
hints EXACTLY: `sql analysis`, `portfolio`, `chat`) → `oah gaps --context`:

- Before this phase: 0 of 375 points ever matched a workflow; priority was
  always the coverage-only baseline (p1/p2 split 265/110).
- After: **118 of 375 points matched** (57 `sql analysis`, 47 `portfolio`,
  14 `chat`) and were re-weighted by real interviewed criticality — 12
  points bumped all the way to `p0` (dark coverage on a `high`-criticality
  workflow with `direct` PII present, e.g. a chat-service call site with
  no OTel/logger evidence nearby).

## Decision

**Fix both halves, not just the one named.** Populating `workflow_hint`
for TypeScript alone would have left the mechanism still silently
disconnected in practice — a heuristic string guess is unlikely to
exactly match whatever free-text name an interviewee independently types,
which is exactly what happened on the first real run: TypeScript's own
computed hints (`"portfolio"`, `"chat"`, `"sql metadata"`) did NOT match
the workflow names picked before this phase's `oah interview` change
existed to show them. Surfacing the hints is what makes exact-match
matching actually usable, without touching `_find_workflow`'s matching
semantics at all — no fuzzy-matching risk introduced, no regression risk
to `tests/test_gap_model.py`'s existing precision-guard tests (an
unrelated hint must still NOT match, unchanged).

**Did not build a TypeScript LLM-disambiguation pass.** That would also
close this gap, but is separately-scoped, much larger work (a real
`skills/s1-surface-mapper`-equivalent skill invocation for TS), and this
repo's own real numbers show the deterministic heuristic already reaches
100% hint coverage (375/375) with zero model cost — good enough evidence
to not justify the larger build right now.

## Consequences

- `oah gaps --context` is now real for TypeScript targets, not a silent
  no-op — the single most consequential fix of this phase, since it was
  previously invisible (no error, no warning; priority just quietly never
  changed).
- The hint-surfacing mechanism benefits Python too, for free — a real,
  independent bug (owner never saw LLM-produced hints) fixed as a side
  effect of investigating the TypeScript-specific one.
- Real, named limitation carried forward: a route's-own-path-segments hint
  and a module-name hint can still collide or feel arbitrary on an
  unfamiliar codebase (e.g. `"portfolios packages"` from a nested route) —
  the interviewee is expected to skim the printed list and pick sensible
  names, not to trust every hint as self-evidently correct.
- `_find_workflow` itself is unchanged — still exact string match after
  strip/lower, on purpose (see Decision).
