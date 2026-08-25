# SP10 — Multi-language surface-mapping architecture

Status: resolved, with a documented sample-size caveat. Blocks E2, E11.
Timebox: 1.5 wk (used: same-day). Prototype:
[`spikes/sp10-multilang/`](../../spikes/sp10-multilang/), building on
[SP1's Python prototype](../../spikes/sp1-surface-mapping/).

## Context

SP1 answered recall for Python alone. SP10 asks the architecture question:
what's the language-agnostic intermediate representation that lets S1 add a
new language without touching pipeline core or S3+, and does a **unified
tree-sitter parse layer** beat **native per-language parsers behind a common
adapter interface**? The prototype must prove the abstraction on two real
languages, not one — a single-language prototype doesn't test whether an
abstraction actually generalizes.

## Approach

Built a real second-language adapter — TypeScript/Node, using the TypeScript
compiler API, mirroring SP1's Python `ast` adapter's design one-to-one — and
a real orchestrator (`orchestrate.py`) that dispatches to either adapter
through one `detect(path, language)` call. Tested against three more real
open-source repos using `@anthropic-ai/sdk` (`transcribee`, `llm-document-ocr`,
`wechatbot` — pinned by commit SHA, not vendored, same policy as SP1's
corpus), hand-labeled the same way. Then, rather than assuming an answer on
the tree-sitter-vs-native question, ran a concrete feasibility probe for the
tree-sitter alternative instead of just weighing it in the abstract.

## Findings

1. **100% recall (21/21) across both languages, 6 real repos, through one
   common interface.** `python3 eval.py --python-corpus-dir <dir>
   --ts-corpus-dir <dir>` reproduces this from the actual source, not from
   this record's prose: 17/17 Python (SP1's corpus) + 4/4 TypeScript, 0
   false positives, 0 silent misses, scored by the exact same code regardless
   of which adapter produced a given candidate.
2. **Both adapters independently converged on the same three-phase shape**
   despite using completely different parser technologies (Python's stdlib
   `ast` vs. the TypeScript compiler API): (1) resolve import aliases for
   that language's module system, (2) prescan the file for "known client"
   bindings, (3) walk call expressions and suffix-match on the last two
   attribute-chain segments. Neither adapter was designed top-down from a
   shared spec — the convergence is evidence the three-phase shape is the
   actual language-agnostic abstraction for S1's detection stage, not an
   artifact of copying one language's design onto the other after the fact
   (the TS adapter was written *after* seeing this shape work in Python, but
   the phase boundaries fell out of TypeScript's own requirements, not a
   forced template — see finding 3).
3. **What does NOT unify: the scope rule for phase 2.** Python's corpus never
   needed anything wider than class-scoped `self.attr` tracking (SP1 finding
   2). TypeScript's did: `wechatbot`'s real call site depends on a
   module-level `let client: Anthropic | null` assigned inside one function
   (`initLLM`) and read inside a different one, with no class involved at
   all — resolvable only with a **file-wide**, not function- or
   class-scoped, prescan. This is a real language-shape difference (TS/JS's
   closures and hoisting make narrower scoping unreliable in a way Python's
   don't), not an implementation shortcut. **Consequence for E2's adapter
   interface: the prescan's scope rule must be a per-language plugin
   parameter, not something pipeline core assumes or provides a single
   default for.**
4. **The wrapper-function pattern recurred independently in TypeScript**
   (`llm-document-ocr`'s local `async function useAnthropic()`, called via
   `await useAnthropic(...)` elsewhere) and resolved the same way it did in
   Python's `beacon` (SP1 finding 2's `LLMProvider.complete`): no call-graph
   propagation needed, because a whole-file scan finds the wrapper's own
   body directly regardless of who calls it. This generalizes across
   languages: **S1 does not need call-graph analysis to handle wrapper
   functions**, in either language tested.
5. **Unified tree-sitter is feasible and pip-installable — confirmed, not
   assumed:** `pip install tree-sitter tree-sitter-python
   tree-sitter-typescript` gives a pure-Python path with no Node.js runtime
   dependency; `treesitter_feasibility_probe.py` parses both a Python and a
   TypeScript snippet through the identical `tree_sitter.Parser` API. **But
   the AST node *type names* are not shared** — Python's grammar calls a
   call site `call`/`attribute`; TypeScript's calls the same shape
   `call_expression`/`member_expression`. A unified parse layer still needs
   a small per-language "grammar profile" (node-type name mapping) — it
   does not eliminate per-language code, it only unifies the *parsing
   toolchain*, not the *semantic-resolution* logic phases 1–2 above still
   need per language regardless of parser choice (confirmed by finding 3,
   which is about semantics, not syntax).
6. **A concrete operational cost was actually hit, not hypothesized:**
   building the native TS adapter required Node.js + the `typescript` npm
   package as a hard OAH runtime dependency. `npm install typescript`
   installed `typescript@7.0.2` by default — the new Go-based "tsgo" port —
   which does **not** expose the classic `ts.createSourceFile`/`ts.SyntaxKind`
   Node API the adapter needs at all (`TypeError: Cannot read properties of
   undefined`); had to pin to `typescript@5.7`. This is exactly the kind of
   external-toolchain churn a second runtime dependency exposes OAH to,
   independent of anything in OAH's own control.

## Decision

- **The three-phase adapter shape is the language-agnostic architecture for
  S1** — import-alias resolution, known-binding prescan (with a
  per-language scope rule), suffix-match call walk — validated on two real
  languages, not proposed from one. E2's per-language plugin interface
  should require exactly these three pieces from each language plugin, with
  phase 2's scope rule as an explicit plugin-supplied parameter (per finding
  3), not a pipeline-core default.
- **Recommend tree-sitter over native per-language parsers/compiler APIs for
  E2's actual parsing layer** — reversing the default this spike started
  with (native, mirroring Python's own `ast` choice). The deciding factor is
  operational, not "less code": finding 5 shows tree-sitter does *not*
  collapse the semantic-resolution phases into shared code (those stay
  per-language either way), so the case for tree-sitter isn't "write it
  once" — it's a single pure-Python dependency instead of bundling a second
  language runtime (Node.js) whose own API surface can break across a major
  version with no warning (finding 6), which is a real deployment and
  maintenance cost for a tool meant to run against arbitrary target repos.
- **Confirms, and generalizes to E11, that wrapper functions never need
  call-graph propagation** — a pipeline-core simplification (whole-repo AST
  scanning is sufficient) that holds regardless of which language plugin is
  active, per finding 4.
- **This spike's own TS adapter (`ts-adapter/detect.js`) is evidence and a
  comparison baseline, not a component to carry into E2.** E2's real
  TypeScript plugin should be built on `tree-sitter-typescript` per the
  recommendation above, not on the Node/compiler-API adapter built here —
  keeping that adapter around specifically because it's what made findings 3
  and 6 possible to state concretely instead of speculatively.

## Consequences

- E2 and E11 are unblocked per the spike table.
- **Honest sample-size caveat, same shape as SP1's:** 3 TypeScript repos, 16
  files, 4 ground-truth positive sites — real and code-grounded, but thinner
  even than SP1's already-small Python sample. E11's own TS corpus fixture
  (ROADMAP.md: "not deferred, follows immediately after SP10's decision
  record") should re-run `eval.py` at real corpus scale before 100% recall
  is treated as durable rather than a strong first signal.
- **The reasoning trail matters here as much as the conclusion:** this spike
  started by building the native/compiler-API path first (the assumption
  going in, mirroring Python's own choice), and only recommends tree-sitter
  *after* hitting the TS7 API break and running the feasibility probe — the
  decision reverses a real default, not a hypothetical one, and is recorded
  as such rather than presented as foreseen from the start.
- E2's registry work (SP1's decision record) and this spike's finding 3
  compose directly: SP1's registry design choices (suffix-match methods,
  alias-resolve imports) transfer to TypeScript unchanged; only the
  known-binding scope rule needed to change per language.
