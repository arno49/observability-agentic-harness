# 026 — `route_is_templated` / `cardinality_guard`

Status: landed. Advances E12 (`docs/decisions/011`).

## Context

`docs/decisions/011`'s own new-gate list named `route_is_templated`
("a route attribute is templated, never a raw path") alongside
`critical_dependency_extra_nine`. The latter landed in
`docs/decisions/021`; this one was deliberately deferred at every E12
phase since, each time naming a real, open design question rather than
guessing: is this an S5 design-time gate, or an S11 validation-time
check? A `design_fragment` signal carries no runtime attribute *value* to
check against — only metadata (name, `maps_to`, tier) — so "is this route
templated" can't be answered by inspecting a signal alone unless the
signal itself is made to say so.

## The resolution

Re-reading the ADR's own Consequences passage settled it: "The
`route_is_templated` gate assumed a framework whose route template can be
read from source... The gate stands, but `cardinality_guard`'s
`unavailable_reason` branch becomes the primary path... a server-side SLI
there is built on Dispatcher and CDN logs... not on spans." This is a
**design-time** question — does the lens's own design account for
whether a route's template is staticaly recoverable — not a runtime
assertion. The fix: make the signal self-describing. A `cardinality_guard`
object (`is_templated: bool`, `unavailable_reason: string|null`) on any
signal that needs to make this claim, gate-checked for internal
consistency only (a `false` needs a real reason), with no cross-referencing
of point kinds required at all.

## What was built

- `schemas/design_fragment.schema.json` and
  `skills/s4-telemetry-cost/io/output.schema.json`: both signal item
  schemas gain an optional `cardinality_guard` field (added to the shared
  schema too, not just the skill's own — the first test run against this
  change caught the gap directly: `validate("design_fragment", ...)`
  rejected the field before the shared schema was updated).
- `oah/design/gates.py`: `check_route_is_templated`, added to `ALL_GATES`
  — the **domain-neutral** gate list, not a service-pack-specific one.
  The check itself is domain-neutral by construction (it only inspects
  whether a `cardinality_guard`, when present, is internally consistent);
  today only the service pack's `telemetry-cost` lens ever sets the
  field, but the gate doesn't need to know that.
- `skills/s4-telemetry-cost/SKILL.md`: the `cardinality_risk` signal for
  any route-kind point must now set `cardinality_guard` — `is_templated:
  true` when S1's own detected route shape (`has_path_parameter` plus the
  framework's own registration syntax) guarantees a template;
  `is_templated: false` with a real, specific `unavailable_reason`
  otherwise, using the ADR's own AEM example directly.
- Real tests: `tests/test_gates.py` (the gate's own unit tests, including
  the no-op case for every signal without the field),
  `tests/test_telemetry_cost_lens.py` (the real `design_telemetry_cost`
  path, both the passing `is_templated: true` case and the
  `is_templated: false` case failing without a reason, then passing with
  one).

## A real E13 byte-identical consequence, handled per its own stated procedure

Adding a new entry to `ALL_GATES` means every fragment from every pack —
including genai's own — now carries one additional (always-passing)
`route_is_templated` finding in its `gate_findings`. This broke
`tests/test_e13_domain_pack_snapshot.py`'s committed golden snapshot, a
real, expected consequence of a genuine, intentional gate addition, not a
wiring bug. That test's own module docstring and failure message name
this exact situation and its own remedy: "If this change is real and
intended... regenerate `tests/fixtures/e13_snapshot/naive_memory.json`."
Done — the diff is a clean, minimal six-line addition (the new gate's own
passing finding), confirming nothing else about genai's byte-identical
output shifted.

## Decision

**Self-contained by design, not cross-referenced against S1 point kinds.**
The gate only ever inspects a signal's own `cardinality_guard` field —
it never looks up whether the signal's `surface_point_ids` actually point
at an `http_server_route`/`declarative_route` kind. This keeps the check
simple and correct by construction (no risk of a stale point-kind lookup)
at the cost of not being able to detect "a route-kind signal that should
have set `cardinality_guard` but didn't" — that omission is a `telemetry-cost`
prompt-following question, not something a structural S5 gate can enforce
without the point-kind cross-reference this phase deliberately avoided.

## Consequences

- E12's `docs/decisions/011`-named gate list is now fully landed:
  `critical_dependency_extra_nine` (021) and `route_is_templated` (this
  phase) both real.
- E12's remaining real gaps: two queue registries
  (`queue_producer`/`queue_consumer`, `amqplib` needing a genuinely harder
  multi-hop resolution chain), S11 provenance's own remaining follow-up
  (bubbling into `ladder_rung`/`verdict`, `docs/decisions/025`), and a
  real vendored-corpus fixture (E7's own territory, DoD (a)'s stronger
  form).
