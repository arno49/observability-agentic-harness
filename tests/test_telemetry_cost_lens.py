"""Regression tests for oah.design.lens's telemetry-cost wiring -- same
mocked-_completion_fn reasoning as test_cost_lens.py: no live API key in
this environment. Cross-cutting like tracing/ops, unlike cost (which
filters to llm_generation via the caller's own pack-driven target_kinds,
docs/decisions/016) -- telemetry-cost's own service pack entry declares
target_kinds: null."""
import json
from types import SimpleNamespace

import pytest

from oah.design.lens import design_telemetry_cost, LensDesignError
from oah.design.gates import run_gates, gates_passed
from oah.schemas import validate


def _fake_response(payload):
    message = SimpleNamespace(content=json.dumps(payload))
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


ROUTE_POINT = {"id": "sp-0001", "kind": "http_server_route", "file": "app.ts", "line": 10,
               "has_path_parameter": True}
DB_POINT = {"id": "sp-0002", "kind": "db_query", "file": "db.ts", "line": 20}

VALID_FRAGMENT = {
    "schema_version": "0.1.0", "lens": "telemetry-cost", "repo_git_sha": "deadbeef",
    "failure_mode": "fail_open",
    "signals": [
        {
            "name": "oah.telemetry_cost.cardinality_risk", "surface_point_ids": ["sp-0001"],
            "maps_to": {"kind": "oah_extension", "attribute": "oah.telemetry_cost.cardinality_risk"},
            "sensitivity_tier": "internal", "pii_masked": False,
            "supports_decision": "whether route templating needs a runtime check",
            "acting_role": "sre", "latency_overhead_budget_ms": 1,
            "cardinality_guard": {"is_templated": True},
        },
        {
            "name": "oah.telemetry_cost.sampling_rate", "surface_point_ids": ["sp-0001"],
            "maps_to": {"kind": "oah_extension", "attribute": "oah.telemetry_cost.sampling_rate"},
            "sensitivity_tier": "internal", "pii_masked": False,
            "supports_decision": "how much of this route's traffic to retain",
            "acting_role": "sre",
        },
    ],
    "decision_menu_steps": [
        {"step": "reduce sampling rate", "type": "throttle",
         "resumption_condition": "oah.telemetry_cost.cardinality_risk returns to medium or below"},
    ],
}


def test_no_points_never_calls_the_model():
    calls = []
    result = design_telemetry_cost([], "deadbeef", _completion_fn=lambda **kw: calls.append(kw))
    assert result is None
    assert calls == []


def test_does_not_filter_by_kind_cross_cutting():
    """Unlike cost (llm_generation only), telemetry-cost's own service pack
    entry declares target_kinds: null -- both a route point and a db_query
    point must reach the model in the same batch when the caller passes both."""
    calls = []

    def fake(**kwargs):
        calls.append(kwargs)
        return _fake_response(VALID_FRAGMENT)

    design_telemetry_cost([ROUTE_POINT, DB_POINT], "deadbeef", _completion_fn=fake)
    sent = json.loads(calls[0]["messages"][1]["content"])
    assert len(sent["points"]) == 2
    kinds = {p["kind"] for p in sent["points"]}
    assert kinds == {"http_server_route", "db_query"}


def test_prompt_uses_real_skill_instructions_not_a_copy():
    captured = {}

    def fake(**kwargs):
        captured.update(kwargs)
        return _fake_response(VALID_FRAGMENT)

    design_telemetry_cost([ROUTE_POINT], "deadbeef", _completion_fn=fake)
    system_msg = captured["messages"][0]["content"]
    assert "You design the telemetry-cost lens's slice" in system_msg


def test_valid_response_returned_and_satisfies_s5_gates():
    result = design_telemetry_cost([ROUTE_POINT], "deadbeef",
                                    _completion_fn=lambda **kw: _fake_response(VALID_FRAGMENT))
    validate("design_fragment", result)
    findings = run_gates(result, surface_map_point_ids=["sp-0001"])
    assert gates_passed(findings)


def test_schema_invalid_response_raises():
    bad = {**VALID_FRAGMENT, "failure_mode": "fail_closed"}  # violates the const

    def fake(**kwargs):
        return _fake_response(bad)

    with pytest.raises(LensDesignError, match="schema validation"):
        design_telemetry_cost([ROUTE_POINT], "deadbeef", _completion_fn=fake)


def test_otel_semconv_kind_rejected_this_lens_has_no_upstream_attributes():
    """Every maps_to.kind must be oah_extension -- the output schema's own
    const enforces this, not just SKILL.md prose."""
    bad = json.loads(json.dumps(VALID_FRAGMENT))
    bad["signals"][0]["maps_to"]["kind"] = "otel_semconv"

    def fake(**kwargs):
        return _fake_response(bad)

    with pytest.raises(LensDesignError, match="schema validation"):
        design_telemetry_cost([ROUTE_POINT], "deadbeef", _completion_fn=fake)


def test_missing_credentials_detected_without_a_call(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(LensDesignError, match="ANTHROPIC_API_KEY"):
        design_telemetry_cost([ROUTE_POINT], "deadbeef")


def test_model_call_exception_wrapped():
    def fake(**kwargs):
        raise RuntimeError("connection reset")

    with pytest.raises(LensDesignError, match="model call failed"):
        design_telemetry_cost([ROUTE_POINT], "deadbeef", _completion_fn=fake)


def test_context_passed_through_when_given():
    captured = {}

    def fake(**kwargs):
        captured.update(kwargs)
        return _fake_response(VALID_FRAGMENT)

    context = {"workflows": [{"name": "booking-checkout", "criticality": "critical"}]}
    design_telemetry_cost([ROUTE_POINT], "deadbeef", context=context, _completion_fn=fake)
    sent = json.loads(captured["messages"][1]["content"])
    assert sent["context"] == context


# --- route_is_templated / cardinality_guard (docs/decisions/026) ---------

def test_cardinality_guard_is_templated_true_passes_s5():
    """VALID_FRAGMENT's own cardinality_risk signal already sets
    cardinality_guard: {is_templated: true} -- confirms it satisfies S5's
    route_is_templated gate through the real design_telemetry_cost path,
    not just gates.py's own unit tests."""
    result = design_telemetry_cost([ROUTE_POINT], "deadbeef",
                                    _completion_fn=lambda **kw: _fake_response(VALID_FRAGMENT))
    findings = run_gates(result, surface_map_point_ids=["sp-0001"])
    assert gates_passed(findings)
    route_finding = next(f for f in findings if f.gate == "route_is_templated")
    assert route_finding.passed


def test_cardinality_guard_is_templated_false_needs_unavailable_reason():
    """docs/decisions/011's own real finding: a CMS/gateway that resolves a
    URL to a content path by resource type has no statically-recoverable
    route template. is_templated: false with no unavailable_reason must
    fail S5's gate, through the real path."""
    bad = json.loads(json.dumps(VALID_FRAGMENT))
    bad["signals"][0]["cardinality_guard"] = {"is_templated": False}

    def fake(**kwargs):
        return _fake_response(bad)

    result = design_telemetry_cost([ROUTE_POINT], "deadbeef", _completion_fn=fake)
    findings = run_gates(result, surface_map_point_ids=["sp-0001"])
    assert not gates_passed(findings)
    route_finding = next(f for f in findings if f.gate == "route_is_templated")
    assert not route_finding.passed

    # ... and passes once a real reason is stated.
    good = json.loads(json.dumps(VALID_FRAGMENT))
    good["signals"][0]["cardinality_guard"] = {
        "is_templated": False,
        "unavailable_reason": "AEM resolves URLs to content paths by resource type -- no static route template",
    }
    result = design_telemetry_cost([ROUTE_POINT], "deadbeef",
                                    _completion_fn=lambda **kw: _fake_response(good))
    findings = run_gates(result, surface_map_point_ids=["sp-0001"])
    assert gates_passed(findings)
