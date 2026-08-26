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
