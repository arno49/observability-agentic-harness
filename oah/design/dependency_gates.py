"""S5's dependency_model-specific gates (docs/decisions/011, docs/decisions/021).

Separate from oah/design/gates.py and oah/design/slo_gates.py for the same
reason those two are separate from each other: dependency_model is a
structurally different artifact (a list of dependency edges, not a flat
signal list and not an SLO structure), so its own checks belong in their
own module rather than gaining an implicit "only applies to X-shaped
input" exception inside a module that doesn't otherwise need one. Reuses
gates.py's own Finding dataclass.
"""
from oah.design.gates import Finding


def _non_trivial(s):
    return isinstance(s, str) and s.strip() != ""


def check_critical_dependency_extra_nine(dependency_model):
    """docs/decisions/011: 'a critical dependency's target is at least one
    nine better than its dependent's.' Only applies to criticality: hard
    edges -- a soft dependency's failure doesn't fail the calling request,
    so its own reliability is a separate, independent concern the extra-
    nine rule doesn't govern. 'One nine better' means the dependency's own
    failure rate (1 - target) is at most one-tenth of the dependent's own
    failure rate (1 - own_target) -- the real arithmetic behind "one more
    nine," not just a larger target value."""
    bad = []
    for edge in dependency_model["edges"]:
        if edge["criticality"] != "hard":
            continue
        own_failure_rate = 1 - edge["own_target"]
        dependency_failure_rate = 1 - edge["required_dependency_target"]
        if dependency_failure_rate > own_failure_rate / 10 * 1.0001:  # small float tolerance
            bad.append({
                "edge": edge["name"], "own_target": edge["own_target"],
                "required_dependency_target": edge["required_dependency_target"],
            })
    if bad:
        return Finding(
            "critical_dependency_extra_nine", False,
            f"hard-dependency edge(s) whose required_dependency_target is not at least one nine "
            f"better than own_target: {bad}",
        )
    return Finding("critical_dependency_extra_nine", True,
                    "every hard dependency's required target is at least one nine better than its dependent's")


def check_budget_split_sums_to_one(dependency_model):
    bad = []
    for edge in dependency_model["edges"]:
        split = edge["budget_split"]
        total = split["own_failures_fraction"] + split["dependency_failures_fraction"]
        if abs(total - 1.0) > 1e-6:
            bad.append({"edge": edge["name"], "total": total})
    if bad:
        return Finding(
            "dependency_budget_split_sums_to_one", False,
            f"edge(s) whose budget_split fractions don't sum to 1.0: {bad}",
        )
    return Finding("dependency_budget_split_sums_to_one", True, "every edge's budget split sums to 1.0")


def check_every_edge_names_fallback_behavior(dependency_model):
    bad = [e["name"] for e in dependency_model["edges"] if not _non_trivial(e.get("fallback_behavior"))]
    if bad:
        return Finding(
            "dependency_edge_names_fallback_behavior", False,
            f"edge(s) with no fallback_behavior stated: {bad}",
        )
    return Finding("dependency_edge_names_fallback_behavior", True, "every edge states its fallback behavior")


ALL_DEPENDENCY_GATES = [
    check_critical_dependency_extra_nine,
    check_budget_split_sums_to_one,
    check_every_edge_names_fallback_behavior,
]


def run_dependency_gates(dependency_model):
    return [gate(dependency_model) for gate in ALL_DEPENDENCY_GATES]


def dependency_gates_passed(findings):
    return all(f.passed for f in findings if f.severity == "error")
