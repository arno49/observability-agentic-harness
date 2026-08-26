"""oah/validate/live_diff.py -- pure function, no I/O."""
from oah.validate.live_diff import check_unknown_attributes

EVENT_SCHEMA = {
    "schema_version": "0.1.0", "repo_git_sha": "x",
    "attributes": [
        {"name": "gen_ai.usage.input_tokens", "kind": "otel_genai", "stability": "development",
         "sensitivity_tier": "internal", "source_lenses": ["generation-capture"], "surface_point_ids": ["sp-1"]},
        {"name": "gen_ai.request.model", "kind": "otel_genai", "stability": "development",
         "sensitivity_tier": "public", "source_lenses": ["generation-capture"], "surface_point_ids": ["sp-1"]},
    ],
}


def test_not_attempted_when_no_event_schema_given():
    spans = [{"name": "s1", "attributes": {"gen_ai.usage.input_tokens": 42}}]
    result = check_unknown_attributes(spans, None)
    assert result == {"status": "not_attempted", "unknown": [], "reason": None}


def test_clean_when_every_captured_attribute_is_declared():
    spans = [{"name": "s1", "attributes": {"gen_ai.usage.input_tokens": 42, "gen_ai.request.model": "x"}}]
    result = check_unknown_attributes(spans, EVENT_SCHEMA)
    assert result == {"status": "clean", "unknown": [], "reason": None}


def test_clean_when_no_spans_captured_at_all():
    result = check_unknown_attributes([], EVENT_SCHEMA)
    assert result["status"] == "clean"


def test_unknown_attributes_found_and_named():
    spans = [{"name": "s1", "attributes": {"gen_ai.usage.input_tokens": 42, "totally.undeclared.attr": True}}]
    result = check_unknown_attributes(spans, EVENT_SCHEMA)
    assert result["status"] == "unknown_attributes_found"
    assert result["unknown"] == ["totally.undeclared.attr"]
    assert "totally.undeclared.attr" in result["reason"]


def test_unknown_attributes_deduplicated_and_sorted_across_multiple_spans():
    spans = [
        {"name": "s1", "attributes": {"zzz.unknown": 1}},
        {"name": "s2", "attributes": {"zzz.unknown": 2, "aaa.unknown": 3}},
    ]
    result = check_unknown_attributes(spans, EVENT_SCHEMA)
    assert result["unknown"] == ["aaa.unknown", "zzz.unknown"]
