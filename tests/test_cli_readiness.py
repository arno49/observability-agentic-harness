"""In-process test for cmd_readiness's full flow -- real S1/S2/S3 + mocked
S4 lens + mocked S6 panel + real deterministic S5/S7/S8/S9 assembly."""
import argparse
import json
import subprocess

from unittest.mock import patch

from oah.cli import cmd_readiness


def _init_git_repo(path):
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "-c", "user.email=t@t.com", "-c", "user.name=t",
                     "commit", "--allow-empty", "-q", "-m", "init"], cwd=path, check=True)


def test_readiness_end_to_end_with_mocked_lens_and_panel(tmp_path):
    target = tmp_path / "target_repo"
    target.mkdir()
    (target / "app.py").write_text(
        "import anthropic\nclient = anthropic.Anthropic()\n"
        "response = client.messages.create(model='x')\n"
    )
    _init_git_repo(target)

    def fake_lens(points, repo_git_sha, context=None, model=None, _completion_fn=None):
        point_id = points[0]["id"]
        return {
            "schema_version": "0.1.0", "lens": "generation-capture", "repo_git_sha": repo_git_sha,
            "failure_mode": "fail_open",
            "signals": [{
                "name": "gen_ai.usage.input_tokens", "surface_point_ids": [point_id],
                "maps_to": {"kind": "otel_genai", "attribute": "gen_ai.usage.input_tokens"},
                "sensitivity_tier": "internal", "pii_masked": False,
                "supports_decision": "cost attribution", "acting_role": "cost owner",
                "latency_overhead_budget_ms": 5,
            }],
        }

    def fake_panel(design_fragments, repo_git_sha, context=None, model=None, _completion_fn=None):
        return {"schema_version": "0.1.0", "persona": "cost_skeptic", "repo_git_sha": repo_git_sha,
                "overall": "pass", "findings": []}

    def fake_generate_dtos(event_schema, points, gaps, repo_git_sha, context=None, model=None, _completion_fn=None, pack=None):
        point_id = points[0]["id"]
        gap_id = gaps[0]["id"]
        return {
            "schema_version": "0.1.0",
            "dtos": [{
                "id": "dto-0001", "gap_id": gap_id, "surface_point_ids": [point_id],
                "change": {"type": "wrap_call", "file": "app.py", "anchor": "run"},
                "expected_events": [{"event_type": "generation",
                                      "required_attributes": ["gen_ai.usage.input_tokens"]}],
                "risk": "low", "rollout_step": 1,
            }],
        }

    args = argparse.Namespace(target=str(target), context=None, output=str(tmp_path / "readiness_report.json"))
    with patch("oah.design.lens.design_generation_capture", side_effect=fake_lens), \
         patch("oah.design.panel.run_cost_skeptic", side_effect=fake_panel), \
         patch("oah.design.dto_generator.generate_dtos", side_effect=fake_generate_dtos):
        rc = cmd_readiness(args)

    assert rc == 0
    report = json.loads((tmp_path / "readiness_report.json").read_text())
    # A designed DTO doesn't close the gap -- no instrumentation has actually
    # been applied (S10) yet, so the underlying gap is still "dark" and, if
    # p0/p1, still blocks. This is the same conservative ceiling as
    # ready_with_conditions taken one step further.
    assert report["recommendation"]["decision"] == "remediate_before_release"
    assert "gen_ai.usage.input_tokens" in report["observability_plan"]["key_signals"]


def test_readiness_no_points_skips_gracefully(tmp_path):
    target = tmp_path / "target_repo"
    target.mkdir()
    (target / "app.py").write_text("x = 1\n")
    _init_git_repo(target)

    args = argparse.Namespace(target=str(target), context=None, output=None)
    assert cmd_readiness(args) == 0


# --- --save-intermediates ---------------------------------------------------
# readiness_report.json's own recommendation only ever aggregates gate names
# and counts -- found while explaining a real remediate_before_release verdict
# from a real 375-point run (docs/decisions/032-036's own mf-analyzer-web
# pilot) that had no way to say WHICH point/lens triggered which gate beyond
# a bare name and a count. The detail (design_fragments, gate_findings with
# their real per-point reasons, panel_verdicts) was already computed inside
# cmd_readiness and silently discarded before this flag existed.

def test_save_intermediates_writes_real_detail_behind_the_summary(tmp_path):
    target = tmp_path / "target_repo"
    target.mkdir()
    (target / "app.py").write_text(
        "import anthropic\nclient = anthropic.Anthropic()\n"
        "response = client.messages.create(model='x')\n"
    )
    _init_git_repo(target)

    def fake_lens(points, repo_git_sha, context=None, model=None, _completion_fn=None):
        point_id = points[0]["id"]
        return {
            "schema_version": "0.1.0", "lens": "generation-capture", "repo_git_sha": repo_git_sha,
            "failure_mode": "fail_open",
            "signals": [{
                "name": "gen_ai.usage.input_tokens", "surface_point_ids": [point_id],
                "maps_to": {"kind": "otel_genai", "attribute": "gen_ai.usage.input_tokens"},
                "sensitivity_tier": "internal", "pii_masked": False,
                "supports_decision": "cost attribution", "acting_role": "cost owner",
                "latency_overhead_budget_ms": 5,
            }],
        }

    def fake_panel(design_fragments, repo_git_sha, context=None, model=None, _completion_fn=None):
        return {"schema_version": "0.1.0", "persona": "cost_skeptic", "repo_git_sha": repo_git_sha,
                "overall": "pass", "findings": []}

    intermediates_path = tmp_path / "intermediates.json"
    args = argparse.Namespace(target=str(target), context=None, output=None,
                               save_intermediates=str(intermediates_path))
    with patch("oah.design.lens.design_generation_capture", side_effect=fake_lens), \
         patch("oah.design.panel.run_cost_skeptic", side_effect=fake_panel):
        rc = cmd_readiness(args)

    assert rc == 0
    saved = json.loads(intermediates_path.read_text())
    assert set(saved.keys()) == {"design_fragments", "gate_findings", "panel_verdicts", "event_schema", "dtos"}
    assert saved["design_fragments"][0]["lens"] == "generation-capture"
    assert saved["panel_verdicts"][0]["persona"] == "cost_skeptic"


def test_no_save_intermediates_flag_writes_nothing_extra(tmp_path):
    """Byte-identical default: a Namespace without save_intermediates at
    all (the shape every caller had before this flag existed) must not
    raise, and must not write anything beyond the normal report."""
    target = tmp_path / "target_repo"
    target.mkdir()
    (target / "app.py").write_text("x = 1\n")
    _init_git_repo(target)

    args = argparse.Namespace(target=str(target), context=None, output=None)
    assert cmd_readiness(args) == 0
    assert not (tmp_path / "intermediates.json").exists()


# --- --html (docs/decisions/047) --------------------------------------------
# A third, human-readable output alongside JSON (-o/stdout) and the
# recommendation/rationale lines already printed to stderr -- on par with
# --save-intermediates, using the same in-memory gate_findings/panel_verdicts
# this run already computed, without requiring --save-intermediates too.

def test_html_flag_writes_self_contained_report(tmp_path):
    target = tmp_path / "target_repo"
    target.mkdir()
    (target / "app.py").write_text(
        "import anthropic\nclient = anthropic.Anthropic()\n"
        "response = client.messages.create(model='x')\n"
    )
    _init_git_repo(target)

    def fake_lens(points, repo_git_sha, context=None, model=None, _completion_fn=None):
        point_id = points[0]["id"]
        return {
            "schema_version": "0.1.0", "lens": "generation-capture", "repo_git_sha": repo_git_sha,
            "failure_mode": "fail_open",
            "signals": [{
                "name": "gen_ai.usage.input_tokens", "surface_point_ids": [point_id],
                "maps_to": {"kind": "otel_genai", "attribute": "gen_ai.usage.input_tokens"},
                "sensitivity_tier": "internal", "pii_masked": False,
                "supports_decision": "cost attribution", "acting_role": "cost owner",
                "latency_overhead_budget_ms": 5,
            }],
        }

    def fake_panel(design_fragments, repo_git_sha, context=None, model=None, _completion_fn=None):
        return {"schema_version": "0.1.0", "persona": "cost_skeptic", "repo_git_sha": repo_git_sha,
                "overall": "pass", "findings": []}

    html_path = tmp_path / "readiness_report.html"
    args = argparse.Namespace(target=str(target), context=None, output=None, html=str(html_path))
    with patch("oah.design.lens.design_generation_capture", side_effect=fake_lens), \
         patch("oah.design.panel.run_cost_skeptic", side_effect=fake_panel):
        rc = cmd_readiness(args)

    assert rc == 0
    out = html_path.read_text()
    assert "<!DOCTYPE html>" in out
    assert "remediate_before_release" in out  # a designed-but-uninstrumented gap still blocks
    assert "gen_ai.usage.input_tokens" in out  # observability_plan.key_signals, from the base report
    assert "cost_skeptic" in out  # real panel_verdicts detail


def test_no_html_flag_writes_nothing_extra(tmp_path):
    """Byte-identical default: a Namespace without `html` at all (the
    shape every caller had before this flag existed) must not raise, and
    must not write anything beyond the normal report."""
    target = tmp_path / "target_repo"
    target.mkdir()
    (target / "app.py").write_text("x = 1\n")
    _init_git_repo(target)

    args = argparse.Namespace(target=str(target), context=None, output=None)
    assert cmd_readiness(args) == 0
    assert not (tmp_path / "readiness_report.html").exists()
