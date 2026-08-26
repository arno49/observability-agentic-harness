"""Regression tests for oah.design.panel — mocked, same reasoning as
test_disambiguate.py / test_design_lens.py."""
import json
import sys
from types import SimpleNamespace

import pytest

from oah.design.panel import run_cost_skeptic, PanelReviewError
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
    "schema_version": "0.1.0", "persona": "cost_skeptic", "repo_git_sha": "deadbeef",
    "overall": "pass", "findings": [],
}


def test_no_fragments_never_calls_the_model():
    calls = []
    result = run_cost_skeptic([], "deadbeef", _completion_fn=lambda **kw: calls.append(kw))
    assert result is None
    assert calls == []


def test_prompt_uses_real_skill_instructions_not_a_copy():
    captured = {}

    def fake(**kwargs):
        captured.update(kwargs)
        return _fake_response(VALID_VERDICT)

    run_cost_skeptic([FRAGMENT], "deadbeef", _completion_fn=fake)
    system_msg = captured["messages"][0]["content"]
    assert "You review a draft design the way a cost-skeptic reviewer" in system_msg
    sent = json.loads(captured["messages"][1]["content"])
    assert sent["design_fragments"] == [FRAGMENT]


def test_valid_empty_findings_verdict_returned():
    result = run_cost_skeptic([FRAGMENT], "deadbeef", _completion_fn=lambda **kw: _fake_response(VALID_VERDICT))
    validate("panel_verdict", result)
    assert result["overall"] == "pass"
    assert result["findings"] == []


def test_verdict_with_error_finding_validates():
    verdict = {
        "schema_version": "0.1.0", "persona": "cost_skeptic", "repo_git_sha": "deadbeef",
        "overall": "fail",
        "findings": [{
            "category": "retention", "severity": "error", "gate": "cs-unbounded-capture-no-retention",
            "summary": "gen_ai.input.messages captured at restricted tier with no retention note",
            "evidence": ["gen_ai.input.messages"],
            "recommendation": "add a retention/sampling policy for this signal",
        }],
    }
    result = run_cost_skeptic([FRAGMENT], "deadbeef", _completion_fn=lambda **kw: _fake_response(verdict))
    validate("panel_verdict", result)
    assert result["overall"] == "fail"
    assert result["findings"][0]["severity"] == "error"


def test_schema_invalid_response_raises():
    bad = {**VALID_VERDICT, "persona": "sre"}  # violates the const in this skill's output schema

    with pytest.raises(PanelReviewError, match="schema validation"):
        run_cost_skeptic([FRAGMENT], "deadbeef", _completion_fn=lambda **kw: _fake_response(bad))


def test_missing_credentials_detected_without_a_call(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(PanelReviewError, match="ANTHROPIC_API_KEY"):
        run_cost_skeptic([FRAGMENT], "deadbeef")


def test_missing_litellm_extra_wrapped_as_panel_review_error(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-key")
    monkeypatch.setitem(sys.modules, "litellm", None)
    with pytest.raises(PanelReviewError, match=r"pip install 'oah\[llm\]'"):
        run_cost_skeptic([FRAGMENT], "deadbeef")


def test_model_call_exception_wrapped():
    def fake(**kwargs):
        raise RuntimeError("connection reset")

    with pytest.raises(PanelReviewError, match="model call failed"):
        run_cost_skeptic([FRAGMENT], "deadbeef", _completion_fn=fake)


def test_finding_missing_evidence_field_fails_schema():
    """evidence is required per panel_verdict.schema.json -- 'a finding
    with no evidence is not a categorized verdict, it's a vibe' per
    SKILL.md; confirm the schema actually enforces that, not just prose."""
    bad = {
        "schema_version": "0.1.0", "persona": "cost_skeptic", "repo_git_sha": "deadbeef",
        "overall": "fail",
        "findings": [{
            "category": "retention", "severity": "error", "gate": "x", "summary": "no evidence here",
        }],
    }
    with pytest.raises(PanelReviewError, match="schema validation"):
        run_cost_skeptic([FRAGMENT], "deadbeef", _completion_fn=lambda **kw: _fake_response(bad))


def test_overall_inconsistent_with_error_finding_rejected():
    """Found by adversarial review: nothing previously checked that a
    persona's own `overall` field agreed with its own `findings` array --
    an `overall: "pass"` with an error-severity finding passed schema
    validation cleanly, silently downgrading what should be a fail."""
    bad = {
        "schema_version": "0.1.0", "persona": "cost_skeptic", "repo_git_sha": "deadbeef",
        "overall": "pass",
        "findings": [{
            "category": "retention", "severity": "error", "gate": "cs-x",
            "summary": "unbounded capture, no retention note", "evidence": ["x"],
        }],
    }
    with pytest.raises(PanelReviewError, match="inconsistent with its own findings"):
        run_cost_skeptic([FRAGMENT], "deadbeef", _completion_fn=lambda **kw: _fake_response(bad))


def test_overall_pass_with_findings_required_when_only_warnings():
    bad = {
        "schema_version": "0.1.0", "persona": "cost_skeptic", "repo_git_sha": "deadbeef",
        "overall": "pass",
        "findings": [{
            "category": "sampling", "severity": "warning", "gate": "cs-y",
            "summary": "no sampling policy addressed", "evidence": ["x"],
        }],
    }
    with pytest.raises(PanelReviewError, match="inconsistent with its own findings"):
        run_cost_skeptic([FRAGMENT], "deadbeef", _completion_fn=lambda **kw: _fake_response(bad))
