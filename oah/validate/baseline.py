"""Runs `oah/validate/live_sandbox.py`'s `run_live_sandbox` against the
target repo's *pre-instrumentation* state -- the baseline
`docs/validation.md`'s "latency overhead vs. declared budget" needs
"overhead" to mean anything relative to. The baseline ref already exists,
not invented here: `instrument_report.json`'s own `repo_git_sha` is
captured by `cmd_instrument` before any DTO is touched (`oah/cli.py`),
so it's exactly the pre-instrumentation SHA.

Isolation verified for real before designing against it: `git worktree
add <tmp-dir> <sha>` creates a checkout at an arbitrary earlier commit
without touching the caller's own working tree at all (confirmed: a
worktree at a parent commit genuinely lacks a file only added in the
child commit); `git worktree remove --force` cleans it up completely.
This module never touches `target_repo`'s own working tree -- only reads
its git history to build a throwaway worktree elsewhere, torn down
unconditionally in a `finally` block, same discipline as
`sandbox.py`/`live_sandbox.py`'s own unconditional container/network
cleanup.

Never raises for an expected failure (the worktree add itself failing,
e.g. an unreachable SHA) -- returns a result dict, same "never raise for
an expected failure, only for a real bug" posture as every sandbox-
adjacent module this session has built.
"""
import subprocess
import tempfile
import uuid

from oah.validate.live_sandbox import run_live_sandbox


def run_baseline_live_sandbox(target_repo, baseline_git_sha, **kwargs):
    """Same keyword arguments and return shape as
    run_live_sandbox -- this is a thin wrapper, not a reimplementation.
    `kwargs` typically reuses the instrumented run's own start_command/
    port/requests/setup_script verbatim (a named, accepted simplification:
    running opentelemetry-instrument around code that never imports
    opentelemetry.trace is a harmless no-op, not a real problem)."""
    with tempfile.TemporaryDirectory() as parent_dir:
        worktree_dir = f"{parent_dir}/oah-baseline-worktree-{uuid.uuid4().hex[:12]}"
        add = subprocess.run(
            ["git", "-C", str(target_repo), "worktree", "add", worktree_dir, baseline_git_sha],
            capture_output=True, text=True, timeout=30,
        )
        if add.returncode != 0:
            return {
                "status": "worktree_failed", "spans": [], "requests": [],
                "latency_p50_ms": None, "latency_p95_ms": None, "fail_open": None,
                "reason": f"git worktree add failed for {baseline_git_sha!r}:\n{add.stderr}",
            }
        try:
            return run_live_sandbox(worktree_dir, **kwargs)
        finally:
            subprocess.run(
                ["git", "-C", str(target_repo), "worktree", "remove", "--force", worktree_dir],
                capture_output=True,
            )
