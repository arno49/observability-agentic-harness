# Changelog

## [Unreleased]

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
