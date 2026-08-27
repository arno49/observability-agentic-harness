"""Regression tests for oah.design.lens's feedback wiring — same mocked-
_completion_fn reasoning as test_design_lens.py: no live API key in this
environment. Third lens targeting a kind other than llm_generation
(kind == "feedback_ingest")."""
import json
from types import SimpleNamespace

import pytest

from oah.design.lens import design_feedback, LensDesignError
from oah.design.gates import run_gates, gates_passed
from oah.schemas import validate


def _fake_response(payload):
    message = SimpleNamespace(content=json.dumps(payload))
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


POINT = {"id": "sp-0001", "kind": "feedback_ingest", "file": "app.py", "line": 10, "symbol": "record_feedback"}

VALID_FRAGMENT = {
    "schema_version": "0.1.0", "lens": "feedback", "repo_git_sha": "deadbeef",
    "failure_mode": "fail_open",
    "signals": [
        {
            "name": "oah.feedback.trace_ref", "surface_point_ids": ["sp-0001"],
            "maps_to": {"kind": "oah_extension", "attribute": "oah.feedback.trace_ref"},
            "sensitivity_tier": "internal", "pii_masked": False,
            "supports_decision": "linking a verdict back to the generation it's about",
            "acting_role": "eval owner", "latency_overhead_budget_ms": 1,
        },
        {
            "name": "oah.feedback.verdict_category", "surface_point_ids": ["sp-0001"],
            "maps_to": {"kind": "oah_extension", "attribute": "oah.feedback.verdict_category"},
            "sensitivity_tier": "internal", "pii_masked": False,
            "supports_decision": "aggregating verdicts by category for quality trend review",
            "acting_role": "eval owner",
        },
    ],
}


def test_no_points_never_calls_the_model():
    calls = []
    result = design_feedback([], "deadbeef", _completion_fn=lambda **kw: calls.append(kw))
    assert result is None
    assert calls == []


def test_does_not_filter_by_kind_filtering_is_the_callers_job():
    """docs/decisions/016: filtering moved to oah/cli.py's _design_all_lenses,
    driven by the loaded pack's own lenses[].target_kinds."""
    calls = []

    def fake(**kwargs):
        calls.append(kwargs)
        return _fake_response(VALID_FRAGMENT)

    other_kind = {"id": "sp-0002", "kind": "llm_generation", "file": "app.py", "line": 20}
    design_feedback([POINT, other_kind], "deadbeef", _completion_fn=fake)
    sent = json.loads(calls[0]["messages"][1]["content"])
    assert len(sent["points"]) == 2


def test_prompt_uses_real_skill_instructions_not_a_copy():
    captured = {}

    def fake(**kwargs):
        captured.update(kwargs)
        return _fake_response(VALID_FRAGMENT)

    design_feedback([POINT], "deadbeef", _completion_fn=fake)
    system_msg = captured["messages"][0]["content"]
    assert "You design the feedback lens's slice" in system_msg


def test_valid_response_returned_and_satisfies_s5_gates():
    result = design_feedback([POINT], "deadbeef", _completion_fn=lambda **kw: _fake_response(VALID_FRAGMENT))
    validate("design_fragment", result)
    findings = run_gates(result, surface_map_point_ids=["sp-0001"])
    assert gates_passed(findings)


def test_schema_invalid_response_raises():
    bad = {**VALID_FRAGMENT, "failure_mode": "fail_closed"}  # violates the const

    def fake(**kwargs):
        return _fake_response(bad)

    with pytest.raises(LensDesignError, match="schema validation"):
        design_feedback([POINT], "deadbeef", _completion_fn=fake)


def test_otel_genai_kind_rejected_this_lens_has_no_upstream_attributes():
    bad = json.loads(json.dumps(VALID_FRAGMENT))
    bad["signals"][0]["maps_to"]["kind"] = "otel_genai"

    def fake(**kwargs):
        return _fake_response(bad)

    with pytest.raises(LensDesignError, match="schema validation"):
        design_feedback([POINT], "deadbeef", _completion_fn=fake)


def test_missing_credentials_detected_without_a_call(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(LensDesignError, match="ANTHROPIC_API_KEY"):
        design_feedback([POINT], "deadbeef")


def test_model_call_exception_wrapped():
    def fake(**kwargs):
        raise RuntimeError("connection reset")

    with pytest.raises(LensDesignError, match="model call failed"):
        design_feedback([POINT], "deadbeef", _completion_fn=fake)


def test_context_passed_through_when_given():
    captured = {}

    def fake(**kwargs):
        captured.update(kwargs)
        return _fake_response(VALID_FRAGMENT)

    context = {"workflows": [{"name": "support", "review_workflow": "weekly QA sample"}]}
    design_feedback([POINT], "deadbeef", context=context, _completion_fn=fake)
    sent = json.loads(captured["messages"][1]["content"])
    assert sent["context"] == context
