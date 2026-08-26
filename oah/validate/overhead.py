"""R1's other defining check, alongside real TCR (`oah/validate/tcr.py`):
`docs/validation.md`'s "p50/p95 latency overhead vs. declared budget."
"Overhead" is the real, measured delta between a baseline (pre-
instrumentation, `oah/validate/baseline.py`) and an instrumented live run
-- never assumed, never estimated from the instrumented run alone.

The "declared budget" is the sum of `estimated_overhead_ms` across DTOs
S10 actually applied (the same applied-only filter
`oah/validate/verdict.py`'s `compute_ladder_verdict` already uses for
R2). A `null` estimate on an applied DTO makes the budget *incomplete* --
reported as such, never silently treated as 0, which would understate the
true budget and make "within budget" artificially easy to satisfy.
"""


def _result(status, reason=None, **fields):
    base = {
        "status": status,
        "baseline_latency_p50_ms": None, "baseline_latency_p95_ms": None,
        "instrumented_latency_p50_ms": None, "instrumented_latency_p95_ms": None,
        "overhead_p50_ms": None, "overhead_p95_ms": None,
        "budget_ms": None, "budget_complete": False, "within_budget": None,
        "reason": reason,
    }
    base.update(fields)
    return base


def not_attempted():
    """The shape `oah/cli.py` uses when --baseline wasn't passed at all --
    same "always a real status object, never a bare null" convention
    `oah/validate/live_diff.py`'s check_unknown_attributes already uses
    for its own not_attempted case."""
    return _result("not_attempted")


def compute_overhead_vs_budget(baseline_result, instrumented_result, dtos, static_results):
    if baseline_result["status"] != "ok":
        return _result("skipped", reason=f"baseline run did not succeed (status: {baseline_result['status']!r})")
    if instrumented_result["status"] != "ok":
        return _result("skipped", reason=f"instrumented run did not succeed (status: {instrumented_result['status']!r})")

    # "Applied" means S10 actually wrote code for this DTO -- checker.py's
    # own vocabulary is present/absent/skipped, where *both* present and
    # absent mean applied (a real code change exists either way, just
    # differing on whether the expected attribute string was found); only
    # skipped means never applied. Same filter compute_ladder_verdict
    # already established for R2's own promotion rule.
    static_by_id = {r["dto_id"]: r for r in static_results}
    applied_dtos = [dto for dto in dtos if static_by_id[dto["id"]]["status"] != "skipped"]

    budget_complete = all(dto.get("estimated_overhead_ms") is not None for dto in applied_dtos)
    budget_ms = sum(dto["estimated_overhead_ms"] for dto in applied_dtos) if budget_complete else None

    overhead_p50_ms = instrumented_result["latency_p50_ms"] - baseline_result["latency_p50_ms"]
    overhead_p95_ms = instrumented_result["latency_p95_ms"] - baseline_result["latency_p95_ms"]

    within_budget = (overhead_p95_ms <= budget_ms) if budget_complete else None

    return _result(
        "ok",
        baseline_latency_p50_ms=baseline_result["latency_p50_ms"],
        baseline_latency_p95_ms=baseline_result["latency_p95_ms"],
        instrumented_latency_p50_ms=instrumented_result["latency_p50_ms"],
        instrumented_latency_p95_ms=instrumented_result["latency_p95_ms"],
        overhead_p50_ms=overhead_p50_ms, overhead_p95_ms=overhead_p95_ms,
        budget_ms=budget_ms, budget_complete=budget_complete, within_budget=within_budget,
    )
