"""The R2/R1 promotion rule: the one place `oah validate` decides whether
a run has earned `ladder_rung: "R2"` or `"R1"` / `verdict: "validated"` --
the first time this codebase has ever been able to say `validated` at all.

docs/validation.md's ladder table defines R2 as BOTH per-DTO dynamic
event-emission assertion (oah/validate/event_assertion.py) AND a static
trace-ID-propagation check (oah/validate/propagation_checker.py) together,
in one row. R1 is a strict superset on top of that: everything R2 needs,
PLUS real TCR (oah/validate/tcr.py) at 1.0 -- every captured trace
complete, none partial -- AND a real latency-overhead-vs-budget comparison
(oah/validate/overhead.py) that's actually within budget. R1's evidence
comes from a *different* sandboxed run than R2's (`--live`/`--baseline`
vs. `--dynamic`), so both must have actually run in the same `oah
validate` invocation for R1 to be reachable at all -- `live_execution` is
optional here (`None` when `--live` was never passed) precisely so R1
promotion is only even considered when that evidence genuinely exists.

This function is deliberately conservative about when each rung's
requirements count as satisfied -- see each branch's own comment for why
-- since a wrong promotion here is a real overclaim, the one thing this
whole R2/R1 effort has been built around avoiding.
"""


def compute_ladder_verdict(dtos, static_results, event_assertions, propagation_checks, regression_gate,
                            live_execution=None):
    """Returns (ladder_rung, verdict). `live_execution` is the report's own
    live_execution block (or None/not_attempted, when --live wasn't
    passed) -- only consulted once R2's own requirements are already met,
    since R1 can never be reached without R2 also holding."""
    if regression_gate["status"] == "failed":
        return "R4", "validation_failed"
    if regression_gate["status"] != "passed":
        # never ran ("not_attempted"/"skipped") -- no dynamic evidence at
        # all, so R2 is never reachable regardless of the static checks.
        return "R4", "needs_review"

    static_by_id = {r["dto_id"]: r for r in static_results}
    event_by_id = {r["dto_id"]: r for r in event_assertions}
    propagation_by_id = {r["dto_id"]: r for r in propagation_checks}

    # Only DTOs S10 actually applied have anything real to claim --
    # matches R4's own applied-only precondition (checker.py's own
    # "skipped: not applied" branch).
    applicable_dtos = [dto for dto in dtos if static_by_id[dto["id"]]["status"] != "skipped"]
    if not applicable_dtos:
        # An empty or all-unapplied DTO set proves nothing -- promoting
        # "nothing to check" to "validated" would be exactly the
        # overclaim this rule exists to prevent.
        return "R4", "needs_review"

    for dto in applicable_dtos:
        dto_id = dto["id"]
        if dto["change"]["type"] == "propagate_context":
            if propagation_by_id[dto_id]["status"] != "present":
                return "R4", "needs_review"
        else:
            if event_by_id[dto_id]["status"] != "observed":
                return "R4", "needs_review"

    if _earns_r1(live_execution):
        return "R1", "validated"
    return "R2", "validated"


def _earns_r1(live_execution):
    """R1 needs a real --live run that actually succeeded, every captured
    trace complete (tcr == 1.0 -- a partially-complete run is real
    evidence of a real gap, not close enough to round up), and a real
    --baseline comparison that's actually within its declared budget.
    Missing/incomplete evidence anywhere here means R1 simply isn't
    reachable yet, not an error."""
    if live_execution is None or live_execution["status"] != "ok":
        return False
    tcr = live_execution["tcr"]["tcr"]
    if tcr is None or tcr != 1.0:
        return False
    overhead = live_execution["overhead_vs_budget"]
    return overhead["status"] == "ok" and overhead["within_budget"] is True
