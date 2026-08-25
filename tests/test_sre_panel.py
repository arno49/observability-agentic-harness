"""Regression tests for oah.design.panel's SRE persona — same mocked-
_completion_fn reasoning as test_design_panel.py."""
import json
from types import SimpleNamespace

import pytest

from oah.design.panel import run_sre, PanelReviewError
from oah.schemas import validate


def _fake_response(payload):
    message = SimpleNamespace(content=json.dumps(payload))
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


FRAGMENT = {
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

VALID_VERDICT = {
    "schema_version": "0.1.0", "persona": "sre", "repo_git_sha": "deadbeef",
    "overall": "pass", "findings": [],
}


def test_no_fragments_never_calls_the_model():
    calls = []
    result = run_sre([], "deadbeef", _completion_fn=lambda **kw: calls.append(kw))
    assert result is None
    assert calls == []


def test_prompt_uses_real_skill_instructions_not_a_copy():
    captured = {}

    def fake(**kwargs):
        captured.update(kwargs)
        return _fake_response(VALID_VERDICT)

    run_sre([FRAGMENT], "deadbeef", _completion_fn=fake)
    system_msg = captured["messages"][0]["content"]
    assert "You review a draft design the way an SRE reviewer" in system_msg
    sent = json.loads(captured["messages"][1]["content"])
    assert sent["design_fragments"] == [FRAGMENT]


def test_valid_empty_findings_verdict_returned():
    result = run_sre([FRAGMENT], "deadbeef", _completion_fn=lambda **kw: _fake_response(VALID_VERDICT))
    validate("panel_verdict", result)
    assert result["overall"] == "pass"
    assert result["findings"] == []


def test_verdict_with_cardinality_finding_validates():
    verdict = {
        "schema_version": "0.1.0", "persona": "sre", "repo_git_sha": "deadbeef",
        "overall": "fail",
        "findings": [{
            "category": "cardinality", "severity": "error", "gate": "sre-raw-id-as-metric-label",
            "summary": "oah.cost.attribution_key used as a metric dimension carries a raw user ID",
            "evidence": ["oah.cost.attribution_key"],
            "recommendation": "aggregate before using as a metric label, or move to span-only",
        }],
    }
    result = run_sre([FRAGMENT], "deadbeef", _completion_fn=lambda **kw: _fake_response(verdict))
    validate("panel_verdict", result)
    assert result["overall"] == "fail"


def test_schema_invalid_response_raises():
    bad = {**VALID_VERDICT, "persona": "cost_skeptic"}  # violates the const in this skill's output schema

    with pytest.raises(PanelReviewError, match="schema validation"):
        run_sre([FRAGMENT], "deadbeef", _completion_fn=lambda **kw: _fake_response(bad))


def test_missing_credentials_detected_without_a_call(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(PanelReviewError, match="ANTHROPIC_API_KEY"):
        run_sre([FRAGMENT], "deadbeef")


def test_model_call_exception_wrapped():
    def fake(**kwargs):
        raise RuntimeError("connection reset")

    with pytest.raises(PanelReviewError, match="model call failed"):
        run_sre([FRAGMENT], "deadbeef", _completion_fn=fake)


def test_finding_missing_evidence_field_fails_schema():
    bad = {
        "schema_version": "0.1.0", "persona": "sre", "repo_git_sha": "deadbeef",
        "overall": "fail",
        "findings": [{
            "category": "cardinality", "severity": "error", "gate": "x", "summary": "no evidence here",
        }],
    }
    with pytest.raises(PanelReviewError, match="schema validation"):
        run_sre([FRAGMENT], "deadbeef", _completion_fn=lambda **kw: _fake_response(bad))
