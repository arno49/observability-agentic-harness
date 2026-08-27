"""Real-Docker end-to-end coverage for `oah validate --live`, wiring
E6 R1's execution mechanism (oah/validate/live_sandbox.py) all the way
through cmd_validate -- not just live_sandbox's own mocked-adjacent unit
tests. Skips cleanly wherever no Docker daemon is reachable; runs for
real here and in CI (Docker preinstalled on ubuntu-latest, confirmed by
earlier E6 phases)."""
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

_APP_PY = '''
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


def _init_git_repo(path):
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "-c", "user.email=t@t.com", "-c", "user.name=t",
                     "commit", "--allow-empty", "-q", "-m", "init"], cwd=path, check=True)


def _write_dtos_file(path, dtos):
    path.write_text(json.dumps({"schema_version": "0.1.0", "dtos": dtos}, indent=2))


def _write_instrument_report(path, results=None):
    results = results or []
    summary = {"total": len(results), "applied": 0, "refused": 0, "unsupported": 0, "failed": 0}
    for r in results:
        summary[r["status"]] += 1
    report = {"schema_version": "0.1.0", "repo_git_sha": "x", "mode": "fix",
              "results": results, "summary": summary}
    path.write_text(json.dumps(report, indent=2))


def _make_target(tmp_path):
    repo = tmp_path / "target_repo"
    repo.mkdir()
    (repo / "app.py").write_text(_APP_PY)
    _init_git_repo(repo)
    return repo


def test_live_end_to_end_reports_real_requests_and_event_assertions(tmp_path):
    target = _make_target(tmp_path)

    dto = {
        "id": "dto-0001", "gap_id": "gap-0001", "surface_point_ids": ["sp-0001"],
        "change": {"type": "wrap_call", "file": "app.py", "anchor": "def do_GET",
                   "preconditions": [], "description": "wrap with a span"},
        "expected_events": [{"event_type": "generation", "required_attributes": ["gen_ai.usage.input_tokens"]}],
        "rollout_step": 1,
    }
    dtos_path = tmp_path / "implementation_dto.json"
    _write_dtos_file(dtos_path, [dto])
    report_path = tmp_path / "instrument_report.json"
    _write_instrument_report(report_path, [
        {"dto_id": "dto-0001", "status": "applied", "commit_sha": "abc123", "reason": None, "syntax_valid": True},
    ])
    requests_path = tmp_path / "requests.json"
    requests_path.write_text(json.dumps([{"path": "/"}, {"path": "/"}]))

    args = argparse.Namespace(
        target=str(target), dtos=str(dtos_path), instrument_report=str(report_path),
        output=str(tmp_path / "validation.json"), live=True,
        start_command=_START_COMMAND, port=8080, requests=str(requests_path), event_schema=None,
        setup_script=_SETUP_SCRIPT,
    )
    rc = cmd_validate(args)
    assert rc == 0

    result = json.loads((tmp_path / "validation.json").read_text())
    live = result["live_execution"]
    assert live["status"] == "ok", live
    assert len(live["requests"]) == 2
    assert all(r["status_code"] == 200 for r in live["requests"])
    assert live["latency_p50_ms"] is not None
    # docs/decisions/025: the target's own tracer = trace.get_tracer(__name__)
    # span (run as `python /repo/app.py`, so __name__ == "__main__") is real,
    # harness-instrumented evidence, not auto-instrumentation -- http.server
    # has no OTel auto-instrumentation library, so opentelemetry-instrument's
    # own bootstrap has nothing to auto-instrument here; --live's OTLP-JSON
    # capture is what actually carries instrumentation_scope, unlike --dynamic.
    assert live["event_assertions"] == [
        {"dto_id": "dto-0001", "status": "observed", "reason": None, "provenance": ["harness_instrumented"]}
    ]
    assert live["unknown_attributes"]["status"] == "not_attempted"
    # two requests, each a single root-only span -> two complete traces
    assert live["tcr"] == {"traces_total": 2, "traces_complete": 2, "tcr": 1.0, "incomplete_trace_ids": []}
    # this phase deliberately never claims R1
    assert result["ladder_rung"] == "R4"


def test_live_with_event_schema_flags_unknown_attributes(tmp_path):
    target = _make_target(tmp_path)

    dtos_path = tmp_path / "implementation_dto.json"
    _write_dtos_file(dtos_path, [])
    report_path = tmp_path / "instrument_report.json"
    _write_instrument_report(report_path)
    requests_path = tmp_path / "requests.json"
    requests_path.write_text(json.dumps([{"path": "/"}]))
    event_schema_path = tmp_path / "event_schema.json"
    event_schema_path.write_text(json.dumps({
        "schema_version": "0.1.0", "repo_git_sha": "x",
        "attributes": [
            {"name": "some.other.attr", "kind": "oah_extension", "stability": "development",
             "sensitivity_tier": "internal", "source_lenses": ["cost"], "surface_point_ids": ["sp-1"]},
        ],
    }))

    args = argparse.Namespace(
        target=str(target), dtos=str(dtos_path), instrument_report=str(report_path),
        output=str(tmp_path / "validation.json"), live=True,
        start_command=_START_COMMAND, port=8080, requests=str(requests_path),
        event_schema=str(event_schema_path), setup_script=_SETUP_SCRIPT,
    )
    rc = cmd_validate(args)
    assert rc == 0

    result = json.loads((tmp_path / "validation.json").read_text())
    unknown = result["live_execution"]["unknown_attributes"]
    assert unknown["status"] == "unknown_attributes_found"
    assert "gen_ai.usage.input_tokens" in unknown["unknown"]


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

_INSTRUMENTED_WITH_DELAY_APP_PY = '''
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from opentelemetry import trace

tracer = trace.get_tracer(__name__)

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        with tracer.start_as_current_span("handle_booking") as span:
            span.set_attribute("gen_ai.usage.input_tokens", 42)
            time.sleep(0.1)  # simulates real instrumentation overhead
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")

    def log_message(self, *args):
        pass

HTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
'''


def test_live_with_baseline_reports_real_positive_overhead(tmp_path):
    """A real two-commit repo: baseline has no delay, the 'instrumented'
    commit adds a deliberate 100ms sleep -- proves overhead_p50_ms/
    overhead_p95_ms are real, measured numbers, not just wired-but-
    always-zero."""
    target = tmp_path / "target_repo"
    target.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=target, check=True)
    (target / "app.py").write_text(_BASELINE_APP_PY)
    subprocess.run(["git", "add", "app.py"], cwd=target, check=True)
    subprocess.run(["git", "-c", "user.email=t@t.com", "-c", "user.name=t",
                     "commit", "-q", "-m", "baseline"], cwd=target, check=True)
    baseline_sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=target,
                                   capture_output=True, text=True, check=True).stdout.strip()

    (target / "app.py").write_text(_INSTRUMENTED_WITH_DELAY_APP_PY)
    subprocess.run(["git", "add", "app.py"], cwd=target, check=True)
    subprocess.run(["git", "-c", "user.email=t@t.com", "-c", "user.name=t",
                     "commit", "-q", "-m", "instrumented"], cwd=target, check=True)

    dto = {
        "id": "dto-0001", "gap_id": "gap-0001", "surface_point_ids": ["sp-0001"],
        "change": {"type": "wrap_call", "file": "app.py", "anchor": "def do_GET",
                   "preconditions": [], "description": "wrap with a span"},
        "expected_events": [{"event_type": "generation", "required_attributes": ["gen_ai.usage.input_tokens"]}],
        "rollout_step": 1, "estimated_overhead_ms": 5.0,
    }
    dtos_path = tmp_path / "implementation_dto.json"
    _write_dtos_file(dtos_path, [dto])
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
        output=str(tmp_path / "validation.json"), live=True,
        start_command=_START_COMMAND, port=8080, requests=str(requests_path), event_schema=None,
        setup_script=_SETUP_SCRIPT, baseline=True,
    )
    rc = cmd_validate(args)
    assert rc == 0

    result = json.loads((tmp_path / "validation.json").read_text())
    ovb = result["live_execution"]["overhead_vs_budget"]
    assert ovb["status"] == "ok", ovb
    # the 100ms sleep is only in the instrumented version -- a real, measured, positive delta
    assert ovb["overhead_p50_ms"] > 50
    assert ovb["overhead_p95_ms"] > 50
    assert ovb["budget_ms"] == 5.0
    assert ovb["budget_complete"] is True
    assert ovb["within_budget"] is False  # 100ms of real overhead vs. a 5ms declared budget


def test_live_missing_required_flags_returns_clean_error(tmp_path):
    target = _make_target(tmp_path)
    dtos_path = tmp_path / "implementation_dto.json"
    _write_dtos_file(dtos_path, [])
    report_path = tmp_path / "instrument_report.json"
    _write_instrument_report(report_path)

    args = argparse.Namespace(
        target=str(target), dtos=str(dtos_path), instrument_report=str(report_path),
        output=None, live=True, start_command=_START_COMMAND, port=None, requests=None, event_schema=None,
    )
    rc = cmd_validate(args)
    assert rc == 1
