"""CLI integration tests, run as real subprocesses through `oah` — the
resume test here is what actually caught state_db.create_run()'s UNIQUE
constraint bug (fixed, see test_state_db.py's idempotency test), so this
stays a real subprocess call rather than calling cmd_map() in-process,
which would have masked the same bug argparse/subprocess wiring could
reintroduce."""
import json
import subprocess
import sys
from pathlib import Path


def _run(args, cwd):
    return subprocess.run(
        [sys.executable, "-m", "oah.cli", *args],
        cwd=cwd, capture_output=True, text=True, timeout=30,
    )


def _init_git_repo(path):
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "-c", "user.email=t@t.com", "-c", "user.name=t",
                     "commit", "--allow-empty", "-q", "-m", "init"], cwd=path, check=True)


def test_doctor_exits_zero_on_healthy_environment(tmp_path):
    result = _run(["doctor"], cwd=tmp_path)
    assert result.returncode == 0
    assert "All checks passed" in result.stdout


def test_map_then_resume_is_idempotent(tmp_path):
    target = tmp_path / "target_repo"
    target.mkdir()
    (target / "app.py").write_text("import anthropic\nc = anthropic.Anthropic()\n"
                                    "r = c.messages.create(model='x')\n")
    _init_git_repo(target)

    workdir = tmp_path / "workdir"
    workdir.mkdir()

    out1 = workdir / "sm1.json"
    first = _run(["map", str(target), "--run-id", "test-run", "-o", str(out1)], cwd=workdir)
    assert first.returncode == 0, first.stderr
    assert "already checkpointed" not in first.stderr

    out2 = workdir / "sm2.json"
    second = _run(["map", str(target), "--run-id", "test-run", "-o", str(out2)], cwd=workdir)
    assert second.returncode == 0, second.stderr
    assert "already checkpointed" in second.stderr

    assert json.loads(out1.read_text()) == json.loads(out2.read_text())

    manifest = json.loads((workdir / ".oah" / "runs" / "test-run.json").read_text())
    assert manifest["stages_completed"] == ["s1"]
    assert manifest["completed_at"] is not None
    assert manifest["started_at"] < manifest["completed_at"]


def test_map_rejects_non_git_target(tmp_path):
    target = tmp_path / "not_a_repo"
    target.mkdir()
    result = _run(["map", str(target)], cwd=tmp_path)
    assert result.returncode == 1
    assert "not a git repository" in result.stderr
