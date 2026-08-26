"""oah/validate/verdict.py -- pure function, no I/O."""
from oah.validate.verdict import compute_ladder_verdict


def _dto(dto_id, change_type="wrap_call"):
    return {"id": dto_id, "change": {"type": change_type}}


def _static(dto_id, status="present"):
    return {"dto_id": dto_id, "status": status}


def _event(dto_id, status="observed"):
    return {"dto_id": dto_id, "status": status}


def _propagation(dto_id, status="present"):
    return {"dto_id": dto_id, "status": status}


def _gate(status):
    return {"status": status, "reason": None}


def test_regression_gate_failed_forces_validation_failed_regardless_of_dtos():
    dtos = [_dto("d1")]
    rung, verdict = compute_ladder_verdict(
        dtos, [_static("d1")], [_event("d1")], [_propagation("d1")], _gate("failed"),
    )
    assert (rung, verdict) == ("R4", "validation_failed")


def test_regression_gate_not_attempted_stays_r4_needs_review():
    dtos = [_dto("d1")]
    rung, verdict = compute_ladder_verdict(
        dtos, [_static("d1")], [_event("d1")], [_propagation("d1")], _gate("not_attempted"),
    )
    assert (rung, verdict) == ("R4", "needs_review")


def test_regression_gate_skipped_stays_r4_needs_review():
    dtos = [_dto("d1")]
    rung, verdict = compute_ladder_verdict(
        dtos, [_static("d1")], [_event("d1")], [_propagation("d1")], _gate("skipped"),
    )
    assert (rung, verdict) == ("R4", "needs_review")


def test_empty_dto_list_never_promotes_even_with_a_passing_gate():
    rung, verdict = compute_ladder_verdict([], [], [], [], _gate("passed"))
    assert (rung, verdict) == ("R4", "needs_review")


def test_all_dtos_skipped_at_static_never_promotes():
    dtos = [_dto("d1")]
    rung, verdict = compute_ladder_verdict(
        dtos, [_static("d1", "skipped")], [_event("d1", "not_attempted")], [_propagation("d1", "not_applicable")],
        _gate("passed"),
    )
    assert (rung, verdict) == ("R4", "needs_review")


def test_one_observed_non_propagate_dto_promotes_to_r2():
    dtos = [_dto("d1")]
    rung, verdict = compute_ladder_verdict(
        dtos, [_static("d1")], [_event("d1", "observed")], [_propagation("d1", "not_applicable")], _gate("passed"),
    )
    assert (rung, verdict) == ("R2", "validated")


def test_one_present_propagate_context_dto_promotes_to_r2():
    dtos = [_dto("d1", change_type="propagate_context")]
    rung, verdict = compute_ladder_verdict(
        dtos, [_static("d1")], [_event("d1", "not_attempted")], [_propagation("d1", "present")], _gate("passed"),
    )
    assert (rung, verdict) == ("R2", "validated")


def test_one_not_observed_dto_blocks_promotion():
    dtos = [_dto("d1")]
    rung, verdict = compute_ladder_verdict(
        dtos, [_static("d1")], [_event("d1", "not_observed")], [_propagation("d1", "not_applicable")], _gate("passed"),
    )
    assert (rung, verdict) == ("R4", "needs_review")


def test_one_absent_propagation_dto_blocks_promotion():
    dtos = [_dto("d1", change_type="propagate_context")]
    rung, verdict = compute_ladder_verdict(
        dtos, [_static("d1")], [_event("d1", "not_attempted")], [_propagation("d1", "absent")], _gate("passed"),
    )
    assert (rung, verdict) == ("R4", "needs_review")


def test_mixed_dtos_all_passing_promotes_to_r2():
    dtos = [_dto("d1"), _dto("d2", change_type="propagate_context")]
    rung, verdict = compute_ladder_verdict(
        dtos,
        [_static("d1"), _static("d2")],
        [_event("d1", "observed"), _event("d2", "not_attempted")],
        [_propagation("d1", "not_applicable"), _propagation("d2", "present")],
        _gate("passed"),
    )
    assert (rung, verdict) == ("R2", "validated")


def test_unapplied_dto_alongside_a_real_r2_earning_dto_still_promotes():
    """A DTO S10 never applied (static status 'skipped') is excluded from
    the promotion decision entirely -- it neither blocks nor is required
    for R2, since there's nothing dynamic to claim about code that was
    never written."""
    dtos = [_dto("d1"), _dto("d2")]
    rung, verdict = compute_ladder_verdict(
        dtos,
        [_static("d1"), _static("d2", "skipped")],
        [_event("d1", "observed"), _event("d2", "not_attempted")],
        [_propagation("d1", "not_applicable"), _propagation("d2", "not_applicable")],
        _gate("passed"),
    )
    assert (rung, verdict) == ("R2", "validated")


def test_mixed_dtos_one_failing_blocks_promotion_for_the_whole_run():
    dtos = [_dto("d1"), _dto("d2", change_type="propagate_context")]
    rung, verdict = compute_ladder_verdict(
        dtos,
        [_static("d1"), _static("d2")],
        [_event("d1", "observed"), _event("d2", "not_attempted")],
        [_propagation("d1", "not_applicable"), _propagation("d2", "absent")],
        _gate("passed"),
    )
    assert (rung, verdict) == ("R4", "needs_review")
