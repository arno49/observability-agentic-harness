# 032 — E12 phase 10: the axios registry and cross-file known-name propagation

Status: landed. Advances E12 (`docs/decisions/011`).

## Context

Unlike every prior E12 phase, this one started from a real target repo, not
a docs-grounded read of an SDK's own API: `oah map --language typescript`
was run against `mf-analyzer-web` (a real ~450-file EPAM React/Vite app)
with the `service` pack. Result: 6 `http_client_call` points (bare
`fetch()`, the fixed-pass detector), 75 `declarative_route`, 0 GenAI
points. The repo's own `package.json` lists `axios` as a dependency and
has ~291 real axios call sites, all routed through `apiClient`, a single
`axios.create({...})` instance — entirely invisible to S1.

A first pass added an axios registry (`chain_hop` from the imported
`axios` binding to a synthetic `"axios#instance"` module, mirroring
amqplib's own precedent from `docs/decisions/028`, plus a
`receiver_method_suffix` entry for the instance's `get`/`post`/`put`/
`delete`/`patch`/`request` methods). Re-running against the real repo:
**0 of the ~291 real call sites detected.** Root cause, found by actually
running it rather than assumed: `apiClient` is built in `src/api/apiClient.ts`
and `export default`-ed; every one of the ~450 real call sites is in a
*different* file that imports it. Every known-name resolution mechanism in
`typescript_adapter.py` — constructor call, factory call, annotation,
chain_hop — has only ever tracked a receiver **within the file that
constructs it**. This is not a new gap invented for axios: SP1
(`docs/decisions/003`, finding 2) named cross-file receiver resolution as
needing an LLM disambiguation pass for the *Python* adapter; the
TypeScript adapter has never had one wired up at all (`oah/cli.py`'s own
`--language` help text: "neither has an LLM-disambiguation counterpart
yet"). A shared-client-module export is arguably the single most common
real-world shape for any constructed SDK instance, not just axios — this
was the first real repo run through this adapter with that shape present
at scale.

## What was built

**The axios registry** (`domains/service/pack.json`, `http_client_call`,
the fifth service-pack registry): a `chain_hop` entry (`axios.create()` →
synthetic `"axios#instance"`) plus a `receiver_method_suffix` entry for
that synthetic module's verb methods, plus a docs-grounded (not
corpus-verified — the real repo never uses this form)
`imported_namespace_method_call` entry for axios's own alternate direct-call
API (`axios.get(url)` with no `.create()` step, mirroring node-cron's
precedent from `docs/decisions/024`). A bare callable-object call
(`axios({method: 'get', ...})`) is a real, separate axios API shape not
covered by any detector shape today — named in the registry entry, not
folded in.

**Cross-file known-name propagation**, the genuinely new mechanism
(`oah/discovery/typescript_adapter.py`), a two-pass repo scan:

- `_collect_export_map(root, src, known_names)`: after a file's own
  ordinary walk runs (which already resolves `export const x = ...`'s
  declaration via `_walk`'s existing generic per-child recursion — nothing
  new needed there), a dedicated top-level-only scan handles the two export
  shapes that reference an *existing* name rather than declare one:
  `export default <identifier>` and `export { x [as y] }`. Returns
  `{exported_name: resolved_module}` for whichever of those actually
  resolved.
- `ImportResolver` gained `all_imports` — every import statement's
  `(local, original_or_None, module, is_default)`, unconditionally, not
  gated on the local name matching a known SDK constructor (a shared
  client variable's name is never itself in `constructor_names`, unlike
  every prior use of `name_alias`).
- `_load_path_aliases`/`_substitute_alias`/`_resolve_module_specifier`:
  reads `tsconfig.json`'s `compilerOptions.baseUrl`/`paths` (best-effort —
  a missing file or JSON the stdlib parser rejects, e.g. real tsconfig
  comments, just means "no aliases," not a crash) and resolves an import
  specifier — relative (`./x`) directly, alias-based (`@/x` → `src/x`, the
  actual mapping `mf-analyzer-web`'s own `tsconfig.json` uses) via `paths`
  — to a real `.ts`/`.tsx` file on disk. A bare package specifier (no
  match either way, e.g. `"axios"`, `"react"`) returns `None` — external
  packages are already handled by the SDK registries directly.
- `detect_repo`: pass 1 calls `detect_file(..., collect_exports=True)` for
  every file, building a repo-wide `{resolved_file: export_map}` index and
  capturing each file's own `all_imports` (points thrown away — pass 1
  only exists to populate `known_names` far enough to resolve exports;
  `next_id` never leaks from it). Pass 2 resolves each file's imports
  against that index and seeds any hit straight into `known_names` *before*
  that file's real walk runs — from there, every existing resolution/
  suffix-match code path (chain_hop, receiver_method_suffix, the whole
  rest of the mechanism) handles it identically to a locally-constructed
  receiver, no further new code. A repo with no cross-file-resolvable case
  produces byte-identical output to the single-pass version this replaced.
- Imports moved from an inline `_walk` branch to a dedicated pre-pass in
  `detect_file` (imports are hoisted, so this changes nothing about single-
  file behavior) — required because cross-file seeding needs them known
  *before* the walk starts, not discovered during it.

**Real, named boundary: single-hop only.** A file that re-exports a name
*from* another file (`export { default } from './real'`, `export * from
'./y'`) is not followed to that further file — a regression test
(`test_reexport_through_a_further_file_is_a_named_gap`) documents this
rather than silently resolving or silently staying broken. `export default
function`/`export default class`/`export function X` are also not handled
by `_collect_export_map` (none reference a plain identifier already in
`known_names` the way the three handled shapes do) — real SDK-client
exports are essentially always a plain instance reference in practice, not
an exported function/class, so this wasn't the shape worth chasing first.
A tsconfig `extends` chain is not followed.

Verified end to end on the motivating repo, not just synthetic fixtures:
**0 → 294 real `http_client_call` points detected** (vs. ~291 by direct
grep — the adapter finds slightly more, consistent with call sites its
AST walk catches that a single-line grep pattern doesn't, e.g. a call
wrapped across multiple lines).

## Decision

**Build the cross-file mechanism now, not defer it.** The alternative —
shipping the axios registry alone, honestly documented as "resolves 0 real
call sites on the repo that motivated it" — was seriously considered (an
earlier version of this registry's own `confidence_note` said exactly
that) and rejected once it was clear the underlying gap is general, not
axios-specific: any exported/imported SDK client instance in ANY future
TypeScript registry hits the identical wall. Fixing it once, generically,
in the adapter is cheaper than every future registry entry separately
discovering and working around the same limitation.

**Single-hop, not a full module-graph resolver.** A real re-export-chain
resolver would need to handle barrel files, `export * from`, circular
imports, and non-trivial graph traversal — a substantially larger,
separate piece of work. The single-hop version already closes the actual
gap found on a real repo; going further wasn't justified by evidence yet.

## Consequences

- This is the service pack's first registry entry that is corpus-verified
  against a real target repo end to end, not docs-grounded-and-unverified
  like every entry before it (named honestly in each of those entries' own
  `confidence_note`, same precedent as genai's own livekit entry).
- The cross-file mechanism is TypeScript-adapter-specific; the Python
  adapter's own cross-file gap (SP1 finding 2) is unaffected and remains
  routed toward its LLM-disambiguation pass, a genuinely different design
  (this mechanism is deterministic, no model call) — not proposed as a
  replacement for that pass, a separate real question if it's ever
  revisited.
- Real, un-closed gaps, named rather than silently dropped: re-export
  chains (barrel files), `export default function/class`, a tsconfig
  `extends` chain, and the bare axios callable-object call shape
  (`axios(config)`).
- No `oah/cli.py` wiring changed — this phase is entirely inside
  `typescript_adapter.py` and `domains/service/pack.json`; the existing
  `--language typescript --pack service` combination just detects more.
