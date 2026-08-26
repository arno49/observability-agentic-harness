"""In-process test for cmd_event_schema's full flow -- real S1 scan, mocked
lens call, real deterministic merge."""
import argparse
import json
import subprocess
from unittest.mock import patch

from oah.cli import cmd_event_schema


def _init_git_repo(path):
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "-c", "user.email=t@t.com", "-c", "user.name=t",
                     "commit", "--allow-empty", "-q", "-m", "init"], cwd=path, check=True)


def test_event_schema_end_to_end_with_mocked_lens_call(tmp_path):
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

    args = argparse.Namespace(target=str(target), context=None, output=str(tmp_path / "event_schema.json"))
    with patch("oah.design.lens.design_generation_capture", side_effect=fake_lens):
        rc = cmd_event_schema(args)

    assert rc == 0
    result = json.loads((tmp_path / "event_schema.json").read_text())
    assert result["summary"]["attribute_count"] == 1
    assert result["attributes"][0]["name"] == "gen_ai.usage.input_tokens"
    assert result["attributes"][0]["source_lenses"] == ["generation-capture"]


def test_event_schema_passes_context_through_to_lenses(tmp_path):
    """Found by adversarial review: cmd_event_schema had no --context
    support at all -- args.context was never read and no design_fn call
    passed context=, unlike oah design/dtos/readiness, which silently
    diverged its output from a context-aware run of any of those three."""
    target = tmp_path / "target_repo"
    target.mkdir()
    (target / "app.py").write_text(
        "import anthropic\nclient = anthropic.Anthropic()\n"
        "response = client.messages.create(model='x')\n"
    )
    _init_git_repo(target)

    context_path = tmp_path / "context.yaml"
    context_path.write_text(
        "schema_version: '0.1.0'\n"
        "repo_git_sha: deadbeef\n"
        "interviewed_at: '2026-01-01T00:00:00Z'\n"
        "workflows:\n"
        "  - name: billing\n"
        "    criticality: critical\n"
    )

    captured = {}

    def fake_lens(points, repo_git_sha, context=None, model=None, _completion_fn=None):
        captured["context"] = context
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

    args = argparse.Namespace(target=str(target), context=str(context_path), output=None)
    with patch("oah.design.lens.design_generation_capture", side_effect=fake_lens):
        rc = cmd_event_schema(args)

    assert rc == 0
    assert captured["context"]["workflows"][0]["name"] == "billing"


def test_event_schema_no_points_skips_gracefully(tmp_path):
    target = tmp_path / "target_repo"
    target.mkdir()
    (target / "app.py").write_text("x = 1\n")
    _init_git_repo(target)

    args = argparse.Namespace(target=str(target), context=None, output=None)
    assert cmd_event_schema(args) == 0
