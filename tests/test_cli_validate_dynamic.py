"""Real-Docker end-to-end coverage for `oah validate --dynamic`, wiring
E6 R2's sandbox mechanism all the way through cmd_validate -- not just
oah.validate.regression_gate's own mocked unit tests. Skips cleanly
wherever no Docker daemon is reachable, matching
tests/test_sandbox_docker.py's own pattern; runs for real here and in
CI (ubuntu-latest ships Docker preinstalled)."""
import argparse
import json
import subprocess

import pytest

from oah.cli import cmd_validate
from oah.validate.sandbox import docker_available

pytestmark = pytest.mark.skipif(
    not docker_available(),
    reason="docker is not available (not on PATH, or the daemon is unreachable)",
)


def _init_git_repo(path):
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "-c", "user.email=t@t.com", "-c", "user.name=t",
                     "commit", "--allow-empty", "-q", "-m", "init"], cwd=path, check=True)


def _write_dtos_file(path, dtos):
    path.write_text(json.dumps({"schema_version": "0.1.0", "dtos": dtos}, indent=2))


def _write_instrument_report(path):
    report = {"schema_version": "0.1.0", "repo_git_sha": "x", "mode": "fix",
              "results": [], "summary": {"total": 0, "applied": 0, "refused": 0, "unsupported": 0, "failed": 0}}
    path.write_text(json.dumps(report, indent=2))


def test_dynamic_with_a_real_passing_suite_keeps_needs_review(tmp_path):
    target = tmp_path / "target_repo"
    (target / "tests").mkdir(parents=True)
    (target / "tests" / "test_it.py").write_text("def test_ok():\n    assert 1 + 1 == 2\n")
    _init_git_repo(target)

    dtos_path = tmp_path / "implementation_dto.json"
    _write_dtos_file(dtos_path, [])
    report_path = tmp_path / "instrument_report.json"
    _write_instrument_report(report_path)

    args = argparse.Namespace(target=str(target), dtos=str(dtos_path), instrument_report=str(report_path),
                               output=str(tmp_path / "validation.json"), dynamic=True)
    rc = cmd_validate(args)
    assert rc == 0

    result = json.loads((tmp_path / "validation.json").read_text())
    assert result["ladder_rung"] == "R4"
    assert result["verdict"] == "needs_review"
    assert result["regression_gate"]["status"] == "passed"


def test_dynamic_with_a_real_failing_suite_forces_validation_failed(tmp_path):
    target = tmp_path / "target_repo"
    (target / "tests").mkdir(parents=True)
    (target / "tests" / "test_it.py").write_text("def test_fails():\n    assert 1 == 2\n")
    _init_git_repo(target)

    dtos_path = tmp_path / "implementation_dto.json"
    _write_dtos_file(dtos_path, [])
    report_path = tmp_path / "instrument_report.json"
    _write_instrument_report(report_path)

    args = argparse.Namespace(target=str(target), dtos=str(dtos_path), instrument_report=str(report_path),
                               output=str(tmp_path / "validation.json"), dynamic=True)
    rc = cmd_validate(args)
    assert rc == 0  # a real regression failure is a reported finding, not a crashed command

    result = json.loads((tmp_path / "validation.json").read_text())
    assert result["ladder_rung"] == "R4"  # unchanged -- this phase never claims R2
    assert result["verdict"] == "validation_failed"
    assert result["regression_gate"]["status"] == "failed"
    assert "1 failed" in result["regression_gate"]["reason"]
