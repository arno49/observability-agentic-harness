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
