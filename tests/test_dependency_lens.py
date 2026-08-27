"""Regression tests for oah.design.lens's dependency wiring
(docs/decisions/021). Same mocked-_completion_fn reasoning as every other
lens test in this suite. Like design_slo, design_dependency's return value
is a wrapper {design_fragment, dependency_model}, not a bare
design_fragment."""
import json
from types import SimpleNamespace

import pytest

from oah.design.lens import design_dependency, LensDesignError
from oah.design.dependency_gates import run_dependency_gates, dependency_gates_passed
from oah.design.gates import run_gates, gates_passed
from oah.schemas import validate


def _fake_response(payload):
    message = SimpleNamespace(content=json.dumps(payload))
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


POINT = {"id": "sp-0001", "kind": "http_client_call", "file": "app.ts", "line": 10}

VALID_OUTPUT = {
    "design_fragment": {
        "schema_version": "0.1.0", "lens": "dependency", "repo_git_sha": "deadbeef",
        "failure_mode": "fail_open",
        "signals": [{
            "name": "oah.dependency.edge_name", "surface_point_ids": ["sp-0001"],
            "maps_to": {"kind": "oah_extension", "attribute": "oah.dependency.edge_name"},
            "sensitivity_tier": "internal", "pii_masked": False,
            "supports_decision": "which dependency_model edge covers this call site",
            "acting_role": "sre", "latency_overhead_budget_ms": 1,
        }],
    },
    "dependency_model": {
        "schema_version": "0.1.0", "repo_git_sha": "deadbeef",
        "surface_point_ids": ["sp-0001"],
        "edges": [{
            "name": "payment-service", "dependency_kind": "http_client_call", "criticality": "hard",
            "own_target": 0.999, "required_dependency_target": 0.9999,
            "budget_split": {"own_failures_fraction": 0.6, "dependency_failures_fraction": 0.4},
            "fallback_behavior": "circuit breaker, falls back to cached rate after 3 consecutive failures",
        }],
    },
}


def test_no_points_never_calls_the_model():
    calls = []
    result = design_dependency([], "deadbeef", _completion_fn=lambda **kw: calls.append(kw))
    assert result is None
    assert calls == []


def test_prompt_uses_real_skill_instructions_not_a_copy():
    captured = {}

    def fake(**kwargs):
        captured.update(kwargs)
        return _fake_response(VALID_OUTPUT)

    design_dependency([POINT], "deadbeef", _completion_fn=fake)
    system_msg = captured["messages"][0]["content"]
    assert "You design the reliability contract" in system_msg


def test_valid_response_returns_both_halves():
    result = design_dependency([POINT], "deadbeef", _completion_fn=lambda **kw: _fake_response(VALID_OUTPUT))
    assert set(result.keys()) == {"design_fragment", "dependency_model"}

    validate("design_fragment", result["design_fragment"])
    findings = run_gates(result["design_fragment"], surface_map_point_ids=["sp-0001"])
    assert gates_passed(findings)

    validate("dependency_model", result["dependency_model"])
    dep_findings = run_dependency_gates(result["dependency_model"])
    assert dependency_gates_passed(dep_findings)


def test_missing_dependency_model_key_rejected_by_schema():
    bad = {"design_fragment": VALID_OUTPUT["design_fragment"]}

    def fake(**kwargs):
        return _fake_response(bad)

    with pytest.raises(LensDesignError, match="schema validation"):
        design_dependency([POINT], "deadbeef", _completion_fn=fake)


def test_missing_credentials_detected_without_a_call(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(LensDesignError, match="ANTHROPIC_API_KEY"):
        design_dependency([POINT], "deadbeef")
