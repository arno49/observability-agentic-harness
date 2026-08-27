# 023 — E12 phase 7: the pg registry (db_query)

Status: landed. Advances E12 (`docs/decisions/011`).

## Context

Of the four point kinds still `declared_undetected` after phase 6
(`db_query`, `queue_producer`, `queue_consumer`, `scheduled_job`),
`db_query` is both the most common in real service backends and — unlike
Express — needed no new adapter mechanism. `pg` (node-postgres), the
dominant PostgreSQL client for Node.js/TypeScript, uses ordinary
constructor-based clients (`new Client()`/`new Pool()`) with a single
`.query()` method — the exact `receiver_method_suffix` shape
Anthropic/Pinecone/LangSmith already use, already fully implemented.

Verified before building, matching this project's own standing
discipline (a background research pass against node-postgres.com, not
assumed from memory):

- `Client` and `Pool` are both real, current, non-deprecated exports.
- Both expose the same `.query(text, values?)` method — `Pool.query`
  auto-acquires/releases a pooled `Client` internally. No dual-purpose-
  method ambiguity the way Express's `.get()` had (settings-getter vs.
  route registration) — `.query()` has exactly one meaning, so no
  argument-count guard was needed here, unlike Express's phase.
- Import shape varies by version and module system: named ES imports
  (`import { Client, Pool } from "pg"`) only work natively since pg
  v8.15; earlier versions and some bundler setups need
  `import pg from "pg"; const { Client, Pool } = pg;` (default import
  then destructure) or CommonJS `require()` destructuring.

## What was built

- `domains/service/pack.json`: a `pg` registry entry
  (`sdk_module: "pg"`, `constructor_names: ["Client", "Pool"]`,
  `method_suffixes: [["query"]]`, `detector_shape: "receiver_method_suffix"`)
  — **zero adapter code changes**, purely a data-only addition, since the
  named-import + `new X()` + method-suffix shape was already fully
  implemented. `db_query`'s `point_kinds[].detected_by` flips from
  `declared_undetected` to `registry`.
- Real tests (`tests/test_service_pack.py`): a named-import `Client`
  query detected; `Pool.query` also detected; the default-pack case
  (genai) never detects `pg` calls, confirming zero behavior change; a
  gap-model dimension check (`db`); and a `require()`-form negative test
  confirming the named, real gap this entry doesn't cover.

## Decision

**Deliberately narrow, three real gaps named rather than silently assumed
covered** (the same discipline the Express registry's own
`confidence_note` established):

- **CommonJS `require("pg")` destructuring** — no registry in this pack
  has ever supported `require()`; a pre-existing limitation of
  `ImportResolver`, not a new gap this entry introduces.
- **The default-import-then-destructure form**
  (`import pg from "pg"; const { Client, Pool } = pg;`) — still common
  for pg < 8.15 and some bundler configurations; `ImportResolver` only
  populates `name_alias` from the import statement itself, not from a
  subsequent destructuring `variable_declarator`.
- **`new pg.Client()` namespace-member construction** — a member-expression
  constructor, which `resolve_constructor_call` doesn't resolve today
  (the same class of gap `express.Router()` was left named for in the
  Express registry).
- **`postgres` (postgres.js)**, a real and increasingly common
  alternative Postgres client with a materially different tagged-template
  API shape, has no registry entry — not guessed at.

## Consequences

- `db_query` moves from fully undetected to registry-detected for the
  named-import shape — `slo`/`dependency`/`pii-governance` (all of which
  target or reach `db_query` points) can now be exercised against real
  detected database call sites, not just hand-built fixture points.
- E12's remaining real gaps, unchanged by this phase: three more S1
  registries (`queue_producer`/`queue_consumer`/`scheduled_job`),
  `route_is_templated`/`cardinality_guard`, S11 signal provenance, and a
  real vendored-corpus fixture (E7's own territory).
