"""Regression tests for oah.design.gates (S5, architecture.md)."""
from oah.design.gates import run_gates, gates_passed
from oah.schemas import validate


def _fragment(**overrides):
    base = {
        "schema_version": "0.1.0",
        "lens": "generation-capture",
        "repo_git_sha": "deadbeef",
        "failure_mode": "fail_open",
        "signals": [{
            "name": "gen_ai.usage.input_tokens",
            "surface_point_ids": ["sp-0001"],
            "maps_to": {"kind": "otel_genai", "attribute": "gen_ai.usage.input_tokens"},
            "sensitivity_tier": "internal",
            "pii_masked": False,
            "supports_decision": "cost attribution per call",
            "acting_role": "cost owner",
            "latency_overhead_budget_ms": 5,
        }],
    }
    base.update(overrides)
    return base


def test_valid_fragment_passes_all_gates_and_schema():
    fragment = _fragment()
    validate("design_fragment", fragment)
    findings = run_gates(fragment, surface_map_point_ids=["sp-0001"])
    assert gates_passed(findings)
    assert all(f.passed for f in findings)


def test_missing_surface_point_coverage_fails():
    fragment = _fragment()
    findings = run_gates(fragment, surface_map_point_ids=["sp-0001", "sp-0002"])
    failed = [f for f in findings if f.gate == "every_surface_point_has_decision"]
    assert not failed[0].passed
    assert "sp-0002" in failed[0].reason
    assert not gates_passed(findings)


def test_empty_supports_decision_fails_anti_hoarding_gate():
    fragment = _fragment(signals=[{
        **_fragment()["signals"][0], "supports_decision": "   ",  # whitespace-only, not truly empty string
    }])
    findings = run_gates(fragment, surface_map_point_ids=["sp-0001"])
    failed = [f for f in findings if f.gate == "signals_name_decision_and_role"]
    assert not failed[0].passed


def test_missing_attribute_mapping_fails():
    fragment = _fragment(signals=[{
        **_fragment()["signals"][0], "maps_to": {"kind": "otel_genai"},  # no attribute
    }])
    findings = run_gates(fragment, surface_map_point_ids=["sp-0001"])
    failed = [f for f in findings if f.gate == "fields_map_to_otel_or_extension"]
    assert not failed[0].passed


def test_restricted_tier_without_masking_fails():
    fragment = _fragment(signals=[{
        **_fragment()["signals"][0], "sensitivity_tier": "restricted", "pii_masked": False,
    }])
    findings = run_gates(fragment, surface_map_point_ids=["sp-0001"])
    failed = [f for f in findings if f.gate == "pii_masked_above_tier"]
    assert not failed[0].passed


def test_restricted_tier_with_masking_passes():
    fragment = _fragment(signals=[{
        **_fragment()["signals"][0], "sensitivity_tier": "restricted", "pii_masked": True,
    }])
    findings = run_gates(fragment, surface_map_point_ids=["sp-0001"])
    failed = [f for f in findings if f.gate == "pii_masked_above_tier"]
    assert failed[0].passed


def test_consistency_assertion_referencing_unknown_signal_fails():
    fragment = _fragment(consistency_assertions=[
        {"description": "x implies y", "fields_involved": ["gen_ai.usage.input_tokens", "does_not_exist"]},
    ])
    findings = run_gates(fragment, surface_map_point_ids=["sp-0001"])
    failed = [f for f in findings if f.gate == "consistency_assertions_referential_integrity"]
    assert not failed[0].passed
    assert "does_not_exist" in str(failed[0].reason)


def test_advisory_contradiction_pair_flagged_as_warning_not_error():
    fragment = _fragment(signals=[
        _fragment()["signals"][0],
        {
            "name": "access_restricted", "surface_point_ids": ["sp-0001"],
            "maps_to": {"kind": "oah_extension", "attribute": "oah.access.restricted"},
            "sensitivity_tier": "internal", "pii_masked": False,
            "supports_decision": "gate response release", "acting_role": "reviewer",
        },
        {
            "name": "needs_review", "surface_point_ids": ["sp-0001"],
            "maps_to": {"kind": "oah_extension", "attribute": "oah.review.needed"},
            "sensitivity_tier": "internal", "pii_masked": False,
            "supports_decision": "route to human review", "acting_role": "reviewer",
        },
    ])
    findings = run_gates(fragment, surface_map_point_ids=["sp-0001"])
    advisory = [f for f in findings if f.gate == "advisory_possible_missing_consistency_assertion"][0]
    assert not advisory.passed
    assert advisory.severity == "warning"
    # A warning must not block progression on its own.
    assert gates_passed(findings)


def test_declared_assertion_clears_the_advisory_warning():
    fragment = _fragment(
        signals=[
            _fragment()["signals"][0],
            {
                "name": "access_restricted", "surface_point_ids": ["sp-0001"],
                "maps_to": {"kind": "oah_extension", "attribute": "oah.access.restricted"},
                "sensitivity_tier": "internal", "pii_masked": False,
                "supports_decision": "gate response release", "acting_role": "reviewer",
            },
            {
                "name": "needs_review", "surface_point_ids": ["sp-0001"],
                "maps_to": {"kind": "oah_extension", "attribute": "oah.review.needed"},
                "sensitivity_tier": "internal", "pii_masked": False,
                "supports_decision": "route to human review", "acting_role": "reviewer",
            },
        ],
        consistency_assertions=[{
            "description": "access_restricted implies needs_review",
            "fields_involved": ["access_restricted", "needs_review"],
        }],
    )
    findings = run_gates(fragment, surface_map_point_ids=["sp-0001"])
    advisory = [f for f in findings if f.gate == "advisory_possible_missing_consistency_assertion"][0]
    assert advisory.passed


def test_missing_latency_budget_fails():
    fragment = _fragment(signals=[{
        **_fragment()["signals"][0], "latency_overhead_budget_ms": None,
    }])
    del fragment["signals"][0]["latency_overhead_budget_ms"]
    findings = run_gates(fragment, surface_map_point_ids=["sp-0001"])
    failed = [f for f in findings if f.gate == "latency_budget_declared_per_point"]
    assert not failed[0].passed


def test_wrong_failure_mode_fails():
    fragment = _fragment(failure_mode="fail_closed")
    findings = run_gates(fragment, surface_map_point_ids=["sp-0001"])
    failed = [f for f in findings if f.gate == "failure_mode_fail_open"]
    assert not failed[0].passed


def test_freeze_step_without_resumption_condition_fails():
    fragment = _fragment(decision_menu_steps=[
        {"step": "freeze expansion", "type": "freeze"},
    ])
    findings = run_gates(fragment, surface_map_point_ids=["sp-0001"])
    failed = [f for f in findings if f.gate == "decision_menu_resumption_paired"]
    assert not failed[0].passed


def test_freeze_step_with_resumption_condition_passes():
    fragment = _fragment(decision_menu_steps=[
        {"step": "freeze expansion", "type": "freeze", "resumption_condition": "error rate back under 1% for 30min"},
    ])
    findings = run_gates(fragment, surface_map_point_ids=["sp-0001"])
    failed = [f for f in findings if f.gate == "decision_menu_resumption_paired"]
    assert failed[0].passed


def test_continue_step_never_needs_resumption_condition():
    fragment = _fragment(decision_menu_steps=[{"step": "continue as normal", "type": "continue"}])
    findings = run_gates(fragment, surface_map_point_ids=["sp-0001"])
    failed = [f for f in findings if f.gate == "decision_menu_resumption_paired"]
    assert failed[0].passed


# --- route_is_templated / cardinality_guard (docs/decisions/026) ---------

def test_signal_with_no_cardinality_guard_unaffected():
    """The gate is a no-op for every signal that doesn't set this optional
    field -- true for every genai signal today, by construction."""
    fragment = _fragment()
    findings = run_gates(fragment, surface_map_point_ids=["sp-0001"])
    result = [f for f in findings if f.gate == "route_is_templated"]
    assert result[0].passed


def test_cardinality_guard_is_templated_true_passes():
    fragment = _fragment(signals=[{
        **_fragment()["signals"][0], "cardinality_guard": {"is_templated": True},
    }])
    findings = run_gates(fragment, surface_map_point_ids=["sp-0001"])
    result = [f for f in findings if f.gate == "route_is_templated"]
    assert result[0].passed


def test_cardinality_guard_is_templated_false_without_reason_fails():
    fragment = _fragment(signals=[{
        **_fragment()["signals"][0], "cardinality_guard": {"is_templated": False},
    }])
    findings = run_gates(fragment, surface_map_point_ids=["sp-0001"])
    result = [f for f in findings if f.gate == "route_is_templated"]
    assert not result[0].passed


def test_cardinality_guard_is_templated_false_with_reason_passes():
    fragment = _fragment(signals=[{
        **_fragment()["signals"][0],
        "cardinality_guard": {"is_templated": False,
                               "unavailable_reason": "AEM resolves URLs to content paths by resource type"},
    }])
    findings = run_gates(fragment, surface_map_point_ids=["sp-0001"])
    result = [f for f in findings if f.gate == "route_is_templated"]
    assert result[0].passed
