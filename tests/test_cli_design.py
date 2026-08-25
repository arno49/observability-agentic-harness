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
    assert result["design_fragments"][0]["lens"] == "generation-capture"
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


def test_design_checks_each_fragment_against_its_own_point_kind(tmp_path):
    """A repo with llm_generation (anthropic), retrieval (pinecone), and
    feedback_ingest (langsmith) points -- LENS_TO_POINT_KIND/
    _point_ids_for_fragment must check each fragment's S5 gates against
    the point kind that lens actually targets, not a single hardcoded
    kind. Before that fix, the retrieval fragment would have been checked
    against llm_generation point IDs -- its own signals cover a different
    point entirely, so check_every_surface_point_has_decision would
    report the llm_generation point 'missing' from the retrieval fragment
    and s5_passed would be False even though both fragments are
    individually complete and correct. Three kinds, not two, proves the
    generalization actually scales rather than happening to work for a
    hardcoded pair. Asserting gates_passed is True here is the
    regression check."""
    target = tmp_path / "target_repo"
    target.mkdir()
    (target / "app.py").write_text(
        "import anthropic\nimport pinecone\nfrom langsmith import Client\n"
        "client = anthropic.Anthropic()\n"
        "pinecone.init(api_key='x', environment='y')\n"
        "index = pinecone.Index('my-index')\n"
        "ls_client = Client()\n"
        "results = index.query(vector=[0.1, 0.2], top_k=5)\n"
        "message = client.messages.create(model='x')\n"
        "ls_client.create_feedback(run_id='abc123', key='user_score', score=1)\n"
    )
    _init_git_repo(target)

    def fake_generation_capture(points, repo_git_sha, context=None, model=None, _completion_fn=None):
        gen_points = [p for p in points if p["kind"] == "llm_generation"]
        assert len(gen_points) == 1
        return _valid_fragment(repo_git_sha, gen_points[0]["id"])

    def fake_retrieval(points, repo_git_sha, context=None, model=None, _completion_fn=None):
        retrieval_points = [p for p in points if p["kind"] == "retrieval"]
        assert len(retrieval_points) == 1
        point_id = retrieval_points[0]["id"]
        return {
            "schema_version": "0.1.0", "lens": "retrieval", "repo_git_sha": repo_git_sha,
            "failure_mode": "fail_open",
            "signals": [{
                "name": "oah.retrieval.sources", "surface_point_ids": [point_id],
                "maps_to": {"kind": "oah_extension", "attribute": "oah.retrieval.sources"},
                "sensitivity_tier": "internal", "pii_masked": False,
                "supports_decision": "judging retrieval relevance quality",
                "acting_role": "retrieval owner", "latency_overhead_budget_ms": 2,
            }],
        }

    def fake_feedback(points, repo_git_sha, context=None, model=None, _completion_fn=None):
        feedback_points = [p for p in points if p["kind"] == "feedback_ingest"]
        assert len(feedback_points) == 1
        point_id = feedback_points[0]["id"]
        return {
            "schema_version": "0.1.0", "lens": "feedback", "repo_git_sha": repo_git_sha,
            "failure_mode": "fail_open",
            "signals": [{
                "name": "oah.feedback.trace_ref", "surface_point_ids": [point_id],
                "maps_to": {"kind": "oah_extension", "attribute": "oah.feedback.trace_ref"},
                "sensitivity_tier": "internal", "pii_masked": False,
                "supports_decision": "linking a verdict back to its generation",
                "acting_role": "eval owner", "latency_overhead_budget_ms": 1,
            }],
        }

    args = argparse.Namespace(target=str(target), output=str(tmp_path / "design.json"), context=None)
    with patch("oah.design.lens.design_generation_capture", side_effect=fake_generation_capture), \
         patch("oah.design.lens.design_retrieval", side_effect=fake_retrieval), \
         patch("oah.design.lens.design_feedback", side_effect=fake_feedback):
        rc = cmd_design(args)

    result = json.loads((tmp_path / "design.json").read_text())
    assert result["gates_passed"] is True
    lenses = {f["lens"] for f in result["design_fragments"]}
    assert lenses == {"generation-capture", "retrieval", "feedback"}
    assert rc == 0


def test_design_no_llm_generation_points_skips_gracefully(tmp_path, capsys):
    target = tmp_path / "target_repo"
    target.mkdir()
    (target / "app.py").write_text("x = 1\n")  # no anthropic call sites at all
    _init_git_repo(target)

    args = argparse.Namespace(target=str(target), output=None, context=None)
    rc = cmd_design(args)
    assert rc == 0
