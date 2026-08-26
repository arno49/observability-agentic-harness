"""oah/validate/overhead.py -- pure function, no I/O."""
from oah.validate.overhead import compute_overhead_vs_budget


def _run(status, p50=None, p95=None):
    return {"status": status, "latency_p50_ms": p50, "latency_p95_ms": p95}


def _dto(dto_id, estimated_overhead_ms):
    return {"id": dto_id, "estimated_overhead_ms": estimated_overhead_ms}


def _static(dto_id, status="present"):
    return {"dto_id": dto_id, "status": status}


def test_baseline_not_ok_is_skipped_not_a_fabricated_comparison():
    result = compute_overhead_vs_budget(_run("build_failed"), _run("ok", 10, 15), [], [])
    assert result["status"] == "skipped"
    assert "baseline" in result["reason"]
    assert result["overhead_p50_ms"] is None


def test_instrumented_not_ok_is_skipped():
    result = compute_overhead_vs_budget(_run("ok", 10, 15), _run("startup_failed"), [], [])
    assert result["status"] == "skipped"
    assert "instrumented" in result["reason"]


def test_within_budget_when_overhead_p95_under_budget():
    dtos = [_dto("d1", 10.0)]
    static_results = [_static("d1")]
    result = compute_overhead_vs_budget(
        _run("ok", p50=100, p95=110), _run("ok", p50=105, p95=115), dtos, static_results,
    )
    assert result["status"] == "ok"
    assert result["budget_ms"] == 10.0
    assert result["budget_complete"] is True
    assert result["overhead_p50_ms"] == 5
    assert result["overhead_p95_ms"] == 5
    assert result["within_budget"] is True


def test_over_budget_when_overhead_p95_exceeds_budget():
    dtos = [_dto("d1", 2.0)]
    static_results = [_static("d1")]
    result = compute_overhead_vs_budget(
        _run("ok", p50=100, p95=110), _run("ok", p50=105, p95=125), dtos, static_results,
    )
    assert result["overhead_p95_ms"] == 15
    assert result["budget_ms"] == 2.0
    assert result["within_budget"] is False


def test_null_estimate_on_an_applied_dto_makes_budget_incomplete_never_zero():
    dtos = [_dto("d1", 10.0), _dto("d2", None)]
    static_results = [_static("d1"), _static("d2", status="absent")]
    result = compute_overhead_vs_budget(
        _run("ok", p50=100, p95=110), _run("ok", p50=105, p95=115), dtos, static_results,
    )
    assert result["budget_complete"] is False
    assert result["budget_ms"] is None
    assert result["within_budget"] is None
    # overhead itself is still reported even though budget is incomplete
    assert result["overhead_p95_ms"] == 5


def test_skipped_never_applied_dto_excluded_from_budget_sum():
    dtos = [_dto("d1", 10.0), _dto("d2", 999.0)]
    static_results = [_static("d1"), _static("d2", status="skipped")]
    result = compute_overhead_vs_budget(
        _run("ok", p50=100, p95=110), _run("ok", p50=105, p95=115), dtos, static_results,
    )
    assert result["budget_ms"] == 10.0  # d2's 999.0 never counted -- it was never applied


def test_negative_overhead_delta_reported_as_is_not_clamped():
    dtos = [_dto("d1", 10.0)]
    static_results = [_static("d1")]
    result = compute_overhead_vs_budget(
        _run("ok", p50=120, p95=130), _run("ok", p50=100, p95=110), dtos, static_results,
    )
    assert result["overhead_p50_ms"] == -20
    assert result["overhead_p95_ms"] == -20
    assert result["within_budget"] is True


def test_no_dtos_at_all_gives_a_complete_zero_budget():
    result = compute_overhead_vs_budget(_run("ok", p50=100, p95=110), _run("ok", p50=100, p95=110), [], [])
    assert result["budget_complete"] is True
    assert result["budget_ms"] == 0
    assert result["overhead_p95_ms"] == 0
    assert result["within_budget"] is True
