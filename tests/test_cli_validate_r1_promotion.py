"""The actual, real proof this whole R1 effort has been building toward:
`oah validate --dynamic --live --baseline`, combined in one real
invocation, reaching `ladder_rung: "R1"` / `verdict: "validated"` for the
first time in this codebase's history -- not just the pure promotion-rule
unit tests in isolation. Real Docker, real git, real pytest-in-sandbox,
real running service, real baseline comparison, all three mechanisms this
session built (E6 R2's sandbox.py, R1's live_sandbox.py, baseline.py)
proving out together.

Skips cleanly wherever no Docker daemon is reachable; runs for real here
and in CI (Docker preinstalled on ubuntu-latest, confirmed by every
earlier E6 phase)."""
import argparse
import json
import subprocess

import pytest

from oah.cli import cmd_validate
from oah.validate.sandbox import docker_available

pytestmark = pytest.mark.skipif(
    not docker_available(),
    reason="docker is not available (not on PATH, or the daemon is unreachable)",
)

# Same app, importable by pytest (for --dynamic's own event assertion,
# captured via the test suite's console-exporter run) and runnable as a
# real HTTP service (for --live's own event assertion/TCR, captured via
# the file exporter) -- one real S10-instrumented handler, two real
# consumers of what it emits.
_APP_PY = '''
from opentelemetry import trace
tracer = trace.get_tracer(__name__)

def handle_booking():
    with tracer.start_as_current_span("handle_booking") as span:
        span.set_attribute("gen_ai.usage.input_tokens", 42)
        return "ok"

if __name__ == "__main__":
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            handle_booking()
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, *args):
            pass

    HTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
'''

_TEST_APP_PY = '''
from app import handle_booking

def test_handle_booking():
    assert handle_booking() == "ok"
'''

_UNINSTRUMENTED_APP_PY = '''
def handle_booking():
    return "ok"

if __name__ == "__main__":
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            handle_booking()
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


def test_dynamic_and_live_and_baseline_together_reach_ladder_rung_r1(tmp_path):
    target = tmp_path / "target_repo"
    target.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=target, check=True)

    # Baseline commit: no OTel at all -- the real pre-instrumentation state.
    (target / "app.py").write_text(_UNINSTRUMENTED_APP_PY)
    subprocess.run(["git", "add", "app.py"], cwd=target, check=True)
    subprocess.run(["git", "-c", "user.email=t@t.com", "-c", "user.name=t",
                     "commit", "-q", "-m", "baseline"], cwd=target, check=True)
    baseline_sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=target,
                                   capture_output=True, text=True, check=True).stdout.strip()

    # Instrumented commit: the real S10-skill-taught pattern, plus a test
    # suite --dynamic can run.
    (target / "app.py").write_text(_APP_PY)
    (target / "tests").mkdir()
    (target / "tests" / "test_app.py").write_text(_TEST_APP_PY)
    subprocess.run(["git", "add", "-A"], cwd=target, check=True)
    subprocess.run(["git", "-c", "user.email=t@t.com", "-c", "user.name=t",
                     "commit", "-q", "-m", "instrumented"], cwd=target, check=True)

    dto = {
        "id": "dto-0001", "gap_id": "gap-0001", "surface_point_ids": ["sp-0001"],
        "change": {"type": "wrap_call", "file": "app.py", "anchor": "def handle_booking",
                   "preconditions": [], "description": "wrap with a span"},
        "expected_events": [{"event_type": "generation", "required_attributes": ["gen_ai.usage.input_tokens"]}],
        "rollout_step": 1,
        # generous on purpose -- this test proves the wiring reaches R1
        # for real, not that overhead measurement is precise to the ms.
        "estimated_overhead_ms": 10000.0,
    }
    dtos_path = tmp_path / "implementation_dto.json"
    dtos_path.write_text(json.dumps({"schema_version": "0.1.0", "dtos": [dto]}, indent=2))

    report_path = tmp_path / "instrument_report.json"
    report_path.write_text(json.dumps({
        "schema_version": "0.1.0", "repo_git_sha": baseline_sha, "mode": "fix",
        "results": [{"dto_id": "dto-0001", "status": "applied", "commit_sha": "abc123",
                     "reason": None, "syntax_valid": True}],
        "summary": {"total": 1, "applied": 1, "refused": 0, "unsupported": 0, "failed": 0},
    }))

    requests_path = tmp_path / "requests.json"
    requests_path.write_text(json.dumps([{"path": "/"}]))

    args = argparse.Namespace(
        target=str(target), dtos=str(dtos_path), instrument_report=str(report_path),
        output=str(tmp_path / "validation.json"),
        dynamic=True,
        live=True, start_command=_START_COMMAND, port=8080, requests=str(requests_path),
        event_schema=None, setup_script=_SETUP_SCRIPT, baseline=True,
    )
    rc = cmd_validate(args)
    assert rc == 0

    result = json.loads((tmp_path / "validation.json").read_text())

    # every piece of real evidence this whole R1/R2 effort built, all
    # present and positive in one real report:
    assert result["regression_gate"]["status"] == "passed", result["regression_gate"]
    # provenance is ["unknown"] -- --dynamic's own console-exporter capture
    # never carries instrumentation_scope (docs/decisions/025).
    assert result["event_assertions"] == [
        {"dto_id": "dto-0001", "status": "observed", "reason": None, "provenance": ["unknown"]}
    ]
    live = result["live_execution"]
    assert live["status"] == "ok", live
    assert live["tcr"]["tcr"] == 1.0, live["tcr"]
    assert live["overhead_vs_budget"]["status"] == "ok", live["overhead_vs_budget"]
    assert live["overhead_vs_budget"]["within_budget"] is True, live["overhead_vs_budget"]

    # docs/decisions/027: the real, combined report-level provenance
    # summary -- one "unknown" from --dynamic's own console-exporter
    # capture (structurally can't carry instrumentation_scope) plus one
    # "harness_instrumented" from --live's own OTLP-JSON capture of the
    # same tracer.get_tracer(__name__) span, run as the real service.
    assert result["signal_provenance"] == {
        "auto_instrumentation": 0, "harness_instrumented": 1, "unknown": 1,
    }

    # the actual point of this whole phase:
    assert result["ladder_rung"] == "R1"
    assert result["verdict"] == "validated"
