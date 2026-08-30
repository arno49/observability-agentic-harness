"""Regression tests for oah.design.readiness_html (docs/decisions/047)."""
from oah.design.readiness_html import render_readiness_html

MINIMAL_REPORT = {
    "schema_version": "0.1.0",
    "repo_git_sha": "deadbeef",
    "deployment_context": {"workflow": "chat", "intended_users": "end users", "environment": "prod"},
    "release_evidence": {"release_identifiers": {}, "owners": {}},
    "observability_plan": {"key_signals": []},
    "failure_response": {"failure_modes": [], "incident_route": "unknown"},
    "recommendation": {
        "decision": "ready_with_conditions",
        "rationale": "S5 gates and S6 review pass; no S10/S11 evidence exists yet.",
        "next_action_owner": "unknown",
    },
}


def test_renders_decision_and_rationale():
    out = render_readiness_html(MINIMAL_REPORT)
    assert "ready_with_conditions" in out
    assert "S5 gates and S6 review pass" in out
    assert "<!DOCTYPE html>" in out


def test_escapes_untrusted_free_text():
    """rationale/reason text ultimately traces back to a model's own
    free-text output -- must never be interpolated unescaped into HTML."""
    report = dict(MINIMAL_REPORT)
    report["recommendation"] = dict(MINIMAL_REPORT["recommendation"])
    report["recommendation"]["rationale"] = "<script>alert(1)</script>"
    out = render_readiness_html(report)
    assert "<script>alert(1)</script>" not in out
    assert "&lt;script&gt;" in out


def test_omits_absent_optional_sections():
    out = render_readiness_html(MINIMAL_REPORT)
    assert "Data & governance" not in out
    assert "Known limitations" not in out
    assert "S5 gate findings" not in out
    assert "S6 panel verdicts" not in out


def test_includes_present_optional_sections():
    report = dict(MINIMAL_REPORT)
    report["known_limitations"] = ["tracing only covers same-process asyncio"]
    report["data_and_governance"] = {"restricted_source_handling": "exclude"}
    out = render_readiness_html(report)
    assert "Known limitations" in out
    assert "tracing only covers same-process asyncio" in out
    assert "Data &amp; governance" in out or "Data & governance" in out
    assert "exclude" in out


def test_gate_summary_rolls_up_pass_and_fail_counts():
    gate_findings = [
        {"gate": "failure_mode_fail_open", "passed": True, "reason": "ok", "severity": "error"},
        {"gate": "every_surface_point_has_decision", "passed": False,
         "reason": "sp-0001 has no decision", "severity": "error"},
        {"gate": "every_surface_point_has_decision", "passed": True, "reason": "ok", "severity": "error"},
    ]
    out = render_readiness_html(MINIMAL_REPORT, gate_findings=gate_findings)
    assert "S5 gate findings" in out
    assert "every_surface_point_has_decision" in out
    assert "1/2" in out  # one pass, one fail for this gate
    assert "sp-0001 has no decision" in out


def test_panel_summary_shows_persona_and_findings():
    panel_verdicts = [
        {"schema_version": "0.1.0", "persona": "security", "repo_git_sha": "deadbeef",
         "overall": "fail", "findings": [{"category": "x", "severity": "error", "gate": "sec-1",
                                           "summary": "unmasked PII", "evidence": ["sp-0001"]}]},
    ]
    out = render_readiness_html(MINIMAL_REPORT, panel_verdicts=panel_verdicts)
    assert "S6 panel verdicts" in out
    assert "security" in out
    assert "unmasked PII" in out


def test_eval_coverage_and_health_thresholds_tables_render():
    report = dict(MINIMAL_REPORT)
    report["release_evidence"] = dict(MINIMAL_REPORT["release_evidence"])
    report["release_evidence"]["eval_coverage"] = [
        {"case_class": "common", "status": "covered", "expected_behavior": "answer", "notes": "n/a"},
    ]
    report["observability_plan"] = dict(MINIMAL_REPORT["observability_plan"])
    report["observability_plan"]["health_thresholds"] = [
        {"attribute": "oah.ops.degradation_response", "lens": "ops", "surface_point_ids": ["sp-0018"],
         "thresholds": [{"state": "red", "condition": "degradation_response == unsafe_fallback",
                          "basis": "assumed", "rationale": "x"}]},
    ]
    out = render_readiness_html(report)
    assert "eval_coverage" in out
    assert "common" in out and "covered" in out
    assert "health_thresholds" in out
    assert "oah.ops.degradation_response" in out
