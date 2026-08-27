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
import json
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


# --- --surface-map (docs/decisions/034) -------------------------------------

def test_surface_map_flag_loads_and_forwards_to_run_interview(tmp_path):
    target = tmp_path / "target_repo"
    target.mkdir()
    _init_git_repo(target)

    sm_path = tmp_path / "surface_map.json"
    sm_path.write_text(json.dumps({"points": [{"id": "sp-0001", "workflow_hint": "portfolio"}]}))

    args = argparse.Namespace(target=str(target), output=None, surface_map=str(sm_path))
    with patch("oah.interview.run_interview", return_value={"schema_version": "0.1.0", "workflows": []}) as mock_run:
        rc = cmd_interview(args)

    assert rc == 0
    assert mock_run.call_args.kwargs["surface_map"]["points"][0]["workflow_hint"] == "portfolio"


def test_missing_surface_map_file_is_a_clean_error_not_a_crash(tmp_path, capsys):
    target = tmp_path / "target_repo"
    target.mkdir()
    _init_git_repo(target)

    args = argparse.Namespace(target=str(target), output=None, surface_map=str(tmp_path / "nope.json"))
    rc = cmd_interview(args)

    assert rc == 1
    assert "could not read --surface-map" in capsys.readouterr().err


def test_no_surface_map_flag_is_byte_identical_default():
    """A Namespace without surface_map at all (the shape every caller had
    before docs/decisions/034) must not raise -- getattr default, not a
    required attribute."""
    args = argparse.Namespace(target="/nonexistent-repo-xyz", output=None)
    rc = cmd_interview(args)
    assert rc == 1  # not a git repo -- the pre-existing error path, reached cleanly
