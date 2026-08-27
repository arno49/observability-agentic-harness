"""Regression tests for oah.design.dependency_gates (docs/decisions/021)."""
from oah.design.dependency_gates import run_dependency_gates, dependency_gates_passed
from oah.schemas import validate


def _valid_dependency_model():
    return {
        "schema_version": "0.1.0", "repo_git_sha": "deadbeef",
        "surface_point_ids": ["sp-0001"],
        "edges": [
            {
                "name": "payment-service", "dependency_kind": "http_client_call", "criticality": "hard",
                "own_target": 0.999, "required_dependency_target": 0.9999,
                "budget_split": {"own_failures_fraction": 0.6, "dependency_failures_fraction": 0.4},
                "fallback_behavior": "circuit breaker, falls back to cached rate after 3 consecutive failures",
            },
            {
                "name": "analytics-events queue", "dependency_kind": "queue_producer", "criticality": "soft",
                "own_target": 0.999, "required_dependency_target": 0.99,
                "budget_split": {"own_failures_fraction": 1.0, "dependency_failures_fraction": 0.0},
                "fallback_behavior": "publish failure logged and dropped; does not affect the request",
            },
        ],
    }


def test_valid_dependency_model_validates_and_passes_all_gates():
    model = _valid_dependency_model()
    validate("dependency_model", model)
    findings = run_dependency_gates(model)
    assert dependency_gates_passed(findings)
    assert all(f.passed for f in findings)


def test_extra_nine_rule_violation_detected_for_hard_edge():
    model = _valid_dependency_model()
    # 0.9995 is "more nines" by digit count but only a 2x tighter failure
    # rate, not the required 10x -- the real bug this gate exists to catch.
    model["edges"][0]["required_dependency_target"] = 0.9995
    findings = run_dependency_gates(model)
    assert not dependency_gates_passed(findings)
    bad = next(f for f in findings if f.gate == "critical_dependency_extra_nine")
    assert not bad.passed


def test_extra_nine_rule_exactly_at_boundary_passes():
    model = _valid_dependency_model()
    # own_target 0.999 -> own_failure_rate 0.001 -> required dependency
    # failure rate <= 0.0001 -> required_dependency_target >= 0.9999 exactly.
    model["edges"][0]["required_dependency_target"] = 0.9999
    findings = run_dependency_gates(model)
    bad = next(f for f in findings if f.gate == "critical_dependency_extra_nine")
    assert bad.passed


def test_extra_nine_rule_not_applied_to_soft_edge():
    model = _valid_dependency_model()
    # The soft edge's required_dependency_target (0.99) would fail the
    # extra-nine ratio against own_target (0.999) if it were checked --
    # confirming the gate correctly skips soft edges entirely.
    findings = run_dependency_gates(model)
    bad = next(f for f in findings if f.gate == "critical_dependency_extra_nine")
    assert bad.passed


def test_budget_split_not_summing_to_one_detected():
    model = _valid_dependency_model()
    model["edges"][0]["budget_split"] = {"own_failures_fraction": 0.5, "dependency_failures_fraction": 0.3}
    findings = run_dependency_gates(model)
    bad = next(f for f in findings if f.gate == "dependency_budget_split_sums_to_one")
    assert not bad.passed


def test_missing_fallback_behavior_detected():
    model = _valid_dependency_model()
    model["edges"][0]["fallback_behavior"] = ""
    findings = run_dependency_gates(model)
    bad = next(f for f in findings if f.gate == "dependency_edge_names_fallback_behavior")
    assert not bad.passed
