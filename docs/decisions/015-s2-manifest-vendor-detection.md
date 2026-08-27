# 015 — S2: package.json vendor/manifest telemetry detection

Status: landed. Unblocks part of E12 (service domain pack, `docs/decisions/011`).

## Context

`docs/decisions/011`'s own text named this directly: "S2 needs its own small
epic alongside. The telemetry inventory scanner is Python-specific and
recognises only stdlib logging, OpenTelemetry and prometheus/statsd/datadog.
It cannot read `package.json` or `tsconfig.json` and does not recognise any
commercial APM or log platform. For any non-Python candidate the inventory is
the weakest link in the pipeline — and the cheapest one to fix, since vendor
detection is pattern matching over manifests, not parsing."

E11-TS phase 1 and the CLI language-dispatch phase (`docs/decisions/014` and
this session's follow-up) already let S1 map a TypeScript target's SDK calls,
routes, and fetch calls. S2 (`oah/discovery/telemetry_scanner.py`) still saw
nothing for that same target beyond whatever its own Python-only,
tree-sitter-based source scan happens to find (i.e. nothing, for a pure
TS/JS repo) — a real gap named, not silently carried forward.

This phase is deliberately the smaller half of that gap: manifest-based
vendor detection (`package.json` dependency names against a real, verified
vendor table), not a full TypeScript port of `telemetry_scanner.py`'s
tree-sitter source scan (logger call sites, error-handling classification).
The ADR's own framing — "the cheapest one to fix" — is the reason for that
split: pattern-matching a manifest needs no parser at all, while a real
TS-source logger/error-handling scan is a materially bigger unit of work
(same shape as E11-TS's own S1 port), named here as an explicit follow-up,
not attempted in this phase.

## What was built

- `oah/discovery/manifest_scanner.py` (new): `scan_package_json(repo_root,
  ids)` reads the repo root's `package.json` (`dependencies`,
  `devDependencies`, `optionalDependencies`, `peerDependencies`), matches
  each declared package name against a real vendor table, and returns one
  finding per match with a `file`/`line` pointing at the manifest itself
  (the same shape every other S2 finding uses, just aimed at a manifest
  key instead of a source import site).
- Vendor table, verified against each vendor's own npm listing or official
  docs before being hardcoded (not guessed): OpenTelemetry JS
  (`@opentelemetry/` scope), Dynatrace (`@dynatrace/oneagent-sdk`), New
  Relic (`newrelic`), Splunk Observability Cloud (`@splunk/otel`), Datadog
  (`dd-trace`), Sentry (`@sentry/` scope), winston, pino, Prometheus
  (`prom-client`), StatsD (`hot-shots`, `node-statsd`, `statsd-client`).
- `oah/discovery/telemetry_scanner.py`'s `build_telemetry_inventory` calls
  `scan_package_json` unconditionally (not gated on any `--language` flag —
  a package.json is real signal regardless of whether this same run's
  Python source scan finds anything, e.g. a Python backend with a JS
  frontend subdirectory), returning a new `vendor_dependencies` array and
  two new summary fields (`vendor_dependencies_count`, `has_commercial_apm`).
- `schemas/telemetry_inventory.schema.json`: `vendor_dependencies` (new,
  additive) plus the two summary fields — no existing field changed shape,
  `oah inventory`'s existing output is unchanged unless a `package.json`
  is actually present.

## Findings

1. **Declared and confirmed are different evidence tiers, and conflating
   them would overclaim.** A `package.json` dependency proves the repo
   *depends on* a package, not that it's imported/used anywhere in code —
   materially weaker evidence than `existing_otel_usage`'s source-level
   import scan. Kept in a separate `vendor_dependencies` category rather
   than folded into `existing_otel_usage`, and `has_existing_otel` was
   deliberately left untouched (still purely source-import-based) rather
   than OR'd with a manifest-only OpenTelemetry hit, to keep that
   distinction real rather than blurred for convenience.
2. **A declared dependency can be systematically absent even when the
   vendor is genuinely in use.** Dynatrace's real auto-instrumentation
   runs as a host-level OneAgent process, not an npm dependency at all —
   `@dynatrace/oneagent-sdk` only ever appears for *manual/custom*
   instrumentation on top of that. `has_commercial_apm: false` therefore
   does not mean "no commercial APM," only "no *declared* one" — the same
   `declared_undetected`-style honesty this project's domain-pack work
   already established, surfacing here as a real limit of manifest-only
   detection rather than a gap in the vendor table.
3. **Splunk's own package is itself an OpenTelemetry distribution, and
   that's a real, separate signal worth keeping distinct.** `@splunk/otel`
   wraps OpenTelemetry JS instrumentation rather than being an unrelated
   proprietary agent — classified under its own `splunk` vendor identifier
   anyway (not folded into `opentelemetry`), since a repo's choice of
   Splunk's distribution over raw `@opentelemetry/*` packages is real
   signal for S3's gap model and E9's backend-target selection, not noise
   to collapse away.
4. **Verified before hardcoding, per this project's own standing
   discipline.** Every package name was checked against the vendor's own
   npm listing or official docs (a background research pass), not assumed
   from memory — one candidate (`@opentelemetry/exporter-trace-otlp-http`)
   came back unconfirmed in that pass and was deliberately left out of the
   table rather than guessed in.

## Decision

Ship manifest-based vendor detection as real, tested, schema-validated S2
output — scoped explicitly to the repo root's `package.json` only, with two
real gaps named rather than silently dropped:

- **Nested/monorepo `package.json` files** (a `frontend/package.json` in a
  repo whose root is something else) are not scanned. A real, separate
  extension, not attempted here.
- **TypeScript source-level scanning** (logger call sites, error-handling
  classification — the deeper equivalent of `scan_file`'s own tree-sitter
  walk, for TS/JS grammar instead of Python's) remains fully unbuilt. This
  phase only closes the "cheapest to fix" half of the gap `docs/decisions/011`
  named; the source-scan half is comparable in size to E11-TS's own S1 port
  and is real, sequenced follow-up work, not silently implied by this
  landing.
- `tsconfig.json` (named in `docs/decisions/011`'s own text as an example
  of "cannot read") was evaluated and deliberately not built against:
  it carries compiler/build configuration, not telemetry-vendor signal —
  `package.json` is where that signal actually lives.

## Consequences

- E12's own DoD and `docs/decisions/011`'s "S2 needs its own small epic"
  both move from "unstarted" to "manifest half landed, source-scan half
  named and deferred" — the first candidate consumer's stack (React/TS SPA,
  already carrying Dynatrace, New Relic and Splunk per `docs/decisions/011`)
  is now a case this detection can actually recognize, once piloted.
- No CLI flag was added — `oah inventory` (and everything downstream that
  calls `build_telemetry_inventory`) picks this up automatically the moment
  a target repo has a `package.json`, with zero output change for a repo
  that doesn't.
- **Revisit trigger** (not a recurring spike): a vendor's package name
  changing (a rename, a new official SDK) would silently stop matching —
  same class of risk this project already named for `tree-sitter-typescript`
  version drift (`docs/decisions/014`'s own revisit trigger), worth the same
  posture: not a scheduled recheck, but a known, named failure mode to
  reconsider if a real target's known-installed vendor package stops
  showing up in a scan.
