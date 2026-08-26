"""Session-wide test fixtures.

oah/state_db.py and oah/run_manifest.py both resolve `.oah/` relative to
the process's cwd (Path(".oah") / "runs" | "state"), not to a per-test
tmp_path -- correct for a real `oah` invocation (state persists across a
run and its resumes), but it means pytest's own cwd (the repo root)
accumulates real state_db.sqlite3 rows and run_manifest.json files across
separate test runs. A test that reuses a fixed run_id string (several do,
matching real `--run-id resume-XXX` usage) can then find a checkpoint
already "completed" from a *previous* pytest invocation and silently
skip work it expected to actually run -- found via
test_cli_instrument.py's own resume test flaking only when run as part
of the full suite after an earlier standalone run had left state behind.

Autouse, function-scoped: wipe any accumulated `.oah/` before every test
so each one starts from the same clean slate regardless of what an
earlier test or an earlier pytest invocation left on disk. `.oah/` is
already gitignored -- this only ever deletes generated, disposable state.
"""
import shutil
from pathlib import Path

import pytest

_OAH_STATE_DIR = Path(__file__).parent.parent / ".oah"


@pytest.fixture(autouse=True)
def _clean_oah_state():
    shutil.rmtree(_OAH_STATE_DIR, ignore_errors=True)
    yield
    shutil.rmtree(_OAH_STATE_DIR, ignore_errors=True)
