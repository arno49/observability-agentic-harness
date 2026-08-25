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
    happened this run."""
    no_context_report = build_readiness_report(
        EMPTY_GAP_MODEL, PASSING_GATE_FINDINGS, PASSING_PANEL, EMPTY_EVENT_SCHEMA, EMPTY_DTOS, repo_git_sha="deadbeef",
    )
    assert any("gap-priority-only" in lim for lim in no_context_report["known_limitations"])

    context = {
        "schema_version": "0.1.0", "repo_git_sha": "deadbeef", "interviewed_at": "2026-01-01T00:00:00Z",
        "workflows": [{"name": "billing", "criticality": "critical"}],
    }
    with_context_report = build_readiness_report(
        EMPTY_GAP_MODEL, PASSING_GATE_FINDINGS, PASSING_PANEL, EMPTY_EVENT_SCHEMA, EMPTY_DTOS,
        context=context, repo_git_sha="deadbeef",
    )
    assert any("real workflow-criticality" in lim for lim in with_context_report["known_limitations"])
    assert not any("gap-priority-only" in lim for lim in with_context_report["known_limitations"])


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
