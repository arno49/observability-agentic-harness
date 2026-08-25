"""Regression tests for oah.design.dto_generator (S8)."""
import json
from types import SimpleNamespace

import pytest

from oah.design.dto_generator import generate_dtos, DtoGenerationError
from oah.schemas import validate


def _fake_response(payload):
    message = SimpleNamespace(content=json.dumps(payload))
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


EVENT_SCHEMA = {
    "schema_version": "0.1.0", "repo_git_sha": "deadbeef",
    "attributes": [{
        "name": "gen_ai.usage.input_tokens", "kind": "otel_genai", "stability": "development",
        "deprecated_by": None, "sensitivity_tier": "internal",
        "source_lenses": ["generation-capture"], "surface_point_ids": ["sp-0001"],
    }],
    "summary": {"attribute_count": 1, "otel_genai_count": 1, "oah_extension_count": 0,
                "lenses_included": ["generation-capture"]},
}

POINTS = [{"id": "sp-0001", "kind": "llm_generation", "file": "app.py", "line": 10, "symbol": "run"}]
GAPS = [{"id": "gap-0001", "surface_point_ids": ["sp-0001"], "dimension": "generation_capture",
         "status": "dark", "priority": "p1", "rationale": "x"}]


def _valid_dto_no_rollout_step():
    return {
        "schema_version": "0.1.0",
        "dtos": [{
            "id": "dto-0001", "gap_id": "gap-0001", "surface_point_ids": ["sp-0001"],
            "change": {"type": "wrap_call", "file": "app.py", "anchor": "run",
                       "preconditions": ["call not already wrapped"]},
            "expected_events": [{"event_type": "generation", "required_attributes": ["gen_ai.usage.input_tokens"]}],
            "risk": "low",
        }],
    }


def test_no_points_never_calls_the_model():
    calls = []
    result = generate_dtos(EVENT_SCHEMA, [], GAPS, "deadbeef", _completion_fn=lambda **kw: calls.append(kw))
    assert result is None
    assert calls == []


def test_valid_dto_gets_rollout_step_assigned_and_validates():
    result = generate_dtos(
        EVENT_SCHEMA, POINTS, GAPS, "deadbeef",
        _completion_fn=lambda **kw: _fake_response(_valid_dto_no_rollout_step()),
    )
    validate("implementation_dto", result)
    assert result["dtos"][0]["rollout_step"] == 1


def test_p0_gap_gets_earlier_rollout_step_than_p2():
    payload = {
        "schema_version": "0.1.0",
        "dtos": [
            {"id": "dto-a", "gap_id": "gap-low-priority", "surface_point_ids": ["sp-0001"],
             "change": {"type": "wrap_call", "file": "app.py"},
             "expected_events": [{"event_type": "generation", "required_attributes": ["gen_ai.usage.input_tokens"]}]},
            {"id": "dto-b", "gap_id": "gap-high-priority", "surface_point_ids": ["sp-0001"],
             "change": {"type": "wrap_call", "file": "app.py"},
             "expected_events": [{"event_type": "generation", "required_attributes": ["gen_ai.usage.input_tokens"]}]},
        ],
    }
    gaps = [
        {"id": "gap-low-priority", "surface_point_ids": ["sp-0001"], "dimension": "generation_capture",
         "status": "dark", "priority": "p2", "rationale": "x"},
        {"id": "gap-high-priority", "surface_point_ids": ["sp-0001"], "dimension": "generation_capture",
         "status": "dark", "priority": "p0", "rationale": "x"},
    ]
    result = generate_dtos(EVENT_SCHEMA, POINTS, gaps, "deadbeef",
                            _completion_fn=lambda **kw: _fake_response(payload))
    steps = {d["gap_id"]: d["rollout_step"] for d in result["dtos"]}
    assert steps["gap-high-priority"] < steps["gap-low-priority"]


def test_critical_workflow_dto_rolls_out_before_low_criticality_workflow():
    """architecture.md S7: 'first workflow = most critical one' -- this
    must win over gap priority alone, not just correlate with it by
    coincidence."""
    payload = {
        "schema_version": "0.1.0",
        "dtos": [
            {"id": "dto-low-wf", "gap_id": "gap-low-wf", "surface_point_ids": ["sp-0001"],
             "change": {"type": "wrap_call", "file": "app.py"},
             "expected_events": [{"event_type": "generation", "required_attributes": ["gen_ai.usage.input_tokens"]}]},
            {"id": "dto-critical-wf", "gap_id": "gap-critical-wf", "surface_point_ids": ["sp-0001"],
             "change": {"type": "wrap_call", "file": "app.py"},
             "expected_events": [{"event_type": "generation", "required_attributes": ["gen_ai.usage.input_tokens"]}]},
        ],
    }
    gaps = [
        {"id": "gap-low-wf", "surface_point_ids": ["sp-0001"], "dimension": "generation_capture",
         "status": "dark", "priority": "p0", "workflow": "internal-tool", "rationale": "x"},
        {"id": "gap-critical-wf", "surface_point_ids": ["sp-0001"], "dimension": "generation_capture",
         "status": "dark", "priority": "p2", "workflow": "billing", "rationale": "x"},
    ]
    context = {"workflows": [
        {"name": "internal-tool", "criticality": "low"},
        {"name": "billing", "criticality": "critical"},
    ]}
    result = generate_dtos(EVENT_SCHEMA, POINTS, gaps, "deadbeef", context=context,
                            _completion_fn=lambda **kw: _fake_response(payload))
    steps = {d["gap_id"]: d["rollout_step"] for d in result["dtos"]}
    # gap-critical-wf has the WORSE (higher) gap priority number but belongs
    # to the more critical workflow -- workflow criticality must win.
    assert steps["gap-critical-wf"] < steps["gap-low-wf"]


def test_dimension_tiering_orders_generation_capture_before_feedback_within_same_workflow():
    payload = {
        "schema_version": "0.1.0",
        "dtos": [
            {"id": "dto-feedback", "gap_id": "gap-feedback", "surface_point_ids": ["sp-0001"],
             "change": {"type": "wrap_call", "file": "app.py"},
             "expected_events": [{"event_type": "generation", "required_attributes": ["gen_ai.usage.input_tokens"]}]},
            {"id": "dto-gencap", "gap_id": "gap-gencap", "surface_point_ids": ["sp-0001"],
             "change": {"type": "wrap_call", "file": "app.py"},
             "expected_events": [{"event_type": "generation", "required_attributes": ["gen_ai.usage.input_tokens"]}]},
        ],
    }
    gaps = [
        {"id": "gap-feedback", "surface_point_ids": ["sp-0001"], "dimension": "feedback",
         "status": "dark", "priority": "p1", "workflow": "billing", "rationale": "x"},
        {"id": "gap-gencap", "surface_point_ids": ["sp-0001"], "dimension": "generation_capture",
         "status": "dark", "priority": "p1", "workflow": "billing", "rationale": "x"},
    ]
    context = {"workflows": [{"name": "billing", "criticality": "critical"}]}
    result = generate_dtos(EVENT_SCHEMA, POINTS, gaps, "deadbeef", context=context,
                            _completion_fn=lambda **kw: _fake_response(payload))
    steps = {d["gap_id"]: d["rollout_step"] for d in result["dtos"]}
    assert steps["gap-gencap"] < steps["gap-feedback"]


def test_no_context_falls_back_to_gap_priority_ordering_not_arbitrary():
    """Without context.yaml, every gap's workflow is unresolved -- must not
    collapse to an arbitrary dto-id order; gap priority still orders them
    sensibly, matching the pre-workflow-ordering behavior."""
    payload = {
        "schema_version": "0.1.0",
        "dtos": [
            {"id": "z-dto", "gap_id": "gap-p2", "surface_point_ids": ["sp-0001"],
             "change": {"type": "wrap_call", "file": "app.py"},
             "expected_events": [{"event_type": "generation", "required_attributes": ["gen_ai.usage.input_tokens"]}]},
            {"id": "a-dto", "gap_id": "gap-p0", "surface_point_ids": ["sp-0001"],
             "change": {"type": "wrap_call", "file": "app.py"},
             "expected_events": [{"event_type": "generation", "required_attributes": ["gen_ai.usage.input_tokens"]}]},
        ],
    }
    gaps = [
        {"id": "gap-p2", "surface_point_ids": ["sp-0001"], "dimension": "generation_capture",
         "status": "dark", "priority": "p2", "rationale": "x"},
        {"id": "gap-p0", "surface_point_ids": ["sp-0001"], "dimension": "generation_capture",
         "status": "dark", "priority": "p0", "rationale": "x"},
    ]
    result = generate_dtos(EVENT_SCHEMA, POINTS, gaps, "deadbeef",
                            _completion_fn=lambda **kw: _fake_response(payload))
    steps = {d["gap_id"]: d["rollout_step"] for d in result["dtos"]}
    assert steps["gap-p0"] < steps["gap-p2"]


def test_unknown_attribute_reference_raises():
    payload = _valid_dto_no_rollout_step()
    payload["dtos"][0]["expected_events"][0]["required_attributes"].append("gen_ai.made_up_attribute")
    with pytest.raises(DtoGenerationError, match="gen_ai.made_up_attribute"):
        generate_dtos(EVENT_SCHEMA, POINTS, GAPS, "deadbeef",
                       _completion_fn=lambda **kw: _fake_response(payload))


def test_rollout_step_in_model_output_is_rejected_by_schema():
    """SKILL.md's hard rule: the model must not set rollout_step. The
    skill's own output schema forbids it (additionalProperties: false
    without rollout_step listed) -- confirm that's actually enforced, not
    just written in prose."""
    payload = _valid_dto_no_rollout_step()
    payload["dtos"][0]["rollout_step"] = 1  # model attempting to set it anyway
    with pytest.raises(DtoGenerationError, match="schema validation"):
        generate_dtos(EVENT_SCHEMA, POINTS, GAPS, "deadbeef",
                       _completion_fn=lambda **kw: _fake_response(payload))


def test_missing_credentials_detected_without_a_call(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(DtoGenerationError, match="ANTHROPIC_API_KEY"):
        generate_dtos(EVENT_SCHEMA, POINTS, GAPS, "deadbeef")


def test_model_call_exception_wrapped():
    def fake(**kwargs):
        raise RuntimeError("connection reset")

    with pytest.raises(DtoGenerationError, match="model call failed"):
        generate_dtos(EVENT_SCHEMA, POINTS, GAPS, "deadbeef", _completion_fn=fake)


def test_dto_for_unknown_gap_id_defaults_to_lowest_priority_ordering():
    """A DTO referencing a gap_id not in the gaps list must not crash --
    falls back to the lowest-priority ordering tier, not an exception."""
    payload = _valid_dto_no_rollout_step()
    payload["dtos"][0]["gap_id"] = "gap-not-in-list"
    result = generate_dtos(EVENT_SCHEMA, POINTS, GAPS, "deadbeef",
                            _completion_fn=lambda **kw: _fake_response(payload))
    assert result["dtos"][0]["rollout_step"] == 1  # only DTO present, still gets a step
