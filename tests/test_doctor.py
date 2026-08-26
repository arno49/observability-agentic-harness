"""Regression tests for oah.doctor's litellm check -- litellm is the
optional `llm` extra (pip install oah[llm]), so a real install missing it
is a valid, working install for the deterministic-only commands, not a
failed one. Before this fix, _check_litellm reported ok=False on a missing
import, which would make `oah doctor` claim "One or more checks failed"
for a perfectly healthy deterministic-only install."""
import sys

from oah.doctor import _check_litellm, format_report


def test_litellm_installed_reports_ok():
    check = _check_litellm()
    assert check.ok is True
    assert check.detail == "importable"


def test_litellm_missing_is_still_ok_not_a_failure(monkeypatch):
    monkeypatch.setitem(sys.modules, "litellm", None)
    check = _check_litellm()
    assert check.ok is True
    assert "optional, not installed" in check.detail
    assert "pip install 'oah[llm]'" in check.detail


def test_missing_litellm_does_not_fail_the_overall_report(monkeypatch):
    monkeypatch.setitem(sys.modules, "litellm", None)
    _, all_ok = format_report([_check_litellm()])
    assert all_ok is True
