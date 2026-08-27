"""Regression tests for oah.design.lens's ops wiring — same mocked-
_completion_fn reasoning as test_design_lens.py: no live API key in this
environment."""
import json
from types import SimpleNamespace

import pytest

from oah.design.lens import design_ops, LensDesignError
from oah.design.gates import run_gates, gates_passed
from oah.schemas import validate


def _fake_response(payload):
    message = SimpleNamespace(content=json.dumps(payload))
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


POINT = {"id": "sp-0001", "kind": "llm_generation", "file": "app.py", "line": 10, "symbol": "run"}

VALID_FRAGMENT = {
    "schema_version": "0.1.0", "lens": "ops", "repo_git_sha": "deadbeef",
    "failure_mode": "fail_open",
    "signals": [
        {
            "name": "oah.ops.release_id", "surface_point_ids": ["sp-0001"],
            "maps_to": {"kind": "oah_extension", "attribute": "oah.ops.release_id"},
            "sensitivity_tier": "internal", "pii_masked": False,
            "supports_decision": "correlating an incident with what changed",
            "acting_role": "on-call SRE", "latency_overhead_budget_ms": 1,
        },
        {
            "name": "oah.ops.incident_owner", "surface_point_ids": ["sp-0001"],
            "maps_to": {"kind": "oah_extension", "attribute": "oah.ops.incident_owner"},
            "sensitivity_tier": "internal", "pii_masked": False,
            "supports_decision": "who is paged for this workflow",
            "acting_role": "on-call SRE",
        },
    ],
    "decision_menu_steps": [
        {"step": "disable workflow for affected region", "type": "escalate",
         "resumption_condition": "incident owner confirms root cause mitigated"},
    ],
}


def test_no_points_never_calls_the_model():
    calls = []
    result = design_ops([], "deadbeef", _completion_fn=lambda **kw: calls.append(kw))
    assert result is None
    assert calls == []


def test_does_not_filter_by_kind_filtering_is_the_callers_job():
    """docs/decisions/016: filtering moved to oah/cli.py's _design_all_lenses,
    driven by the loaded pack's own lenses[].target_kinds -- this fix is
    what actually makes the service pack's own ops-lens reuse real (the
    pack sets target_kinds: null for ops; the old hardcoded llm_generation
    filter here would have silently discarded every service-domain point)."""
    calls = []

    def fake(**kwargs):
        calls.append(kwargs)
        return _fake_response(VALID_FRAGMENT)

    other_kind = {"id": "sp-0002", "kind": "retrieval", "file": "app.py", "line": 20}
    design_ops([POINT, other_kind], "deadbeef", _completion_fn=fake)
    sent = json.loads(calls[0]["messages"][1]["content"])
    assert len(sent["points"]) == 2


def test_prompt_uses_real_skill_instructions_not_a_copy():
    captured = {}

    def fake(**kwargs):
        captured.update(kwargs)
        return _fake_response(VALID_FRAGMENT)

    design_ops([POINT], "deadbeef", _completion_fn=fake)
    system_msg = captured["messages"][0]["content"]
    assert "You design the ops lens's slice" in system_msg


def test_valid_response_returned_and_satisfies_s5_gates():
    result = design_ops([POINT], "deadbeef", _completion_fn=lambda **kw: _fake_response(VALID_FRAGMENT))
    validate("design_fragment", result)
    findings = run_gates(result, surface_map_point_ids=["sp-0001"])
    assert gates_passed(findings)


def test_schema_invalid_response_raises():
    bad = {**VALID_FRAGMENT, "failure_mode": "fail_closed"}  # violates the const

    def fake(**kwargs):
        return _fake_response(bad)

    with pytest.raises(LensDesignError, match="schema validation"):
        design_ops([POINT], "deadbeef", _completion_fn=fake)


def test_otel_genai_kind_rejected_this_lens_has_no_upstream_attributes():
    """Unlike generation-capture, ops has no gen_ai.* signals of its own --
    every maps_to.kind must be oah_extension; the output schema's own const
    enforces this, not just SKILL.md prose."""
    bad = json.loads(json.dumps(VALID_FRAGMENT))
    bad["signals"][0]["maps_to"]["kind"] = "otel_genai"

    def fake(**kwargs):
        return _fake_response(bad)

    with pytest.raises(LensDesignError, match="schema validation"):
        design_ops([POINT], "deadbeef", _completion_fn=fake)


def test_missing_credentials_detected_without_a_call(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(LensDesignError, match="ANTHROPIC_API_KEY"):
        design_ops([POINT], "deadbeef")


def test_model_call_exception_wrapped():
    def fake(**kwargs):
        raise RuntimeError("connection reset")

    with pytest.raises(LensDesignError, match="model call failed"):
        design_ops([POINT], "deadbeef", _completion_fn=fake)


def test_context_passed_through_when_given():
    captured = {}

    def fake(**kwargs):
        captured.update(kwargs)
        return _fake_response(VALID_FRAGMENT)

    context = {"workflows": [{"name": "support", "criticality": "high"}]}
    design_ops([POINT], "deadbeef", context=context, _completion_fn=fake)
    sent = json.loads(captured["messages"][1]["content"])
    assert sent["context"] == context
