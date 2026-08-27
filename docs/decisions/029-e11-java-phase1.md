# 029 — E11-Java phase 1: a real Java S1 adapter, `static_builder_chain`

Status: landed. Advances E11 (`docs/decisions/004`'s own priority order —
TypeScript first, Java second).

## Context

E11's own priority order named Java second, after TypeScript, as "a
heavier lift (Spring AI / LangChain4j patterns, different async model)".
Following the same "verify before building" discipline every language
port in this project has used (SP1's Python spike, SP10/SP12's TS
research), two things were verified directly before any adapter code was
written:

1. **Grammar**, explored directly against `tree_sitter_java` (installed
   fresh, not previously a dependency): `import_declaration`'s own
   `scoped_identifier` child text IS the dotted import path (no structural
   flattening needed, unlike TS's member-expression chains);
   `method_invocation.object`/`.name`/`.arguments` are real fields, and a
   call chain is represented as NESTED `method_invocation` nodes (`.object`
   is the inner call) rather than TS's separate member-expression-then-call
   split; `object_creation_expression.type` for `new X()`;
   `field_declaration`/`local_variable_declaration` both expose `.type` +
   `variable_declarator` children; a dedicated `this` node type, mirroring
   TS's own.
2. **Real SDK shapes**, via a background research agent against the
   official Anthropic and OpenAI Java SDKs' own READMEs (not guessed):
   both construct their client via a **static builder method chain**
   rooted at a known class name —
   `AnthropicOkHttpClient.builder().apiKey(...).build()` or the shorter
   `AnthropicOkHttpClient.fromEnv()` — **never `new X()`**. Spring AI's
   idiomatic construction is dependency-injection-based (`ChatClient.Builder`
   as an autoconfigured bean, no direct call site to find at all) —
   confirmed structurally harder, so not attempted as the first entry.

This second finding meant TS phase 1's own first detector shape
(`receiver_method_suffix` via `new X()`) would have had **no real registry
to attach to** — Java's own idiomatic SDK construction needed a shape none
of the four shapes built so far (across genai and the service pack)
covers.

## What was built

- **`oah/discovery/java_adapter.py`** (new), mirroring
  `oah/discovery/python_adapter.py`'s architecture more than
  `typescript_adapter.py`'s: Java's own OOP shape (explicit class/field
  declarations, no closures capturing outer-function locals) means a
  **class-scoped** known-name prescan (`KnownNames.self_attrs`, mirroring
  Python's own) is the right model, not TS's file-wide one (SP10 finding 3
  was JS/TS-specific). One real addition beyond a blind Python port: Java
  allows a field to be accessed **unqualified** from within its own
  class's instance methods (`client.foo()` inside a method of the class
  declaring `private Client client` implicitly means `this.client.foo()`)
  — neither Python (always explicit `self.`) nor TS/JS (always explicit
  `this.`) has an equivalent, so `_resolve_root` checks `self_attrs` as a
  fallback for a bare identifier root, not only for an explicit `this.`
  chain.
- **`static_builder_chain`**, a new `detector_shape`
  (`schemas/domain_pack.schema.json`): `constructor_names` names the
  class(es) that may serve as a chain root, `terminal_methods` names the
  method(s) whose presence as the chain's **last segment** (regardless of
  how many configuration calls precede it — `.apiKey(...)`, `.timeout(...)`,
  ...) confirms the chain actually produced a client. Once resolved,
  `sdk_module`/`method_suffixes` on the same entry are matched exactly like
  `receiver_method_suffix` — this shape only changes how the receiver
  itself is recognized. `oah/discovery/registry.py`'s
  `java_static_builder_index(pack, language)` derives
  `{class_simple_name: (sdk_module, frozenset(terminal_methods))}`;
  `static_builder_chain` was added to `_RECEIVER_SHAPES` so these entries
  still feed `constructor_names`/`module_to_registry`/`all_method_suffixes`
  normally.
- `object_creation_expression` (`new X()`) support is real, general
  infrastructure in the same module (`ImportResolver.resolve_constructor_call`)
  — no registry uses it yet, but a future plain-constructor Java SDK
  doesn't need the adapter rebuilt for it.
- **Async, without an async/await keyword to key off**: Java has no
  syntactic async marker. The real SDKs expose a genuinely separate async
  surface instead (`AnthropicClientAsync`/`AnthropicOkHttpClientAsync`, or
  `.async()` inserted as an extra hop on a sync client, e.g.
  `client.async().messages().create(...)`). Since suffix matching only
  checks a chain's tail, that extra hop never blocks the match — checking
  `"async" in chain` is what lets `sync_nature` be real instead of a blind
  `"sync"` default. The async client classes are also declared as chain
  roots in the same registry entry (same module/terminals), covering full
  standalone async construction too.
- `domains/genai/pack.json`: one new registry entry (`language: "java"`,
  `sdk_module: "com.anthropic.client"`, `constructor_names:
  ["AnthropicOkHttpClient", "AnthropicClient", "AnthropicOkHttpClientAsync",
  "AnthropicClientAsync"]`, `terminal_methods: ["build", "fromEnv"]`,
  same `method_suffixes` as the Python/TS entries). `AnthropicClient` (the
  interface, never itself chain-called) is included only so a
  constructor-injected already-typed field/parameter still resolves via
  `annotation_sdk` — the same trust every adapter already extends to a
  typed parameter.
- `oah/cli.py`: `--language java` added to every subcommand's `choices`
  (7 call sites) and to `_build_surface_map`'s dispatch — the SAME pattern
  E11-TS's own CLI dispatch phase established, landed in the same phase
  here rather than deferred (unlike TS, which shipped CLI dispatch as a
  separate follow-up phase).
- `pyproject.toml`: `tree-sitter-java>=0.23` (matching the existing
  `tree-sitter-python`/`tree-sitter-typescript` pins).
- Real tests: `tests/test_java_adapter.py` (20 cases) covering both
  construction shapes (`fromEnv()`, full `.builder()...build()` chain with
  intermediate config calls), the async-hop detection, Java's own
  unqualified-field-access idiom (and the explicit `this.` form),
  prescan order-independence, constructor-injected typed fields/parameters,
  lambda-body scope inheritance, local-variable-shadows-field precedence,
  unresolved-receiver silence, a synthetic-pack test proving
  `object_creation_expression` support independent of any real SDK,
  `detect_repo`'s build-output/test-source exclusions, and
  `build_surface_map` schema validation. `tests/test_cli.py` gets the real
  subprocess CLI-dispatch test mirroring TS's own.

## A real gap found while testing, not guessed at

`_resolve_static_builder` only recognizes a chain whose **last** segment is
a terminal method — the assign-then-call shape the real SDKs' own README
examples actually use. A single, unassigned expression chaining
construction AND the eventual call together
(`AnthropicOkHttpClient.fromEnv().messages().create(params)`, terminal
buried mid-chain rather than at the end) is **not** resolved. Found by a
test written the terse way first (which silently returned zero points),
not by design review — fixed by rewriting the test to the realistic form
and adding a dedicated regression test documenting the gap explicitly,
rather than expanding scope to chase it in phase 1.

## Decision

**Java phase 1 ships with one real, corpus-independent-verified registry
entry** (Anthropic Java SDK), matching TS phase 1's own scoping discipline
(one real entry, additional registries as later phases) — not a
speculative multi-SDK phase 1. OpenAI Java SDK (same shape, confirmed by
the same research pass) is the natural next registry, not added here to
keep this phase to one library at a time, the same discipline every prior
registry phase in this project has used.

## Consequences

- E11's own priority order is now current on both languages it named:
  TypeScript (landed earlier, `docs/decisions/014`) and Java (this phase).
  Go/C#/.NET remain out of scope, per E11's own stated sequencing.
- Real, named gaps for a future phase: OpenAI Java SDK registry (same
  shape, not added here); LangChain4j (`AnthropicChatModel.builder()...build()`,
  same `static_builder_chain` mechanism, different call shape —
  `.chat(...)`, not `.messages().create(...)`); Spring AI (DI-based
  construction, a structurally different detection problem — no chain-call
  site to find at all for the idiomatic path); the mid-chain-terminal gap
  named above; no Java service-domain registries exist yet (Java's own
  `--pack service` runs but finds nothing new, matching Python's existing
  scope boundary); no real vendored Java corpus fixture (E7's own
  territory, same honesty precedent as TS's own still-pending corpus work);
  static-imported members and wildcard imports remain unresolved, named
  gaps matching every other adapter's own require()/wildcard exclusions.
