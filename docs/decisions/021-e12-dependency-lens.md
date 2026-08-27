# 021 — E12 phase 6: the dependency lens — all six lenses now real

Status: landed. Advances E12 (`docs/decisions/011`).

## Context

`dependency` is the last of E12's six lenses: three reused unchanged
(`tracing`, `ops`, `pii-governance`), one adapted (`telemetry-cost`), and
two new (`slo`, landed in `docs/decisions/020`; `dependency`, this phase).
Per the ADR: "edge criticality, the extra-nine rule, and budget split
between own failures and dependency failures." Structurally the same
shape of problem `slo` already solved — a real structure
(criticality/target/split/fallback per edge) that isn't expressible as
`design_fragment`'s flat signal list — so this phase reuses the
multi-artifact plumbing `docs/decisions/020` built rather than adding to
it.

## What was built

- **`schemas/dependency_model.schema.json`** (new): one entry per
  dependency edge — `dependency_kind` (`http_client_call`/
  `queue_producer`), `criticality` (`hard`/`soft`), `own_target`,
  `required_dependency_target`, a `budget_split` (two fractions), and a
  required `fallback_behavior`.
- **`oah/design/dependency_gates.py`** (new, separate from `gates.py` and
  `slo_gates.py` for the same reason those two are separate from each
  other): three gates.
  - `check_critical_dependency_extra_nine` — the real arithmetic behind
    "one nine better": a **hard** edge's dependency failure rate `(1 -
    required_dependency_target)` must be at most one-tenth of the
    dependent's own failure rate `(1 - own_target)`. Deliberately verified
    against a real trap in the tests: `own_target: 0.999` (0.1% own
    failure budget) paired with `required_dependency_target: 0.9995`
    *looks* like "more nines" by digit count but is only a 2x tighter
    bound, not the required 10x — the gate catches this; a naive
    "does the target have more decimal 9s" check would not have.
  - `check_budget_split_sums_to_one` — the two `budget_split` fractions
    must sum to exactly 1.0.
  - `check_every_edge_names_fallback_behavior` — required, non-trivial,
    for every edge (hard or soft).
- **`skills/s4-dependency/`** (new): `SKILL.md` teaches the extra-nine
  formula in failure-rate terms explicitly, with the same worked-example
  discipline `s4-slo`'s own burn-rate section established, and states the
  digit-count trap directly ("do not simply add one to the digit after
  the decimal and call it done"). `io/output.schema.json` is a wrapper
  (`{design_fragment, dependency_model}`, both required) — the second
  skill in this project (after `s4-slo`) whose output isn't a bare
  `design_fragment`.
- `oah/design/lens.py`: `design_dependency`, documented the same way
  `design_slo` is.
- `domains/service/pack.json`: `dependency` lens entry, `target_kinds:
  ["http_client_call", "queue_producer"]` (the two dependency-dimension
  point kinds already in this pack), `emits: ["design_fragment",
  "dependency_model"]`.
- `oah/cli.py`'s `cmd_design`: `run_dependency_gates` wired in alongside
  `run_slo_gates` — the multi-artifact unpacking loop
  (`docs/decisions/020`) needed no change, only a second `artifacts.get(...)`
  check for the new key.
- Real tests: `tests/test_dependency_gates.py` (6, including the
  digit-count-vs-real-ratio trap and confirming the rule correctly does
  NOT apply to `soft` edges), `tests/test_dependency_lens.py` (5, the real
  `design_dependency` function against the real `SKILL.md`),
  `tests/test_service_pack.py` extended for the real 6-lens pack.

## Decision

**`route_is_templated`/`cardinality_guard`, named in the same ADR
sentence as the extra-nine rule, are NOT part of this phase.** They are
about route-point attribute templating, not dependency-edge structure —
batching them in here on the strength of textual proximity in the ADR
would be exactly the kind of unevidenced scope-stretch this project's own
discipline refuses elsewhere. They remain a real, separate, still-named
gap — not smuggled into `dependency`'s scope to close out a checklist.

## Consequences

**All six of E12's lenses are now real** — `docs/decisions/011`'s own
lens roster is fully built for the first time: three reused, one adapted,
two new. Combined with phases 1–5, DoD (b) ("the three reused lenses run
with no edit to their SKILL.md files") is proven, and the pack now has a
complete, real design surface for every point kind it declares except the
four still-`declared_undetected` ones.

**Still fully unbuilt, named not implied**: four more S1 registries
(`db_query`/`queue_*`/`scheduled_job`) — meaning `slo`/`dependency`
can be exercised end-to-end today only against `http_server_route`/
`declarative_route`/`http_client_call`/`queue_producer` points, not
`db_query`; `route_is_templated`/`cardinality_guard`; S11 signal
provenance; and a real corpus fixture (DoD (a) — the actual end-to-end
S1→S9 proof against a real, not hand-built, repository).
