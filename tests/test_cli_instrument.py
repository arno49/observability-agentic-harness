"""In-process test for cmd_instrument's full flow -- real target repo +
DTO file on disk, mocked agent call, real diff computation and
checkpointing -- same reasoning as test_cli_design.py: this is the wiring
that oah.instrument.executor's own unit tests don't exercise."""
import argparse
import json
import subprocess
from unittest.mock import patch

from oah.cli import cmd_instrument
from oah.design.readiness_report import build_readiness_report


def _init_git_repo(path):
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "-c", "user.email=t@t.com", "-c", "user.name=t",
                     "commit", "--allow-empty", "-q", "-m", "init"], cwd=path, check=True)


def _write_git_target(tmp_path, content="response = client.messages.create(model='x')\n"):
    """Unlike _init_git_repo (empty commit, app.py left untracked -- fine
    for report-only tests, wrong for fix mode's clean-working-tree
    precondition), this actually commits app.py so the tree starts clean."""
    target = tmp_path / "target_repo"
    target.mkdir()
    (target / "app.py").write_text(content)
    subprocess.run(["git", "init", "-q"], cwd=target, check=True)
    subprocess.run(["git", "add", "-A"], cwd=target, check=True)
    subprocess.run(["git", "-c", "user.email=t@t.com", "-c", "user.name=t",
                     "commit", "-q", "-m", "init"], cwd=target, check=True)
    return target


def _write_dtos_file(path, dtos):
    path.write_text(json.dumps({"schema_version": "0.1.0", "dtos": dtos}, indent=2))


def _write_readiness_file(path, decision="ready_with_conditions"):
    """Builds a real, schema-valid readiness_report.json via the actual
    S9 assembler rather than a hand-typed fixture -- gap_model empty (or,
    for a non-ready decision, one unaddressed p0 dark gap, which
    _decide() maps straight to remediate_before_release)."""
    event_schema = {"schema_version": "0.1.0", "repo_git_sha": "x", "attributes": [],
                     "summary": {"attribute_count": 0, "otel_genai_count": 0,
                                 "oah_extension_count": 0, "lenses_included": []}}
    dtos = {"schema_version": "0.1.0", "dtos": []}
    if decision == "ready_with_conditions":
        gap_model = {"gaps": []}
    elif decision == "remediate_before_release":
        gap_model = {"gaps": [{"id": "gap-0001", "surface_point_ids": ["sp-0001"],
                                "dimension": "generation_capture", "status": "dark",
                                "priority": "p0", "rationale": "no capture at all"}]}
    else:
        raise ValueError(decision)
    report = build_readiness_report(gap_model, [], [], event_schema, dtos, repo_git_sha="deadbeef")
    assert report["recommendation"]["decision"] == decision
    path.write_text(json.dumps(report, indent=2))


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


# --- --mode fix ----------------------------------------------------------

def test_fix_mode_requires_readiness_flag(tmp_path):
    target = _write_git_target(tmp_path)
    dtos_path = tmp_path / "implementation_dto.json"
    _write_dtos_file(dtos_path, [DTO])

    args = argparse.Namespace(target=str(target), dtos=str(dtos_path), output=None,
                               model=None, mode="fix", readiness=None)
    rc = cmd_instrument(args)
    assert rc == 1


def test_fix_mode_refuses_when_readiness_decision_is_not_ready(tmp_path):
    target = _write_git_target(tmp_path)
    dtos_path = tmp_path / "implementation_dto.json"
    _write_dtos_file(dtos_path, [DTO])
    readiness_path = tmp_path / "readiness_report.json"
    _write_readiness_file(readiness_path, decision="remediate_before_release")

    args = argparse.Namespace(target=str(target), dtos=str(dtos_path), output=None, model=None,
                               mode="fix", readiness=str(readiness_path))
    with patch("oah.instrument.executor.apply_dto_fix") as fake_fix:
        rc = cmd_instrument(args)
    assert rc == 1
    fake_fix.assert_not_called()


def test_fix_mode_refuses_on_dirty_working_tree(tmp_path):
    target = _write_git_target(tmp_path)
    (target / "app.py").write_text("uncommitted local edit\n")  # dirty, never git-added

    dtos_path = tmp_path / "implementation_dto.json"
    _write_dtos_file(dtos_path, [DTO])
    readiness_path = tmp_path / "readiness_report.json"
    _write_readiness_file(readiness_path)

    args = argparse.Namespace(target=str(target), dtos=str(dtos_path), output=None, model=None,
                               mode="fix", readiness=str(readiness_path))
    with patch("oah.instrument.executor.apply_dto_fix") as fake_fix:
        rc = cmd_instrument(args)
    assert rc == 1
    fake_fix.assert_not_called()
    # The precondition check itself must not have touched the dirty file.
    assert (target / "app.py").read_text() == "uncommitted local edit\n"


def test_fix_mode_end_to_end_writes_and_commits(tmp_path):
    target = _write_git_target(tmp_path)
    dtos_path = tmp_path / "implementation_dto.json"
    _write_dtos_file(dtos_path, [DTO])
    readiness_path = tmp_path / "readiness_report.json"
    _write_readiness_file(readiness_path)

    patched = "telemetry.emit()\nresponse = client.messages.create(model='x')\n"

    def fake_apply_dto_fix(dto, target_repo, model=None):
        return {"dto_id": dto["id"], "status": "applied", "commit_sha": "abc123",
                "reason": None, "syntax_valid": True}

    args = argparse.Namespace(target=str(target), dtos=str(dtos_path),
                               output=str(tmp_path / "report.json"), model=None,
                               mode="fix", readiness=str(readiness_path))
    with patch("oah.instrument.executor.apply_dto_fix", side_effect=fake_apply_dto_fix):
        rc = cmd_instrument(args)

    assert rc == 0
    report = json.loads((tmp_path / "report.json").read_text())
    assert report["mode"] == "fix"
    assert report["results"][0]["commit_sha"] == "abc123"
    assert report["summary"] == {"total": 1, "applied": 1, "refused": 0, "unsupported": 0, "failed": 0}


def test_report_only_and_fix_checkpoints_never_collide_on_the_same_run_id(tmp_path):
    """Same --run-id used for a report-only run and then a fix run against
    the same target must not let the fix run silently reuse the
    report-only run's differently-shaped (diff, not commit_sha)
    checkpointed result."""
    target = _write_git_target(tmp_path)
    dtos_path = tmp_path / "implementation_dto.json"
    _write_dtos_file(dtos_path, [DTO])
    readiness_path = tmp_path / "readiness_report.json"
    _write_readiness_file(readiness_path)

    def fake_report_only(dto, target_repo, model=None):
        return {"dto_id": dto["id"], "status": "applied", "diff": "d", "reason": None, "syntax_valid": True}

    def fake_fix(dto, target_repo, model=None):
        return {"dto_id": dto["id"], "status": "applied", "commit_sha": "abc123",
                "reason": None, "syntax_valid": True}

    args1 = argparse.Namespace(target=str(target), dtos=str(dtos_path), output=None, model=None,
                                mode="report-only", readiness=None, run_id="shared-run")
    with patch("oah.instrument.executor.apply_dto_report_only", side_effect=fake_report_only):
        rc1 = cmd_instrument(args1)
    assert rc1 == 0

    args2 = argparse.Namespace(target=str(target), dtos=str(dtos_path),
                                output=str(tmp_path / "fix_report.json"), model=None,
                                mode="fix", readiness=str(readiness_path), run_id="shared-run")
    with patch("oah.instrument.executor.apply_dto_fix", side_effect=fake_fix) as fake_fix_mock:
        rc2 = cmd_instrument(args2)
    assert rc2 == 0
    fake_fix_mock.assert_called_once()  # not skipped as "already checkpointed"
    report2 = json.loads((tmp_path / "fix_report.json").read_text())
    assert report2["results"][0]["commit_sha"] == "abc123"
