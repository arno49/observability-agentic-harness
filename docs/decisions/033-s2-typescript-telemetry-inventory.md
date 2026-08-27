# 033 — S2 gains a real TypeScript telemetry inventory

Status: landed. Closes a gap named while assessing E12 phase 10
(`docs/decisions/032`'s own retrospective).

## Context

Running the full deterministic pipeline (`oah map` → `oah inventory` →
`oah gaps`) against `mf-analyzer-web` (the same real EPAM target repo
`docs/decisions/032` used) surfaced a real, previously unnoticed gap: `oah
inventory` reported **zero findings** on a real ~450-file app —
`oah/discovery/telemetry_scanner.py`'s `build_telemetry_inventory` only
ever scanned `*.py` files, unconditionally, with no `--language` flag at
all. Every downstream `oah gaps` run against a TypeScript target was
therefore joining S1's real surface points against an S2 inventory that
had structurally never looked at the target's actual source — every point
showed `dark`/`p1` regardless of whether real application-level logging
existed near it, which it did (see below).

Reading the target repo's own source, not guessing: `src/utils/logger.ts`
defines a hand-rolled `class Logger { error()/warn()/info()/debug()
{...} }`, instantiated once (`export const logger = new Logger();`), and
imported into **~140 different consumer files** with **~790 real call
sites** — the identical shared-singleton-module shape that forced
`docs/decisions/032`'s cross-file mechanism for axios, now needed a second
time for a completely different concern (logging, not HTTP). This is not
a coincidence specific to axios or to logging: a shared client/service
module built once and re-exported is evidently a common real-world
TypeScript/React pattern in general.

## What was built

**`oah/discovery/ts_module_resolution.py`** (new): the cross-file
module-graph resolution mechanism `docs/decisions/032` built inside
`typescript_adapter.py` — `collect_export_map`, `load_path_aliases`,
`substitute_alias`, `resolve_module_specifier` — extracted into its own
module and imported back into `typescript_adapter.py` under its original
names (zero behavior change, all existing S1 tests pass unmodified). It
was already detector-agnostic by construction (`collect_export_map`
doesn't inspect what a "known name" represents, only copies whatever
value a caller's own known-names dict holds), so no logic changed in the
extraction — only where it lives.

**`oah/discovery/ts_telemetry_scanner.py`** (new): a real S2 scanner for
TypeScript/TSX, matching `telemetry_scanner.py`'s four categories and
`schemas/telemetry_inventory.schema.json`'s exact output shape, but built
against real TS/JS vocabulary rather than a blind Python port:

- **Loggers**: `console.log/error/warn/info/debug` (kind `print`, mirroring
  Python's own treatment of bare `print()`), plus a `custom_wrapper`
  heuristic covering three real shapes: a locally-defined class or object
  literal whose own method/property names intersect
  `{error, warn, info, debug, log, trace}` on at least two names (two, not
  one, to avoid a false hit on an unrelated class defining a single
  `.info()`); and `winston`/`pino` (the only two packages
  `oah/discovery/manifest_scanner.py`'s own `_VENDOR_RULES` already
  recognizes, kept consistent rather than inventing new vendor identifiers)
  used via `winston.createLogger(...)` or a direct `pino()` factory call.
  `wrapper_module` is the defining file's own relative path for a
  locally-defined wrapper, or the real npm package name for winston/pino.
- **`existing_otel_usage`**: any import whose specifier starts with
  `@opentelemetry/` (JS OTel's real npm scope), same-file only — an import
  IS the usage signal, no cross-file propagation needed.
- **`metrics_libraries`**: `prom-client`/`hot-shots`/`node-statsd`/
  `statsd-client`/`dd-trace` imports, normalized to the SAME vendor-level
  identifiers `manifest_scanner.py`'s table and the schema's own
  `library` enum already use (`prometheus_client`, `statsd`, `ddtrace`) —
  not raw npm package spelling, so a source-confirmed and a
  manifest-declared finding for the same real library report under one
  shared name.
- **`error_handling`**: `catch_clause` classified `reraised` (body
  contains a `throw` anywhere) > `logged` (body contains a call whose
  method name is a recognized log-level name, receiver-agnostic — the
  same coarse heuristic Python's own `_except_pattern` already uses) >
  `swallowed`. `exception_type` is never populated — TS/JS catch bindings
  carry no real static exception-type information the way Python's
  `except SomeError as e` does (a `: unknown`/`: any` annotation conveys
  no real type), a genuine "not applicable," not a missing field.

Cross-file resolution reuses `ts_module_resolution.py` unchanged: pass 1
scans every file once (`collect_exports=True`) to build a repo-wide
`{resolved_file: {export_name: (kind, wrapper_module)}}` index; pass 2
resolves each file's own imports against that index and seeds any hit
into `known_loggers` before that file's real scan runs — from there every
existing call-site/catch-clause code path handles it exactly like a
locally-defined logger.

**`oah/cli.py`**: new `_build_telemetry_inventory(target, git_sha,
language)` dispatcher, mirroring `_build_surface_map`'s own shape exactly
— `typescript` routes to the new scanner, everything else (including
`java`, which has no S2 scanner yet, a real named gap) falls back to the
Python one, byte-identical to every pre-existing caller. Wired into all
four commands that build an inventory (`inventory`, `gaps`, `dtos`,
`readiness`); `inventory` itself gained a `--language` flag it never had
before (the other three already had one for S1, now shared).

## Verified end to end

Ran the real pipeline against `mf-analyzer-web` before and after:

| | before | after |
|---|---|---|
| S2 files scanned | 0 | 440 |
| logger call sites | 0 | 759 (709 `custom_wrapper` via cross-file resolution, 50 `print`) |
| error_handling entries | 0 | 688 (396 logged, 202 reraised, 90 swallowed) |
| `oah gaps` dark points | 375 (100%) | 265 |
| `oah gaps` partial points | 0 | 110 |

759 vs. a precise grep recount of the same repo (710 `logger.error/warn/
info/debug(` + 49 direct `console.*(`, 759 total) — matches within 0
points at this recount granularity; the earlier, cruder grep pattern that
originally suggested "485 call sites" in `docs/decisions/032` was itself
imprecise, corrected here for the record.

## Decision

**Extract the cross-file mechanism into shared infrastructure now, not
duplicate it a second time.** The alternative — writing S2's own
independent cross-file logic, or skipping cross-file resolution for S2
entirely and shipping a scanner that (like the first version of the axios
registry in `docs/decisions/032`) finds 0 real call sites on the repo
that motivated it — was rejected for the same reason `docs/decisions/032`
gave: the underlying gap (a shared singleton module, built once,
re-exported everywhere) is general, not specific to one detector. Two
real, independent findings on one repo needing the identical mechanism is
real evidence it belongs in shared infrastructure, not a coincidence to
special-case twice.

## Consequences

- S2 is now real for two of the three S1-supported languages (Python,
  TypeScript); Java has no S2 scanner at all — a real, named gap, not
  silently claimed, falling back to the Python scanner's honest-empty
  result on a Java repo.
- `oah gaps`'s dark/partial/covered classification for TypeScript targets
  is now grounded in the target's own real logging, not structurally
  guaranteed to report 100% dark regardless of source content.
- Real, un-closed gaps, named rather than silently dropped: only two
  external logging packages recognized (winston, pino — matching
  `manifest_scanner.py`'s existing vocabulary, not exhaustive); only one
  real custom-wrapper *shape* recognized (class/object with logger-shaped
  methods) — a plain function-based logger factory or a Proxy-based one
  would not be detected; `metrics_libraries`/`existing_otel_usage` are
  same-file-only (no cross-file need was found on the motivating repo, so
  none was built).
