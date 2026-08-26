"""Regression test for cmd_interview's cancellation handling -- found by
adversarial review: run_interview had no EOFError/KeyboardInterrupt
handling, and cmd_interview had no try/except around it either, so a real
Ctrl+D crashed with a raw traceback.

Patches oah.interview.run_interview directly (not builtins.input): the
`ask=input` default in run_interview's own signature is bound to the
input function object at interview.py's *module import time*, not
re-resolved per call -- patching builtins.input afterward doesn't affect
an already-bound default argument, a real gotcha caught while writing this
test. run_interview's own EOF/KeyboardInterrupt handling is covered
directly, via its `ask=` injection point, in tests/test_interview.py; this
test's job is verifying cmd_interview's own try/except around it."""
import argparse
import subprocess
from unittest.mock import patch

from oah.cli import cmd_interview
from oah.interview import InterviewAborted


def _init_git_repo(path):
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "-c", "user.email=t@t.com", "-c", "user.name=t",
                     "commit", "--allow-empty", "-q", "-m", "init"], cwd=path, check=True)


def test_interview_cancelled_mid_way_returns_clean_error(tmp_path, capsys):
    target = tmp_path / "target_repo"
    target.mkdir()
    _init_git_repo(target)

    args = argparse.Namespace(target=str(target), output=None)
    with patch("oah.interview.run_interview", side_effect=InterviewAborted("interview cancelled before completion")):
        rc = cmd_interview(args)

    assert rc == 1
    assert "cancelled" in capsys.readouterr().err
