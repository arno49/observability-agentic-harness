"""Regression tests for oah.design.event_schema (S7, deterministic merge)."""
import pytest

from oah.design.event_schema import build_event_schema, EventSchemaConflictError
from oah.schemas import validate


def _fragment(lens, signals):
    return {
        "schema_version": "0.1.0", "lens": lens, "repo_git_sha": "deadbeef",
        "failure_mode": "fail_open", "signals": signals,
    }


def _signal(name, attribute, kind="otel_genai", tier="internal", points=("sp-0001",)):
    return {
        "name": name, "surface_point_ids": list(points),
        "maps_to": {"kind": kind, "attribute": attribute},
        "sensitivity_tier": tier, "pii_masked": False,
        "supports_decision": "x", "acting_role": "y",
    }


def test_single_fragment_produces_valid_schema():
    fragment = _fragment("generation-capture", [_signal("gen_ai.usage.input_tokens", "gen_ai.usage.input_tokens")])
    result = build_event_schema([fragment], "deadbeef")
    validate("event_schema", result)
    assert result["summary"]["attribute_count"] == 1
    assert result["attributes"][0]["stability"] == "development"


def test_same_attribute_from_two_lenses_merges_source_lenses_and_points():
    f1 = _fragment("generation-capture", [_signal("gen_ai.usage.input_tokens", "gen_ai.usage.input_tokens", points=("sp-0001",))])
    f2 = _fragment("cost", [_signal("gen_ai.usage.input_tokens", "gen_ai.usage.input_tokens", points=("sp-0002",))])
    result = build_event_schema([f1, f2], "deadbeef")
    assert result["summary"]["attribute_count"] == 1  # deduplicated, not 2
    attr = result["attributes"][0]
    assert attr["source_lenses"] == ["cost", "generation-capture"]
    assert attr["surface_point_ids"] == ["sp-0001", "sp-0002"]


def test_conflicting_kind_raises_not_silently_resolved():
    f1 = _fragment("generation-capture", [_signal("x", "oah.custom", kind="oah_extension")])
    f2 = _fragment("cost", [_signal("x", "oah.custom", kind="otel_genai")])
    with pytest.raises(EventSchemaConflictError, match="kind"):
        build_event_schema([f1, f2], "deadbeef")


def test_conflicting_sensitivity_tier_raises():
    f1 = _fragment("generation-capture", [_signal("x", "gen_ai.usage.input_tokens", tier="internal")])
    f2 = _fragment("pii-governance", [_signal("x", "gen_ai.usage.input_tokens", tier="restricted")])
    with pytest.raises(EventSchemaConflictError, match="sensitivity_tier"):
        build_event_schema([f1, f2], "deadbeef")


def test_oah_extension_and_otel_genai_counted_separately():
    f = _fragment("generation-capture", [
        _signal("a", "gen_ai.usage.input_tokens", kind="otel_genai"),
        _signal("b", "oah.custom.thing", kind="oah_extension"),
    ])
    result = build_event_schema([f], "deadbeef")
    assert result["summary"]["otel_genai_count"] == 1
    assert result["summary"]["oah_extension_count"] == 1


def test_semconv_pin_included_when_given():
    f = _fragment("generation-capture", [_signal("a", "gen_ai.usage.input_tokens")])
    result = build_event_schema([f], "deadbeef", semconv_pin="abc123")
    validate("event_schema", result)
    assert result["semconv_pin"] == "abc123"


def test_semconv_pin_omitted_when_not_given():
    f = _fragment("generation-capture", [_signal("a", "gen_ai.usage.input_tokens")])
    result = build_event_schema([f], "deadbeef")
    validate("event_schema", result)
    assert "semconv_pin" not in result


def test_empty_fragments_produces_empty_valid_schema():
    result = build_event_schema([], "deadbeef")
    validate("event_schema", result)
    assert result["attributes"] == []


_GREEN_LOW = {"state": "green", "condition": "cardinality_risk == low", "basis": "assumed", "rationale": "x"}
_RED_HIGH = {"state": "red", "condition": "cardinality_risk == high", "basis": "assumed", "rationale": "y"}
_RED_DIFFERENT = {"state": "red", "condition": "cardinality_risk == very_high", "basis": "assumed", "rationale": "z"}


def test_one_lens_declaring_health_thresholds_and_the_other_not_is_no_conflict():
    """docs/decisions/039 Phase D: silence isn't a competing claim -- only
    two fragments that BOTH declare health_thresholds for the same
    attribute and disagree is a conflict."""
    f1 = _fragment("telemetry-cost", [{
        **_signal("x", "oah.telemetry_cost.cardinality_risk", kind="oah_extension"),
        "health_thresholds": [_GREEN_LOW, _RED_HIGH],
    }])
    f2 = _fragment("ops", [_signal("y", "oah.telemetry_cost.cardinality_risk", kind="oah_extension")])
    result = build_event_schema([f1, f2], "deadbeef")
    validate("event_schema", result)
    assert result["summary"]["attribute_count"] == 1


def test_identical_health_thresholds_from_two_lenses_is_no_conflict():
    f1 = _fragment("telemetry-cost", [{
        **_signal("x", "oah.telemetry_cost.cardinality_risk", kind="oah_extension"),
        "health_thresholds": [_GREEN_LOW, _RED_HIGH],
    }])
    f2 = _fragment("ops", [{
        **_signal("y", "oah.telemetry_cost.cardinality_risk", kind="oah_extension"),
        "health_thresholds": [_GREEN_LOW, _RED_HIGH],
    }])
    result = build_event_schema([f1, f2], "deadbeef")
    validate("event_schema", result)
    assert result["summary"]["attribute_count"] == 1


def test_conflicting_health_thresholds_raises_not_silently_resolved():
    f1 = _fragment("telemetry-cost", [{
        **_signal("x", "oah.telemetry_cost.cardinality_risk", kind="oah_extension"),
        "health_thresholds": [_GREEN_LOW, _RED_HIGH],
    }])
    f2 = _fragment("ops", [{
        **_signal("y", "oah.telemetry_cost.cardinality_risk", kind="oah_extension"),
        "health_thresholds": [_GREEN_LOW, _RED_DIFFERENT],
    }])
    with pytest.raises(EventSchemaConflictError, match="health_thresholds"):
        build_event_schema([f1, f2], "deadbeef")
