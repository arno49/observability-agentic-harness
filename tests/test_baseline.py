"""E6 R1's baseline mechanism -- real Docker AND real git, not mocked.
Skips cleanly wherever no Docker daemon is reachable; runs for real here
and in CI (Docker preinstalled on ubuntu-latest, confirmed by earlier
E6 phases)."""
import subprocess

import pytest

from oah.validate.baseline import run_baseline_live_sandbox
from oah.validate.sandbox import docker_available

pytestmark = pytest.mark.skipif(
    not docker_available(),
    reason="docker is not available (not on PATH, or the daemon is unreachable)",
)

_BASELINE_APP_PY = '''
from http.server import BaseHTTPRequestHandler, HTTPServer

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *args):
        pass

HTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
'''

_INSTRUMENTED_APP_PY = '''
from http.server import BaseHTTPRequestHandler, HTTPServer
from opentelemetry import trace

tracer = trace.get_tracer(__name__)

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        with tracer.start_as_current_span("handle_booking") as span:
            span.set_attribute("gen_ai.usage.input_tokens", 42)
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")

    def log_message(self, *args):
        pass

HTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
'''

_START_COMMAND = "opentelemetry-instrument python /repo/app.py"
_SETUP_SCRIPT = (
    "pip install --no-cache-dir opentelemetry-api opentelemetry-sdk "
    "opentelemetry-exporter-otlp-proto-http opentelemetry-instrumentation opentelemetry-distro"
)


def _init_two_commit_repo(tmp_path):
    """First commit: uninstrumented app.py (the real baseline). Second
    commit: the S10-skill-pattern instrumented version -- mirrors what a
    real S10 fix-mode run produces (one commit per DTO, on top of a real
    pre-instrumentation state)."""
    repo = tmp_path / "target_repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    (repo / "app.py").write_text(_BASELINE_APP_PY)
    subprocess.run(["git", "add", "app.py"], cwd=repo, check=True)
    subprocess.run(["git", "-c", "user.email=t@t.com", "-c", "user.name=t",
                     "commit", "-q", "-m", "baseline"], cwd=repo, check=True)
    baseline_sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo,
                                   capture_output=True, text=True, check=True).stdout.strip()

    (repo / "app.py").write_text(_INSTRUMENTED_APP_PY)
    subprocess.run(["git", "add", "app.py"], cwd=repo, check=True)
    subprocess.run(["git", "-c", "user.email=t@t.com", "-c", "user.name=t",
                     "commit", "-q", "-m", "instrumented"], cwd=repo, check=True)

    return repo, baseline_sha


def _worktree_list(repo):
    result = subprocess.run(["git", "-C", str(repo), "worktree", "list", "--porcelain"],
                             capture_output=True, text=True)
    return result.stdout


def test_baseline_run_uses_real_pre_instrumentation_code_and_captures_no_spans(tmp_path):
    repo, baseline_sha = _init_two_commit_repo(tmp_path)
    status_before = subprocess.run(["git", "-C", str(repo), "status", "--porcelain"],
                                    capture_output=True, text=True).stdout
    worktrees_before = _worktree_list(repo)

    result = run_baseline_live_sandbox(
        repo, baseline_sha, start_command=_START_COMMAND, port=8080, requests=[{"path": "/"}],
        setup_script=_SETUP_SCRIPT, startup_timeout_s=30,
    )

    assert result["status"] == "ok", result
    assert result["requests"][0]["status_code"] == 200
    # the baseline code never imports opentelemetry.trace -- no spans, real evidence it ran the OLDER code
    assert result["spans"] == []

    # the caller's own working tree and worktree list are exactly as before
    status_after = subprocess.run(["git", "-C", str(repo), "status", "--porcelain"],
                                   capture_output=True, text=True).stdout
    assert status_after == status_before
    assert _worktree_list(repo) == worktrees_before
    assert (repo / "app.py").read_text() == _INSTRUMENTED_APP_PY


def test_worktree_failed_when_sha_does_not_exist(tmp_path):
    repo, _ = _init_two_commit_repo(tmp_path)
    worktrees_before = _worktree_list(repo)

    result = run_baseline_live_sandbox(
        repo, "0" * 40, start_command=_START_COMMAND, port=8080, requests=[{"path": "/"}],
    )

    assert result["status"] == "worktree_failed"
    assert _worktree_list(repo) == worktrees_before
