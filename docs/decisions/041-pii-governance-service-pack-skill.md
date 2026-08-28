# 041 — pii-governance gets its own service-pack skill; pack-driven lens dispatch fixed

Status: **landed** (2026-08-28), same-day follow-up to `docs/decisions/040`.

## Context

`docs/decisions/040`'s step-3 full 375-point re-run against `mf-analyzer-web`
left one failure unexplained: `pii-governance lens design failed,
continuing without it: model output failed schema validation: signals: []
should be non-empty`, on the service pack's own ~75-point
`http_server_route`/`declarative_route`/`db_query` batch. Step 1 of that
investigation had already ruled out "refuses on any kind mismatch" as the
general explanation (`ops` designed 8 sensible signals despite an
identical framing mismatch); `pii-governance`'s own failure was left open,
root cause unknown.

Investigating it for real (not guessed at) took three isolated Sonnet
calls, cheapest first, same discipline `docs/decisions/040` itself used:

1. **2-point probe, real `mf-analyzer-web` `declarative_route` points**:
   did NOT reproduce the empty-array failure. The model self-corrected —
   emitted a single honest `no_applicable_llm_generation_points_in_batch`
   signal explaining that neither point was an `llm_generation` call site,
   rather than fabricating governance for content that doesn't exist.
2. **75-point probe** (the actual failing batch size): did NOT reproduce
   empty signals either. Instead the model **hallucinated**: it invented
   that two arbitrary points (`sp-0294`, `sp-0295`, plain JSX `<Route>`
   elements in `App.tsx` with `workflow_hint: "app"`, not `"chat"`) were
   "raw chat completions captured under the app-shell mounted chat
   surface", grounding this in `context.yaml`'s unrelated `chat` workflow
   (`pii_presence: direct`) despite neither point's own `workflow_hint`
   resolving to it. The other 73 points were left completely uncovered.
3. **The original real run's own log** (`readiness_sonnet_v2.log`):
   confirms the actual failure was a third outcome again —
   `signals: []`, literally empty.

Three different outcomes (honest refusal, hallucinated partial coverage,
empty refusal) from the same task on different runs is the signature of a
model with **no coherent task to perform**, not a random glitch. The root
cause: `skills/s4-pii-governance/SKILL.md` is written entirely around
`llm_generation` semantics — "design the governance signals for whatever
[LLM] content is captured" — and has no valid referent when fed
`http_server_route`/`declarative_route`/`db_query` points, which capture
no LLM content at all.

This directly contradicts `domains/service/pack.json`'s own claim (phase
1, `docs/decisions/016`): "the three lenses reused UNCHANGED from genai
(tracing, ops, pii-governance) run against real service-domain points
with zero SKILL.md edits" — verified at the time by
`test_reused_lens_functions_run_for_real_against_service_points_no_skill_md_edit`,
whose LLM call was **mocked**, echoing back a hand-built valid fragment
regardless of what the real prompt said. That test could structurally
never have caught this: it proves the plumbing (schema loads, output
validates, gates pass), never that a real model has a coherent task. The
same gap this whole `docs/decisions/039`/`040` investigation kept finding
in different shapes — verify against a real model, not a mock, before
trusting a "reused unchanged" claim — applied here too, just not checked
before now.

`tracing` and `ops`, also `reused_from: "genai"` in the service pack,
don't have this problem: their tasks (execution-context propagation risk;
release/rollback/incident-routing) don't depend on "content captured at
this specific point kind" the way pii-governance's entire task
definition does. Confirmed, not assumed — `ops` succeeded for real on the
full 375-point run; `tracing` did too, modulo the separate, already-known
`sensitivity_tier_meets_pii_floor` under-classification gap
(`docs/decisions/040`'s own Third addendum).

## Decision

### 1. A new, genuinely-designed skill: `skills/s4-pii-governance-route`

Not a copy-edit of `skills/s4-pii-governance` — a distinct SKILL.md
designed for what PII governance actually means at
`http_server_route`/`declarative_route`/`db_query` points: masking,
role-scoped access, a retention matrix, and deletion-by-subject for the
**path parameters, query-string parameters, and request/response body
fields** a route causes to reach access logs or traces, and the **query
bind parameter values** a `db_query` causes to reach query logs or
traces — never "captured LLM content", which does not exist for these
point kinds. Same `oah.pii.*` attribute names as the genai variant (same
governance concepts, different referent data), same `lens:
"pii-governance"` output value (S7/S9 aggregate by lens name, not skill
directory; the two skills never run in the same target since a target
loads exactly one domain pack).

Two hard rules directly target the two real failure modes just observed:

- **Explicit anti-hallucination rule**: never describe a signal as
  governing "captured LLM content", a "chat completion", or any
  generation-lens vocabulary — grounded in the `sp-0294`/`sp-0295`
  fabrication above.
- **Explicit full-coverage rule**: "cover every point in the batch... a
  fragment that designs signals for a handful of points and leaves the
  rest uncovered fails S5's `every_surface_point_has_decision` gate" —
  grounded in the 75-point run only covering 2/75.
- **Workflow-linkage rule**: ground every workflow-derived judgment in
  the point's own `workflow_hint`, resolved by the same exact
  stripped/lowered match `find_workflow` uses; an unresolved
  `workflow_hint` (a placeholder like `"app"`, or one that doesn't match
  any declared workflow) never borrows another workflow's `pii_presence`
  — grounded directly in the `sp-0294`/`sp-0295` fabrication, which
  borrowed `chat`'s `pii_presence: direct` for points whose own
  `workflow_hint` was `"app"`, matching no declared workflow at all.

`domains/service/pack.json`'s `pii-governance` lens entry now points at
`"skill": "s4-pii-governance-route"` with no `reused_from` — it is no
longer reused unchanged, and per `schemas/domain_pack.schema.json`'s own
definition of that field ("a lens listed here must run against this
pack's points with no edit to its SKILL.md"), claiming it while shipping
a different skill would make the field's own claim false. The pack
manifest's own `description` field (a live, tooling-read string, not a
dated ADR narrative) is corrected in place rather than left stale.

### 2. A real dispatch bug found and fixed: `oah/cli.py`'s `_lens_fns_for_pack`

Giving the *same* `lens: "pii-governance"` name two different skills
across packs exposed a real, previously-invisible bug: `_lens_fns_for_pack`
derived which Python wrapper function to call from the **lens name**
(`getattr(lens_module, f"design_{entry['lens'].replace('-', '_')}")`),
never from the pack's own declared `lenses[].skill` field. Every lens's
skill name happened to already equal `"s4-" + lens_name` for every
existing entry in both packs, so this was invisible until now — the
`skill` field was documentation, not something dispatch actually read,
the exact same class of "single-instance abstraction" bug
`docs/decisions/016`'s own Finding 1 found for `target_kinds` filtering
one phase earlier.

Fixed by deriving the wrapper function name from the **skill** instead
(`entry["skill"].removeprefix("s4-").replace("-", "_")`) — for every
existing lens this resolves to the exact same function name as before
(`s4-tracing` → `design_tracing`, etc.), so genai's and the rest of
service's behavior is unchanged; only `pii-governance`'s two variants
(`s4-pii-governance` → `design_pii_governance`,
`s4-pii-governance-route` → `design_pii_governance_route`, the latter a
new wrapper added alongside the new skill) now resolve differently
depending on which pack is loaded. Deliberately still goes through the
named `design_<skill_suffix>` wrapper functions rather than calling
`design_lens()` directly — every existing lens-mocking test patches one
of these named attributes (`patch("oah.design.lens.design_tracing",
...)`), and an initial version of this fix that bypassed them via
`functools.partial(design_lens, skill)` broke that mocking seam for
every lens, not just pii-governance, caught before landing by running the
full suite.

## Verification

Real Sonnet calls against `skills/s4-pii-governance-route`, same real
`mf-analyzer-web` surface map, `context_v2.yaml`, and point set the
original bug and `docs/decisions/040`'s own investigation used:

- **2-point isolated call**: both points (`workflow_hint` `"source-code"`
  and `"portfolios bms"`, neither resolving to a declared workflow) get
  full 4-signal coverage each. The model explicitly reasons in
  `supports_decision` text that the `workflow_hint` "does not exactly
  stripped/lowered-match the declared 'portfolio' workflow, so
  pii_presence is treated as unknown here rather than borrowed" — the
  workflow-linkage rule holding under direct test. All 13 S5 gates pass.
- **75-point call, the exact batch size and content that produced the
  original failure**: first attempt hit `litellm.Timeout` at 600s (a
  real infrastructure limit for a ~300-signal structured-output
  response, not a logic failure); re-run with `timeout=1200` completed.
  Result: **300 signals, 75/75 points covered, zero missing, all 13 S5
  gates pass.** No empty array, no hallucinated content, full coverage —
  the same batch that previously produced three different failure modes
  across three separate runs now succeeds cleanly.

`tests/test_service_pack.py` updated: the "reused unchanged" set is now
`{"tracing", "ops"}`, not all three; a new
`test_pii_governance_route_lens_runs_for_real_against_service_points`
proves the plumbing (real SKILL.md/schema, mocked LLM call, gates pass)
for the new skill, with its own docstring stating plainly that the real
model-behavior claim above is verified out-of-band, not by this mocked
test — the same honesty gap this whole investigation started from is not
repeated in its own regression test. `tests/test_e12_service_pack_integration.py`'s
mock patch target updated from `design_pii_governance` to
`design_pii_governance_route`. 2 new tests, 762 passing overall (up from
760 at the start of `docs/decisions/040`'s own work).

## Consequences

- The last of the three named open gaps from `docs/decisions/040`'s
  Second addendum that had a findable root cause is now closed.
  `pii-governance`'s own coverage for the service pack is real for the
  first time — not a copy of a skill designed for a different kind of
  point entirely.
- The pack-driven lens dispatch bug is a real, if latent, correctness fix
  independent of pii-governance itself: any future lens needing a
  different skill per pack for the same lens name now works correctly,
  where before it silently could not.
- `test_reused_lens_functions_run_for_real_against_service_points_no_skill_md_edit`'s
  own name is now accurate only for `tracing`/`ops` — `pii-governance`
  moved out of it, not silently left claiming something no longer true.
- Real, named, not addressed here: `docs/decisions/040`'s remaining open
  item, journey-first S4 batching, is unrelated to this fix and still
  fully deferred.
