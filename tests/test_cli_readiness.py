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

    def fake_generate_dtos(event_schema, points, gaps, repo_git_sha, model=None, _completion_fn=None):
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
