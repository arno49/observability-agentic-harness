"""Regression tests for oah.state_db — specifically the resume path, since
a real CLI test caught create_run() failing with a UNIQUE constraint error
on a second call with the same run_id (resuming an existing run is the
normal case checkpoint/resume exists for, not an error)."""
from oah.state_db import StateDB


def test_create_run_idempotent(tmp_path):
    db = StateDB(tmp_path / "state.sqlite3")
    db.create_run("run-1", "/some/repo", "abc123", "2026-01-01T00:00:00Z")
    db.create_run("run-1", "/some/repo", "abc123", "2026-01-01T00:00:00Z")  # must not raise
    assert db.get_run("run-1")["run_id"] == "run-1"


def test_checkpoint_and_resume(tmp_path):
    db = StateDB(tmp_path / "state.sqlite3")
    db.create_run("run-1", "/some/repo", "abc123", "2026-01-01T00:00:00Z")
    assert not db.is_checkpointed("run-1", "s1", "full_scan")

    db.checkpoint("run-1", "s1", "full_scan", {"points": [1, 2, 3]}, "2026-01-01T00:01:00Z")
    assert db.is_checkpointed("run-1", "s1", "full_scan")
    assert db.get_checkpoint_result("run-1", "s1", "full_scan") == {"points": [1, 2, 3]}


def test_checkpoint_overwrite_on_retry(tmp_path):
    """Re-checkpointing the same unit (e.g. a retried stage) overwrites
    rather than creating a duplicate row."""
    db = StateDB(tmp_path / "state.sqlite3")
    db.create_run("run-1", "/some/repo", "abc123", "2026-01-01T00:00:00Z")
    db.checkpoint("run-1", "s1", "full_scan", {"v": 1}, "2026-01-01T00:01:00Z")
    db.checkpoint("run-1", "s1", "full_scan", {"v": 2}, "2026-01-01T00:02:00Z")
    assert db.get_checkpoint_result("run-1", "s1", "full_scan") == {"v": 2}
    assert len(db.completed_units("run-1", "s1")) == 1


def test_sub_stage_granularity(tmp_path):
    """Checkpoint granularity is sub-stage — multiple units within one
    stage_id, each independently resumable."""
    db = StateDB(tmp_path / "state.sqlite3")
    db.create_run("run-1", "/some/repo", "abc123", "2026-01-01T00:00:00Z")
    db.checkpoint("run-1", "s10", "dto-001", {"applied": True}, "2026-01-01T00:01:00Z")
    db.checkpoint("run-1", "s10", "dto-002", {"applied": True}, "2026-01-01T00:02:00Z")
    assert db.completed_units("run-1", "s10") == {"dto-001", "dto-002"}
    assert not db.is_checkpointed("run-1", "s10", "dto-003")
