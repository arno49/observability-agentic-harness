"""Regression tests for oah.discovery.manifest_scanner (S2's package.json
vendor-dependency detection)."""
import json

from oah.discovery.manifest_scanner import scan_package_json
from oah.discovery.telemetry_scanner import Ids


def _write_package_json(tmp_path, deps=None, dev_deps=None):
    data = {"name": "app", "version": "1.0.0"}
    if deps:
        data["dependencies"] = deps
    if dev_deps:
        data["devDependencies"] = dev_deps
    (tmp_path / "package.json").write_text(json.dumps(data, indent=2))


def test_no_package_json_returns_empty(tmp_path):
    assert scan_package_json(tmp_path, Ids()) == []


def test_malformed_package_json_returns_empty_not_a_crash(tmp_path):
    (tmp_path / "package.json").write_text("{not valid json")
    assert scan_package_json(tmp_path, Ids()) == []


def test_opentelemetry_scope_detected(tmp_path):
    _write_package_json(tmp_path, deps={"@opentelemetry/api": "^1.9.0", "@opentelemetry/sdk-node": "^0.55.0"})
    findings = scan_package_json(tmp_path, Ids())
    assert len(findings) == 2
    assert all(f["vendor"] == "opentelemetry" and f["category"] == "apm_tracing" for f in findings)
    packages = {f["package"] for f in findings}
    assert packages == {"@opentelemetry/api", "@opentelemetry/sdk-node"}


def test_commercial_apm_vendors_detected(tmp_path):
    _write_package_json(tmp_path, deps={
        "newrelic": "^14.0.0",
        "dd-trace": "^6.0.0",
        "@dynatrace/oneagent-sdk": "^1.5.0",
        "@splunk/otel": "^3.0.0",
    })
    findings = scan_package_json(tmp_path, Ids())
    vendors = {f["vendor"] for f in findings}
    assert vendors == {"new_relic", "datadog", "dynatrace", "splunk"}
    assert all(f["category"] == "apm_tracing" for f in findings)


def test_logging_and_metrics_and_error_tracking_libraries_detected(tmp_path):
    _write_package_json(tmp_path, deps={
        "winston": "^3.13.0", "pino": "^9.0.0",
        "prom-client": "^15.0.0", "hot-shots": "^10.0.0",
        "@sentry/node": "^8.0.0",
    })
    findings = scan_package_json(tmp_path, Ids())
    by_vendor = {f["vendor"]: f for f in findings}
    assert by_vendor["winston"]["category"] == "logging"
    assert by_vendor["pino"]["category"] == "logging"
    assert by_vendor["prometheus"]["category"] == "metrics"
    assert by_vendor["statsd"]["category"] == "metrics"
    assert by_vendor["sentry"]["category"] == "error_tracking"


def test_dev_dependencies_are_also_scanned(tmp_path):
    _write_package_json(tmp_path, dev_deps={"pino": "^9.0.0"})
    findings = scan_package_json(tmp_path, Ids())
    assert len(findings) == 1
    assert findings[0]["vendor"] == "pino"


def test_unrelated_dependencies_are_ignored(tmp_path):
    _write_package_json(tmp_path, deps={"react": "^18.0.0", "express": "^4.19.0"})
    assert scan_package_json(tmp_path, Ids()) == []


def test_line_numbers_point_at_the_actual_dependency_key(tmp_path):
    _write_package_json(tmp_path, deps={"react": "^18.0.0", "winston": "^3.13.0"})
    findings = scan_package_json(tmp_path, Ids())
    assert len(findings) == 1
    text = (tmp_path / "package.json").read_text()
    lines = text.splitlines()
    assert '"winston":' in lines[findings[0]["line"] - 1]
