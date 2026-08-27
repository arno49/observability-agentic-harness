# Changelog

## [Unreleased]

### Added
- E12 phase 4 (`docs/decisions/019`): the `telemetry-cost` lens
  (`skills/s4-telemetry-cost/`), adapted from genai's `cost` -- token
  accounting becomes cardinality/sampling/retention accounting.
  Cross-cutting, unlike `cost`. Cardinality risk is directly informed by
  S1's own `has_path_parameter` field on route points. No new S5 gates
  needed.
- E12 phase 3 (`docs/decisions/018`): the Express registry (`http_server_route`),
  DoD (c)'s second structurally-different detector shape. Implemented
  `module_function_call` for real (named in the schema since E13, never
  built) and made `oah/discovery/typescript_adapter.py`'s registry
  resolution pack-parameterized (`pack=` on `detect_file`/`detect_repo`/
  `build_surface_map`, default genai, byte-identical). New `--pack
  {genai,service}` CLI flag on `map`/`gaps`/`design`/`event-schema`/`dtos`/
  `readiness` (default `genai`). Docs-grounded, not corpus-verified --
  named explicitly.
- E12 phase 2 (`docs/decisions/017`): the anti-redundancy gate (DoD (d)).
  `generate_dtos` now refuses any model-proposed DTO whose every
  `expected_events[].required_attributes` entry is already covered by the
  loaded pack's `auto_instrumentation_baseline` -- reported under a new,
  additive `refused_dtos` field, never given a rollout step. Zero behavior
  change for genai (declares no baseline).
- E12 phase 1 (`docs/decisions/016`): `domains/service/pack.json`, the
  service domain pack's skeleton -- seven point kinds and the three lenses
  (`tracing`, `ops`, `pii-governance`) reused unchanged from genai, verified
  for real against real SKILL.md files and real S5 gates. Fixed a real bug
  found along the way: every `design_*` wrapper but `design_tracing`
  hardcoded its own point-kind filter instead of reading the loaded pack's
  `lenses[].target_kinds` -- filtering now happens once, pack-driven, in
  `oah/cli.py`'s `_design_all_lenses`. `schemas/domain_pack.schema.json`'s
  `detected_by` enum gains `fixed_pass` for E11-TS's hardcoded (not
  registry-driven) detector passes.
- SP11 resolved: DB/messaging/RPC/browser semantic-convention stability
  checked against primary sources (`docs/decisions/012`). `db.*` is stable
  for the spans/collection-name/operation-duration attributes E12 needs;
  `messaging.*` is development (with a real `receive`-is-CLIENT-not-CONSUMER
  span-kind wrinkle for `queue_consumer`); `rpc.*` sits at OTel's
  intermediate "release candidate" stage, a rung `domain_pack.schema.json`'s
  `stability` enum didn't have a name for until this change (added, purely
  additive, no existing pack uses it); `browser.*` is development but
  ordinary client request timing already rides on the already-stable
  `http.client.*` namespace. `error.type` confirmed stable and conditionally
  required on both HTTP duration histograms, so a good/valid-event
  availability SLI is computable from metrics alone, no spans required.
- SP12 resolved: two TS detector shapes the Python adapter doesn't have --
  declarative route registration (JSX `<Route>`, `createBrowserRouter`
  route-object arrays) and a global unimported callee (bare `fetch(...)`)
  -- prototyped in `spikes/sp10-multilang/ts-adapter/detect.js`
  (`docs/decisions/013`). 14/14 (100%) recall, 0 false positives across 4
  real TS corpus repos (3 existing + one newly sourced, `cocktail-app`,
  MIT-licensed); `wechatbot`'s ground truth extended with 6 real `fetch()`
  sites the new shape surfaced as unrecorded, same precedent
  `docs/decisions/011` already set. `schemas/domain_pack.schema.json`'s
  `detector_shape` enum gains `declarative_registration` and
  `global_unimported_callee` (purely additive). Two design-time bugs
  caught and fixed by the spike's own smoke test before real corpus code
  was even touched: path parameters (`:id`) live inside React Router's
  string literal itself, not as a separate JS expression; a file-wide
  shadow check for `fetch` wrongly suppressed unrelated genuine global
  calls elsewhere in the same file, fixed with a real (partial) lexical
  scope walk.
- E11-TS phase 1: `oah/discovery/typescript_adapter.py`, a real,
  tree-sitter-based S1 adapter for TypeScript/TSX (`docs/decisions/014`).
  SP10 already decided against porting `detect.js` (the Node/compiler-API
  spike) into `oah/` -- this is a fresh implementation of SP10's own
  three-phase shape plus SP12's two detector shapes, against
  `tree-sitter-typescript` instead (pure-Python, no Node.js runtime
  dependency). Reaches the exact recall SP10+SP12 already measured: 14/14
  (100%), 0 false positives, verified against all 4 real corpus repos.
  `schemas/domain_pack.schema.json`'s `registries[]` gained a `language`
  field (purely additive) so one pack can declare per-language SDK
  registries for the same domain; `domains/genai/pack.json` now has a real
  TypeScript Anthropic-SDK entry alongside the Python one. Not yet wired
  into `oah/cli.py`'s command dispatch or vendored into `corpus/` -- named
  explicitly as follow-up work, zero user-visible CLI change from this
  phase.
- CLI language dispatch: `--language {python,typescript}` on `map`, `gaps`,
  `design`, `event-schema`, `dtos`, `readiness` (default `python`, unchanged
  behavior). Fixed a real interface gap the dispatch wiring surfaced:
  `typescript_adapter.build_surface_map` returned a bare dict instead of
  `python_adapter`'s own `(surface_map, still_ambiguous)` 2-tuple, so the
  E11-TS decision record's "swap adapters without touching downstream" claim
  didn't actually hold until this fix. `run_manifest.json`'s pre-existing
  `primary_language` field is no longer hardcoded to `"python"`.
- S2 manifest-based vendor telemetry detection (`docs/decisions/015`):
  `oah/discovery/manifest_scanner.py` scans a target repo's root
  `package.json` dependencies against a verified vendor table (OpenTelemetry
  JS, Dynatrace, New Relic, Splunk, Datadog, Sentry, winston, pino,
  prom-client, StatsD clients) and reports them under a new
  `vendor_dependencies` array in `telemetry_inventory.schema.json`
  (additive; no existing field changed shape). Runs unconditionally inside
  `build_telemetry_inventory`, no new CLI flag. Deliberately the smaller
  half of S2's TypeScript gap -- real source-level TS logger/error-handling
  scanning remains unbuilt, named as follow-up.

### Changed
- ROADMAP.md: E12 ("second domain pack") rewritten from an unpicked stub into a
  concrete, sequenced epic — service domain pack (ordinary request-driven
  services), informed by a real first candidate consumer. New E13 ("domain pack
  extraction") lands as its hard prerequisite: an enumeration of the sixteen
  places GenAI is hardwired into pipeline core found the domain-agnostic claim in
  README's "Why" true for S5–S11 and false for the seam itself — see
  `docs/decisions/011-service-domain-pack-architecture.md`. E12 no longer depends
  on M4 for design (still does for evidence); it now depends on E13, E11's
  TypeScript half, and two new spikes (SP11: DB/messaging/RPC/browser semconv
  stability; SP12: two TS detector shapes the Python adapter lacks).

### Added
- E13 (domain pack extraction): `schemas/domain_pack.schema.json`,
  `oah/domains/loader.py`, and `domains/genai/pack.json` — the GenAI domain now
  ships as a data manifest (point kinds, S1 registries, lens roster, semconv
  namespaces, DTO event types, advisory word pairs) instead of sixteen literals
  spread across `oah/cli.py`, `oah/design/gates.py`,
  `oah/discovery/{gap_model,registry,python_adapter}.py` and eight schema files.
  Verified byte-identical against the pre-extraction behavior via a new
  golden-snapshot test (`tests/test_e13_domain_pack_snapshot.py`) and proven to
  actually generalize via a throwaway second pack running real S3/S5/S7/S8 with
  zero edits under `oah/` or `schemas/` (`tests/test_domain_pack_loader.py`).
  `oah/discovery/disambiguate.py` gained a runtime check (kind must be one of the
  loaded pack's declared kinds) to replace the protection five schema enums lost
  when they opened from closed lists to pack-validated strings.
- `oah instrument`: S10 agentic instrumentation, both modes. `report-only`
  (default) proposes a diff per DTO, never writes. `--mode fix` writes and
  creates one git commit per successfully verified DTO; requires
  `--readiness` (must be `ready`/`ready_with_conditions`) and a clean
  working tree; any failure past verification rolls back cleanly. Covers
  4 of 13 `change.type` values (pure source edits).
- `oah validate`: S11 R4, static-only — for each applied DTO, checks its
  expected attribute names appear in the code at or after its anchor.
  `--dynamic`: a real deterministic regression gate and per-DTO
  event-emission assertion, both over one Docker-sandboxed run of the
  target's own test suite (E6 R2's mechanism). A static trace-ID-
  propagation check for `propagate_context` DTOs runs unconditionally.
  Together these let `ladder_rung` reach `"R2"` / `verdict: "validated"`
  for the first time.
  `--live`: E6 R1's mechanism — starts the target as a real running
  service alongside a real local OTel Collector on an internet-isolated
  Docker network, drives real traffic, reports real captured
  requests/latency, per-DTO event assertions, an `event_schema.json`
  unknown-attribute check, and real TCR (Trace Completeness Rate,
  `docs/architecture.md`'s own primary metric).
  `--baseline` (with `--live`): runs the target's real pre-instrumentation
  code (a `git worktree` at the pre-instrumentation SHA) and reports real
  measured latency overhead against each applied DTO's declared budget.
  With `--dynamic --live --baseline` combined, `ladder_rung` can now
  reach `"R1"` for real — every rung `docs/validation.md`'s ladder
  defines short of R3 is reachable through the real pipeline.
- `oah backend-config` (E9): deterministic `otel-collector-config.yaml`
  generation for `otel-only` or `langfuse` targets, no LLM/agent call.
- E10 self-telemetry: every real LLM/Agent-SDK call OAH's own pipeline
  makes emits a real `opentelemetry-sdk` span to `.oah/traces/oah.jsonl`.
- Initial design package: README, roadmap (epics + spikes), pipeline
  architecture (4 phases / 11 stages), target event model, skills system,
  validation ladder, harness security model.
- Artifact JSON Schemas: surface map (S1), gap model (S3), implementation DTO (S8),
  instrument report (S10), validation report (S11).
- First skill draft: s1-surface-mapper (disambiguation role); S10 instrumenter
  skill now names a concrete telemetry API (`opentelemetry.trace`/`context`)
  instead of leaving emission library choice to the agent.
- Packaging: `oah` installable via `pip install oah`; `.github/workflows/publish-pypi.yml`
  publishes to PyPI via Trusted Publishing (OIDC) on a `v*` tag push.
  `litellm` is now an optional `oah[llm]` extra; `--model` CLI flag to
  switch provider/local model.

### Fixed
- `apply_dto_fix`'s `git commit` call relied on ambient global git config
  for author identity, which exists on dev machines but not on a fresh CI
  runner — passed explicit `-c user.name`/`-c user.email` instead.
- The OTel Collector's `otel/opentelemetry-collector` image runs as a
  non-root UID by default; a bind-mounted output file owned by the host
  user wasn't writable to it under a real Linux Docker daemon (worked
  locally under Docker Desktop's more permissive bind-mount layer, so
  this only ever failed in CI) — made the file world-writable, and added
  a real liveness check so a collector that starts then crashes is now a
  diagnosable error instead of a silent empty result.
