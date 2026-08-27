"""Regression tests for oah.design.slo_gates (docs/decisions/020)."""
import json

from oah.design.slo_gates import run_slo_gates, slo_gates_passed
from oah.schemas import validate


def _valid_slo_spec():
    return {
        "schema_version": "0.1.0", "repo_git_sha": "deadbeef",
        "surface_point_ids": ["sp-0001"],
        "indicator": {
            "name": "booking-checkout availability",
            "good_event_definition": "http.server.request.duration sample with error.type absent",
            "aggregation_method": "ratio_of_counts",
        },
        "objective": {
            "target": 0.999, "period_days": 30,
            "up_predicate": "error.type is absent on the request",
            "granularity": "1m",
            "brownout_classification": "elevated latency > 2x baseline counts as brownout, half-weighted",
        },
        "alert_tiers": [
            {"tier": "fast_burn", "budget_fraction": 0.02, "detection_window_hours": 1,
             "short_window_hours": 0.0833, "short_window_rationale": "5 minutes, within on-call ack SLA",
             "burn_rate_multiplier": 14.4},
            {"tier": "slow_burn", "budget_fraction": 0.10, "detection_window_hours": 24,
             "short_window_hours": 2, "short_window_rationale": "2 hours, catches sustained degradation",
             "burn_rate_multiplier": 3.0},
        ],
        "error_budget_policy": {
            "steps": [
                {"step": "page on-call", "entry_criterion_tier": "fast_burn",
                 "exit_criterion": "burn rate returns below 14.4 for 15 minutes"},
                {"step": "freeze non-critical deploys", "entry_criterion_tier": "slow_burn",
                 "exit_criterion": "burn rate returns below 3.0 for 6 hours"},
            ],
        },
    }


def test_valid_slo_spec_validates_and_passes_all_gates():
    spec = _valid_slo_spec()
    validate("slo_spec", spec)
    findings = run_slo_gates(spec)
    assert slo_gates_passed(findings)
    assert all(f.passed for f in findings)


def test_burn_rate_mismatch_detected():
    spec = _valid_slo_spec()
    spec["alert_tiers"][0]["burn_rate_multiplier"] = 99.0
    findings = run_slo_gates(spec)
    assert not slo_gates_passed(findings)
    bad = next(f for f in findings if f.gate == "slo_burn_rate_matches_declared_inputs")
    assert not bad.passed


def test_burn_rate_recomputes_correctly_for_every_worked_example_row():
    """docs/decisions/011 Finding 3's own worked table, 30-day period."""
    period_hours = 30 * 24
    rows = [
        (0.02, 1, 14.4),
        (0.05, 6, 6.0),
        (0.10, 24, 3.0),
        (0.10, 72, 1.0),
    ]
    for budget_fraction, window, expected in rows:
        spec = _valid_slo_spec()
        spec["alert_tiers"] = [{
            "tier": "t", "budget_fraction": budget_fraction, "detection_window_hours": window,
            "short_window_hours": window / 2, "short_window_rationale": "test",
            "burn_rate_multiplier": budget_fraction * period_hours / window,
        }]
        spec["error_budget_policy"]["steps"] = [
            {"step": "s", "entry_criterion_tier": "t", "exit_criterion": "c"},
        ]
        findings = run_slo_gates(spec)
        assert slo_gates_passed(findings), (budget_fraction, window, findings)
        computed = spec["alert_tiers"][0]["burn_rate_multiplier"]
        assert abs(computed - expected) < 1e-9


def test_short_window_not_shorter_than_detection_window_rejected():
    spec = _valid_slo_spec()
    spec["alert_tiers"][0]["short_window_hours"] = 2.0  # >= detection_window_hours (1)
    findings = run_slo_gates(spec)
    bad = next(f for f in findings if f.gate == "slo_alert_tier_has_paired_short_window")
    assert not bad.passed


def test_empty_short_window_rationale_rejected():
    spec = _valid_slo_spec()
    spec["alert_tiers"][0]["short_window_rationale"] = "  "
    findings = run_slo_gates(spec)
    bad = next(f for f in findings if f.gate == "slo_alert_tier_has_paired_short_window")
    assert not bad.passed


def test_policy_step_missing_exit_criterion_rejected():
    spec = _valid_slo_spec()
    spec["error_budget_policy"]["steps"][0]["exit_criterion"] = ""
    findings = run_slo_gates(spec)
    bad = next(f for f in findings if f.gate == "slo_policy_step_has_exit_criterion")
    assert not bad.passed


def test_policy_step_dangling_tier_reference_rejected():
    spec = _valid_slo_spec()
    spec["error_budget_policy"]["steps"][0]["entry_criterion_tier"] = "no_such_tier"
    findings = run_slo_gates(spec)
    bad = next(f for f in findings if f.gate == "slo_policy_entry_criterion_references_real_tier")
    assert not bad.passed


def test_objective_missing_brownout_classification_rejected():
    spec = _valid_slo_spec()
    spec["objective"]["brownout_classification"] = ""
    findings = run_slo_gates(spec)
    bad = next(f for f in findings if f.gate == "slo_objective_declares_required_fields")
    assert not bad.passed


def test_target_of_one_rejected():
    spec = _valid_slo_spec()
    spec["objective"]["target"] = 1.0
    # schema itself already rejects target: 1.0 (exclusiveMaximum), but the
    # gate is a real, separate check -- verify it directly, not just via
    # schema validation, in case a future schema revision loosens the bound.
    findings = run_slo_gates(spec)
    bad = next(f for f in findings if f.gate == "slo_target_not_perfect")
    assert not bad.passed


def test_target_of_one_rejected_by_schema_too():
    import pytest
    from oah.schemas import SchemaValidationError
    spec = _valid_slo_spec()
    spec["objective"]["target"] = 1.0
    with pytest.raises(SchemaValidationError):
        validate("slo_spec", spec)


def test_averaged_percentile_aggregation_method_rejected_by_schema():
    """The schema's own enum has no value spelling out 'average of
    precomputed percentiles' -- an attempt to use one fails schema
    validation before the gate is even reached."""
    import pytest
    from oah.schemas import SchemaValidationError
    spec = _valid_slo_spec()
    spec["indicator"]["aggregation_method"] = "average_of_precomputed_percentiles"
    with pytest.raises(SchemaValidationError):
        validate("slo_spec", spec)
