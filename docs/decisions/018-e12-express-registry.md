# 018 — E12 phase 3: the Express registry, `module_function_call`, and `--pack`

Status: landed. Advances E12 (`docs/decisions/011`, DoD (c)).

## Context

E12's DoD (c) requires "registry families with structurally different
detector shapes are proven, not several of the same shape." E11-TS already
proved `declarative_registration` and `global_unimported_callee` (SP12).
`http_server_route` was still fully `declared_undetected` after phase 1
(`docs/decisions/016`). Express is the obvious first library — dominant
for Node.js backends, and `docs/decisions/011`'s own real candidate
consumer's stack is adjacent to exactly this shape.

## What was found before building

Attempting to detect `const app = express(); app.get(path, handler)`
immediately hit two pre-existing gaps, not new ones this phase invented:

1. **`module_function_call` was named but never implemented.**
   `schemas/domain_pack.schema.json` and `oah/discovery/registry.py` both
   described this detector shape since E13 — a receiver created via a bare
   factory call (`express()`) rather than `new X()` — but neither
   `python_adapter.py` nor `typescript_adapter.py`'s known-name prescan
   ever checked for a bare `call_expression` value, only `new_expression`.
   Confirmed directly (not assumed): adding an Express registry entry and
   running `detect_repo` against a real `const app = express()` fixture
   returned `[]`.
2. **The TypeScript adapter's registry data was genai-only at the module
   level.** `REGISTRIES`/`MODULE_TO_REGISTRY`/etc. were derived once, at
   import time, from `load_pack("genai")` — exactly the "process-global
   constants... a real, separate cost with no second real pack yet to
   justify it" `docs/decisions/016`'s own module docstring already named
   as deferred. Confirmed the same way: an Express registry entry in
   `domains/service/pack.json` alone changed nothing, because the adapter
   never consulted that pack at all.

## What was built

- **`module_function_call`, for real**: `ImportResolver.resolve_factory_call`
  (mirrors `resolve_constructor_call`, checking a bare `call_expression`'s
  function identifier instead of a `new_expression`'s constructor) plus a
  matching branch in the known-name prescan (`variable_declarator` and
  `assignment_expression`, alongside the existing `new_expression`
  handling). Once a receiver is known, downstream suffix-matching is
  identical regardless of which shape created it — no other code changed.
- **Pack-parameterized TypeScript detection**: a `_RegistryContext`
  namedtuple (`constructor_names`, `module_to_registry`,
  `all_method_suffixes`, `suffix_lengths`) threads through `_walk`'s
  recursion as one parameter; `detect_file`/`detect_repo`/`build_surface_map`
  all gained a `pack=None` parameter (default `None` → genai, byte-identical
  to every existing caller). `ImportResolver.__init__` now takes
  `constructor_names` explicitly instead of reading a module global.
- **`domains/service/pack.json`**: one registry entry, `express`
  (`sdk_module: "express"`, `constructor_names: ["express"]`,
  `method_suffixes: [get, post, put, delete, patch]`,
  `detector_shape: "module_function_call"`). `http_server_route`'s
  `point_kinds[].detected_by` flips from `declared_undetected` to
  `registry`.
- **Two real precision guards, not corpus-verified but reasoned from
  Express's own documented API**: (a) `app.get(name)` (1 argument) reads a
  setting, `app.get(path, ...handlers)` (2+ arguments) registers a route —
  the adapter requires 2+ call arguments before treating any matched
  suffix as `http_server_route`. (b) `app.use(...)`/`app.all(...)` are
  deliberately excluded from `method_suffixes` — `use` is overwhelmingly
  called for plain middleware with no path argument in real Express code
  (`app.use(cors())`), and this suffix-match mechanism alone can't tell
  that apart from a genuine path-mounted sub-router.
- **`--pack {genai,service}`** on `map`/`gaps`/`design`/`event-schema`/
  `dtos`/`readiness`, default `genai` (byte-identical default). A new
  `_load_pack_for_args(args)` helper replaces every command's own
  hardcoded `load_pack("genai")`; threaded into `_build_surface_map` (S1),
  `build_gap_model` (S3, already pack-aware from E13), and
  `_design_all_lenses`/`build_event_schema`/`generate_dtos` (already
  pack-aware). `--pack service` only does something new with
  `--language typescript` today — python_adapter.py's own registries
  remain genai-only, named explicitly in `_PACK_HELP`, not silently
  implied to work.
- Real tests: `tests/test_service_pack.py` (route detection, the
  settings-getter guard, the `use()` exclusion, zero-behavior-change for
  the default pack, an end-to-end S1→S3 proof through the real
  `build_gap_model`) and `tests/test_cli.py` (a real subprocess
  `oah map --language typescript --pack service` run, plus a default-pack
  regression proving Express routes stay invisible without `--pack service`).

## Decision

**Docs-grounded, not corpus-verified — named explicitly, same precedent as
genai's own livekit registry.** No real Express repository has been run
through this adapter. This is a materially different evidence tier from
every genai registry with real corpus numbers (anthropic: 100% recall
across SP1/SP10/SP12/E11-TS's combined real-repo evidence). The
`confidence_note` on the registry entry itself states this rather than
implying corpus rigor it doesn't have.

**Deliberately narrow scope, three real gaps named rather than silently
assumed covered:**
- `express.Router()` sub-router creation (a namespaced factory call, not a
  bare one) is a different receiver-creation shape, not implemented.
- CommonJS `require("express")` is not tracked — `ImportResolver` only
  ever handled ES `import` statements, for every registry, before this
  phase; not a new gap this phase introduces.
- `db_query`, `queue_producer`, `queue_consumer`, `scheduled_job` remain
  fully `declared_undetected` — each needs its own per-library research at
  the same rigor this phase just established for Express, not attempted
  here.

## Consequences

- E12's DoD (c) — "registry families with structurally different detector
  shapes are proven" — now has a second, real (if not corpus-verified)
  shape alongside `declarative_registration`/`global_unimported_callee`.
- The `module_function_call` fix and the pack-parameterization fix are
  both real, general improvements to `oah/discovery/typescript_adapter.py`
  independent of Express specifically — any future TS registry needing
  either shape inherits both for free.
- `python_adapter.py` remains genai-only at the module level — the same
  "process-global constants, no second Python pack yet to justify
  re-parameterizing" reasoning `docs/decisions/016` already accepted for
  it still holds, since no Python-language service-domain registry exists
  yet to force the question the way Express just forced it for TypeScript.
- E12 remains far from done: `telemetry-cost`/`slo`/`dependency`, four
  more S1 registries, `docs/decisions/011`'s own new S5 gates, S11 signal
  provenance, and a real corpus fixture (DoD (a)) are all still unbuilt.
