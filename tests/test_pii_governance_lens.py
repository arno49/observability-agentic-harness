"""Regression tests for oah.design.lens's pii-governance wiring — same
mocked-_completion_fn reasoning as test_design_lens.py: no live API key in
this environment."""
import json
from types import SimpleNamespace

import pytest

from oah.design.lens import design_pii_governance, LensDesignError
from oah.design.gates import run_gates, gates_passed
from oah.schemas import validate


def _fake_response(payload):
    message = SimpleNamespace(content=json.dumps(payload))
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


POINT = {"id": "sp-0001", "kind": "llm_generation", "file": "app.py", "line": 10, "symbol": "run"}

VALID_FRAGMENT = {
    "schema_version": "0.1.0", "lens": "pii-governance", "repo_git_sha": "deadbeef",
    "failure_mode": "fail_open",
    "signals": [
        {
            "name": "oah.pii.masked_at_ingestion", "surface_point_ids": ["sp-0001"],
            "maps_to": {"kind": "oah_extension", "attribute": "oah.pii.masked_at_ingestion"},
            "sensitivity_tier": "confidential", "pii_masked": True,
            "supports_decision": "whether raw content is safe to store unmasked",
            "acting_role": "compliance reviewer", "latency_overhead_budget_ms": 1,
        },
        {
            "name": "oah.pii.retention_class", "surface_point_ids": ["sp-0001"],
            "maps_to": {"kind": "oah_extension", "attribute": "oah.pii.retention_class"},
            "sensitivity_tier": "confidential", "pii_masked": True,
            "supports_decision": "how long captured content is retained",
            "acting_role": "compliance reviewer",
        },
    ],
}


def test_no_points_never_calls_the_model():
    calls = []
    result = design_pii_governance([], "deadbeef", _completion_fn=lambda **kw: calls.append(kw))
    assert result is None
    assert calls == []


def test_does_not_filter_by_kind_filtering_is_the_callers_job():
    """docs/decisions/016: filtering moved to oah/cli.py's _design_all_lenses,
    driven by the loaded pack's own lenses[].target_kinds -- this design
    function itself has never filtered by kind, genai or otherwise; the
    service pack's own pii-governance points now go through the separate
    s4-pii-governance-route skill (docs/decisions/041), not this one, but
    the "filtering is the caller's job" contract this test proves is
    unchanged."""
    calls = []

    def fake(**kwargs):
        calls.append(kwargs)
        return _fake_response(VALID_FRAGMENT)

    other_kind = {"id": "sp-0002", "kind": "retrieval", "file": "app.py", "line": 20}
    design_pii_governance([POINT, other_kind], "deadbeef", _completion_fn=fake)
    sent = json.loads(calls[0]["messages"][1]["content"])
    assert len(sent["points"]) == 2


def test_prompt_uses_real_skill_instructions_not_a_copy():
    captured = {}

    def fake(**kwargs):
        captured.update(kwargs)
        return _fake_response(VALID_FRAGMENT)

    design_pii_governance([POINT], "deadbeef", _completion_fn=fake)
    system_msg = captured["messages"][0]["content"]
    assert "You design the pii-governance lens's slice" in system_msg


def test_valid_response_returned_and_satisfies_s5_gates():
    result = design_pii_governance([POINT], "deadbeef", _completion_fn=lambda **kw: _fake_response(VALID_FRAGMENT))
    validate("design_fragment", result)
    findings = run_gates(result, surface_map_point_ids=["sp-0001"])
    assert gates_passed(findings)


def test_schema_invalid_response_raises():
    bad = {**VALID_FRAGMENT, "failure_mode": "fail_closed"}  # violates the const

    def fake(**kwargs):
        return _fake_response(bad)

    with pytest.raises(LensDesignError, match="schema validation"):
        design_pii_governance([POINT], "deadbeef", _completion_fn=fake)


def test_otel_genai_kind_rejected_this_lens_has_no_upstream_attributes():
    """Unlike generation-capture, pii-governance has no gen_ai.* signals at
    all -- every maps_to.kind must be oah_extension; the output schema's
    own const enforces this, not just SKILL.md prose."""
    bad = json.loads(json.dumps(VALID_FRAGMENT))
    bad["signals"][0]["maps_to"]["kind"] = "otel_genai"

    def fake(**kwargs):
        return _fake_response(bad)

    with pytest.raises(LensDesignError, match="schema validation"):
        design_pii_governance([POINT], "deadbeef", _completion_fn=fake)


def test_missing_credentials_detected_without_a_call(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(LensDesignError, match="ANTHROPIC_API_KEY"):
        design_pii_governance([POINT], "deadbeef")


def test_model_call_exception_wrapped():
    def fake(**kwargs):
        raise RuntimeError("connection reset")

    with pytest.raises(LensDesignError, match="model call failed"):
        design_pii_governance([POINT], "deadbeef", _completion_fn=fake)


def test_context_passed_through_when_given():
    captured = {}

    def fake(**kwargs):
        captured.update(kwargs)
        return _fake_response(VALID_FRAGMENT)

    context = {"workflows": [{"name": "support", "criticality": "high", "pii_presence": "direct"}]}
    design_pii_governance([POINT], "deadbeef", context=context, _completion_fn=fake)
    sent = json.loads(captured["messages"][1]["content"])
    assert sent["context"] == context
