"""Regression tests for oah.design.panel's security persona — same
mocked-_completion_fn reasoning as test_design_panel.py."""
import json
from types import SimpleNamespace

import pytest

from oah.design.panel import run_security, PanelReviewError
from oah.schemas import validate


def _fake_response(payload):
    message = SimpleNamespace(content=json.dumps(payload))
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


FRAGMENT = {
    "schema_version": "0.1.0", "lens": "generation-capture", "repo_git_sha": "deadbeef",
    "failure_mode": "fail_open",
    "signals": [{
        "name": "gen_ai.input.messages", "surface_point_ids": ["sp-0001"],
        "maps_to": {"kind": "otel_genai", "attribute": "gen_ai.input.messages"},
        "sensitivity_tier": "confidential", "pii_masked": True,
        "supports_decision": "debugging generation quality", "acting_role": "on-call SRE",
        "latency_overhead_budget_ms": 5,
    }],
}

VALID_VERDICT = {
    "schema_version": "0.1.0", "persona": "security", "repo_git_sha": "deadbeef",
    "overall": "pass", "findings": [],
}


def test_no_fragments_never_calls_the_model():
    calls = []
    result = run_security([], "deadbeef", _completion_fn=lambda **kw: calls.append(kw))
    assert result is None
    assert calls == []


def test_prompt_uses_real_skill_instructions_not_a_copy():
    captured = {}

    def fake(**kwargs):
        captured.update(kwargs)
        return _fake_response(VALID_VERDICT)

    run_security([FRAGMENT], "deadbeef", _completion_fn=fake)
    system_msg = captured["messages"][0]["content"]
    assert "You review a draft design the way a security reviewer" in system_msg
    sent = json.loads(captured["messages"][1]["content"])
    assert sent["design_fragments"] == [FRAGMENT]


def test_valid_empty_findings_verdict_returned():
    result = run_security([FRAGMENT], "deadbeef", _completion_fn=lambda **kw: _fake_response(VALID_VERDICT))
    validate("panel_verdict", result)
    assert result["overall"] == "pass"
    assert result["findings"] == []


def test_verdict_with_injection_surface_finding_validates():
    verdict = {
        "schema_version": "0.1.0", "persona": "security", "repo_git_sha": "deadbeef",
        "overall": "fail",
        "findings": [{
            "category": "injection_surface", "severity": "error", "gate": "sec-no-content-separation",
            "summary": "gen_ai.input.messages captured with no sibling signal separating user content from system instructions",
            "evidence": ["gen_ai.input.messages"],
            "recommendation": "add an oah_extension signal keeping user-supplied content structurally separate",
        }],
    }
    result = run_security([FRAGMENT], "deadbeef", _completion_fn=lambda **kw: _fake_response(verdict))
    validate("panel_verdict", result)
    assert result["overall"] == "fail"


def test_context_passed_through_when_given():
    captured = {}

    def fake(**kwargs):
        captured.update(kwargs)
        return _fake_response(VALID_VERDICT)

    context = {"trust_boundaries": [{"context_field": "role", "verified_server_side": False}]}
    run_security([FRAGMENT], "deadbeef", context=context, _completion_fn=fake)
    sent = json.loads(captured["messages"][1]["content"])
    assert sent["context"] == context


def test_schema_invalid_response_raises():
    bad = {**VALID_VERDICT, "persona": "sre"}  # violates the const in this skill's output schema

    with pytest.raises(PanelReviewError, match="schema validation"):
        run_security([FRAGMENT], "deadbeef", _completion_fn=lambda **kw: _fake_response(bad))


def test_missing_credentials_detected_without_a_call(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(PanelReviewError, match="ANTHROPIC_API_KEY"):
        run_security([FRAGMENT], "deadbeef")


def test_model_call_exception_wrapped():
    def fake(**kwargs):
        raise RuntimeError("connection reset")

    with pytest.raises(PanelReviewError, match="model call failed"):
        run_security([FRAGMENT], "deadbeef", _completion_fn=fake)


def test_finding_missing_evidence_field_fails_schema():
    bad = {
        "schema_version": "0.1.0", "persona": "security", "repo_git_sha": "deadbeef",
        "overall": "fail",
        "findings": [{
            "category": "injection_surface", "severity": "error", "gate": "x", "summary": "no evidence here",
        }],
    }
    with pytest.raises(PanelReviewError, match="schema validation"):
        run_security([FRAGMENT], "deadbeef", _completion_fn=lambda **kw: _fake_response(bad))
