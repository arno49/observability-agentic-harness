"""In-process test for cmd_instrument's full flow -- real target repo +
DTO file on disk, mocked agent call, real diff computation and
checkpointing -- same reasoning as test_cli_design.py: this is the wiring
that oah.instrument.executor's own unit tests don't exercise."""
import argparse
import json
import subprocess
from unittest.mock import patch

from oah.cli import cmd_instrument


def _init_git_repo(path):
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "-c", "user.email=t@t.com", "-c", "user.name=t",
                     "commit", "--allow-empty", "-q", "-m", "init"], cwd=path, check=True)


def _write_dtos_file(path, dtos):
    path.write_text(json.dumps({"schema_version": "0.1.0", "dtos": dtos}, indent=2))


DTO = {
    "id": "dto-0001", "gap_id": "gap-0001", "surface_point_ids": ["sp-0001"],
    "change": {
        "type": "wrap_call", "file": "app.py",
        "anchor": "response = client.messages.create(",
        "preconditions": ["a direct client.messages.create(...) call"],
        "description": "wrap with a span",
    },
    "expected_events": [{"event_type": "generation", "required_attributes": ["gen_ai.usage.input_tokens"]}],
    "rollout_step": 1,
}


def test_instrument_end_to_end_with_mocked_agent(tmp_path):
    target = tmp_path / "target_repo"
    target.mkdir()
    (target / "app.py").write_text("response = client.messages.create(model='x')\n")
    _init_git_repo(target)

    dtos_path = tmp_path / "implementation_dto.json"
    _write_dtos_file(dtos_path, [DTO])

    def fake_apply(dto, target_repo, model=None):
        return {"dto_id": dto["id"], "status": "applied",
                "diff": "--- a/app.py\n+++ b/app.py\n@@ ...\n+telemetry.emit()\n",
                "reason": None, "syntax_valid": True}

    args = argparse.Namespace(target=str(target), dtos=str(dtos_path),
                               output=str(tmp_path / "report.json"), model=None)
    with patch("oah.instrument.executor.apply_dto_report_only", side_effect=fake_apply):
        rc = cmd_instrument(args)

    assert rc == 0
    report = json.loads((tmp_path / "report.json").read_text())
    assert report["mode"] == "report-only"
    assert report["summary"] == {"total": 1, "applied": 1, "refused": 0, "unsupported": 0, "failed": 0}
    assert report["results"][0]["dto_id"] == "dto-0001"


def test_instrument_never_writes_to_the_target_repo(tmp_path):
    """The whole point of report-only mode -- confirm app.py on disk is
    byte-for-byte unchanged after a run that "applied" a DTO."""
    target = tmp_path / "target_repo"
    target.mkdir()
    original = "response = client.messages.create(model='x')\n"
    (target / "app.py").write_text(original)
    _init_git_repo(target)

    dtos_path = tmp_path / "implementation_dto.json"
    _write_dtos_file(dtos_path, [DTO])

    def fake_apply(dto, target_repo, model=None):
        return {"dto_id": dto["id"], "status": "applied", "diff": "would-be-a-diff",
                "reason": None, "syntax_valid": True}

    args = argparse.Namespace(target=str(target), dtos=str(dtos_path), output=None, model=None)
    with patch("oah.instrument.executor.apply_dto_report_only", side_effect=fake_apply):
        cmd_instrument(args)

    assert (target / "app.py").read_text() == original


def test_failed_status_makes_the_command_exit_nonzero(tmp_path):
    target = tmp_path / "target_repo"
    target.mkdir()
    (target / "app.py").write_text("x = 1\n")
    _init_git_repo(target)

    dtos_path = tmp_path / "implementation_dto.json"
    _write_dtos_file(dtos_path, [DTO])

    def fake_apply(dto, target_repo, model=None):
        return {"dto_id": dto["id"], "status": "failed", "diff": None,
                "reason": "agent session failed: transport closed", "syntax_valid": None}

    args = argparse.Namespace(target=str(target), dtos=str(dtos_path), output=None, model=None)
    with patch("oah.instrument.executor.apply_dto_report_only", side_effect=fake_apply):
        rc = cmd_instrument(args)

    assert rc == 1


def test_refused_status_does_not_fail_the_command(tmp_path):
    """A considered refusal (SP4's dto-003 case) is a correct outcome, not
    a tool failure -- only status=failed should make the command fail."""
    target = tmp_path / "target_repo"
    target.mkdir()
    (target / "app.py").write_text("x = 1\n")
    _init_git_repo(target)

    dtos_path = tmp_path / "implementation_dto.json"
    _write_dtos_file(dtos_path, [DTO])

    def fake_apply(dto, target_repo, model=None):
        return {"dto_id": dto["id"], "status": "refused", "diff": None,
                "reason": "anchor not found", "syntax_valid": None}

    args = argparse.Namespace(target=str(target), dtos=str(dtos_path), output=None, model=None)
    with patch("oah.instrument.executor.apply_dto_report_only", side_effect=fake_apply):
        rc = cmd_instrument(args)

    assert rc == 0


def test_resume_reuses_checkpointed_result_without_recalling_the_agent(tmp_path):
    target = tmp_path / "target_repo"
    target.mkdir()
    (target / "app.py").write_text("response = client.messages.create(model='x')\n")
    _init_git_repo(target)

    dtos_path = tmp_path / "implementation_dto.json"
    _write_dtos_file(dtos_path, [DTO])

    call_count = {"n": 0}

    def fake_apply(dto, target_repo, model=None):
        call_count["n"] += 1
        return {"dto_id": dto["id"], "status": "applied", "diff": "d",
                "reason": None, "syntax_valid": True}

    args = argparse.Namespace(target=str(target), dtos=str(dtos_path), output=None,
                               model=None, run_id="resume-run")
    with patch("oah.instrument.executor.apply_dto_report_only", side_effect=fake_apply):
        cmd_instrument(args)
    assert call_count["n"] == 1

    # Same run_id, second invocation: must reuse the checkpointed result,
    # not call the agent again -- this is what "S10 checkpoints per
    # applied DTO" (architecture.md) is actually for.
    with patch("oah.instrument.executor.apply_dto_report_only", side_effect=fake_apply):
        cmd_instrument(args)
    assert call_count["n"] == 1


def test_no_run_id_given_means_no_cross_run_resume(tmp_path):
    """Without --run-id, each invocation gets its own fresh run_id (same
    posture as `oah map`) -- checkpointing only protects a single run's
    own resume when --run-id is explicitly reused, not automatic
    cross-invocation caching."""
    target = tmp_path / "target_repo"
    target.mkdir()
    (target / "app.py").write_text("response = client.messages.create(model='x')\n")
    _init_git_repo(target)

    dtos_path = tmp_path / "implementation_dto.json"
    _write_dtos_file(dtos_path, [DTO])

    call_count = {"n": 0}

    def fake_apply(dto, target_repo, model=None):
        call_count["n"] += 1
        return {"dto_id": dto["id"], "status": "applied", "diff": "d",
                "reason": None, "syntax_valid": True}

    args = argparse.Namespace(target=str(target), dtos=str(dtos_path), output=None, model=None, run_id=None)
    with patch("oah.instrument.executor.apply_dto_report_only", side_effect=fake_apply):
        cmd_instrument(args)
    with patch("oah.instrument.executor.apply_dto_report_only", side_effect=fake_apply):
        cmd_instrument(args)
    assert call_count["n"] == 2


def test_malformed_dtos_file_returns_clean_error(tmp_path):
    target = tmp_path / "target_repo"
    target.mkdir()
    _init_git_repo(target)

    dtos_path = tmp_path / "implementation_dto.json"
    dtos_path.write_text("not json")

    args = argparse.Namespace(target=str(target), dtos=str(dtos_path), output=None, model=None)
    rc = cmd_instrument(args)
    assert rc == 1


def test_empty_dtos_list_is_a_clean_noop(tmp_path):
    target = tmp_path / "target_repo"
    target.mkdir()
    _init_git_repo(target)

    dtos_path = tmp_path / "implementation_dto.json"
    _write_dtos_file(dtos_path, [])

    args = argparse.Namespace(target=str(target), dtos=str(dtos_path), output=None, model=None)
    rc = cmd_instrument(args)
    assert rc == 0
