"""Regression tests for oah.design.lens — mocked, same reasoning as
test_disambiguate.py: no live API key in this environment, so
_completion_fn stands in for litellm.completion throughout."""
import json
import sys
from types import SimpleNamespace

import pytest

from oah.design.lens import design_generation_capture, design_lens, LensDesignError
from oah.design.gates import run_gates, gates_passed
from oah.schemas import validate


def _fake_response(payload):
    message = SimpleNamespace(content=json.dumps(payload))
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


POINT = {"id": "sp-0001", "kind": "llm_generation", "file": "app.py", "line": 10, "symbol": "run"}

VALID_FRAGMENT = {
    "schema_version": "0.1.0", "lens": "generation-capture", "repo_git_sha": "deadbeef",
    "failure_mode": "fail_open",
    "signals": [{
        "name": "gen_ai.usage.input_tokens", "surface_point_ids": ["sp-0001"],
        "maps_to": {"kind": "otel_genai", "attribute": "gen_ai.usage.input_tokens"},
        "sensitivity_tier": "internal", "pii_masked": False,
        "supports_decision": "cost attribution", "acting_role": "cost owner",
        "latency_overhead_budget_ms": 5,
    }],
}


def test_no_points_never_calls_the_model():
    calls = []
    result = design_generation_capture([], "deadbeef", _completion_fn=lambda **kw: calls.append(kw))
    assert result is None
    assert calls == []


def test_filters_to_llm_generation_kind_only():
    calls = []

    def fake(**kwargs):
        calls.append(kwargs)
        return _fake_response(VALID_FRAGMENT)

    other_kind = {"id": "sp-0002", "kind": "retrieval", "file": "app.py", "line": 20}
    design_generation_capture([POINT, other_kind], "deadbeef", _completion_fn=fake)
    sent = json.loads(calls[0]["messages"][1]["content"])
    assert len(sent["points"]) == 1
    assert sent["points"][0]["id"] == "sp-0001"


def test_prompt_uses_real_skill_instructions_not_a_copy():
    captured = {}

    def fake(**kwargs):
        captured.update(kwargs)
        return _fake_response(VALID_FRAGMENT)

    design_generation_capture([POINT], "deadbeef", _completion_fn=fake)
    system_msg = captured["messages"][0]["content"]
    assert "You design the generation-capture lens's slice" in system_msg


def test_valid_response_returned_and_satisfies_s5_gates():
    result = design_generation_capture([POINT], "deadbeef", _completion_fn=lambda **kw: _fake_response(VALID_FRAGMENT))
    validate("design_fragment", result)
    findings = run_gates(result, surface_map_point_ids=["sp-0001"])
    assert gates_passed(findings)


def test_schema_invalid_response_raises():
    bad = {**VALID_FRAGMENT, "failure_mode": "fail_closed"}  # violates the const

    def fake(**kwargs):
        return _fake_response(bad)

    with pytest.raises(LensDesignError, match="schema validation"):
        design_generation_capture([POINT], "deadbeef", _completion_fn=fake)


def test_missing_credentials_detected_without_a_call(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(LensDesignError, match="ANTHROPIC_API_KEY"):
        design_generation_capture([POINT], "deadbeef")


def test_missing_litellm_extra_wrapped_as_lens_design_error(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-key")
    monkeypatch.setitem(sys.modules, "litellm", None)
    with pytest.raises(LensDesignError, match=r"pip install 'oah\[llm\]'"):
        design_generation_capture([POINT], "deadbeef")


def test_model_call_exception_wrapped():
    def fake(**kwargs):
        raise RuntimeError("connection reset")

    with pytest.raises(LensDesignError, match="model call failed"):
        design_generation_capture([POINT], "deadbeef", _completion_fn=fake)


def test_context_passed_through_when_given():
    captured = {}

    def fake(**kwargs):
        captured.update(kwargs)
        return _fake_response(VALID_FRAGMENT)

    context = {"workflows": [{"name": "support", "criticality": "high"}]}
    design_generation_capture([POINT], "deadbeef", context=context, _completion_fn=fake)
    sent = json.loads(captured["messages"][1]["content"])
    assert sent["context"] == context


def test_context_omitted_when_not_given():
    captured = {}

    def fake(**kwargs):
        captured.update(kwargs)
        return _fake_response(VALID_FRAGMENT)

    design_generation_capture([POINT], "deadbeef", _completion_fn=fake)
    sent = json.loads(captured["messages"][1]["content"])
    assert "context" not in sent
