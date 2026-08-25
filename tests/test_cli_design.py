"""In-process test for cmd_design's full flow -- real S1 scan, mocked lens
call, real S5 gates -- same reasoning as test_cli_disambiguate.py: this is
the wiring that unit tests of the individual pieces don't exercise."""
import argparse
import json
import subprocess
from unittest.mock import patch

from oah.cli import cmd_design


def _init_git_repo(path):
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "-c", "user.email=t@t.com", "-c", "user.name=t",
                     "commit", "--allow-empty", "-q", "-m", "init"], cwd=path, check=True)


def test_design_end_to_end_with_mocked_lens_call(tmp_path):
    target = tmp_path / "target_repo"
    target.mkdir()
    (target / "app.py").write_text(
        "import anthropic\nclient = anthropic.Anthropic()\n"
        "response = client.messages.create(model='x')\n"
    )
    _init_git_repo(target)

    def fake_design_generation_capture(points, repo_git_sha, context=None, model=None, _completion_fn=None):
        assert len(points) == 1
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

    args = argparse.Namespace(target=str(target), output=str(tmp_path / "design.json"), context=None)
    with patch("oah.design.lens.design_generation_capture", side_effect=fake_design_generation_capture):
        rc = cmd_design(args)

    assert rc == 0
    result = json.loads((tmp_path / "design.json").read_text())
    assert result["gates_passed"] is True
    assert result["design_fragment"]["lens"] == "generation-capture"
    assert all(f["passed"] for f in result["gate_findings"] if f["severity"] == "error")


def test_design_reports_gate_failures_with_nonzero_exit(tmp_path):
    target = tmp_path / "target_repo"
    target.mkdir()
    (target / "app.py").write_text(
        "import anthropic\nclient = anthropic.Anthropic()\n"
        "response = client.messages.create(model='x')\n"
    )
    _init_git_repo(target)

    def fake_incomplete_design(points, repo_git_sha, context=None, model=None, _completion_fn=None):
        # Deliberately incomplete: failure_mode wrong, no gate should be able to pass.
        return {
            "schema_version": "0.1.0", "lens": "generation-capture", "repo_git_sha": repo_git_sha,
            "failure_mode": "fail_closed",
            "signals": [{
                "name": "x", "surface_point_ids": [points[0]["id"]],
                "maps_to": {"kind": "otel_genai", "attribute": "gen_ai.usage.input_tokens"},
                "sensitivity_tier": "internal", "pii_masked": False,
                "supports_decision": "cost attribution", "acting_role": "cost owner",
            }],
        }

    args = argparse.Namespace(target=str(target), output=str(tmp_path / "design.json"), context=None)
    with patch("oah.design.lens.design_generation_capture", side_effect=fake_incomplete_design):
        rc = cmd_design(args)

    assert rc == 1
    result = json.loads((tmp_path / "design.json").read_text())
    assert result["gates_passed"] is False


def _valid_fragment(repo_git_sha, point_id):
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


def test_design_s6_panel_fail_makes_overall_command_fail_even_if_s5_passed(tmp_path):
    target = tmp_path / "target_repo"
    target.mkdir()
    (target / "app.py").write_text(
        "import anthropic\nclient = anthropic.Anthropic()\n"
        "response = client.messages.create(model='x')\n"
    )
    _init_git_repo(target)

    def fake_lens(points, repo_git_sha, context=None, model=None, _completion_fn=None):
        return _valid_fragment(repo_git_sha, points[0]["id"])

    def fake_panel(design_fragments, repo_git_sha, context=None, model=None, _completion_fn=None):
        return {
            "schema_version": "0.1.0", "persona": "cost_skeptic", "repo_git_sha": repo_git_sha,
            "overall": "fail",
            "findings": [{
                "category": "retention", "severity": "error", "gate": "cs-test",
                "summary": "unbounded capture with no retention note",
                "evidence": ["gen_ai.usage.input_tokens"],
            }],
        }

    args = argparse.Namespace(target=str(target), output=str(tmp_path / "design.json"), context=None)
    with patch("oah.design.lens.design_generation_capture", side_effect=fake_lens), \
         patch("oah.design.panel.run_cost_skeptic", side_effect=fake_panel):
        rc = cmd_design(args)

    assert rc == 1  # S5 passed but S6 failed -> overall command still fails
    result = json.loads((tmp_path / "design.json").read_text())
    assert result["gates_passed"] is True
    assert result["panel_verdicts"][0]["overall"] == "fail"


def test_design_s6_panel_pass_with_findings_does_not_fail_command(tmp_path):
    target = tmp_path / "target_repo"
    target.mkdir()
    (target / "app.py").write_text(
        "import anthropic\nclient = anthropic.Anthropic()\n"
        "response = client.messages.create(model='x')\n"
    )
    _init_git_repo(target)

    def fake_lens(points, repo_git_sha, context=None, model=None, _completion_fn=None):
        return _valid_fragment(repo_git_sha, points[0]["id"])

    def fake_panel(design_fragments, repo_git_sha, context=None, model=None, _completion_fn=None):
        return {
            "schema_version": "0.1.0", "persona": "cost_skeptic", "repo_git_sha": repo_git_sha,
            "overall": "pass_with_findings",
            "findings": [{
                "category": "sampling", "severity": "warning", "gate": "cs-no-sampling-mentioned",
                "summary": "no sampling policy addressed anywhere",
                "evidence": ["gen_ai.usage.input_tokens"],
            }],
        }

    args = argparse.Namespace(target=str(target), output=str(tmp_path / "design.json"), context=None)
    with patch("oah.design.lens.design_generation_capture", side_effect=fake_lens), \
         patch("oah.design.panel.run_cost_skeptic", side_effect=fake_panel):
        rc = cmd_design(args)

    assert rc == 0
    result = json.loads((tmp_path / "design.json").read_text())
    assert result["panel_verdicts"][0]["overall"] == "pass_with_findings"


def test_design_no_llm_generation_points_skips_gracefully(tmp_path, capsys):
    target = tmp_path / "target_repo"
    target.mkdir()
    (target / "app.py").write_text("x = 1\n")  # no anthropic call sites at all
    _init_git_repo(target)

    args = argparse.Namespace(target=str(target), output=None, context=None)
    rc = cmd_design(args)
    assert rc == 0
