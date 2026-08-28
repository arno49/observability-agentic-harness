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


@pytest.fixture(autouse=True)
def _block_real_anthropic_credentials(monkeypatch):
    """docs/decisions/039's own verification pass found this for real, not
    theoretically: once a dev machine's ~/.env carries a genuine
    ANTHROPIC_API_KEY (needed to actually exercise real Sonnet calls,
    per this session's earlier credential-loading work), python-dotenv's
    inconsistent autoload (triggered by some import chains, e.g.
    oah/cli.py's own top-level fastapi import, and not others) can inject
    that real key into a test process's os.environ mid-run -- observed
    directly via a faulthandler thread-stack dump showing
    tests/test_cli_design.py::test_design_reports_gate_failures_with_nonzero_exit
    blocked on a real live HTTPS read from Anthropic's API, because one
    lens it deliberately leaves unmocked (to test gate-failure reporting)
    silently stopped fail-fast'ing on a missing-credential check and
    started making a real, slow, billed call instead. oah/llm_client.py's
    own missing_credentials() only ever checks whether the env var is
    present, so forcing it empty (not unset -- python-dotenv's default
    load_dotenv(override=False) only fills in a var that is entirely
    absent from os.environ, not one already present with an empty value)
    keeps every test's credential-check path exactly as fail-fast as it
    was designed to be, regardless of what happens to be sitting in the
    developer's own ~/.env."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
