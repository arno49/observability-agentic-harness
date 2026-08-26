"""Regression tests for oah.instrument.executor -- mocked, same reasoning
as test_disambiguate.py/test_design_lens.py: no live Claude Agent SDK
session is available in this environment, so `_agent_runner` stands in
for the real query()-based session throughout."""
import subprocess
import sys

import pytest

from oah.instrument.executor import (
    MissingAgentSDKError, apply_dto_fix, apply_dto_report_only, get_agent_runner,
)

WRAP_CALL_DTO = {
    "id": "dto-0001",
    "gap_id": "gap-0001",
    "surface_point_ids": ["sp-0001"],
    "change": {
        "type": "wrap_call",
        "file": "app.py",
        "anchor": "response = client.messages.create(",
        "preconditions": ["a direct client.messages.create(...) call assigned to `response`"],
        "description": "wrap the call with a span",
    },
    "expected_events": [{"event_type": "generation", "required_attributes": ["gen_ai.usage.input_tokens"]}],
    "rollout_step": 1,
}


def _write_target(tmp_path, content="response = client.messages.create(model='x')\n"):
    target = tmp_path / "target_repo"
    target.mkdir()
    (target / "app.py").write_text(content)
    return target


def _write_git_target(tmp_path, content="response = client.messages.create(model='x')\n"):
    target = _write_target(tmp_path, content)
    subprocess.run(["git", "init", "-q"], cwd=target, check=True)
    subprocess.run(["git", "add", "-A"], cwd=target, check=True)
    subprocess.run(["git", "-c", "user.email=t@t.com", "-c", "user.name=t",
                     "commit", "-q", "-m", "init"], cwd=target, check=True)
    return target


def _git_log(target):
    result = subprocess.run(["git", "-C", str(target), "log", "--oneline"],
                             capture_output=True, text=True, check=True)
    return result.stdout.strip().splitlines()


def _git_status_clean(target):
    result = subprocess.run(["git", "-C", str(target), "status", "--porcelain"],
                             capture_output=True, text=True, check=True)
    return result.stdout.strip() == ""


def test_unsupported_change_type_never_calls_the_agent(tmp_path):
    target = _write_target(tmp_path)
    dto = {**WRAP_CALL_DTO, "change": {**WRAP_CALL_DTO["change"], "type": "add_compose_service"}}
    calls = []
    result = apply_dto_report_only(dto, target, _agent_runner=lambda *a: calls.append(a))
    assert result["status"] == "unsupported"
    assert "add_compose_service" in result["reason"]
    assert calls == []


def test_missing_target_file_refused_without_calling_the_agent(tmp_path):
    target = tmp_path / "target_repo"
    target.mkdir()
    calls = []
    result = apply_dto_report_only(WRAP_CALL_DTO, target, _agent_runner=lambda *a: calls.append(a))
    assert result["status"] == "refused"
    assert "app.py" in result["reason"]
    assert calls == []


def test_agent_refusal_is_a_real_dto003_style_result(tmp_path):
    target = _write_target(tmp_path)

    def fake_runner(dto, target_repo, model):
        return {"dto_id": dto["id"], "status": "refused", "patched_content": None,
                "reason": "anchor text not found at or near the DTO's stated location"}

    result = apply_dto_report_only(WRAP_CALL_DTO, target, _agent_runner=fake_runner)
    assert result["status"] == "refused"
    assert "anchor" in result["reason"]
    assert result["diff"] is None


def test_applied_diff_is_computed_by_oah_not_the_agent(tmp_path):
    original = "response = client.messages.create(model='x')\n"
    target = _write_target(tmp_path, content=original)
    patched = "oah_telemetry.emit('start')\nresponse = client.messages.create(model='x')\n"

    def fake_runner(dto, target_repo, model):
        return {"dto_id": dto["id"], "status": "applied", "patched_content": patched, "reason": None}

    result = apply_dto_report_only(WRAP_CALL_DTO, target, _agent_runner=fake_runner)
    assert result["status"] == "applied"
    assert "oah_telemetry.emit" in result["diff"]
    assert "+oah_telemetry.emit" in result["diff"]  # a real unified diff, not the raw content
    assert result["syntax_valid"] is True


def test_applied_diff_flags_invalid_python_as_syntax_invalid(tmp_path):
    target = _write_target(tmp_path)
    broken = "response = client.messages.create(model='x'\n"  # unbalanced paren

    def fake_runner(dto, target_repo, model):
        return {"dto_id": dto["id"], "status": "applied", "patched_content": broken, "reason": None}

    result = apply_dto_report_only(WRAP_CALL_DTO, target, _agent_runner=fake_runner)
    assert result["status"] == "applied"
    assert result["syntax_valid"] is False


def test_malformed_agent_output_is_a_failed_result_not_a_crash(tmp_path):
    target = _write_target(tmp_path)

    def fake_runner(dto, target_repo, model):
        return {"dto_id": dto["id"], "status": "applied"}  # missing required patched_content

    result = apply_dto_report_only(WRAP_CALL_DTO, target, _agent_runner=fake_runner)
    assert result["status"] == "failed"
    assert "schema validation" in result["reason"]


def test_agent_runner_exception_is_a_failed_result_not_a_crash(tmp_path):
    target = _write_target(tmp_path)

    def fake_runner(dto, target_repo, model):
        raise RuntimeError("transport closed")

    result = apply_dto_report_only(WRAP_CALL_DTO, target, _agent_runner=fake_runner)
    assert result["status"] == "failed"
    assert "transport closed" in result["reason"]


def test_get_agent_runner_raises_actionable_error_when_sdk_not_installed(monkeypatch):
    monkeypatch.setitem(sys.modules, "claude_agent_sdk", None)
    with pytest.raises(MissingAgentSDKError, match=r"pip install 'oah\[agent\]'"):
        get_agent_runner()


def test_missing_agent_sdk_surfaces_as_failed_result_not_a_crash(tmp_path, monkeypatch):
    target = _write_target(tmp_path)
    monkeypatch.setitem(sys.modules, "claude_agent_sdk", None)
    result = apply_dto_report_only(WRAP_CALL_DTO, target)  # no _agent_runner override
    assert result["status"] == "failed"
    assert "pip install 'oah[agent]'" in result["reason"]


# --- apply_dto_fix -----------------------------------------------------

PATCHED = "oah_telemetry.emit('start')\nresponse = client.messages.create(model='x')\n"


def test_fix_writes_the_file_and_creates_one_commit(tmp_path):
    target = _write_git_target(tmp_path)
    log_before = _git_log(target)

    def fake_runner(dto, target_repo, model):
        return {"dto_id": dto["id"], "status": "applied", "patched_content": PATCHED, "reason": None}

    result = apply_dto_fix(WRAP_CALL_DTO, target, _agent_runner=fake_runner)
    assert result["status"] == "applied"
    assert result["commit_sha"]
    assert (target / "app.py").read_text() == PATCHED
    assert _git_status_clean(target)
    log_after = _git_log(target)
    assert len(log_after) == len(log_before) + 1
    assert "dto-0001" in log_after[0]


def test_fix_refusal_never_touches_the_file_or_git(tmp_path):
    target = _write_git_target(tmp_path)
    original = (target / "app.py").read_text()
    log_before = _git_log(target)

    def fake_runner(dto, target_repo, model):
        return {"dto_id": dto["id"], "status": "refused", "patched_content": None, "reason": "anchor not found"}

    result = apply_dto_fix(WRAP_CALL_DTO, target, _agent_runner=fake_runner)
    assert result["status"] == "refused"
    assert result["commit_sha"] is None
    assert (target / "app.py").read_text() == original
    assert _git_log(target) == log_before
    assert _git_status_clean(target)


def test_fix_rolls_back_syntax_invalid_content_without_committing(tmp_path):
    target = _write_git_target(tmp_path)
    original = (target / "app.py").read_text()
    log_before = _git_log(target)
    broken = "response = client.messages.create(model='x'\n"  # unbalanced paren

    def fake_runner(dto, target_repo, model):
        return {"dto_id": dto["id"], "status": "applied", "patched_content": broken, "reason": None}

    result = apply_dto_fix(WRAP_CALL_DTO, target, _agent_runner=fake_runner)
    assert result["status"] == "failed"
    assert "fails to parse" in result["reason"]
    assert result["commit_sha"] is None
    # The critical assertion: the file on disk is restored, not left broken.
    assert (target / "app.py").read_text() == original
    assert _git_log(target) == log_before
    assert _git_status_clean(target)


def test_fix_rolls_back_on_git_commit_failure(tmp_path):
    target = _write_git_target(tmp_path)
    original = (target / "app.py").read_text()
    log_before = _git_log(target)

    # A commit.gpgsign misconfiguration, a rejecting pre-commit hook, or any
    # other git-level failure -- simulate by pointing GIT_AUTHOR/COMMITTER
    # config at something git itself will refuse. Simplest reliable
    # trigger: an empty commit message is rejected by git, but our code
    # always supplies one -- so simulate directly by making the repo's
    # .git/hooks/pre-commit reject everything.
    hooks_dir = target / ".git" / "hooks"
    hooks_dir.mkdir(exist_ok=True)
    hook = hooks_dir / "pre-commit"
    hook.write_text("#!/bin/sh\nexit 1\n")
    hook.chmod(0o755)

    def fake_runner(dto, target_repo, model):
        return {"dto_id": dto["id"], "status": "applied", "patched_content": PATCHED, "reason": None}

    result = apply_dto_fix(WRAP_CALL_DTO, target, _agent_runner=fake_runner)
    assert result["status"] == "failed"
    assert "git commit failed, rolled back" in result["reason"]
    assert result["commit_sha"] is None
    assert (target / "app.py").read_text() == original
    assert _git_log(target) == log_before
    assert _git_status_clean(target)


def test_fix_unsupported_type_never_touches_git(tmp_path):
    target = _write_git_target(tmp_path)
    log_before = _git_log(target)
    dto = {**WRAP_CALL_DTO, "change": {**WRAP_CALL_DTO["change"], "type": "add_compose_service"}}

    calls = []
    result = apply_dto_fix(dto, target, _agent_runner=lambda *a: calls.append(a))
    assert result["status"] == "unsupported"
    assert calls == []
    assert _git_log(target) == log_before
    assert _git_status_clean(target)
