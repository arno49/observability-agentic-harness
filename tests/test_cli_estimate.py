"""Regression test for cmd_estimate's target validation -- found by
adversarial review: every sibling command validates the target is a real
git repo before doing anything; cmd_estimate didn't, so a nonexistent path
silently produced a confident-looking dollar estimate instead of an error."""
import argparse

from oah.cli import cmd_estimate


def test_estimate_nonexistent_target_returns_error(tmp_path, capsys):
    args = argparse.Namespace(target=str(tmp_path / "does-not-exist"), workflows=None, json=False)
    rc = cmd_estimate(args)
    assert rc == 1
    assert "is not a git repository" in capsys.readouterr().err
