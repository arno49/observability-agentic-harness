# 028 — E12 phase 9: the amqplib registry (queue_producer/queue_consumer) and `chain_hop`

Status: landed. Advances E12 (`docs/decisions/011`), closes the gap named
in `docs/decisions/024`'s own Consequences section.

## Context

`queue_producer`/`queue_consumer` were the last two `declared_undetected`
point kinds in the service pack. `docs/decisions/024` already investigated
amqplib (RabbitMQ's Node client) as the candidate library and found — via a
background research agent against amqplib's own README/API docs, not a
guess — that its real API is a **three-hop async resolution chain**:

```
const conn    = await amqp.connect(url);        // hop 1: namespace -> Connection
const channel = await conn.createChannel();      // hop 2: Connection -> Channel
channel.sendToQueue(queue, content);              // hop 3: the real operation, on the Channel
```

None of the three existing receiver-resolution shapes fit:
`receiver_method_suffix` (pg) resolves one hop via `new X()`;
`module_function_call` (Express) resolves one hop via a bare factory call;
`imported_namespace_method_call` (node-cron) resolves **zero** hops — the
import itself is the receiver. All three stop at the first hop from
import/construction to the eventual method call. amqplib needs the
known-name prescan to propagate "this variable is a Channel from amqplib"
through **two** already-tracked intermediate variables, a capability that
did not exist in `oah/discovery/typescript_adapter.py` before this phase.

A cheap heuristic — matching `sendToQueue`/`consume`/`publish` by bare
method name with no receiver resolution at all — was considered and
rejected in the same investigation that produced `docs/decisions/024`:
unlike `fetch()` (SP12's `global_unimported_callee` shape, safe because
`fetch` as a bare global identifier is exotic/unambiguous), these method
names are generic enough to collide with unrelated APIs on unrelated
objects. No registry in this pack has ever reported an unresolved
receiver as a match; doing so here would be a real precision regression,
not a shortcut.

## What was built

- **`chain_hop`**, a new `detector_shape` (`schemas/domain_pack.schema.json`)
  that is deliberately **not** a surface-point detector at all — it is pure
  known-name propagation data: `sdk_module` (the already-resolved module a
  receiver must be known as), `via_method` (the method called on it),
  `produces_module` (a synthetic module string, e.g. `"amqplib#connection"`,
  that the assignment's target variable becomes known as). A chain of N
  hops is N `chain_hop` entries, each one's `sdk_module` matching the
  previous one's `produces_module`; the first entry's `sdk_module` is a
  real module name, resolved exactly like `imported_namespace_method_call`
  resolves one. `surface_kind` was relaxed from schema-required to
  shape-conditional (matching the existing convention for
  `content_signal`/`detector_name`), since a `chain_hop` entry has none.
- `oah/discovery/registry.py`: `chain_hop_index(pack, language)` derives
  `{(sdk_module, via_method): produces_module}` from a pack's `chain_hop`
  entries; `build_registry_index` folds their `constructor_names` into its
  existing union (so the chain's first-hop import, e.g. `amqp`, gets
  tracked by `ImportResolver` the same way `imported_namespace_method_call`
  needs).
- `oah/discovery/typescript_adapter.py`:
  - `_unwrap_await` peels an `await_expression` before every known-name
    check (`new_expression`/factory call/chain hop) — every real hop in
    amqplib's chain is awaited, unlike any existing registry's construction
    call.
  - `_resolve_receiver_module` factors out the two-step lookup (`known_names`
    first, `resolver.name_alias` fallback second) already used at call
    sites, now shared with the new prescan step.
  - `_resolve_chain_hop`: given a `<receiver>.<method>()` value node, if
    the receiver already resolves to a module the pack's `chain_hops` table
    tracks, returns the hop's `produces_module`. Wired into both the
    `variable_declarator` and `assignment_expression` known-name prescan
    branches — a variable assigned from a chain hop becomes known under the
    synthetic module, and from that point on the **existing**
    `receiver_method_suffix` machinery handles the eventual method-suffix
    match with no further new code path.
  - **One real wrinkle, not anticipated when `docs/decisions/024` scoped
    this as future work**: `queue_producer` and `queue_consumer` are two
    *different* `surface_kind` entries that legitimately share the same
    `produces_module` (`"amqplib#channel"` — a single real Channel variable
    calls both `sendToQueue` and `consume` in real code). The pre-existing
    `module_to_registry` (one entry per `sdk_module`, last-write-wins) can't
    express that. `_RegistryContext` gained a parallel `module_to_registries`
    (module → list), and call-site resolution now picks whichever entry's
    own `method_suffixes` contains the matched suffix, not the module alone.
    For every module with exactly one registry (every module before this
    phase) this is behaviorally identical to the old single-entry lookup.
- `domains/service/pack.json`: two `chain_hop` entries (`amqp.connect` →
  `"amqplib#connection"`, `.createChannel()` → `"amqplib#channel"`) plus two
  `receiver_method_suffix` entries keyed off `"amqplib#channel"`
  (`queue_producer`: `sendToQueue`/`publish`; `queue_consumer`: `consume`).
  Both point kinds flip from `declared_undetected` to `registry`.
- Real tests: `tests/test_typescript_adapter.py` gets a generic,
  amqplib-independent regression suite against a minimal synthetic
  two-hop pack (proves the *mechanism*, not one SDK's shape) — including a
  negative case that skipping a hop doesn't accidentally resolve, and that
  the mechanism works with or without `await`. `tests/test_service_pack.py`
  gets the real amqplib registry's own tests: producer detection, consumer
  detection, both on the same `channel` variable, `connect`/`createChannel`/
  `assertQueue` producing zero spurious points, the unrelated-local-import
  precision guard (same pattern as node-cron's own), and gap-model
  dimension checks for both kinds (`dependency` for producer, `routing` for
  consumer — an inbound entrypoint, not an outbound call).

## Decision

**A general chained-hop mechanism, not a one-off amqplib hardcode.**
`docs/decisions/024`'s own text posed this as a choice between "obscured
generality" and "a point-hardcode that the next multi-hop library would
need its own version of." `chain_hop` is pack-data, language-adapter-generic
(nothing amqplib-specific lives in `typescript_adapter.py` itself), and
composes with the *existing* `receiver_method_suffix` machinery instead of
duplicating it — a future N-hop SDK (e.g. `kafkajs`'s
`kafka.producer()` → `producer.send()`, a real two-hop shape noted but not
built in `docs/decisions/024`) is now a pure pack-data addition, no adapter
code change.

**Two real, named exclusions, not silently folded in**: `assertQueue`
(queue/topology declaration, not a produce/consume event) and
`createConfirmChannel()` (a real alternate second hop). Both are named in
their registry entries' own `confidence_note`, not guessed at.

## Consequences

- E12's S1 registry set for the service pack is now four entries deep
  (Express, pg, node-cron, amqplib) across all four detector-shape
  families that exist (`module_function_call`, `receiver_method_suffix`,
  `imported_namespace_method_call`, `chain_hop`).
- E12's remaining real gaps: no real TS corpus repo has been run through
  this adapter yet (every registry here is docs-grounded, stated in each
  entry's own `confidence_note`) — E7's own territory; `route_is_templated`/
  `cardinality_guard` for the two new kinds was not revisited (a queue
  operation has no route template to guard); and whether `queue_consumer`
  should get its own `slo` lens treatment (today only
  `http_server_route`/`declarative_route` do) is a real, separate design
  question, not decided here.
