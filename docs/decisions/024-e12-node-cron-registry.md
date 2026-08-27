# 024 — E12 phase 8: the node-cron registry (scheduled_job) and `imported_namespace_method_call`

Status: landed. Advances E12 (`docs/decisions/011`).

## Context

Of the four point kinds still `declared_undetected` after phase 7,
`scheduled_job` was next. Verified before choosing a library (a live npm
download-count query, not an estimate): `cron` (~6.8M/week, inflated by
transitive `@nestjs/schedule` installs that never call `new CronJob()`
directly), `node-cron` (~5.5M/week), `node-schedule` (~4.4M/week).
`node-cron`'s own README confirms `cron.schedule(cronExpression,
callback)` called **directly on the default-imported module** — no
constructor or factory call first, unlike every registry built so far.

## What was found before building

Neither existing receiver-resolution mechanism fit: `receiver_method_suffix`
requires a `new X()` construction; `module_function_call` (Express)
requires a bare factory call (`express()`) that returns the real
receiver. `node-cron` has neither — the imported name `cron` **is** the
receiver already, bound at the import statement itself.

`ImportResolver.name_alias` already stores this exact `(module, local)`
mapping for every constructor-based registry too (populated at import
time, unconditionally) — it was just never consulted as a receiver
resolution source at the call site, only for `new X()`/`X()` construction.

## What was built

- **`imported_namespace_method_call`**, a third receiver-resolution shape
  added to `schemas/domain_pack.schema.json`'s `detector_shape` enum and
  `oah/discovery/registry.py`'s `_RECEIVER_SHAPES`. Implementation is a
  single fallback in `typescript_adapter.py`'s call-site resolution: when
  `known_names.get(root)` (populated only by a real construction) finds
  nothing, fall back to `resolver.name_alias.get(root)` (the import
  binding itself). No new prescan pass, no new resolver method.
- **Safety argument, not just an assumption**: this fallback is safe for
  every existing constructor-based registry because calling a method
  directly on an unconstructed SDK class (e.g.
  `Anthropic.messages.create(...)` instead of an instance) is not valid
  real-world TypeScript — the fallback only ever fires for genuinely
  namespace-shaped SDKs where no constructed instance exists to prefer.
- `domains/service/pack.json`: a `node-cron` registry entry
  (`constructor_names: ["cron"]`, `method_suffixes: [["schedule"]]`,
  `detector_shape: "imported_namespace_method_call"`). `scheduled_job`'s
  `detected_by` flips from `declared_undetected` to `registry`.
- Real tests: detection against a real `cron.schedule(...)` fixture; the
  default pack (genai) never detects it; a gap-model dimension check.

## Decision

**One library this phase, two real gaps named rather than folded in**:
`cron`'s `new CronJob(cronTime, onTick, ...)` is real (verified, ~6.8M
weekly downloads including transitive NestJS installs) but needs a
**fourth** detector shape — the constructor call itself is the
registration event, with no subsequent method call to suffix-match
against at all, structurally unlike every shape built so far. Not
attempted here. `node-schedule`'s `schedule.scheduleJob(...)` shares
today's new `imported_namespace_method_call` shape exactly and would be a
real, low-effort follow-up registry entry — not added in this phase, to
keep it to one library at a time, matching every prior registry phase's
own discipline.

## Consequences

- A third receiver-resolution shape is now real infrastructure, available
  to any future registry needing it (e.g. `node-schedule`) for free.
- E12's remaining real gaps, unchanged by this phase: two more S1
  registries (`queue_producer`/`queue_consumer` — verified in this same
  session to need a genuinely harder, multi-hop resolution chain
  `amqplib` doesn't fit any existing shape for, deliberately not
  attempted as a low-confidence heuristic), `route_is_templated`/
  `cardinality_guard`, and a real vendored-corpus fixture (E7's own
  territory).
