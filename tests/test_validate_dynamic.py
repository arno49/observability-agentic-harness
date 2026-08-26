"""oah/validate/dynamic.py -- sandbox_runner injected with a fake, no
Docker needed. Real-Docker end-to-end coverage lives in
tests/test_cli_validate_dynamic.py."""
from oah.validate import dynamic as dynamic_module
from oah.validate.dynamic import run_dynamic_validation

DTOS = [
    {"id": "dto-0001", "expected_events": [{"event_type": "generation", "required_attributes": ["attr.a"]}]},
    {"id": "dto-0002", "expected_events": [{"event_type": "span", "required_attributes": ["attr.b"]}]},
]


def _fake_sandbox(exit_code, stdout="", stderr=""):
    def runner(target_repo, script, **kwargs):
        return {"exit_code": exit_code, "stdout": stdout, "stderr": stderr, "timed_out": False}
    return runner


def test_not_attempted_marks_every_dto_not_attempted_and_never_calls_the_runner(tmp_path):
    calls = []

    def runner(target_repo, script, **kwargs):
        calls.append(1)
        return {"exit_code": 0, "stdout": "", "stderr": "", "timed_out": False}

    result = run_dynamic_validation(tmp_path, DTOS, dynamic=False, sandbox_runner=runner)
    assert result["regression_gate"] == {"status": "not_attempted", "reason": None}
    assert result["event_assertions"] == [
        {"dto_id": "dto-0001", "status": "not_attempted", "reason": None},
        {"dto_id": "dto-0002", "status": "not_attempted", "reason": None},
    ]
    assert calls == []


def test_docker_unavailable_skips_gate_and_every_dto_with_the_same_reason(tmp_path, monkeypatch):
    monkeypatch.setattr(dynamic_module, "docker_available", lambda: False)
    result = run_dynamic_validation(tmp_path, DTOS, dynamic=True, sandbox_runner=_fake_sandbox(0))
    assert result["regression_gate"]["status"] == "skipped"
    assert all(ea["status"] == "skipped" for ea in result["event_assertions"])
    assert all(ea["reason"] == result["regression_gate"]["reason"] for ea in result["event_assertions"])


def test_no_tests_found_skips_every_dto_not_not_observed(tmp_path, monkeypatch):
    monkeypatch.setattr(dynamic_module, "docker_available", lambda: True)
    result = run_dynamic_validation(tmp_path, DTOS, dynamic=True, sandbox_runner=_fake_sandbox(0))
    assert result["regression_gate"]["status"] == "skipped"
    assert result["regression_gate"]["reason"] == "no pytest suite found in the target repo"
    assert all(ea["status"] == "skipped" for ea in result["event_assertions"])


def test_passed_run_reports_per_dto_observed_and_not_observed(tmp_path, monkeypatch):
    monkeypatch.setattr(dynamic_module, "docker_available", lambda: True)
    (tmp_path / "tests").mkdir()
    stdout = (
        "===== 2 passed in 0.10s =====\n"
        '{"name": "s1", "context": {}, "attributes": {"attr.a": 1}}\n'
    )
    result = run_dynamic_validation(
        tmp_path, DTOS, dynamic=True, sandbox_runner=_fake_sandbox(0, stdout=stdout),
    )
    assert result["regression_gate"] == {"status": "passed", "reason": None}
    by_id = {ea["dto_id"]: ea for ea in result["event_assertions"]}
    assert by_id["dto-0001"]["status"] == "observed"
    assert by_id["dto-0002"]["status"] == "not_observed"


def test_failed_run_still_reports_event_assertions_not_just_the_gate(tmp_path, monkeypatch):
    """A real test failure forces regression_gate to 'failed', but the
    event-assertion pass still runs against whatever spans WERE
    captured before the failure -- these are independent signals, not
    short-circuited by each other."""
    monkeypatch.setattr(dynamic_module, "docker_available", lambda: True)
    (tmp_path / "tests").mkdir()
    stdout = (
        "===== 1 failed, 1 passed in 0.10s =====\n"
        '{"name": "s1", "context": {}, "attributes": {"attr.a": 1}}\n'
    )
    result = run_dynamic_validation(
        tmp_path, DTOS, dynamic=True, sandbox_runner=_fake_sandbox(1, stdout=stdout),
    )
    assert result["regression_gate"]["status"] == "failed"
    by_id = {ea["dto_id"]: ea for ea in result["event_assertions"]}
    assert by_id["dto-0001"]["status"] == "observed"
    assert by_id["dto-0002"]["status"] == "not_observed"


def test_makes_exactly_one_sandbox_call_for_both_checks(tmp_path, monkeypatch):
    monkeypatch.setattr(dynamic_module, "docker_available", lambda: True)
    (tmp_path / "tests").mkdir()
    calls = []

    def runner(target_repo, script, **kwargs):
        calls.append(script)
        return {"exit_code": 0, "stdout": "===== 1 passed in 0.01s =====", "stderr": "", "timed_out": False}

    run_dynamic_validation(tmp_path, DTOS, dynamic=True, sandbox_runner=runner)
    assert len(calls) == 1
