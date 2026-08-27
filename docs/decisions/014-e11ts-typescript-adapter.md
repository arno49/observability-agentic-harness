# 014 — E11-TS phase 1: a real, tree-sitter-based TypeScript adapter for S1

Status: landed. Unblocks part of E12 (service domain pack, `docs/decisions/011`).

## Context

E12 is hard-blocked on "E11's TypeScript half": the first real candidate
consumer (a React/TypeScript SPA) has no Python anywhere in its stack.
SP10 (`docs/decisions/004`) already answered the architecture question — the
three-phase shape (import resolution, known-binding prescan, suffix-match
call walk) generalizes across languages — and, critically, already decided
the parser choice: `spikes/sp10-multilang/ts-adapter/detect.js` (the
TypeScript-compiler-API/Node.js prototype) is explicitly "evidence and a
comparison baseline, not a component to carry into E2" — SP10 hit a real
operational cost (a Node.js runtime dependency whose own `typescript` npm
package broke its documented API across a major version with no warning)
and recommended `tree-sitter-typescript` instead: a pure-Python dependency,
no second language runtime.

This phase is therefore not a port of `detect.js`'s code — it's a fresh
implementation of the same validated three-phase shape, plus SP12's two
additional detector shapes (`docs/decisions/013`), against a different
parser, mirroring `oah/discovery/python_adapter.py`'s own architecture the
way that module already mirrors SP1's Python spike.

## What was built

- `oah/discovery/typescript_adapter.py` (new): `ImportResolver`
  (default/named/aliased imports), a **file-wide** known-binding prescan
  (not class-scoped — SP10 finding 3: TS/JS closures and hoisting make
  narrower scoping unreliable in a way Python's don't), a member-chain
  flattener, and three detector passes: receiver/method-suffix call sites,
  declarative route registration (JSX `<Route>`, `createBrowserRouter`-style
  route-object arrays), and a global unimported callee (bare `fetch(...)`,
  scope-aware shadow suppression via a real `node.parent` walk). Same
  public API shape as `python_adapter.py` (`detect_file`/`detect_repo`/
  `build_surface_map`).
- `schemas/domain_pack.schema.json`: `registries[]` gains an optional
  `language` field (`python`/`typescript`, default `python` for backward
  compat — purely additive, E13's byte-identical guarantee holds).
- `domains/genai/pack.json`: existing four registries get explicit
  `"language": "python"`; one new entry, Anthropic's TS SDK
  (`@anthropic-ai/sdk`, same `method_suffixes` as the Python entry — the
  suffix pattern is SDK-shape, not language-shape).
- `oah/discovery/registry.py`: `build_registry_index`/
  `structural_pattern_registries` gain a `language` parameter (default
  `"python"`), filtering pack entries before deriving lookup structures.

## Findings

1. **The tree-sitter reimplementation reaches exactly the same recall
   SP10+SP12 measured with the Node/compiler-API prototype: 14/14 (100%),
   0 false positives, across all 4 real corpus repos and all 3 detector
   shapes.** Verified directly (not assumed) by cloning and pinning all
   four repos (`transcribee`, `llm-document-ocr`, `wechatbot`,
   `cocktail-app` — the same commits `docs/decisions/004`/`013` pin) and
   running this module's own `detect_repo()` against each: `transcribee`
   1/1, `llm-document-ocr` 2/2, `wechatbot` 7/7 (1 `llm_generation` + the 6
   `http_client_call` sites SP12 already added to its ground truth),
   `cocktail-app` 4/4 (2 `declarative_route` + 2 `http_client_call`,
   including both `has_path_parameter: true` results — the `:pageId`
   dynamic segment and the `*` wildcard). Byte-identical file/line output
   to `detect.js`'s own real-corpus results.
2. **The grammar exploration this phase started with (verify before
   building, same discipline as every Docker/git spike this project has
   used) caught what would otherwise have been two real implementation
   bugs, before any test existed.** `jsx_attribute` is the one node type
   checked whose `child_by_field_name` returns `None` for both name and
   value — every other node type explored (imports, variable declarators,
   call/member expressions, class fields, function parameters) exposes
   real named fields. Discovered by direct probing against
   `tree_sitter_typescript`, not assumed from the JS-side grammar's shape.
3. **Two real bugs were caught by this module's own test suite, immediately
   after writing it — not the corpus check.** (a) `has_path_parameter` was
   computed inside the notes-string helper but never actually attached to
   the emitted candidate dict — a `KeyError` on the very first test that
   asserted it. (b) The global-fetch-import suppression check reused
   `ImportResolver.name_alias`, which only ever populates entries already
   in `CONSTRUCTOR_NAMES` (the SDK-registry vocabulary) — so `import {
   fetch } from "cross-fetch"` was silently never recognized as an import
   of `fetch` at all, and the corresponding suppression never fired. Fixed
   by adding a separate `imported_names` set tracking every locally-bound
   import name regardless of SDK relevance — a genuinely different
   question from "is this a known SDK constructor," which the shared dict
   had conflated.
4. **A real vocabulary gap, named rather than papered over.** The two SP12
   passes emit `kind: "declarative_route"` / `kind: "http_client_call"`,
   neither of which the `genai` pack's `point_kinds[]` declares (SPA
   routing and generic HTTP calls aren't GenAI-domain vocabulary any more
   than they're Python-specific). `oah/discovery/gap_model.py`'s own
   `kind_to_dim.get(kind)` already treats an unmapped kind as "not a gap
   this pass can classify" and silently excludes it — so today, S3 sees
   the `llm_generation` points from this adapter but quietly drops the
   other two shapes' points. Not a bug in either module; a real, honest
   gap that belongs to E12's service pack, which will actually own that
   vocabulary. Named here so it isn't rediscovered as a mystery later.

## Decision

Ship the adapter as real, tested, callable module-level code — not wired
into `oah/cli.py`'s command dispatch yet (every CLI command still
hardcodes the Python adapter; zero user-visible/CLI behavior change from
this phase) and with no corpus fixture vendored into `corpus/` yet. Both
are real, separate follow-up work, not silently dropped:

- **CLI language dispatch** — which adapter a target repo actually runs
  through — needs a real decision (file-extension sniffing? a
  `primary_language` field? explicit `--language`?) this phase deliberately
  didn't rush.
- **Corpus vendoring + multi-language `oah/eval_corpus.py` scoring** — E7's
  own territory. `cocktail-app` (MIT, already hand-verified twice now —
  once for SP12, once for this phase's own real-corpus check) is the
  natural first candidate.
- **S2 vendor/manifest detection for TS** (`package.json`, commercial
  APM/log platforms) — `docs/decisions/011`'s own named next epic, unrelated
  to S1.
- **A TS `structural_pattern`/`content_signal` registry** (a TS
  `tool_use`-dispatch equivalent) — no SP10/SP12 evidence exists for it.
- **Pinecone/LangSmith/LiveKit TS registry entries** — no evidence for
  their TS SDK call shapes.

## Consequences

- E12's own DoD bullet (c) — "registry families with structurally different
  detector shapes are proven" — now has a real, corpus-verified TS
  implementation behind it, not just a spike.
- `schemas/domain_pack.schema.json`'s `registries[].detector_shape`
  description (E13) still says `declarative_registration`/
  `global_unimported_callee` have "no Python-adapter or oah/ implementation
  yet" for the receiver-suffix shape's Python side specifically — that
  sentence is about a *different* axis (structural_pattern's Python-only
  `tool_use` check) and remains accurate; this phase's own registry
  `language` field is the real answer for the shapes that did land.
- **Revisit trigger** (not a recurring spike): re-run this module's own
  4-repo verification whenever `tree-sitter-typescript` bumps a minor
  version, the same "don't assume a pinned dependency's behavior never
  drifts" posture SP10's own finding 6 (the Node `typescript` package
  break) already established as a real risk class for a second-language
  toolchain.
