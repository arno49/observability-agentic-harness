# 022 — E12 DoD (a): a real S1→S9 mechanism proof, and a real `cmd_readiness` gap fix

Status: landed. Advances E12 (`docs/decisions/011`, DoD (a)).

## Context

E12's DoD (a): "a corpus fixture in this domain passes S1→S9 and clears
S5/S6." With all six lenses real (phases 1–6), this was the first point
where attempting that proof was possible at all. Building it surfaced a
real, separate bug worth fixing before the proof could be trusted.

## What was found before the proof could be built

`cmd_readiness` (S9) calls `_design_all_lenses` and discarded its second
return value entirely (`fragments, _extra_artifacts = ...`) — meaning
`slo_spec`/`dependency_model` gate findings (`docs/decisions/020`/`021`)
never reached S9's `gate_findings`, only `cmd_design`'s. A readiness
decision for the service pack would have silently ignored every
slo/dependency gate result — the exact "an artifact exists but nothing
downstream checks it" gap this project's own discipline exists to catch.
Found by design review while wiring the integration test below, before
any test ran, not by a failing assertion.

## What was built

- **`oah/cli.py`'s `cmd_readiness`**: now unpacks `extra_artifacts` the
  same way `cmd_design` already does, running `run_slo_gates`/
  `run_dependency_gates` and folding their findings into `gate_findings`
  before `build_readiness_report` runs. `cmd_event_schema`/`cmd_dtos`
  were checked too — neither computes S5 gate findings at all (genai's
  own pre-existing behavior), so there was nothing to fix there.
- **`tests/test_e12_service_pack_integration.py`**: a real S1→S9 run
  through `cmd_readiness`, `--pack service --language typescript`,
  against a small, hand-authored Express+`fetch` TypeScript fixture (one
  parameterized route, one static route, one outbound dependency call).
  Only the LLM-calling stages are mocked (all six lenses, one S6 persona,
  S8's DTO generation) — the same pattern `tests/test_cli_readiness.py`
  already established for genai, extended to a pack with two
  multi-artifact lenses. Verified directly, not just asserted: printing
  the real report showed S1 detecting all three points for real, all six
  lenses' signals present in the merged `event_schema.json`
  (`key_signals` lists `oah.tracing.signal` through
  `oah.dependency.signal`), S5's ordinary gates AND the new slo/dependency
  gates passing (no gate-failure warnings), S6's `sre`/`security`
  personas correctly skipping via the real missing-credentials path (not
  mocked, matching the existing genai test's own precedent), S8
  proposing one DTO, and S9 reaching a real `remediate_before_release`
  decision (gaps remain dark — DTOs proposed, not yet applied via S10;
  the same conservative ceiling the genai integration test already
  documents).

## Decision

**Named honestly as a mechanism proof, not the full DoD (a).** The test's
own docstring states this directly: the fixture is hand-authored, not a
vendored real-world repository — that remains E7's own separate
territory. What this actually proves is that S1 (real detection against
the real Express registry), S3, S4 (all six lenses, including both
wrapper-shaped ones), S5 (both gate sets), S7, S8, and S9 genuinely
compose end to end for this pack, including the two multi-artifact
lenses' gate findings actually reaching the readiness decision now that
the `cmd_readiness` gap above is fixed. A real vendored-corpus proof
(the stronger claim DoD (a)'s own text点s toward) is not attempted here.

## Consequences

- The `cmd_readiness` fix is a real, if latent, correctness improvement
  independent of this proof — it was already wrong for any future pack
  with a multi-artifact lens, the same class of gap `docs/decisions/016`'s
  own lens-filtering bug was.
- E12's remaining real gaps, unchanged by this phase: four more S1
  registries (`db_query`/`queue_*`/`scheduled_job`), `route_is_templated`/
  `cardinality_guard`, S11 signal provenance, and the real vendored-corpus
  version of DoD (a) that E7 would need to actually source and verify.
