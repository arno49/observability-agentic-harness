"""Regression tests for oah.design.readiness_report (S9, deterministic assembly)."""
from oah.design.readiness_report import build_readiness_report
from oah.schemas import validate

PASSING_GATE_FINDINGS = [{"gate": "failure_mode_fail_open", "passed": True, "reason": "ok", "severity": "error"}]
PASSING_PANEL = [{"schema_version": "0.1.0", "persona": "cost_skeptic", "repo_git_sha": "deadbeef",
                   "overall": "pass", "findings": []}]
EMPTY_EVENT_SCHEMA = {"schema_version": "0.1.0", "repo_git_sha": "deadbeef", "attributes": [],
                       "summary": {"attribute_count": 0, "otel_genai_count": 0, "oah_extension_count": 0, "lenses_included": []}}
EMPTY_GAP_MODEL = {"schema_version": "0.1.0", "repo_git_sha": "deadbeef", "gaps": []}
EMPTY_DTOS = {"schema_version": "0.1.0", "dtos": []}
SOME_DTOS = {"schema_version": "0.1.0", "dtos": [{
    "id": "dto-0001", "gap_id": "gap-0001", "surface_point_ids": ["sp-0001"],
    "change": {"type": "wrap_call", "file": "app.py", "anchor": "run"},
    "expected_events": [{"event_type": "generation", "required_attributes": []}],
    "risk": "low", "rollout_step": 1,
}]}


def test_clean_design_is_ready_with_conditions_not_ready_outright():
    """No S10/S11 evidence exists at this pipeline stage -- 'ready' would
    overclaim applied instrumentation that hasn't happened."""
    report = build_readiness_report(
        EMPTY_GAP_MODEL, PASSING_GATE_FINDINGS, PASSING_PANEL, EMPTY_EVENT_SCHEMA, EMPTY_DTOS,
        repo_git_sha="deadbeef",
    )
    validate("readiness_report", report)
    assert report["recommendation"]["decision"] == "ready_with_conditions"
    assert report["recommendation"]["top_blocker"] is None


def test_failed_gate_forces_remediate_before_release():
    failing = [{"gate": "failure_mode_fail_open", "passed": False, "reason": "wrong mode", "severity": "error"}]
    report = build_readiness_report(
        EMPTY_GAP_MODEL, failing, PASSING_PANEL, EMPTY_EVENT_SCHEMA, EMPTY_DTOS, repo_git_sha="deadbeef",
    )
    validate("readiness_report", report)
    assert report["recommendation"]["decision"] == "remediate_before_release"
    assert report["recommendation"]["top_blocker"] == "failure_mode_fail_open"


def test_failed_panel_forces_remediate_before_release():
    failing_panel = [{"schema_version": "0.1.0", "persona": "cost_skeptic", "repo_git_sha": "deadbeef",
                       "overall": "fail", "findings": [{"category": "x", "severity": "error", "gate": "cs-x",
                                                          "summary": "bad", "evidence": ["y"]}]}]
    report = build_readiness_report(
        EMPTY_GAP_MODEL, PASSING_GATE_FINDINGS, failing_panel, EMPTY_EVENT_SCHEMA, EMPTY_DTOS, repo_git_sha="deadbeef",
    )
    validate("readiness_report", report)
    assert report["recommendation"]["decision"] == "remediate_before_release"
    assert report["recommendation"]["top_blocker"] == "cs-x"


def test_unaddressed_critical_dark_gap_forces_remediate():
    gap_model = {"schema_version": "0.1.0", "repo_git_sha": "deadbeef", "gaps": [
        {"id": "gap-0001", "surface_point_ids": ["sp-0001"], "dimension": "generation_capture",
         "status": "dark", "priority": "p0", "rationale": "x"},
    ]}
    report = build_readiness_report(
        gap_model, PASSING_GATE_FINDINGS, PASSING_PANEL, EMPTY_EVENT_SCHEMA, EMPTY_DTOS, repo_git_sha="deadbeef",
    )
    assert report["recommendation"]["decision"] == "remediate_before_release"
    assert report["recommendation"]["top_blocker"] == "gap-0001"


def test_p3_dark_gap_does_not_block():
    """Only p0/p1 dark gaps force remediation -- a p3 dark gap is real but
    not release-blocking on its own."""
    gap_model = {"schema_version": "0.1.0", "repo_git_sha": "deadbeef", "gaps": [
        {"id": "gap-0001", "surface_point_ids": ["sp-0001"], "dimension": "generation_capture",
         "status": "dark", "priority": "p3", "rationale": "x"},
    ]}
    report = build_readiness_report(
        gap_model, PASSING_GATE_FINDINGS, PASSING_PANEL, EMPTY_EVENT_SCHEMA, EMPTY_DTOS, repo_git_sha="deadbeef",
    )
    assert report["recommendation"]["decision"] == "ready_with_conditions"


def test_context_populates_workflow_and_governance_fields():
    context = {
        "schema_version": "0.1.0", "repo_git_sha": "deadbeef", "interviewed_at": "2026-01-01T00:00:00Z",
        "workflows": [{"name": "support-chat", "criticality": "high", "pii_presence": "indirect"}],
        "source_inventory": [{"source": "internal-kb", "approval_status": "approved"}],
        "trust_boundaries": [{"context_field": "role", "verified_server_side": True}],
        "tool_action_boundary": "can send messages only",
    }
    report = build_readiness_report(
        EMPTY_GAP_MODEL, PASSING_GATE_FINDINGS, PASSING_PANEL, EMPTY_EVENT_SCHEMA, EMPTY_DTOS,
        context=context, repo_git_sha="deadbeef",
    )
    validate("readiness_report", report)
    assert "support-chat" in report["deployment_context"]["workflow"]
    assert report["data_and_governance"]["source_inventory"][0]["source"] == "internal-kb"
    assert "role" in report["data_and_governance"]["trust_boundary_verification"]
    assert report["data_and_governance"]["tool_action_boundary"] == "can send messages only"


def test_no_context_omits_data_and_governance_section_rather_than_fabricating():
    report = build_readiness_report(
        EMPTY_GAP_MODEL, PASSING_GATE_FINDINGS, PASSING_PANEL, EMPTY_EVENT_SCHEMA, EMPTY_DTOS, repo_git_sha="deadbeef",
    )
    assert "data_and_governance" not in report


def test_known_limitations_and_unknown_evidence_always_present():
    """The honest scoping (each lens's own narrower-than-architecture.md
    scope, no S10/S11) must always be stated, not just when something
    fails."""
    report = build_readiness_report(
        EMPTY_GAP_MODEL, PASSING_GATE_FINDINGS, PASSING_PANEL, EMPTY_EVENT_SCHEMA, EMPTY_DTOS, repo_git_sha="deadbeef",
    )
    assert len(report["known_limitations"]) >= 2
    assert any("S10" in u for u in report["recommendation"]["evidence_position"]["unknown"])
    assert any("S11" in u for u in report["recommendation"]["evidence_position"]["unknown"])


def test_rollout_ordering_limitation_reflects_whether_context_was_supplied():
    """This claim was stale before: it unconditionally said gap-priority-
    only even after S8 started using real workflow-criticality ordering
    whenever --context is supplied. Must reflect which one actually
    happened this run. Uses SOME_DTOS (not EMPTY_DTOS) since the claim is
    specifically about how DTOs that exist were ordered."""
    no_context_report = build_readiness_report(
        EMPTY_GAP_MODEL, PASSING_GATE_FINDINGS, PASSING_PANEL, EMPTY_EVENT_SCHEMA, SOME_DTOS, repo_git_sha="deadbeef",
    )
    assert any("gap-priority-only" in lim for lim in no_context_report["known_limitations"])

    context = {
        "schema_version": "0.1.0", "repo_git_sha": "deadbeef", "interviewed_at": "2026-01-01T00:00:00Z",
        "workflows": [{"name": "billing", "criticality": "critical"}],
    }
    with_context_report = build_readiness_report(
        EMPTY_GAP_MODEL, PASSING_GATE_FINDINGS, PASSING_PANEL, EMPTY_EVENT_SCHEMA, SOME_DTOS,
        context=context, repo_git_sha="deadbeef",
    )
    assert any("real workflow-criticality" in lim for lim in with_context_report["known_limitations"])
    assert not any("gap-priority-only" in lim for lim in with_context_report["known_limitations"])


def test_rollout_ordering_limitation_does_not_apply_when_no_dtos_exist():
    """Found by adversarial review: this claim used to be derived purely
    from whether context.yaml had workflows, ignoring the `dtos` argument
    entirely (accepted but never read) -- so it asserted a real ordering
    rule had been followed even when zero DTOs existed for it to apply
    to. Must say ordering doesn't apply, not claim either ordering
    happened, when dtos is empty -- even with a real workflow context."""
    context = {
        "schema_version": "0.1.0", "repo_git_sha": "deadbeef", "interviewed_at": "2026-01-01T00:00:00Z",
        "workflows": [{"name": "billing", "criticality": "critical"}],
    }
    report = build_readiness_report(
        EMPTY_GAP_MODEL, PASSING_GATE_FINDINGS, PASSING_PANEL, EMPTY_EVENT_SCHEMA, EMPTY_DTOS,
        context=context, repo_git_sha="deadbeef",
    )
    assert any("does not apply" in lim for lim in report["known_limitations"])
    assert not any("real workflow-criticality" in lim for lim in report["known_limitations"])
    assert not any("gap-priority-only" in lim for lim in report["known_limitations"])


def test_missing_persona_verdicts_surfaced_as_unknown():
    """PASSING_PANEL only has a cost_skeptic verdict -- sre/security ran
    but produced none this round (or never ran) must be named explicitly,
    not silently absent from evidence_position.unknown."""
    report = build_readiness_report(
        EMPTY_GAP_MODEL, PASSING_GATE_FINDINGS, PASSING_PANEL, EMPTY_EVENT_SCHEMA, EMPTY_DTOS, repo_git_sha="deadbeef",
    )
    unknown = report["recommendation"]["evidence_position"]["unknown"]
    assert any("sre" in u and "security" in u for u in unknown)


def test_no_gates_or_panel_run_does_not_falsely_claim_confirmed():
    """When S4 produced no design fragment (e.g. no credentials), S5/S6
    never ran at all -- gate_findings and panel_verdicts are both empty.
    Vacuous truth over an empty list must not read as 'checked and passed';
    that would fabricate confirmation of something that never happened."""
    report = build_readiness_report(
        EMPTY_GAP_MODEL, [], [], EMPTY_EVENT_SCHEMA, EMPTY_DTOS, repo_git_sha="deadbeef",
    )
    validate("readiness_report", report)
    assert report["recommendation"]["evidence_position"]["confirmed"] == []
    assert any("S5 gates have not run" in u for u in report["recommendation"]["evidence_position"]["unknown"])
    assert any("S6 panel has not run" in u for u in report["recommendation"]["evidence_position"]["unknown"])


def test_event_schema_attributes_become_key_signals():
    event_schema = {**EMPTY_EVENT_SCHEMA, "attributes": [
        {"name": "gen_ai.usage.input_tokens", "kind": "otel_genai", "stability": "development",
         "deprecated_by": None, "sensitivity_tier": "internal", "source_lenses": ["generation-capture"],
         "surface_point_ids": ["sp-0001"]},
    ]}
    report = build_readiness_report(
        EMPTY_GAP_MODEL, PASSING_GATE_FINDINGS, PASSING_PANEL, event_schema, EMPTY_DTOS, repo_git_sha="deadbeef",
    )
    assert "gen_ai.usage.input_tokens" in report["observability_plan"]["key_signals"]


FRAGMENT_WITH_HEALTH_THRESHOLDS = {
    "schema_version": "0.1.0", "lens": "telemetry-cost", "repo_git_sha": "deadbeef", "failure_mode": "fail_open",
    "signals": [{
        "name": "oah.telemetry_cost.cardinality_risk",
        "surface_point_ids": ["sp-0001"],
        "maps_to": {"kind": "oah_extension", "attribute": "oah.telemetry_cost.cardinality_risk"},
        "sensitivity_tier": "internal", "supports_decision": "sampling adjustment", "acting_role": "cost owner",
        "health_thresholds": [
            {"state": "green", "condition": "cardinality_risk == low", "basis": "assumed", "rationale": "stable"},
            {"state": "red", "condition": "cardinality_risk == high", "basis": "assumed", "rationale": "unbounded"},
        ],
    }],
}


def test_no_design_fragments_omits_health_thresholds_section():
    """docs/decisions/039 -- absent by default, like data_and_governance."""
    report = build_readiness_report(
        EMPTY_GAP_MODEL, PASSING_GATE_FINDINGS, PASSING_PANEL, EMPTY_EVENT_SCHEMA, EMPTY_DTOS, repo_git_sha="deadbeef",
    )
    validate("readiness_report", report)
    assert "health_thresholds" not in report["observability_plan"]
    assert report["observability_plan"]["alert_triggers"] == []


def test_health_thresholds_rolled_up_from_design_fragments():
    report = build_readiness_report(
        EMPTY_GAP_MODEL, PASSING_GATE_FINDINGS, PASSING_PANEL, EMPTY_EVENT_SCHEMA, EMPTY_DTOS,
        repo_git_sha="deadbeef", design_fragments=[FRAGMENT_WITH_HEALTH_THRESHOLDS],
    )
    validate("readiness_report", report)
    rollup = report["observability_plan"]["health_thresholds"]
    assert len(rollup) == 1
    assert rollup[0]["attribute"] == "oah.telemetry_cost.cardinality_risk"
    assert rollup[0]["lens"] == "telemetry-cost"
    assert len(rollup[0]["thresholds"]) == 2


def test_health_thresholds_red_state_becomes_alert_trigger():
    report = build_readiness_report(
        EMPTY_GAP_MODEL, PASSING_GATE_FINDINGS, PASSING_PANEL, EMPTY_EVENT_SCHEMA, EMPTY_DTOS,
        repo_git_sha="deadbeef", design_fragments=[FRAGMENT_WITH_HEALTH_THRESHOLDS],
    )
    triggers = report["observability_plan"]["alert_triggers"]
    assert len(triggers) == 1
    assert "cardinality_risk == high" in triggers[0]
    assert "green" not in "".join(triggers)


def test_assumed_health_thresholds_surfaced_in_evidence_position_assumed():
    report = build_readiness_report(
        EMPTY_GAP_MODEL, PASSING_GATE_FINDINGS, PASSING_PANEL, EMPTY_EVENT_SCHEMA, EMPTY_DTOS,
        repo_git_sha="deadbeef", design_fragments=[FRAGMENT_WITH_HEALTH_THRESHOLDS],
    )
    assumed = report["recommendation"]["evidence_position"]["assumed"]
    assert any("basis=assumed" in a for a in assumed)


def test_confirmed_health_thresholds_flagged_as_unverified_not_trusted():
    """docs/decisions/039's own named gap: no S5 gate blocks a lens from
    claiming basis=confirmed at S4 time, when it's never true this early.
    S9 must not silently promote that claim into evidence_position.confirmed."""
    fragment = {
        **FRAGMENT_WITH_HEALTH_THRESHOLDS,
        "signals": [{
            **FRAGMENT_WITH_HEALTH_THRESHOLDS["signals"][0],
            "health_thresholds": [
                {"state": "red", "condition": "cardinality_risk == high", "basis": "confirmed",
                 "rationale": "unbounded"},
            ],
        }],
    }
    report = build_readiness_report(
        EMPTY_GAP_MODEL, PASSING_GATE_FINDINGS, PASSING_PANEL, EMPTY_EVENT_SCHEMA, EMPTY_DTOS,
        repo_git_sha="deadbeef", design_fragments=[fragment],
    )
    unknown = report["recommendation"]["evidence_position"]["unknown"]
    assert any("basis=confirmed" in u and "unverified" in u for u in unknown)
    assert not any("confirmed" in c for c in report["recommendation"]["evidence_position"]["confirmed"])
