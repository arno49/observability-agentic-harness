"""S5 — deterministic invariant gates (architecture.md S5). Pure code, no
LLM: every check here is either a referential-integrity check against
surface_map.json, or a structural check the design_fragment schema alone
can't express (a required-when-conditional rule, a referenced ID that must
actually exist, a string that must be non-trivial not just non-empty).

A failed gate returns a machine-readable Finding (architecture.md: "A
failed gate blocks progression with a machine-readable reason"), not a
free-text complaint — S6/S9 downstream need to consume these
programmatically, not re-parse prose.

One deliberate scope boundary, stated not hidden: architecture.md's
"declared cross-field consistency assertions... are present wherever a
structured output has more than one field whose values can contradict
each other" requires understanding which fields *could* contradict —
that's a judgment call, not a mechanical one. This module checks
referential integrity of whatever assertions a fragment DOES declare
(every fields_involved name must correspond to a real signal), and flags
common contradiction-prone naming pairs as advisory, not authoritative --
it does not claim to determine "needed an assertion and didn't have one"
in general.
"""
from dataclasses import dataclass, field


@dataclass
class Finding:
    gate: str
    passed: bool
    reason: str
    severity: str = "error"  # "error" blocks progression; "warning" doesn't


# Naming pairs where, if both appear as signal names in one fragment with no
# consistency_assertions covering them, it's worth a human/S6 second look --
# advisory only, per this module's stated scope boundary above.
_ADVISORY_CONTRADICTION_PAIRS = [
    ({"restricted", "access_denied", "access_result"}, {"needs_review"}),
]


def _non_trivial(s):
    return isinstance(s, str) and s.strip() != ""


def check_every_surface_point_has_decision(fragment, surface_map_point_ids):
    covered = set()
    for signal in fragment.get("signals", []):
        covered.update(signal.get("surface_point_ids", []))
    missing = sorted(set(surface_map_point_ids) - covered)
    if missing:
        return Finding(
            "every_surface_point_has_decision", False,
            f"{len(missing)} surface point(s) have no design decision in this fragment: {missing}",
        )
    return Finding("every_surface_point_has_decision", True, "every surface point covered")


def check_no_phantom_surface_points(fragment, surface_map_point_ids):
    """Every lens's own SKILL.md states, verbatim, a Hard rule: 'Do not
    design signals for points not in the input batch.' The gate above only
    checks the missing direction (a real point with no signal); this
    checks the other direction (a signal naming a point ID that was never
    in the input at all) -- found by adversarial review to have no
    enforcement anywhere, meaning a hallucinated point ID silently passed
    schema validation, every existing S5 gate, and would have flowed
    into S7's merged event schema and S8's DTO generation undetected."""
    known = set(surface_map_point_ids)
    phantom = set()
    for signal in fragment.get("signals", []):
        phantom.update(set(signal.get("surface_point_ids", [])) - known)
    if phantom:
        return Finding(
            "no_phantom_surface_points", False,
            f"signal(s) reference surface point ID(s) not in this fragment's input batch: {sorted(phantom)}",
        )
    return Finding("no_phantom_surface_points", True, "no signal references a point outside the input batch")


def check_signals_name_decision_and_role(fragment):
    bad = [s["name"] for s in fragment.get("signals", [])
           if not _non_trivial(s.get("supports_decision")) or not _non_trivial(s.get("acting_role"))]
    if bad:
        return Finding(
            "signals_name_decision_and_role", False,
            f"signal(s) with an empty/trivial supports_decision or acting_role (anti-metric-hoarding gate): {bad}",
        )
    return Finding("signals_name_decision_and_role", True, "every signal names a decision and a role")


def check_fields_map_to_otel_or_extension(fragment):
    bad = []
    for s in fragment.get("signals", []):
        maps_to = s.get("maps_to", {})
        if maps_to.get("kind") not in ("otel_genai", "oah_extension") or not _non_trivial(maps_to.get("attribute")):
            bad.append(s["name"])
    if bad:
        return Finding(
            "fields_map_to_otel_or_extension", False,
            f"signal(s) missing a concrete OTel/oah.* attribute mapping: {bad}",
        )
    return Finding("fields_map_to_otel_or_extension", True, "every signal maps to a concrete attribute")


def check_pii_masked_above_tier(fragment):
    bad = [s["name"] for s in fragment.get("signals", [])
           if s.get("sensitivity_tier") in ("confidential", "restricted") and not s.get("pii_masked")]
    if bad:
        return Finding(
            "pii_masked_above_tier", False,
            f"signal(s) at confidential/restricted tier without pii_masked=true: {bad}",
        )
    return Finding("pii_masked_above_tier", True, "no unmasked PII above declared tier")


def check_consistency_assertions_referential_integrity(fragment):
    signal_names = {s["name"] for s in fragment.get("signals", [])}
    bad = []
    for assertion in fragment.get("consistency_assertions", []):
        unknown = [f for f in assertion["fields_involved"] if f not in signal_names]
        if unknown:
            bad.append({"assertion": assertion["description"], "unknown_fields": unknown})
    if bad:
        return Finding(
            "consistency_assertions_referential_integrity", False,
            f"consistency assertion(s) reference signal names not declared in this fragment: {bad}",
        )
    return Finding("consistency_assertions_referential_integrity", True, "all assertions reference real signals")


def check_advisory_possible_missing_consistency_assertion(fragment):
    signal_names = {s["name"] for s in fragment.get("signals", [])}
    covered_pairs = set()
    for a in fragment.get("consistency_assertions", []):
        covered_pairs.add(frozenset(a["fields_involved"]))

    for group_a, group_b in _ADVISORY_CONTRADICTION_PAIRS:
        matches_a = {n for n in signal_names if any(k in n for k in group_a)}
        matches_b = {n for n in signal_names if any(k in n for k in group_b)}
        for a in matches_a:
            for b in matches_b:
                if not any({a, b} <= pair for pair in covered_pairs):
                    return Finding(
                        "advisory_possible_missing_consistency_assertion", False,
                        f"'{a}' and '{b}' look like they could contradict each other with no declared "
                        f"consistency assertion covering both -- worth a human/S6 look, not a hard failure",
                        severity="warning",
                    )
    return Finding("advisory_possible_missing_consistency_assertion", True, "no obvious uncovered pair found")


def check_latency_budget_declared_per_point(fragment, surface_map_point_ids):
    points_with_budget = set()
    for s in fragment.get("signals", []):
        if s.get("latency_overhead_budget_ms") is not None:
            points_with_budget.update(s.get("surface_point_ids", []))
    missing = sorted(set(surface_map_point_ids) - points_with_budget)
    if missing:
        return Finding(
            "latency_budget_declared_per_point", False,
            f"surface point(s) with no latency-overhead budget declared on any covering signal: {missing}",
        )
    return Finding("latency_budget_declared_per_point", True, "every surface point has a declared latency budget")


def check_failure_mode_fail_open(fragment):
    if fragment.get("failure_mode") != "fail_open":
        return Finding(
            "failure_mode_fail_open", False,
            f"failure_mode is {fragment.get('failure_mode')!r}, must be 'fail_open' — telemetry loss must never break the product",
        )
    return Finding("failure_mode_fail_open", True, "failure_mode is fail_open")


def check_decision_menu_resumption_paired(fragment):
    bad = [
        step["step"] for step in fragment.get("decision_menu_steps", [])
        if step["type"] in ("pause", "freeze", "throttle") and not _non_trivial(step.get("resumption_condition"))
    ]
    if bad:
        return Finding(
            "decision_menu_resumption_paired", False,
            f"decision-menu step(s) of type pause/freeze/throttle with no paired resumption condition: {bad}",
        )
    return Finding("decision_menu_resumption_paired", True, "every pause/freeze/throttle step has a resumption condition")


ALL_GATES = [
    check_every_surface_point_has_decision,
    check_no_phantom_surface_points,
    check_signals_name_decision_and_role,
    check_fields_map_to_otel_or_extension,
    check_pii_masked_above_tier,
    check_consistency_assertions_referential_integrity,
    check_advisory_possible_missing_consistency_assertion,
    check_latency_budget_declared_per_point,
    check_failure_mode_fail_open,
    check_decision_menu_resumption_paired,
]

# Gates that need surface_map_point_ids as a second argument, vs. fragment-only.
_NEEDS_POINT_IDS = {
    check_every_surface_point_has_decision,
    check_no_phantom_surface_points,
    check_latency_budget_declared_per_point,
}


def run_gates(fragment, surface_map_point_ids):
    findings = []
    for gate in ALL_GATES:
        if gate in _NEEDS_POINT_IDS:
            findings.append(gate(fragment, surface_map_point_ids))
        else:
            findings.append(gate(fragment))
    return findings


def gates_passed(findings):
    """Only 'error' severity findings block progression -- 'warning' ones
    (the advisory contradiction check) surface for human/S6 attention
    without failing the gate outright, per this module's stated scope
    boundary."""
    return all(f.passed for f in findings if f.severity == "error")
