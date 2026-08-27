"""S5's slo_spec-specific gates (docs/decisions/011, docs/decisions/020).

Separate from oah/design/gates.py deliberately: every gate in that module
checks a design_fragment (a flat signal list); slo_spec is a structurally
different artifact (indicator/objective/alert_tiers/error_budget_policy),
and folding these checks into run_gates() would mean every gate function
in that module silently gaining an implicit "and this only applies to
design_fragment-shaped input" assumption it doesn't have today. Reuses
gates.py's own Finding dataclass -- same machine-readable-reason contract,
not a parallel one.
"""
from oah.design.gates import Finding


def _non_trivial(s):
    return isinstance(s, str) and s.strip() != ""


def check_burn_rate_matches_declared_inputs(slo_spec):
    """docs/decisions/011 Finding 3: burn_rate_multiplier is computed, not
    asserted -- budget_fraction * (period_days * 24) / detection_window_hours.
    Recomputed here and compared against every tier's own declared value;
    small floating-point drift is tolerated, a materially different number
    is not."""
    period_hours = slo_spec["objective"]["period_days"] * 24
    bad = []
    for tier in slo_spec["alert_tiers"]:
        expected = tier["budget_fraction"] * period_hours / tier["detection_window_hours"]
        if abs(expected - tier["burn_rate_multiplier"]) > 1e-6 * max(1, abs(expected)):
            bad.append({"tier": tier["tier"], "declared": tier["burn_rate_multiplier"], "expected": expected})
    if bad:
        return Finding(
            "slo_burn_rate_matches_declared_inputs", False,
            f"tier(s) whose burn_rate_multiplier doesn't match budget_fraction * period_hours / "
            f"detection_window_hours: {bad}",
        )
    return Finding("slo_burn_rate_matches_declared_inputs", True, "every tier's burn rate recomputes correctly")


def check_alert_tier_has_paired_short_window(slo_spec):
    """Every tier must declare a real short_window_hours (shorter than its
    own detection_window_hours -- a short window that isn't actually
    shorter defeats the multi-window-alerting purpose it exists for) and a
    non-trivial short_window_rationale -- Finding 3's own required-prose
    field, since the ratio itself has no derivation to gate on."""
    bad = []
    for tier in slo_spec["alert_tiers"]:
        if tier["short_window_hours"] >= tier["detection_window_hours"]:
            bad.append({"tier": tier["tier"], "reason": "short_window_hours is not shorter than detection_window_hours"})
        elif not _non_trivial(tier.get("short_window_rationale")):
            bad.append({"tier": tier["tier"], "reason": "missing/empty short_window_rationale"})
    if bad:
        return Finding(
            "slo_alert_tier_has_paired_short_window", False,
            f"tier(s) with an invalid or unexplained short window: {bad}",
        )
    return Finding("slo_alert_tier_has_paired_short_window", True, "every tier has a real, explained short window")


def check_policy_step_has_exit_criterion(slo_spec):
    bad = [s["step"] for s in slo_spec["error_budget_policy"]["steps"] if not _non_trivial(s.get("exit_criterion"))]
    if bad:
        return Finding(
            "slo_policy_step_has_exit_criterion", False,
            f"error-budget-policy step(s) with no exit_criterion: {bad}",
        )
    return Finding("slo_policy_step_has_exit_criterion", True, "every policy step has an exit criterion")


def check_policy_entry_criterion_references_real_tier(slo_spec):
    known_tiers = {t["tier"] for t in slo_spec["alert_tiers"]}
    bad = [s["step"] for s in slo_spec["error_budget_policy"]["steps"]
           if s.get("entry_criterion_tier") not in known_tiers]
    if bad:
        return Finding(
            "slo_policy_entry_criterion_references_real_tier", False,
            f"error-budget-policy step(s) whose entry_criterion_tier names a tier not in this "
            f"spec's own alert_tiers: {bad}",
        )
    return Finding("slo_policy_entry_criterion_references_real_tier", True,
                    "every policy step's entry criterion names a real tier")


def check_objective_declares_required_fields(slo_spec):
    objective = slo_spec["objective"]
    missing = [f for f in ("up_predicate", "granularity", "brownout_classification")
               if not _non_trivial(objective.get(f))]
    if missing:
        return Finding(
            "slo_objective_declares_required_fields", False,
            f"objective is missing/empty required field(s): {missing}",
        )
    return Finding("slo_objective_declares_required_fields", True,
                    "objective declares up_predicate, granularity, and brownout_classification")


def check_target_not_perfect(slo_spec):
    if slo_spec["objective"]["target"] >= 1.0:
        return Finding(
            "slo_target_not_perfect", False,
            f"objective.target is {slo_spec['objective']['target']} -- a target of 1.0 declares zero "
            f"error budget, making every alert tier's burn-rate math meaningless",
        )
    return Finding("slo_target_not_perfect", True, "objective.target is a real, non-perfect target")


def check_indicator_not_averaged_percentile(slo_spec):
    """schemas/slo_spec.schema.json's own aggregation_method enum already
    excludes 'averaging multiple precomputed percentiles' as a spellable
    option -- this gate is the belt to that schema's suspenders, in case a
    future schema revision widens the enum without carrying this specific
    invariant forward."""
    method = slo_spec["indicator"]["aggregation_method"]
    if method not in ("ratio_of_counts", "raw_histogram_bucket", "single_pass_percentile"):
        return Finding(
            "slo_indicator_not_averaged_percentile", False,
            f"indicator.aggregation_method {method!r} is not one of the schema's known-valid "
            f"single-pass methods -- averaging multiple precomputed percentiles is not a valid "
            f"percentile of the combined distribution",
        )
    return Finding("slo_indicator_not_averaged_percentile", True, "indicator uses a valid single-pass aggregation")


ALL_SLO_GATES = [
    check_burn_rate_matches_declared_inputs,
    check_alert_tier_has_paired_short_window,
    check_policy_step_has_exit_criterion,
    check_policy_entry_criterion_references_real_tier,
    check_objective_declares_required_fields,
    check_target_not_perfect,
    check_indicator_not_averaged_percentile,
]


def run_slo_gates(slo_spec):
    return [gate(slo_spec) for gate in ALL_SLO_GATES]


def slo_gates_passed(findings):
    return all(f.passed for f in findings if f.severity == "error")
