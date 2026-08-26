"""The R2 promotion rule: the one place `oah validate` decides whether a
run has earned `ladder_rung: "R2"` / `verdict: "validated"` -- the first
time this codebase has ever been able to say `validated` at all.

docs/validation.md's ladder table defines R2 as BOTH per-DTO dynamic
event-emission assertion (oah/validate/event_assertion.py) AND a static
trace-ID-propagation check (oah/validate/propagation_checker.py) together,
in one row. This function is deliberately conservative about when both
count as satisfied -- see each branch's own comment for why -- since a
wrong promotion here is a real overclaim, the one thing this whole R2
effort has been built around avoiding.
"""


def compute_ladder_verdict(dtos, static_results, event_assertions, propagation_checks, regression_gate):
    """Returns (ladder_rung, verdict)."""
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

    return "R2", "validated"
