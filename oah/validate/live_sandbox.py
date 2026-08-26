"""E6 R1's execution primitive: run a target's own long-running service
inside a Docker network isolated from the internet but able to talk to a
real local OTel Collector -- what `docs/validation.md`'s R1 rung ("Full
dynamic") needs: run the product, drive synthetic traffic, intercept via a
real local OTLP collector, compute real per-request latency. Unlike E6
R2's `sandbox.py` (a single container, `--network none`, one shell script
that runs to completion), R1 needs two long-running containers that can
talk to *each other* but nowhere else -- a materially different isolation
shape, verified for real before designing against it:

- `docker network create --internal` produces a network with no route to
  the internet (`docker network inspect` confirms `Internal: true`), while
  still letting containers on it reach each other by container name (DNS).
- The collector's `debug` exporter (the first thing reached for, matching
  R2's console-exporter precedent) prints a custom, versioned Go text
  format -- not JSON, and a real parsing-fragility risk. The `file`
  exporter produces clean, spec-compliant, line-delimited OTLP-JSON
  instead, but requires its target path to already exist (`open: no such
  file or directory` -- a real failure hit while building this), worked
  around with a bind-mounted, pre-created empty file. This is a deliberate,
  narrow exception to R2's "no bind mount" posture: `sandbox.py` avoids
  bind-mounting *target repo* content (hostile, per `docs/security.md`
  T1); the collector here is OAH's own trusted, generated config, the
  mount is directional (host reads collector output back), and no
  target-repo code ever touches it.

Never raises for an expected failure mode (Docker missing, network/build/
startup failure) -- returns a result dict with the failure named, same
"never raise for an expected failure, only for a real bug" posture as
`sandbox.py`. Unconditional cleanup in a `finally` block: both containers,
the built image, and the network, regardless of which path got there --
including the case where the collector was already removed mid-run by the
fail-open check below.
"""
import base64
import json
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

from oah.validate.sandbox import docker_available

_COLLECTOR_CONFIG = """
receivers:
  otlp:
    protocols:
      http:
        endpoint: 0.0.0.0:4318
exporters:
  file:
    path: /tmp/spans.json
service:
  pipelines:
    traces:
      receivers: [otlp]
      exporters: [file]
""".strip()

# One driver container per request: issues exactly one HTTP call against
# the target's own container-DNS name and prints {"status_code", "latency_ms"}
# as its only stdout line. Runs on the same isolated network as the target
# and collector -- never touches the host directly.
_DRIVER_SCRIPT_TEMPLATE = """
import json, time, urllib.error, urllib.request
start = time.monotonic()
try:
    req = urllib.request.Request({url!r}, method={method!r})
    resp = urllib.request.urlopen(req, timeout={timeout})
    status = resp.status
    resp.read()
except urllib.error.HTTPError as e:
    status = e.code
except Exception:
    status = None
elapsed_ms = (time.monotonic() - start) * 1000
print(json.dumps({{"status_code": status, "latency_ms": elapsed_ms}}))
""".strip()


def _live_result(status, spans=None, requests=None, latency_p50_ms=None,
                  latency_p95_ms=None, fail_open=None, reason=None):
    return {
        "status": status, "spans": spans if spans is not None else [],
        "requests": requests if requests is not None else [],
        "latency_p50_ms": latency_p50_ms, "latency_p95_ms": latency_p95_ms,
        "fail_open": fail_open, "reason": reason,
    }


def _percentile(sorted_values, pct):
    """Real percentile over the run's own raw samples -- never an average
    of percentiles pulled from elsewhere (docs/validation.md's own rule)."""
    if not sorted_values:
        return None
    k = (len(sorted_values) - 1) * pct
    lo, hi = int(k), min(int(k) + 1, len(sorted_values) - 1)
    if lo == hi:
        return sorted_values[lo]
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (k - lo)


def _drive_request(network, target_name, port, method, path, timeout_s):
    url = f"http://{target_name}:{port}{path}"
    script = _DRIVER_SCRIPT_TEMPLATE.format(url=url, method=method, timeout=timeout_s)
    result = subprocess.run(
        ["docker", "run", "--rm", "--network", network, "python:3.12-slim", "python3", "-c", script],
        capture_output=True, text=True, timeout=timeout_s + 15,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return {"status_code": None, "latency_ms": None}
    try:
        return json.loads(result.stdout.strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError):
        return {"status_code": None, "latency_ms": None}


def _wait_for_ready(network, target_name, port, startup_timeout_s):
    deadline = time.monotonic() + startup_timeout_s
    while time.monotonic() < deadline:
        if _drive_request(network, target_name, port, "GET", "/", timeout_s=5)["status_code"] is not None:
            return True
        time.sleep(1)
    return False


def _wait_for_file_size_to_stabilize(path, timeout_s=15, poll_interval_s=1.5):
    """Polls `path`'s size until two consecutive checks agree, rather than
    guessing a fixed sleep -- a real race, not a hypothetical one: a fixed
    1s sleep intermittently missed the readiness probe's own async span
    flush. `poll_interval_s` must stay comfortably above the target's own
    OTEL_BSP_SCHEDULE_DELAY (set to 500ms below) -- an earlier version of
    this used a 300ms interval, shorter than the SDK's own flush cycle, so
    two "equal" reads could land in the pause *between* two flush batches
    and falsely declare stability with a span still pending; caught only
    by running this module's own real-Docker test three times in a row,
    since a single run could still get lucky."""
    deadline = time.monotonic() + timeout_s
    previous = -1
    while time.monotonic() < deadline:
        current = path.stat().st_size
        if current == previous:
            return current
        previous = current
        time.sleep(poll_interval_s)
    return path.stat().st_size
    return False


def _parse_span_file(path, start_offset=0):
    """The file exporter writes one OTLP-JSON `resourceSpans` document per
    line -- flattened here to the same {name, attributes} shape
    pytest_runner.parse_captured_spans already returns, so
    event_assertion.check_dto_dynamic can consume either source unchanged.
    Attribute values keep whatever type OTLP-JSON's typed-value encoding
    gives them (e.g. an int64 attribute arrives as a numeral *string*, per
    the protobuf-JSON mapping) -- check_dto_dynamic only ever checks
    attribute *key* presence, never compares values, so this is never
    normalized further.

    `start_offset` skips bytes written before it -- used to exclude the
    readiness probe's own span (a real request against the target's real
    handler, which a naive target app may instrument identically to real
    traffic; a real bug this module's own real-Docker test caught: a
    single request produced two captured spans, one from the request and
    one from _wait_for_ready's own probe). Reading from an offset avoids
    truncating a file the collector process still has open, which risks
    corrupting its next write."""
    spans = []
    with open(path, "r") as f:
        f.seek(start_offset)
        content = f.read()
    for line in content.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            doc = json.loads(line)
        except json.JSONDecodeError:
            continue
        for resource_span in doc.get("resourceSpans", []):
            for scope_span in resource_span.get("scopeSpans", []):
                for span in scope_span.get("spans", []):
                    attributes = {}
                    for attr in span.get("attributes", []):
                        value = attr.get("value", {})
                        attributes[attr["key"]] = next(iter(value.values()), None)
                    spans.append({"name": span.get("name"), "attributes": attributes})
    return spans


def run_live_sandbox(target_repo, *, start_command, port, requests,
                      kill_collector_after_request=None, setup_script=None,
                      image="python:3.12-slim", startup_timeout_s=30,
                      request_timeout_s=10, collector_image="otel/opentelemetry-collector:latest"):
    """Builds target_repo into a throwaway image whose CMD is
    `start_command` (a long-running server, not a one-shot script), starts
    it alongside a real OTel Collector on a throwaway internet-isolated
    network, drives each entry in `requests` (`{"method", "path"}`) against
    it from a separate driver container, and reports real captured spans
    plus real per-request latency/status.

    `kill_collector_after_request`, if given, is a 0-based index: the
    collector is killed right after that request completes and before the
    next one is issued, proving docs/validation.md's fail-open check with
    the same infrastructure -- `fail_open` in the result is True only if
    every request issued after the kill still got a real 200 back.

    Never raises for an expected failure (Docker unavailable, network/
    build/startup failure) -- returns status
    "docker_unavailable"/"build_failed"/"startup_failed" instead, `reason`
    naming why. "ok" is the only status with real requests/spans/latency
    data attached."""
    if not docker_available():
        return _live_result("docker_unavailable",
                             reason="docker is not available (not on PATH, or the daemon is unreachable)")

    run_id = uuid.uuid4().hex[:12]
    network = f"oah-live-net-{run_id}"
    tag = f"oah-live-app-{run_id}"
    target_name = f"oah-live-app-run-{run_id}"
    collector_name = f"oah-live-collector-run-{run_id}"

    network_created = False
    target_started = False
    collector_started = False

    try:
        create_net = subprocess.run(
            ["docker", "network", "create", "--internal", network],
            capture_output=True, text=True, timeout=30,
        )
        if create_net.returncode != 0:
            return _live_result("docker_unavailable", reason=f"failed to create isolated network:\n{create_net.stderr}")
        network_created = True

        with tempfile.TemporaryDirectory() as build_dir:
            dockerfile_path = Path(build_dir) / "Dockerfile"
            dockerfile_lines = [f"FROM {image}", "COPY . /repo", "WORKDIR /repo"]
            if setup_script:
                encoded = base64.b64encode(setup_script.encode()).decode()
                dockerfile_lines.append(f"RUN echo {encoded} | base64 -d | sh")
            dockerfile_lines.append(f"CMD {start_command}")
            dockerfile_path.write_text("\n".join(dockerfile_lines) + "\n")

            build = subprocess.run(
                ["docker", "build", "-f", str(dockerfile_path), "-t", tag, str(target_repo)],
                capture_output=True, text=True, timeout=120,
            )
            if build.returncode != 0:
                return _live_result("build_failed", reason=f"docker build failed:\n{build.stderr}")

        with tempfile.TemporaryDirectory() as collector_dir:
            config_path = Path(collector_dir) / "config.yaml"
            config_path.write_text(_COLLECTOR_CONFIG)
            output_path = Path(collector_dir) / "spans.json"
            output_path.write_text("")
            # otel/opentelemetry-collector runs as a non-root UID (10001)
            # by default -- a real CI-only failure, not hypothetical: this
            # worked locally under Docker Desktop on macOS, whose bind-mount
            # translation layer doesn't enforce real UID/GID checks, but
            # silently produced zero captured spans on a real Linux Docker
            # daemon (GitHub Actions), where the collector couldn't open a
            # host-owned file for writing and crashed. World-writable makes
            # this independent of whichever UID the collector image uses.
            output_path.chmod(0o666)

            collector_run = subprocess.run(
                ["docker", "run", "-d", "--network", network, "--name", collector_name,
                 "-v", f"{config_path}:/etc/otelcol/config.yaml",
                 "-v", f"{output_path}:/tmp/spans.json",
                 collector_image, "--config", "/etc/otelcol/config.yaml"],
                capture_output=True, text=True, timeout=30,
            )
            if collector_run.returncode != 0:
                return _live_result("build_failed", reason=f"failed to start the OTel collector:\n{collector_run.stderr}")
            collector_started = True

            # `docker run -d` succeeding only means the container started,
            # not that its process stayed up -- a real blind spot until
            # this check existed: the collector crashing shortly after
            # start (e.g. the permission issue above) previously surfaced
            # as silent zero-spans results, not a real error. A short
            # settle-then-inspect catches an immediate crash without
            # slowing down the common case.
            time.sleep(1)
            inspect = subprocess.run(
                ["docker", "inspect", "--format", "{{.State.Running}}", collector_name],
                capture_output=True, text=True, timeout=10,
            )
            if inspect.stdout.strip() != "true":
                logs = subprocess.run(["docker", "logs", collector_name], capture_output=True, text=True, timeout=10)
                return _live_result("build_failed",
                                     reason=f"the OTel collector container exited shortly after starting:\n{logs.stdout}\n{logs.stderr}")

            target_run = subprocess.run(
                ["docker", "run", "-d", "--network", network, "--name", target_name,
                 "-e", "OTEL_TRACES_EXPORTER=otlp",
                 "-e", f"OTEL_EXPORTER_OTLP_ENDPOINT=http://{collector_name}:4318",
                 "-e", "OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf",
                 "-e", "OTEL_METRICS_EXPORTER=none", "-e", "OTEL_LOGS_EXPORTER=none",
                 "-e", "OTEL_BSP_SCHEDULE_DELAY=500",
                 tag],
                capture_output=True, text=True, timeout=30,
            )
            if target_run.returncode != 0:
                return _live_result("build_failed", reason=f"failed to start the target container:\n{target_run.stderr}")
            target_started = True

            if not _wait_for_ready(network, target_name, port, startup_timeout_s):
                return _live_result("startup_failed",
                                     reason=f"target service never became ready within {startup_timeout_s}s")

            # Anything the readiness probe's own request emitted lands
            # before this offset -- excluded from the spans this call
            # reports, since it isn't one of the caller's own `requests`.
            span_read_offset = _wait_for_file_size_to_stabilize(output_path)

            request_results = []
            for i, req in enumerate(requests):
                result = _drive_request(network, target_name, port, req.get("method", "GET"),
                                         req["path"], request_timeout_s)
                request_results.append({"path": req["path"], **result})
                if kill_collector_after_request == i:
                    subprocess.run(["docker", "rm", "-f", collector_name], capture_output=True)
                    collector_started = False

            if collector_started:
                _wait_for_file_size_to_stabilize(output_path)  # let the batch span processor's async flush land

            spans = _parse_span_file(output_path, start_offset=span_read_offset) if collector_started else []
            latencies = sorted(r["latency_ms"] for r in request_results if r["latency_ms"] is not None)

            fail_open = None
            if kill_collector_after_request is not None:
                after_kill = request_results[kill_collector_after_request + 1:]
                fail_open = bool(after_kill) and all(r["status_code"] == 200 for r in after_kill)

            return _live_result(
                "ok", spans=spans, requests=request_results,
                latency_p50_ms=_percentile(latencies, 0.5), latency_p95_ms=_percentile(latencies, 0.95),
                fail_open=fail_open,
            )
    finally:
        if target_started:
            subprocess.run(["docker", "rm", "-f", target_name], capture_output=True)
        if collector_started:
            subprocess.run(["docker", "rm", "-f", collector_name], capture_output=True)
        subprocess.run(["docker", "image", "rm", "-f", tag], capture_output=True)
        if network_created:
            subprocess.run(["docker", "network", "rm", network], capture_output=True)
