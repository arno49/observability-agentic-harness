"""SQLite-backed run state, outside the target repo.

Checkpoint granularity is sub-stage, not just stage-boundary (architecture.md
E1's DoD, itself written to avoid a specific VVAH pain point: no way to pick
back up mid-stage after hitting a session limit). A "unit" is whatever the
calling stage defines as its resumable increment — a disambiguation batch
for S1, one DTO for S10, one scenario for S11 — the state DB doesn't care
what a unit means, only that (run_id, stage_id, unit_id) is a stable key a
stage can re-check before redoing work.
"""
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    target_path TEXT NOT NULL,
    target_git_sha TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    status TEXT NOT NULL DEFAULT 'running'
);

CREATE TABLE IF NOT EXISTS checkpoints (
    run_id TEXT NOT NULL,
    stage_id TEXT NOT NULL,
    unit_id TEXT NOT NULL,
    status TEXT NOT NULL,
    completed_at TEXT NOT NULL,
    result_json TEXT,
    PRIMARY KEY (run_id, stage_id, unit_id),
    FOREIGN KEY (run_id) REFERENCES runs(run_id)
);
"""

DEFAULT_STATE_DIR = Path(".oah") / "state"


class StateDB:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def close(self):
        self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def create_run(self, run_id, target_path, target_git_sha, started_at):
        """Idempotent: resuming an existing run_id must not fail — a run
        being resumed is the normal case checkpoint/resume exists for, not
        an error."""
        self._conn.execute(
            "INSERT OR IGNORE INTO runs (run_id, target_path, target_git_sha, started_at) VALUES (?, ?, ?, ?)",
            (run_id, str(target_path), target_git_sha, started_at),
        )
        self._conn.commit()

    def get_run(self, run_id):
        row = self._conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        return dict(row) if row else None

    def mark_run_status(self, run_id, status, completed_at=None):
        self._conn.execute(
            "UPDATE runs SET status = ?, completed_at = COALESCE(?, completed_at) WHERE run_id = ?",
            (status, completed_at, run_id),
        )
        self._conn.commit()

    def checkpoint(self, run_id, stage_id, unit_id, result, completed_at):
        """Idempotent: re-checkpointing the same (run_id, stage_id, unit_id)
        overwrites, so a retried unit doesn't create duplicate rows."""
        self._conn.execute(
            """INSERT INTO checkpoints (run_id, stage_id, unit_id, status, completed_at, result_json)
               VALUES (?, ?, ?, 'completed', ?, ?)
               ON CONFLICT(run_id, stage_id, unit_id)
               DO UPDATE SET status='completed', completed_at=excluded.completed_at,
                              result_json=excluded.result_json""",
            (run_id, stage_id, unit_id, completed_at, json.dumps(result)),
        )
        self._conn.commit()

    def is_checkpointed(self, run_id, stage_id, unit_id):
        row = self._conn.execute(
            "SELECT 1 FROM checkpoints WHERE run_id=? AND stage_id=? AND unit_id=? AND status='completed'",
            (run_id, stage_id, unit_id),
        ).fetchone()
        return row is not None

    def get_checkpoint_result(self, run_id, stage_id, unit_id):
        row = self._conn.execute(
            "SELECT result_json FROM checkpoints WHERE run_id=? AND stage_id=? AND unit_id=? AND status='completed'",
            (run_id, stage_id, unit_id),
        ).fetchone()
        return json.loads(row["result_json"]) if row and row["result_json"] is not None else None

    def completed_units(self, run_id, stage_id):
        rows = self._conn.execute(
            "SELECT unit_id FROM checkpoints WHERE run_id=? AND stage_id=? AND status='completed'",
            (run_id, stage_id),
        ).fetchall()
        return {r["unit_id"] for r in rows}

    def stage_results(self, run_id, stage_id):
        """All checkpointed results for a stage, in unit_id order — how a
        resumed run reassembles a stage's full output from completed units."""
        rows = self._conn.execute(
            "SELECT unit_id, result_json FROM checkpoints WHERE run_id=? AND stage_id=? AND status='completed' ORDER BY unit_id",
            (run_id, stage_id),
        ).fetchall()
        return [(r["unit_id"], json.loads(r["result_json"])) for r in rows if r["result_json"] is not None]


@contextmanager
def open_state_db(target_repo_path):
    """The state DB lives outside the target repo (architecture.md: 'Checkpoints
    live in a SQLite state DB outside the target repo'), under the harness's
    own working directory, keyed by nothing about the target beyond its path
    appearing in the runs table — never written inside the scanned repo."""
    db_path = Path.cwd() / DEFAULT_STATE_DIR / "oah.sqlite3"
    db = StateDB(db_path)
    try:
        yield db
    finally:
        db.close()
