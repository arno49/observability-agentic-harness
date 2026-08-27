"""Regression tests for oah.design.lens's slo wiring (docs/decisions/020).
Same mocked-_completion_fn reasoning as every other lens test in this
suite: no live API key in this environment. Unlike every other lens,
design_slo's return value is a wrapper {design_fragment, slo_spec}, not a
bare design_fragment -- these tests exercise that shape specifically."""
import json
from types import SimpleNamespace

import pytest

from oah.design.lens import design_slo, LensDesignError
from oah.design.slo_gates import run_slo_gates, slo_gates_passed
from oah.design.gates import run_gates, gates_passed
from oah.schemas import validate


def _fake_response(payload):
    message = SimpleNamespace(content=json.dumps(payload))
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


POINT = {"id": "sp-0001", "kind": "http_server_route", "file": "app.ts", "line": 10,
         "has_path_parameter": False}

VALID_OUTPUT = {
    "design_fragment": {
        "schema_version": "0.1.0", "lens": "slo", "repo_git_sha": "deadbeef",
        "failure_mode": "fail_open",
        "signals": [{
            "name": "oah.slo.indicator_name", "surface_point_ids": ["sp-0001"],
            "maps_to": {"kind": "oah_extension", "attribute": "oah.slo.indicator_name"},
            "sensitivity_tier": "internal", "pii_masked": False,
            "supports_decision": "which SLO covers this route", "acting_role": "sre",
            "latency_overhead_budget_ms": 1,
        }],
    },
    "slo_spec": {
        "schema_version": "0.1.0", "repo_git_sha": "deadbeef",
        "surface_point_ids": ["sp-0001"],
        "indicator": {
            "name": "booking-checkout availability",
            "good_event_definition": "http.server.request.duration sample with error.type absent",
            "aggregation_method": "ratio_of_counts",
        },
        "objective": {
            "target": 0.999, "period_days": 30,
            "up_predicate": "error.type is absent",
            "granularity": "1m",
            "brownout_classification": "elevated latency counts as half-weighted brownout",
        },
        "alert_tiers": [
            {"tier": "fast_burn", "budget_fraction": 0.02, "detection_window_hours": 1,
             "short_window_hours": 0.0833, "short_window_rationale": "5 minutes, within on-call ack SLA",
             "burn_rate_multiplier": 14.4},
        ],
        "error_budget_policy": {
            "steps": [
                {"step": "page on-call", "entry_criterion_tier": "fast_burn",
                 "exit_criterion": "burn rate returns below 14.4 for 15 minutes"},
            ],
        },
    },
}


def test_no_points_never_calls_the_model():
    calls = []
    result = design_slo([], "deadbeef", _completion_fn=lambda **kw: calls.append(kw))
    assert result is None
    assert calls == []


def test_prompt_uses_real_skill_instructions_not_a_copy():
    captured = {}

    def fake(**kwargs):
        captured.update(kwargs)
        return _fake_response(VALID_OUTPUT)

    design_slo([POINT], "deadbeef", _completion_fn=fake)
    system_msg = captured["messages"][0]["content"]
    assert "You design service-level objectives" in system_msg


def test_valid_response_returns_both_halves():
    result = design_slo([POINT], "deadbeef", _completion_fn=lambda **kw: _fake_response(VALID_OUTPUT))
    assert set(result.keys()) == {"design_fragment", "slo_spec"}

    validate("design_fragment", result["design_fragment"])
    findings = run_gates(result["design_fragment"], surface_map_point_ids=["sp-0001"])
    assert gates_passed(findings)

    validate("slo_spec", result["slo_spec"])
    slo_findings = run_slo_gates(result["slo_spec"])
    assert slo_gates_passed(slo_findings)


def test_missing_slo_spec_key_rejected_by_schema():
    bad = {"design_fragment": VALID_OUTPUT["design_fragment"]}

    def fake(**kwargs):
        return _fake_response(bad)

    with pytest.raises(LensDesignError, match="schema validation"):
        design_slo([POINT], "deadbeef", _completion_fn=fake)


def test_target_of_one_rejected_by_output_schema():
    bad = json.loads(json.dumps(VALID_OUTPUT))
    bad["slo_spec"]["objective"]["target"] = 1.0

    def fake(**kwargs):
        return _fake_response(bad)

    with pytest.raises(LensDesignError, match="schema validation"):
        design_slo([POINT], "deadbeef", _completion_fn=fake)


def test_missing_credentials_detected_without_a_call(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(LensDesignError, match="ANTHROPIC_API_KEY"):
        design_slo([POINT], "deadbeef")
