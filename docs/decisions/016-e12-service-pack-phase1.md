# 016 — E12 phase 1: the service domain pack's skeleton and its three reused lenses

Status: landed (partial — see Decision for what this phase deliberately
does not cover). Advances E12 (`docs/decisions/011`).

## Context

By this point in the session, every blocker `docs/decisions/011` named for
E12 had actually landed: E13 (domain pack extraction), E11-TS phase 1 plus
CLI language dispatch, SP11 (DB/messaging/RPC stability), and SP12 (TS
detector shapes). E12 itself — the service pack — had not been started.

E12 is genuinely epic-sized: six point kinds, six lenses (three reused
unchanged, one adapted, two new), an anti-redundancy gate, new S1 detector
registries, and real domain content (SLO burn-rate math, dependency
criticality). Attempting all of it in one pass would violate this
project's own "smallest honest slice" discipline, the same reasoning that
split E13 from E12 in the first place. This phase is the first slice:
the pack manifest itself, and a real, verified answer to E12's own DoD
(b) — "the three reused lenses run with no edit to their SKILL.md files."

## What was built

- `domains/service/pack.json` (new): seven point kinds (`declarative_route`,
  `http_server_route`, `http_client_call`, `db_query`, `queue_producer`,
  `queue_consumer`, `scheduled_job`), three lenses (`tracing`, `ops`,
  `pii-governance`, each `reused_from: "genai"`, same skill directories,
  zero SKILL.md edits), `semconv_namespaces` using SP11's real findings
  (`http`/`db` stable, `messaging` development, all pinned to
  `https://opentelemetry.io/schemas/1.44.0` per `docs/decisions/012`'s own
  citation), and an `auto_instrumentation_baseline` (route/duration/
  `error.type` — declared, not yet gate-enforced, see Decision).
- `schemas/domain_pack.schema.json`: `point_kinds[].detected_by` gains
  `fixed_pass` — a real, missing vocabulary gap this phase's own design
  work surfaced. E11-TS's TypeScript adapter already emits
  `declarative_route`/`http_client_call` via hardcoded passes (SP12), not
  a `registries[]` table entry — neither `registry` nor `structural_pattern`
  honestly described that shape.
- **A real bug found and fixed, not routed around**: every `design_*`
  wrapper in `oah/design/lens.py` but `design_tracing` hardcoded its own
  point-kind filter (`design_ops` filtered to `kind == "llm_generation"`,
  etc.) instead of reading it from the loaded pack's own
  `lenses[].target_kinds`. `oah/cli.py`'s `_design_all_lenses` now does
  that filtering once, driven by pack data, and every `design_*` wrapper
  is a pure pass-through — the same contract `design_tracing` already had.
- `tests/test_service_pack.py` (new): loads the real service pack, proves
  `_design_all_lenses` filters each of the three lenses to the right point
  subset, calls the real `design_tracing`/`design_ops`/`design_pii_governance`
  functions (real `SKILL.md`, real output-schema validation, mocked LLM
  call only) against real service-domain points and confirms each produces
  a fragment that passes S5 gates, and confirms `declarative_route`/
  `http_client_call` points are now gap-model-visible via S3.
- 8 existing lens test files updated: the `test_filters_to_<kind>_only`
  test each one had is superseded by `_design_all_lenses`'s own new
  filtering responsibility — renamed to prove the opposite (no internal
  filtering) and a shared regression test added at the caller level.

## Findings

1. **E13's own "the seam exists" claim was incomplete, and a second real
   pack is what actually proved it.** `_point_ids_for_fragment` (used
   after a fragment already exists, for gate-checking) already read
   `target_kinds` from the pack correctly. `oah/design/lens.py`'s
   wrappers — used *before* a fragment exists, to decide which points a
   lens even sees — did not. Confirmed directly, not assumed: calling
   `design_ops` with a real `http_server_route` point (no live model call
   mocked to assert it should never fire) returned `None` silently,
   before any fix. `genai`'s own behavior never exposed this because the
   pack was extracted *from* those exact literals in E13 — a
   single-instance abstraction, the same risk class SP10 already named
   for languages and this session's E13 test suite already named for
   packs, caught here in the one place a single instance can't catch it.
2. **`declarative_route` is real, already-detected, service-domain
   vocabulary that no pack owned until now.** `docs/decisions/014` named
   this gap explicitly and deferred it to E12; this phase is where that
   deferral is paid off. The E12 ADR's own point-kind list only names
   `http_server_route` (a not-yet-built server-side detector) — this
   phase adds `declarative_route` alongside it as a distinct, already-real
   kind (client-side SPA routing), since the first real candidate
   consumer's stack is exactly a client-side SPA and "the four business
   journeys *are* the routes" (`docs/decisions/011`) refers to routes this
   adapter can already see.
3. **`pii-governance`'s target_kinds for the service domain is a real
   design call, not mechanical.** Set to `["http_server_route",
   "declarative_route", "db_query"]` — the points most likely to carry
   request/stored user data — rather than reusing genai's
   `["llm_generation"]` verbatim (which would silently match nothing) or
   defaulting to cross-cutting like tracing/ops. A judgment call, stated
   as one, revisitable once the real candidate's own S1 output is
   available to check it against.

## Decision

Land the pack skeleton, the three reused lenses (real, verified), and the
lens.py bug fix. Everything else E12's own DoD names is explicitly
deferred, not silently implied by this landing:

- **`telemetry-cost`, `slo`, `dependency`** — not reused unchanged; each
  needs genuine new skill content (cardinality/sampling accounting,
  burn-rate derivation, dependency-criticality rules — `docs/decisions/011`'s
  own Finding 3 already worked out the burn-rate math, not yet turned into
  a skill). Comparable in size to building three new S4 lenses from
  scratch.
- **New S1 detector registries** for `http_server_route`, `db_query`,
  `queue_producer`, `queue_consumer`, `scheduled_job` — all still
  `declared_undetected`. Each needs real per-library call-shape research
  (Express/Fastify route registration; `pg`/`mysql2`/Prisma for DB;
  `amqplib`/`kafkajs`/BullMQ for queues; `node-cron`/`node-schedule` for
  scheduled jobs), the same SP1/SP10-grade verification discipline every
  existing registry entry in this project required — not guessed at here.
- **The anti-redundancy gate** (DoD (d)) — `auto_instrumentation_baseline`
  is declared in the manifest but no gate reads it yet. A real, separate
  piece of gate logic (S5 or S8), not attempted in this phase.
- **The new S5 gates `docs/decisions/011` names** (burn-rate recomputation,
  alert-tier/window pairing, `route_is_templated`/`cardinality_guard`,
  `single_correlation_backbone`, `critical_dependency_extra_nine`) — all
  depend on the slo/dependency lenses existing first.
- **S11 signal provenance** (auto-instrumentation vs. harness-edited
  evidence) — named in the ADR, not started.
- **A corpus fixture** — DoD (a) ("a corpus fixture in this domain passes
  S1→S9") is not attempted; this phase's own service points are hand-built
  test fixtures, the same precedent `tests/test_domain_pack_loader.py`'s
  throwaway pack already set for proving a mechanism without a real corpus.

## Consequences

- E12's DoD (b) is now concretely true, not just designed for: verified
  against the real pack, the real skill files, and real S5 gates.
- The lens.py fix is a real, if latent, correctness improvement to the
  *existing* genai pack's own extensibility story — it was already broken
  for any future third pack, not just this one; E12 is simply what
  surfaced it.
- E12 remains far from done. The remaining pieces (two new lenses, five
  new registries, the anti-redundancy gate, new S5 gates, S11 provenance,
  a corpus fixture) are each real, separately-sequenced units of work —
  named here so the epic's own remaining shape is visible, not
  rediscovered piecemeal.
