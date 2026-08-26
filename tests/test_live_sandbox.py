"""E6 R1 -- real Docker containers, not mocked. Formalizes the spike that
grounded this phase's plan: a real target service, started long-running
(not a one-shot test run like E6 R2's sandbox.py), on an internet-isolated
Docker network alongside a real OTel Collector, driven by real HTTP
traffic from a separate container, with real captured spans and real
per-request latency.

Skips cleanly (not a failure) wherever no Docker daemon is reachable;
runs for real here and in CI (Docker preinstalled on ubuntu-latest,
already confirmed by the E6 R2 phase)."""
import subprocess
import tempfile
from pathlib import Path

import pytest

from oah.validate.live_sandbox import run_live_sandbox
from oah.validate.sandbox import docker_available

pytestmark = pytest.mark.skipif(
    not docker_available(),
    reason="docker is not available (not on PATH, or the daemon is unreachable)",
)

# /delay/<ms> sleeps that many milliseconds before responding -- lets
# requests produce real, distinguishable latencies for the percentile test,
# matching exactly the S10 skill's own taught telemetry pattern.
_APP_PY = '''
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from opentelemetry import trace

tracer = trace.get_tracer(__name__)

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        with tracer.start_as_current_span("handle_booking") as span:
            span.set_attribute("gen_ai.usage.input_tokens", 42)
            if self.path.startswith("/delay/"):
                time.sleep(int(self.path.rsplit("/", 1)[-1]) / 1000)
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


def _make_target(tmp_path):
    repo = tmp_path / "target_repo"
    repo.mkdir()
    (repo / "app.py").write_text(_APP_PY)
    return repo


def _networks():
    result = subprocess.run(["docker", "network", "ls", "-q", "--filter", "name=oah-live-net-"],
                             capture_output=True, text=True)
    return set(result.stdout.split())


def _containers():
    result = subprocess.run(["docker", "ps", "-a", "-q", "--filter", "name=oah-live-"],
                             capture_output=True, text=True)
    return set(result.stdout.split())


def _images():
    result = subprocess.run(["docker", "image", "ls", "-q", "--filter", "reference=oah-live-app-*"],
                             capture_output=True, text=True)
    return set(result.stdout.split())


def test_real_request_returns_status_and_captures_span(tmp_path):
    repo = _make_target(tmp_path)
    nets_before, containers_before, images_before = _networks(), _containers(), _images()

    result = run_live_sandbox(
        repo, start_command=_START_COMMAND, port=8080, requests=[{"path": "/"}],
        setup_script=_SETUP_SCRIPT, startup_timeout_s=30,
    )

    assert result["status"] == "ok", result
    assert len(result["requests"]) == 1
    assert result["requests"][0]["path"] == "/"
    assert result["requests"][0]["status_code"] == 200
    assert result["requests"][0]["latency_ms"] > 0
    assert len(result["spans"]) == 1
    assert result["spans"][0]["name"] == "handle_booking"
    assert result["spans"][0]["attributes"].get("gen_ai.usage.input_tokens") is not None
    assert result["latency_p50_ms"] is not None
    assert result["latency_p95_ms"] is not None

    assert _networks() == nets_before
    assert _containers() == containers_before
    assert _images() == images_before


def test_multiple_requests_produce_distinct_latencies_and_sane_percentiles(tmp_path):
    repo = _make_target(tmp_path)

    result = run_live_sandbox(
        repo, start_command=_START_COMMAND, port=8080,
        requests=[{"path": "/delay/10"}, {"path": "/delay/10"}, {"path": "/delay/300"}],
        setup_script=_SETUP_SCRIPT, startup_timeout_s=30,
    )

    assert result["status"] == "ok", result
    assert all(r["status_code"] == 200 for r in result["requests"])
    assert result["latency_p95_ms"] >= result["latency_p50_ms"]
    # the one genuinely slow request should pull p95 well above the two fast ones
    assert result["latency_p95_ms"] > 200
    assert len(result["spans"]) == 3


def test_kill_collector_after_request_proves_fail_open(tmp_path):
    repo = _make_target(tmp_path)

    result = run_live_sandbox(
        repo, start_command=_START_COMMAND, port=8080,
        requests=[{"path": "/"}, {"path": "/"}, {"path": "/"}],
        kill_collector_after_request=0,
        setup_script=_SETUP_SCRIPT, startup_timeout_s=30,
    )

    assert result["status"] == "ok", result
    assert all(r["status_code"] == 200 for r in result["requests"])
    assert result["fail_open"] is True
    # only the pre-kill request's span could have been captured
    assert len(result["spans"]) <= 1


def test_docker_unavailable_returns_clean_status_and_creates_nothing(tmp_path, monkeypatch):
    import oah.validate.live_sandbox as live_sandbox_module
    monkeypatch.setattr(live_sandbox_module, "docker_available", lambda: False)

    nets_before, containers_before = _networks(), _containers()
    repo = _make_target(tmp_path)
    result = run_live_sandbox(repo, start_command=_START_COMMAND, port=8080, requests=[{"path": "/"}])

    assert result["status"] == "docker_unavailable"
    assert _networks() == nets_before
    assert _containers() == containers_before


def test_collector_crash_is_detected_not_silently_zero_spans(tmp_path):
    """The real bug this catches: `docker run -d` succeeding only proves
    the container *started*, not that it stayed running -- a collector
    that crashes shortly after start (this session hit a real, CI-only
    case: the collector's own image runs as a non-root UID, and a bind-
    mounted host file wasn't writable to it under a real Linux Docker
    daemon, though it worked locally under Docker Desktop's more
    permissive bind-mount layer) previously surfaced as a silent
    zero-captured-spans "ok" result, not a real error.

    Needs a "collector" image whose container genuinely starts (so
    `docker run -d` itself succeeds, exercising the *later* liveness
    check rather than the earlier "failed to start" one) and then exits
    on its own -- most images with no real ENTRYPOINT fail at the
    `docker run` invocation itself instead (Docker tries to exec the
    bogus `--config ...` args directly as the command), which was tried
    first and doesn't reach the code path this test means to prove.
    A tiny custom image with a real `ENTRYPOINT ["sh", "-c", "exit 1"]`
    ignores any trailing args and reliably starts-then-exits instead."""
    crash_image = "oah-test-crash-image"
    with tempfile.TemporaryDirectory() as build_dir:
        (Path(build_dir) / "Dockerfile").write_text(
            'FROM alpine:latest\nENTRYPOINT ["sh", "-c", "exit 1"]\n'
        )
        subprocess.run(["docker", "build", "-t", crash_image, "-q", build_dir], check=True, capture_output=True)

    try:
        repo = _make_target(tmp_path)
        nets_before, containers_before = _networks(), _containers()

        result = run_live_sandbox(
            repo, start_command=_START_COMMAND, port=8080, requests=[{"path": "/"}],
            setup_script=_SETUP_SCRIPT, collector_image=crash_image,
        )

        assert result["status"] == "build_failed"
        assert "collector container exited" in result["reason"]
        assert _networks() == nets_before
        assert _containers() == containers_before
    finally:
        subprocess.run(["docker", "image", "rm", "-f", crash_image], capture_output=True)


def test_build_failed_cleans_up_the_network_and_leaves_no_image(tmp_path):
    repo = tmp_path / "target_repo"
    repo.mkdir()
    nets_before, containers_before, images_before = _networks(), _containers(), _images()

    # A setup_script that genuinely fails `docker build` itself -- the
    # same "make the failure real" approach sandbox.py's own tests use.
    result = run_live_sandbox(
        repo, start_command="python /repo/app.py", port=8080, requests=[{"path": "/"}],
        setup_script="exit 1",
    )

    assert result["status"] == "build_failed"
    assert _networks() == nets_before
    assert _containers() == containers_before
    assert _images() == images_before


def test_startup_failed_when_service_never_binds_the_port(tmp_path):
    repo = tmp_path / "target_repo"
    repo.mkdir()
    (repo / "app.py").write_text("import sys; sys.exit(1)\n")

    nets_before, containers_before, images_before = _networks(), _containers(), _images()

    result = run_live_sandbox(
        repo, start_command="python /repo/app.py", port=8080, requests=[{"path": "/"}],
        startup_timeout_s=5,
    )

    assert result["status"] == "startup_failed"
    assert "never became ready" in result["reason"]

    assert _networks() == nets_before
    assert _containers() == containers_before
    assert _images() == images_before
