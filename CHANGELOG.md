# Changelog

## [Unreleased]

### Added
- S2 (existing telemetry inventory) now supports TypeScript
  (`docs/decisions/033`). Found by running the full pipeline against a real
  target repo: `oah inventory` reported 0 findings on a real ~450-file app
  since `telemetry_scanner.py` only ever scanned `*.py` files. New
  `oah/discovery/ts_telemetry_scanner.py` detects `console.*` calls, a
  `winston`/`pino`/locally-defined-logger-class heuristic, `@opentelemetry/*`
  imports, and `try`/`catch` classification (swallowed/logged/reraised).
  Reuses a new shared `oah/discovery/ts_module_resolution.py` (extracted
  from `typescript_adapter.py`'s own cross-file mechanism, docs/decisions/032)
  to resolve a logger singleton exported from one file and imported into
  ~140 consumer files -- the same pattern that forced the axios cross-file
  fix, needed a second time. `oah inventory` gained a `--language` flag;
  `oah/cli.py` gained a `_build_telemetry_inventory` dispatcher wired into
  `inventory`/`gaps`/`dtos`/`readiness`. Verified end to end: 0 -> 759
  logger call sites, 0 -> 688 error_handling entries, and `oah gaps` moved
  from 100% dark to 265 dark / 110 partial on the motivating repo.
- E12 phase 10: `axios` registry (`http_client_call`) and the TypeScript
  adapter's first cross-file known-name propagation mechanism
  (`docs/decisions/032`). Found by running `oah map` against a real EPAM
  target repo (mf-analyzer-web): ~291 real axios call sites, all through
  one shared `axios.create()` instance built in one file and imported into
  ~450 others -- a registry entry alone resolved 0 of them, since every
  known-name mechanism this adapter has ever had was same-file-only.
  `typescript_adapter.py` gained a two-pass repo scan (`_collect_export_map`,
  tsconfig-`paths`-aware `_resolve_module_specifier`) that seeds a
  cross-file-resolved receiver into a consumer file's known_names before its
  walk runs, so every existing detection path handles it unchanged.
  Single-hop only (a re-export chain through a further file is a named,
  tested gap). Verified end to end on the motivating repo: 0 -> 294 real
  call sites detected.
- E8 phase 2: private-gateway visibility (`docs/decisions/031`). Verified
  directly against litellm's own installed source that a base-URL
  override (`ANTHROPIC_API_BASE`/`ANTHROPIC_BASE_URL`) and mTLS
  (`SSL_CERTIFICATE`/`SSL_VERIFY`) already work today via plain
  environment variables, with zero OAH code involved -- E8's own
  "private-gateway mode: unbuilt" was wrong, it was built-but-invisible
  inside a dependency. Not re-implemented; `oah doctor` gained a new
  `llm_gateway` check (informational, never blocking) surfacing whether
  either override is active before a run starts.
- E8 phase 1: secret-pattern redaction (`docs/decisions/030`). New
  `oah/security/redaction.py` -- provider-specific patterns (AWS,
  Anthropic, OpenAI, GitHub, Slack, JWT, PEM private keys) plus a generic
  secret-assignment catch-all, wired into
  `oah/discovery/python_adapter.py`'s `_excerpt` (S1's ambiguous-candidate
  `code_excerpt`, both LLM-sent and state-DB-persisted -- the one real
  leak path identified before this phase; `docs/security.md`'s T2
  mitigation had zero code behind it until now). Found and fixed a real
  bug while building: the generic catch-all was re-matching a value a
  provider-specific pattern had already redacted (the placeholder text
  itself is 8+ chars), downgrading a specific label to the generic one.
- E11-Java phase 1 (`docs/decisions/029`): a real, tree-sitter-based Java
  S1 adapter (`oah/discovery/java_adapter.py`), `--language java` CLI
  dispatch, and a real Anthropic Java SDK registry entry
  (`domains/genai/pack.json`). Verified before building: the real
  `tree-sitter-java` grammar (call chains are nested `method_invocation`
  nodes, not TS's member-expression-then-call split) and the real
  Anthropic/OpenAI Java SDKs' own construction pattern via a background
  research agent -- both build their client through a static builder
  method chain (`X.builder()...build()`/`.fromEnv()`), never `new X()`.
  New `static_builder_chain` detector shape: a chain rooted at a known
  class name, recognized by its LAST segment matching a declared
  `terminal_methods` set (arbitrary builder configuration in between is
  not matched). Class-scoped known-name prescan (mirroring the Python
  adapter, not the TypeScript one -- Java's own OOP shape fits it), plus
  one real Java-specific addition: unqualified instance-field access
  (`client.foo()` with no `this.`) resolves via a fallback to the current
  class's own tracked fields, something neither Python nor TS/JS needs.
  Async detection checks for a `.async()` hop inserted mid-chain (Java has
  no async/await keyword). A real gap found by testing, not designed
  around: a single unassigned expression chaining construction and the
  eventual call together (terminal buried mid-chain) doesn't resolve --
  named and regression-tested, not chased in phase 1.
- E12 phase 9 (`docs/decisions/028`): the `amqplib` registry
  (`queue_producer`/`queue_consumer`) and a fourth, genuinely new
  `detector_shape`, `chain_hop` -- pure known-name-propagation data (no
  surface point of its own) that lets a receiver resolve through more than
  one hop of awaited assignment, needed because amqplib's real API is a
  three-hop chain (`amqp.connect()` -> `await` -> `.createChannel()` ->
  `await` -> the real queue operation) none of the three prior
  receiver-resolution shapes could express. Once resolved, the existing
  `receiver_method_suffix` matching handles the rest unchanged. Found and
  fixed along the way: two different `surface_kind`s (`queue_producer`,
  `queue_consumer`) can share one chain-produced synthetic module, which
  the prior one-entry-per-module lookup couldn't express --
  `typescript_adapter.py`'s `_RegistryContext` gained a `module_to_registries`
  (module -> list) resolved by matched suffix, byte-identical for every
  pre-existing non-colliding module. General by construction: a future
  N-hop SDK is now pure pack data, no adapter code change.
- Signal provenance summary (`docs/decisions/027`): a new top-level
  `signal_provenance` field on `validation_report` combines `--dynamic`'s
  and `--live`'s per-DTO provenance into one real, report-level answer
  (`oah/validate/event_assertion.py`'s `summarize_provenance`).
  Deliberately not wired into `ladder_rung`/`verdict`'s own promotion
  rule -- an informational answer, not a new gate.
- `route_is_templated`/`cardinality_guard` (`docs/decisions/026`): the
  last of `docs/decisions/011`'s two named new gates. A new optional
  `cardinality_guard: {is_templated, unavailable_reason}` field on any
  design_fragment signal, gate-checked for internal consistency
  (`oah/design/gates.py`'s new `check_route_is_templated`, added to the
  domain-neutral `ALL_GATES`). `telemetry-cost`'s own signal is the first
  real consumer. Regenerated E13's golden snapshot (a real, expected
  consequence of a new always-run gate, per that test's own documented
  remedy).
- S11 signal provenance (`docs/decisions/025`): `docs/decisions/011`'s own
  named S11 addition -- whether a validated event came from zero-code
  auto-instrumentation or from code S10 actually edited.
  `oah/validate/live_sandbox.py` now extracts each span's
  `instrumentation_scope`; `oah/validate/event_assertion.py` classifies it
  into a new `provenance` field on `observed` event assertions. Verified
  against a real live OTel SDK capture. `--dynamic`'s own capture
  mechanism structurally can't carry this field (confirmed empirically,
  not assumed) and always reports `["unknown"]`; `--live` gives a real
  answer.
- E12 phase 8 (`docs/decisions/024`): the `node-cron` registry
  (`scheduled_job`) and a third receiver-resolution shape,
  `imported_namespace_method_call` -- for a method called directly on an
  imported module with no constructor/factory step at all. Verified via a
  live npm download-count query before choosing `node-cron` over `cron`
  (inflated by transitive NestJS installs) and `node-schedule`.
- E12 phase 7 (`docs/decisions/023`): the `pg` registry (`db_query`) --
  zero adapter code changes, since `pg`'s `Client`/`Pool` + `.query()`
  is the same `receiver_method_suffix` shape already implemented.
  Verified against node-postgres's own docs before building.
- E12 DoD (a) mechanism proof (`docs/decisions/022`):
  `tests/test_e12_service_pack_integration.py` drives the real S1->S9
  chain against a hand-authored Express+fetch TypeScript fixture through
  the real service pack -- all six lenses, both gate sets, S7/S8/S9 all
  composing end to end. Found and fixed a real bug first: `cmd_readiness`
  discarded `_design_all_lenses`'s `extra_artifacts`, so slo/dependency
  gate findings never reached the readiness decision for the service
  pack. Named honestly as a mechanism proof, not the vendored-corpus
  version of DoD (a), which remains E7's own territory.
- E12 phase 6 (`docs/decisions/021`): the `dependency` lens -- all six of
  E12's lenses are now real (three reused, one adapted, two new). New
  `schemas/dependency_model.schema.json` and `oah/design/dependency_gates.py`
  (3 gates, including the extra-nine rule's real failure-rate arithmetic,
  verified against a digit-count trap). `skills/s4-dependency/` reuses
  phase 5's multi-artifact plumbing (`{design_fragment, dependency_model}`).
- E12 phase 5 (`docs/decisions/020`): the `slo` lens and multi-artifact
  lens support. `oah/cli.py`'s `_design_all_lenses` now unpacks a lens
  whose `emits` has more than one entry into `(fragments, extra_artifacts)`
  -- the deferred work E13 named ("extending design_lens()'s return
  contract... E12 does that when the slo lens actually needs a second
  artifact type"). New `schemas/slo_spec.schema.json` and
  `oah/design/slo_gates.py` (7 gates, including burn-rate recomputation
  verified against `docs/decisions/011`'s own worked table). `skills/s4-slo/`
  emits `{design_fragment, slo_spec}` -- the one skill in this project
  whose output isn't a bare `design_fragment`.
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
