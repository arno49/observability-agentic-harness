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


def _context(workflows):
    return {"schema_version": "0.1.0", "repo_git_sha": "deadbeef",
            "interviewed_at": "2026-01-01T00:00:00Z", "workflows": workflows}


def test_workflow_hint_matches_context_weights_priority_up():
    """dark + critical workflow -> p0, not the coverage-only p1 baseline."""
    sm = _surface_map([{"id": "sp-0001", "kind": "llm_generation", "file": "app.py", "line": 10,
                         "detection": "signature", "confidence": 0.95, "workflow_hint": "billing"}])
    context = _context([{"name": "billing", "criticality": "critical"}])
    gm = build_gap_model(sm, _telemetry(), context=context)
    assert gm["gaps"][0]["priority"] == "p0"
    assert gm["gaps"][0]["priority_drivers"] == ["workflow_criticality"]
    assert "context_ref" in gm


def test_workflow_hint_matches_low_criticality_weights_priority_down():
    """dark + low criticality -> p2, lower urgency than the p1 baseline
    would otherwise imply — weighting can move priority either direction,
    not just escalate it."""
    sm = _surface_map([{"id": "sp-0001", "kind": "llm_generation", "file": "app.py", "line": 10,
                         "detection": "signature", "confidence": 0.95, "workflow_hint": "internal-tool"}])
    context = _context([{"name": "internal-tool", "criticality": "low"}])
    gm = build_gap_model(sm, _telemetry(), context=context)
    assert gm["gaps"][0]["priority"] == "p2"


def test_direct_pii_bumps_priority_further():
    sm = _surface_map([{"id": "sp-0001", "kind": "llm_generation", "file": "app.py", "line": 10,
                         "detection": "signature", "confidence": 0.95, "workflow_hint": "support"}])
    context = _context([{"name": "support", "criticality": "high", "pii_presence": "direct"}])
    gm = build_gap_model(sm, _telemetry(), context=context)
    # dark+high -> p1 baseline, then PII bump -> p0
    assert gm["gaps"][0]["priority"] == "p0"
    assert gm["gaps"][0]["priority_drivers"] == ["workflow_criticality", "pii_exposure"]


def test_covered_point_never_bumped_by_pii_despite_criticality():
    sm = _surface_map([{"id": "sp-0001", "kind": "llm_generation", "file": "app.py", "line": 10,
                         "detection": "signature", "confidence": 0.95, "workflow_hint": "support"}])
    inv = _telemetry(otel=[{"id": "otel-0001", "file": "app.py", "line": 1, "package": "opentelemetry"}])
    # file-level otel presence -> "partial" not "covered" per this module's
    # own design, so use a scenario that actually reaches "covered": none
    # currently exist (call-site-level coverage isn't detected), so this
    # test instead confirms the covered branch of the priority table itself
    # stays capped at p3 regardless of criticality, via direct unit access.
    from oah.discovery.gap_model import _WEIGHTED_PRIORITY
    assert _WEIGHTED_PRIORITY["covered"]["critical"] == "p3"


def test_unmatched_workflow_hint_falls_back_to_coverage_only():
    """A hint that doesn't match anything in context.yaml must not silently
    apply some other workflow's criticality -- falls back to baseline."""
    sm = _surface_map([{"id": "sp-0001", "kind": "llm_generation", "file": "app.py", "line": 10,
                         "detection": "signature", "confidence": 0.95, "workflow_hint": "typo-name"}])
    context = _context([{"name": "billing", "criticality": "critical"}])
    gm = build_gap_model(sm, _telemetry(), context=context)
    assert gm["gaps"][0]["priority"] == "p1"  # dark baseline, unchanged
    assert "priority_drivers" not in gm["gaps"][0]


def test_no_workflow_hint_falls_back_to_coverage_only_even_with_context():
    sm = _surface_map([{"id": "sp-0001", "kind": "llm_generation", "file": "app.py", "line": 10,
                         "detection": "signature", "confidence": 0.95}])
    context = _context([{"name": "billing", "criticality": "critical"}])
    gm = build_gap_model(sm, _telemetry(), context=context)
    assert gm["gaps"][0]["priority"] == "p1"
    assert "priority_drivers" not in gm["gaps"][0]
