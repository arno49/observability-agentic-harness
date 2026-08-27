# SP12 — Two TS detector shapes the Python adapter doesn't have

Status: resolved. Blocks E12 (see ROADMAP.md). Timebox: 1 wk (used: same-day).

## Context

The first real E12 candidate consumer (`docs/decisions/011`, §12) is a
React/TypeScript SPA where the four business journeys **are** its routes —
but `spikes/sp10-multilang/ts-adapter/detect.js` (SP10's TS prototype) only
has one detector shape: a resolved receiver whose call's last-N
attribute-chain segments match a declared suffix
(`client.messages.create(...)`), the direct TS analogue of the Python
adapter's `receiver_method_suffix`. Two shapes the candidate's stack
actually needs were missing entirely: **declarative registration** (SPA
routes as JSX `<Route>` elements or a route-object array — neither a method
call on a tracked receiver nor a decorator) and a **global unimported
callee** (`fetch(...)` has no import to anchor on; the adapter's whole
resolution model is import-anchored). Per SP12's own ROADMAP row, output is
a decision record + TS prototype + corpus fixture, measured against E2's
recall/FP bar — this is that check.

This is a spike (prototype + evidence), not production integration:
`spikes/sp10-multilang/ts-adapter/` stays a spike; nothing here ships into
`oah/` (that's E11-TS's job, informed by this spike, same relationship
SP10 already has to E11).

## Findings

1. **Both shapes are detectable at 100% recall, 0 false positives, on a
   real corpus.** `detect.js` gained two new passes over the same
   `ts.SourceFile` AST it already builds (not a rewrite), plus a `shape`
   field on every candidate. Scored via `eval.py` (extended to break recall
   down per shape, not just one pooled number) against all four TS corpus
   repos — SP10's original three (`transcribee`, `llm-document-ocr`,
   `wechatbot`) plus one new fixture sourced for this spike
   (`cocktail-app`, added to `ground_truth/corpus_manifest.json`): **14/14
   ground-truth sites found, 0 missed, 0 false positives**, broken down as
   `receiver_method_suffix` 4/4, `declarative_registration` 2/2,
   `global_unimported_callee` 8/8.
2. **The route-object-array syntax (`createBrowserRouter([{path: ...}])`)
   is prototype-verified only, not corpus-verified.** Real GitHub search
   (six candidate repos evaluated, four rejected for license/language/
   library reasons — see the research agent's own rejection list) turned
   up `Majkan1/Cocktail-App` (MIT, React Router v7, 3 real source files) as
   the one fixture meeting every requirement (permissive license,
   TypeScript, real global `fetch`, small enough to hand-verify
   exhaustively) — but it uses only the JSX `<Route>` form, not
   `createBrowserRouter`. The route-object-array pass is exercised by a
   hand-written smoke-test snippet (correct there, including a dynamic
   `/property/:id` entry) but has no real-repo evidence behind it. Named
   here rather than silently claimed as corpus-proven — E11-TS should
   source a second, `createBrowserRouter`-using fixture before treating
   that specific form as verified at the same evidentiary bar as the rest.
3. **A path parameter lives inside the string literal itself, not as a
   separate JS expression — this session's own first design draft got it
   wrong.** The original plan assumed a "dynamic/templated path" would show
   up as a non-literal JS expression (e.g. a template-literal interpolation
   or a variable), with a plain string literal always meaning "fully
   static." React Router's real syntax puts the parameter marker (`:id`,
   or `*` for a catch-all) *inside* an otherwise perfectly ordinary string
   literal (`"/property/:id"`) — caught immediately by this spike's own
   first smoke test, before the real corpus fixture was even sourced.
   Fixed by adding a separate `has_path_parameter` field (checked by
   pattern-matching the literal's text for `:name` or `*`), kept distinct
   from `confidence` — conflating the two would have silently misreported
   every parameterized route as fully static, exactly the
   `route_is_templated`/`cardinality_guard` distinction
   `docs/decisions/011` already named as consequential.
4. **File-wide shadow-suppression is the wrong default for a negative
   gate, even though this adapter already uses file-wide tracking
   elsewhere.** The first draft of the `fetch`-shadowing check suppressed
   *every* global-fetch candidate in a file if *any* function in that file
   had a parameter named `fetch` — caught by this spike's own smoke test
   (a synthetic `wrappedFetch(fetch: typeof window.fetch)` utility
   correctly suppressed its own internal call, but incorrectly suppressed
   an unrelated, genuinely-global `fetch()` call elsewhere in the same
   file). File-wide tracking is a deliberate, accepted simplification for
   Pass 1/2's *positive* receiver resolution (it strictly increases recall,
   at some precision cost, and is documented as such in `detect.js`'s own
   comments) — but the same simplification applied to a *negative*
   exclusion gate strictly decreases recall instead, which is the wrong
   direction. Fixed with a real (if intentionally partial) scope walk via
   `.parent` (available because `createSourceFile` already passes
   `setParentNodes: true`): only a `fetch` binding in an *enclosing*
   function/block actually shadows a given call site; only the module-level
   import case stays file-wide, since an import genuinely does apply to
   the whole file.
5. **The ground-truth landmine `docs/decisions/011` already named for a
   different registry hit here too, immediately, on real data.** Running
   the new `global_unimported_callee` pass against `wechatbot` (one of
   SP10's original three fixtures, whose ground truth was built only for
   SDK-call detection) surfaced 6 "false positives" that were, on
   inspection, 6 real, genuine, unshadowed `fetch()` calls
   (`src/api.ts:51`, `src/auth.ts:65,76`, `src/cdn.ts:50,61,111`) the
   original ground truth simply never recorded because it wasn't scoped to
   test for this shape. Extended `wechatbot.json` in this same change, per
   `docs/decisions/011`'s own stated precedent ("ground truth for every
   existing fixture must be extended in the same commit as the first [new]
   registry, not after") — not left to surface as a false positive in a
   later, unrelated change.

## Options considered

- **A — ship the two new passes without a real corpus fixture**, relying
  on the hand-written smoke test alone. Rejected: this project's own
  standing discipline (SP1's real 3-repo corpus, SP10's real two-language
  corpus) treats "prototype-verified" and "corpus-verified" as different,
  non-substitutable claims; a smoke test proves the code runs, not that it
  generalizes to real-world code shape variation the way finding 3 and 4
  (both caught only by the smoke test, before real code was even involved)
  already shows real code can differ from a first design assumption.
- **B — synthesize a fixture instead of sourcing one**, to avoid the real
  cost of GitHub search + license/quality vetting. Rejected for the same
  reason: SP1/SP10's corpus policy is "not vendored, clone and pin a real
  commit," specifically so recall/FP numbers mean something about real
  code, not about code shaped to make the detector look good.
- **C — source one real fixture covering both syntactic forms of
  declarative registration**, timebox the search, and name explicitly
  which form ends up prototype-only if a single fixture can't cover both.
  Chosen — six real candidates were actually evaluated (not a token
  search), and the one that met every requirement (license, language, real
  global `fetch`, hand-verifiable size) happens to use only the JSX form;
  reported as a real, stated gap (finding 2) rather than glossed over.

## Decision

Option C.

- **E11-TS's real TS adapter** (when built) should carry forward: the
  `shape` field on every candidate (already how the domain pack manifest's
  `registries[].detector_shape` enum is structured — E13 already has slots
  for `receiver_method_suffix` and `structural_pattern`; this spike adds
  real evidence for two more: `declarative_registration` needs a slot with
  a `path`-attribute-name field, `global_unimported_callee` needs a
  callee-name field, plus the `has_path_parameter` distinction as its own
  data point, not folded into `confidence`); the scope-aware (not file-wide)
  shadow check for negative-gate patterns generally, not just `fetch`; and
  a second, `createBrowserRouter`-using fixture sourced before E12 treats
  the route-object-array form as corpus-verified at the same bar as the
  JSX form.
- **`schemas/domain_pack.schema.json`'s `registries[].detector_shape` enum**
  gains `declarative_registration` and `global_unimported_callee` in this
  same change (purely additive, no existing pack uses either, E13's
  byte-identical guarantee holds) — both now corpus-verified TS shapes,
  distinct from `decorator_registration` (still unimplemented and
  unevidenced; SP12 corrected the earlier assumption that it was the
  web-framework gap that mattered most). The schema doesn't yet define a
  `content_signal`-analogous data shape for the JSX-attribute-name /
  route-object-array-callee-name pair each new value needs — that's
  E11-TS's job, once a real Python-or-TS adapter actually consumes these
  values (E13's own `structural_pattern` + `content_signal` precedent is
  the shape to follow).
- **No change to `oah/`** — explicitly out of scope for a spike; this
  decision record and the working prototype under `spikes/` are E11-TS's
  starting evidence, not a partial implementation to build on top of
  in-place.

## Consequences

- E12 gains real, corpus-verified evidence for two of its three needed
  detector shapes (the third, `structural_pattern`, already exists from
  E13's Python-side extraction); `route_is_templated`/`cardinality_guard`
  gate design can rely on `has_path_parameter` as a real, checkable signal
  rather than an assumption.
- E12's DoD clause (c) — "registry families with structurally different
  detector shapes are proven, not several of the same shape" — is now
  backed by real evidence for the JSX declarative-registration form and
  the global-callee form; the route-object-array form is a named, open gap
  until a second fixture covers it.
- `ground_truth/wechatbot.json` grew by 6 real sites in this change,
  matching `docs/decisions/011`'s own precedent for exactly this failure
  mode — the corpus's own ground truth is now current for both shapes
  `wechatbot` actually exercises, not just the one SP10 originally tested.
- **Revisit trigger** (not a recurring spike): source the
  `createBrowserRouter`-using fixture (finding 2) before E12 relies on
  that specific form; re-run this spike's own smoke-test discipline (write
  a synthetic edge case before trusting a new pass) for any further
  detector-shape additions, since two of five real findings here came from
  exactly that step, before any real corpus code was even touched.
