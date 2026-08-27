"""Regression tests for cmd_estimate's input validation -- found by
adversarial review: every sibling command validates the target is a real
git repo before doing anything; cmd_estimate didn't, so a nonexistent path
silently produced a confident-looking dollar estimate instead of an error.
Also found: --workflows accepted a negative value with no validation,
reporting a nonsensical driver count verbatim in the output."""
import argparse
import subprocess

from oah.cli import cmd_estimate


def _init_git_repo(path):
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "-c", "user.email=t@t.com", "-c", "user.name=t",
                     "commit", "--allow-empty", "-q", "-m", "init"], cwd=path, check=True)


def test_estimate_nonexistent_target_returns_error(tmp_path, capsys):
    args = argparse.Namespace(target=str(tmp_path / "does-not-exist"), workflows=None, json=False)
    rc = cmd_estimate(args)
    assert rc == 1
    assert "is not a git repository" in capsys.readouterr().err


def test_estimate_negative_workflows_returns_error(tmp_path, capsys):
    target = tmp_path / "target_repo"
    target.mkdir()
    _init_git_repo(target)

    args = argparse.Namespace(target=str(target), workflows=-5, json=False)
    rc = cmd_estimate(args)
    assert rc == 1
    assert "--workflows must be >= 0" in capsys.readouterr().err


def test_estimate_language_typescript_dispatches_to_ts_adapter(tmp_path, capsys):
    """docs/decisions/035's own CLI dispatch: --language typescript must
    route the free phase-1 pre-scan through the TS adapter, not silently
    report 0 candidates for a .ts-only target."""
    target = tmp_path / "target_repo"
    target.mkdir()
    (target / "app.ts").write_text(
        'import Anthropic from "@anthropic-ai/sdk";\nconst c = new Anthropic();\n'
        'c.messages.create({model: "x"});\n'
    )
    _init_git_repo(target)

    args = argparse.Namespace(target=str(target), workflows=None, json=True, language="typescript", pack="genai")
    rc = cmd_estimate(args)
    assert rc == 0

    import json
    result = json.loads(capsys.readouterr().out)
    assert result["driver_counts"]["candidate_call_sites"] == 1


def test_estimate_no_language_attr_defaults_to_python(tmp_path):
    """A Namespace without language/pack at all (the shape every caller had
    before docs/decisions/035) must not raise -- getattr defaults, not
    required attributes."""
    target = tmp_path / "target_repo"
    target.mkdir()
    (target / "app.ts").write_text('console.log("x");\n')
    _init_git_repo(target)

    args = argparse.Namespace(target=str(target), workflows=None, json=False)
    rc = cmd_estimate(args)
    assert rc == 0
