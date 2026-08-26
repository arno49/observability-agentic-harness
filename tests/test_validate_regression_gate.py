"""oah/validate/regression_gate.py -- sandbox_runner injected with a
fake, no Docker needed. The real-Docker end-to-end path through
cmd_validate lives in tests/test_cli_validate_dynamic.py."""
from oah.validate import regression_gate as regression_gate_module
from oah.validate.regression_gate import check_regression_gate


def _fake_sandbox(exit_code, stdout="", stderr=""):
    def runner(target_repo, script, **kwargs):
        return {"exit_code": exit_code, "stdout": stdout, "stderr": stderr, "timed_out": False}
    return runner


def test_not_attempted_when_dynamic_is_false_and_never_calls_the_runner(tmp_path):
    calls = []

    def runner(target_repo, script, **kwargs):
        calls.append(1)
        return {"exit_code": 0, "stdout": "", "stderr": "", "timed_out": False}

    result = check_regression_gate(tmp_path, dynamic=False, sandbox_runner=runner)
    assert result == {"status": "not_attempted", "reason": None}
    assert calls == []


def test_skipped_when_docker_is_not_available(tmp_path, monkeypatch):
    monkeypatch.setattr(regression_gate_module, "docker_available", lambda: False)
    result = check_regression_gate(tmp_path, dynamic=True, sandbox_runner=_fake_sandbox(0))
    assert result["status"] == "skipped"
    assert "docker" in result["reason"].lower()


def test_skipped_when_no_tests_found(tmp_path, monkeypatch):
    monkeypatch.setattr(regression_gate_module, "docker_available", lambda: True)
    result = check_regression_gate(tmp_path, dynamic=True, sandbox_runner=_fake_sandbox(0))
    assert result["status"] == "skipped"
    assert "no pytest suite" in result["reason"]


def test_skipped_when_install_failed(tmp_path, monkeypatch):
    monkeypatch.setattr(regression_gate_module, "docker_available", lambda: True)
    (tmp_path / "tests").mkdir()
    result = check_regression_gate(
        tmp_path, dynamic=True,
        sandbox_runner=_fake_sandbox(1, stderr="pip install failed, no summary line ever appears"),
    )
    assert result["status"] == "skipped"
    assert "install" in result["reason"].lower()


def test_passed_never_affects_verdict_material(tmp_path, monkeypatch):
    monkeypatch.setattr(regression_gate_module, "docker_available", lambda: True)
    (tmp_path / "tests").mkdir()
    result = check_regression_gate(
        tmp_path, dynamic=True,
        sandbox_runner=_fake_sandbox(0, stdout="===== 3 passed in 0.10s ====="),
    )
    assert result == {"status": "passed", "reason": None}


def test_failed_includes_parsed_pass_fail_counts_in_the_reason(tmp_path, monkeypatch):
    monkeypatch.setattr(regression_gate_module, "docker_available", lambda: True)
    (tmp_path / "tests").mkdir()
    result = check_regression_gate(
        tmp_path, dynamic=True,
        sandbox_runner=_fake_sandbox(1, stdout="===== 1 failed, 2 passed in 0.12s ====="),
    )
    assert result["status"] == "failed"
    assert "1 failed" in result["reason"]
    assert "2 passed" in result["reason"]


def test_failed_still_reports_something_reasonable_when_summary_is_unparseable(tmp_path, monkeypatch):
    """Belt-and-suspenders: run_pytest_suite should never return status
    'failed' without a parseable summary (that's what 'install_failed'
    is for), but the gate must not crash or fabricate counts if it ever
    did -- covers the module's own defensive branch."""
    monkeypatch.setattr(regression_gate_module, "docker_available", lambda: True)
    monkeypatch.setattr(
        regression_gate_module, "run_pytest_suite",
        lambda target_repo, sandbox_runner, **kwargs: {
            "status": "failed", "exit_code": 1, "stdout": "", "stderr": "", "summary": None,
        },
    )
    result = check_regression_gate(tmp_path, dynamic=True, sandbox_runner=_fake_sandbox(1))
    assert result["status"] == "failed"
    assert result["reason"] == "target's own test suite failed after instrumentation"
