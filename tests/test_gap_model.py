"""Regression tests for oah.discovery.gap_model (S3, deterministic half)."""
from oah.discovery.gap_model import build_gap_model
from oah.schemas import validate


def _surface_map(points):
    return {
        "schema_version": "0.1.0",
        "repo": {"path": "/x", "git_sha": "deadbeef", "primary_language": "python"},
        "generated_by": {"harness_version": "0.1.0", "skill_versions": {}},
        "points": points,
        "coverage_stats": {"files_scanned": 1, "points_total": len(points), "points_llm_disambiguated": 0},
    }


def _telemetry(loggers=None, otel=None):
    return {
        "schema_version": "0.1.0",
        "repo": {"path": "/x", "git_sha": "deadbeef"},
        "generated_by": {"harness_version": "0.1.0"},
        "loggers": loggers or [],
        "existing_otel_usage": otel or [],
        "metrics_libraries": [],
        "error_handling": [],
    }


def test_dark_when_no_nearby_telemetry():
    sm = _surface_map([{"id": "sp-0001", "kind": "llm_generation", "file": "app.py", "line": 10,
                         "detection": "signature", "confidence": 0.95}])
    gm = build_gap_model(sm, _telemetry())
    validate("gap_model", gm)
    assert gm["gaps"][0]["status"] == "dark"
    assert gm["summary"]["dark_points"] == 1
    assert gm["summary"]["estimated_tcr_current"] == 0.0


def test_partial_when_logger_nearby():
    sm = _surface_map([{"id": "sp-0001", "kind": "llm_generation", "file": "app.py", "line": 10,
                         "detection": "signature", "confidence": 0.95}])
    inv = _telemetry(loggers=[{"id": "log-0001", "file": "app.py", "line": 12,
                                "level": "info", "logger_kind": "stdlib_logging"}])
    gm = build_gap_model(sm, inv)
    validate("gap_model", gm)
    assert gm["gaps"][0]["status"] == "partial"
    assert gm["gaps"][0]["existing_telemetry_refs"] == ["log-0001"]


def test_far_logger_does_not_count_as_partial():
    sm = _surface_map([{"id": "sp-0001", "kind": "llm_generation", "file": "app.py", "line": 10,
                         "detection": "signature", "confidence": 0.95}])
    inv = _telemetry(loggers=[{"id": "log-0001", "file": "app.py", "line": 500,
                                "level": "info", "logger_kind": "stdlib_logging"}])
    gm = build_gap_model(sm, inv)
    assert gm["gaps"][0]["status"] == "dark"


def test_partial_when_file_has_existing_otel():
    """File-level OTel import presence -> partial, not covered — call-site-
    level coverage isn't verified by this pass."""
    sm = _surface_map([{"id": "sp-0001", "kind": "llm_generation", "file": "app.py", "line": 10,
                         "detection": "signature", "confidence": 0.95}])
    inv = _telemetry(otel=[{"id": "otel-0001", "file": "app.py", "line": 1, "package": "opentelemetry"}])
    gm = build_gap_model(sm, inv)
    assert gm["gaps"][0]["status"] == "partial"


def test_no_gaps_conservative_priority_no_fabricated_drivers():
    """Without context.yaml, priority_drivers must never be fabricated —
    only what's actually knowable (coverage status) drives priority."""
    sm = _surface_map([{"id": "sp-0001", "kind": "llm_generation", "file": "app.py", "line": 10,
                         "detection": "signature", "confidence": 0.95}])
    gm = build_gap_model(sm, _telemetry())
    assert "priority_drivers" not in gm["gaps"][0]
