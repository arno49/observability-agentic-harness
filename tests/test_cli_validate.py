"""In-process test for cmd_validate's full flow -- real target repo, real
implementation_dto.json + instrument_report.json on disk -- same
reasoning as test_cli_instrument.py: this is the wiring
oah.validate.checker's own unit tests don't exercise. No agent, no LLM,
nothing mocked -- R4 needs neither."""
import argparse
import json
import subprocess

from oah.cli import cmd_validate


def _init_git_repo(path):
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "-c", "user.email=t@t.com", "-c", "user.name=t",
                     "commit", "--allow-empty", "-q", "-m", "init"], cwd=path, check=True)


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


def _write_dtos_file(path, dtos):
    path.write_text(json.dumps({"schema_version": "0.1.0", "dtos": dtos}, indent=2))


def _write_instrument_report(path, results):
    summary = {"total": len(results), "applied": 0, "refused": 0, "unsupported": 0, "failed": 0}
    for r in results:
        summary[r["status"]] += 1
    report = {"schema_version": "0.1.0", "repo_git_sha": "x", "mode": "fix",
              "results": results, "summary": summary}
    path.write_text(json.dumps(report, indent=2))


def test_validate_end_to_end_present(tmp_path):
    target = tmp_path / "target_repo"
    target.mkdir()
    (target / "app.py").write_text(
        "def answer():\n"
        "    response = client.messages.create(model='x')\n"
        "    telemetry.emit('gen_ai.usage.input_tokens')\n"
    )
    _init_git_repo(target)

    dtos_path = tmp_path / "implementation_dto.json"
    _write_dtos_file(dtos_path, [DTO])
    report_path = tmp_path / "instrument_report.json"
    _write_instrument_report(report_path, [
        {"dto_id": "dto-0001", "status": "applied", "commit_sha": "abc123", "reason": None, "syntax_valid": True},
    ])

    args = argparse.Namespace(target=str(target), dtos=str(dtos_path),
                               instrument_report=str(report_path), output=str(tmp_path / "validation.json"))
    rc = cmd_validate(args)
    assert rc == 0

    result = json.loads((tmp_path / "validation.json").read_text())
    assert result["ladder_rung"] == "R4"
    assert result["verdict"] == "needs_review"
    assert result["results"][0]["status"] == "present"
    assert result["summary"] == {"total": 1, "present": 1, "absent": 0, "skipped": 0}
    # No `dynamic` attribute on this Namespace at all -- proves the
    # getattr(args, "dynamic", False) default matches old behavior.
    assert result["regression_gate"] == {"status": "not_attempted", "reason": None}
    assert result["event_assertions"] == [{"dto_id": "dto-0001", "status": "not_attempted", "reason": None}]
    assert result["propagation_checks"] == [{"dto_id": "dto-0001", "status": "not_applicable", "reason": "this checker only evaluates propagate_context DTOs"}]


def test_validate_end_to_end_absent(tmp_path):
    target = tmp_path / "target_repo"
    target.mkdir()
    (target / "app.py").write_text("response = client.messages.create(model='x')\n")  # no telemetry call at all
    _init_git_repo(target)

    dtos_path = tmp_path / "implementation_dto.json"
    _write_dtos_file(dtos_path, [DTO])
    report_path = tmp_path / "instrument_report.json"
    _write_instrument_report(report_path, [
        {"dto_id": "dto-0001", "status": "applied", "commit_sha": "abc123", "reason": None, "syntax_valid": True},
    ])

    args = argparse.Namespace(target=str(target), dtos=str(dtos_path),
                               instrument_report=str(report_path), output=None)
    rc = cmd_validate(args)
    assert rc == 0  # R4 never fails the command -- absent is a reported finding, not a crash


def test_validate_skips_dtos_that_were_not_applied(tmp_path):
    target = tmp_path / "target_repo"
    target.mkdir()
    (target / "app.py").write_text("response = client.messages.create(model='x')\n")
    _init_git_repo(target)

    dtos_path = tmp_path / "implementation_dto.json"
    _write_dtos_file(dtos_path, [DTO])
    report_path = tmp_path / "instrument_report.json"
    _write_instrument_report(report_path, [
        {"dto_id": "dto-0001", "status": "refused", "commit_sha": None, "reason": "anchor mismatch", "syntax_valid": None},
    ])

    args = argparse.Namespace(target=str(target), dtos=str(dtos_path),
                               instrument_report=str(report_path), output=str(tmp_path / "validation.json"))
    rc = cmd_validate(args)
    assert rc == 0
    result = json.loads((tmp_path / "validation.json").read_text())
    assert result["results"][0]["status"] == "skipped"
    assert result["summary"] == {"total": 1, "present": 0, "absent": 0, "skipped": 1}


def test_validate_malformed_dtos_file_returns_clean_error(tmp_path):
    target = tmp_path / "target_repo"
    target.mkdir()
    _init_git_repo(target)

    dtos_path = tmp_path / "implementation_dto.json"
    dtos_path.write_text("not json")
    report_path = tmp_path / "instrument_report.json"
    _write_instrument_report(report_path, [])

    args = argparse.Namespace(target=str(target), dtos=str(dtos_path),
                               instrument_report=str(report_path), output=None)
    rc = cmd_validate(args)
    assert rc == 1


def test_validate_malformed_instrument_report_returns_clean_error(tmp_path):
    target = tmp_path / "target_repo"
    target.mkdir()
    _init_git_repo(target)

    dtos_path = tmp_path / "implementation_dto.json"
    _write_dtos_file(dtos_path, [])
    report_path = tmp_path / "instrument_report.json"
    report_path.write_text("not json")

    args = argparse.Namespace(target=str(target), dtos=str(dtos_path),
                               instrument_report=str(report_path), output=None)
    rc = cmd_validate(args)
    assert rc == 1


def test_validate_not_a_git_repo_returns_clean_error(tmp_path):
    target = tmp_path / "not_a_repo"
    target.mkdir()
    dtos_path = tmp_path / "implementation_dto.json"
    _write_dtos_file(dtos_path, [])
    report_path = tmp_path / "instrument_report.json"
    _write_instrument_report(report_path, [])

    args = argparse.Namespace(target=str(target), dtos=str(dtos_path),
                               instrument_report=str(report_path), output=None)
    rc = cmd_validate(args)
    assert rc == 1
