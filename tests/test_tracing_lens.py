"""Regression tests for oah.design.lens's tracing wiring — same mocked-
_completion_fn reasoning as test_design_lens.py: no live API key in this
environment. Unlike every other lens, design_tracing does NOT filter by
kind -- tracing is cross-cutting per architecture.md."""
import json
from types import SimpleNamespace

import pytest

from oah.design.lens import design_tracing, LensDesignError
from oah.design.gates import run_gates, gates_passed
from oah.schemas import validate


def _fake_response(payload):
    message = SimpleNamespace(content=json.dumps(payload))
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


ASYNC_POINT = {"id": "sp-0001", "kind": "llm_generation", "file": "app.py", "line": 10,
               "symbol": "run", "sync_nature": "async"}
RETRIEVAL_POINT = {"id": "sp-0002", "kind": "retrieval", "file": "app.py", "line": 20}

VALID_FRAGMENT = {
    "schema_version": "0.1.0", "lens": "tracing", "repo_git_sha": "deadbeef",
    "failure_mode": "fail_open",
    "signals": [
        {
            "name": "oah.tracing.propagation_risk", "surface_point_ids": ["sp-0001", "sp-0002"],
            "maps_to": {"kind": "oah_extension", "attribute": "oah.tracing.propagation_risk"},
            "sensitivity_tier": "internal", "pii_masked": False,
            "supports_decision": "whether a thread-pool/queue instrumentor presence check is needed",
            "acting_role": "tracing owner", "latency_overhead_budget_ms": 1,
        },
    ],
}


def test_no_points_never_calls_the_model():
    calls = []
    result = design_tracing([], "deadbeef", _completion_fn=lambda **kw: calls.append(kw))
    assert result is None
    assert calls == []


def test_does_not_filter_by_kind_unlike_every_other_lens():
    """The one lens that must NOT drop points of other kinds -- tracing is
    cross-cutting, so a retrieval point and an llm_generation point must
    both reach the model in the same batch."""
    calls = []

    def fake(**kwargs):
        calls.append(kwargs)
        return _fake_response(VALID_FRAGMENT)

    design_tracing([ASYNC_POINT, RETRIEVAL_POINT], "deadbeef", _completion_fn=fake)
    sent = json.loads(calls[0]["messages"][1]["content"])
    assert len(sent["points"]) == 2
    kinds = {p["kind"] for p in sent["points"]}
    assert kinds == {"llm_generation", "retrieval"}


def test_prompt_uses_real_skill_instructions_not_a_copy():
    captured = {}

    def fake(**kwargs):
        captured.update(kwargs)
        return _fake_response(VALID_FRAGMENT)

    design_tracing([ASYNC_POINT], "deadbeef", _completion_fn=fake)
    system_msg = captured["messages"][0]["content"]
    assert "You design the tracing lens's slice" in system_msg


def test_valid_response_returned_and_satisfies_s5_gates():
    result = design_tracing([ASYNC_POINT, RETRIEVAL_POINT], "deadbeef",
                             _completion_fn=lambda **kw: _fake_response(VALID_FRAGMENT))
    validate("design_fragment", result)
    findings = run_gates(result, surface_map_point_ids=["sp-0001", "sp-0002"])
    assert gates_passed(findings)


def test_schema_invalid_response_raises():
    bad = {**VALID_FRAGMENT, "failure_mode": "fail_closed"}  # violates the const

    def fake(**kwargs):
        return _fake_response(bad)

    with pytest.raises(LensDesignError, match="schema validation"):
        design_tracing([ASYNC_POINT], "deadbeef", _completion_fn=fake)


def test_otel_genai_kind_rejected_this_lens_has_no_upstream_attributes():
    bad = json.loads(json.dumps(VALID_FRAGMENT))
    bad["signals"][0]["maps_to"]["kind"] = "otel_genai"

    def fake(**kwargs):
        return _fake_response(bad)

    with pytest.raises(LensDesignError, match="schema validation"):
        design_tracing([ASYNC_POINT], "deadbeef", _completion_fn=fake)


def test_missing_credentials_detected_without_a_call(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(LensDesignError, match="ANTHROPIC_API_KEY"):
        design_tracing([ASYNC_POINT], "deadbeef")


def test_model_call_exception_wrapped():
    def fake(**kwargs):
        raise RuntimeError("connection reset")

    with pytest.raises(LensDesignError, match="model call failed"):
        design_tracing([ASYNC_POINT], "deadbeef", _completion_fn=fake)


def test_context_passed_through_when_given():
    captured = {}

    def fake(**kwargs):
        captured.update(kwargs)
        return _fake_response(VALID_FRAGMENT)

    context = {"workflows": [{"name": "support", "criticality": "high"}]}
    design_tracing([ASYNC_POINT], "deadbeef", context=context, _completion_fn=fake)
    sent = json.loads(captured["messages"][1]["content"])
    assert sent["context"] == context
