"""S2 manifest-based vendor/telemetry-package detection: package.json
dependencies, not source imports. A declared dependency is real evidence a
target repo has *some* telemetry vendor wired up, but -- unlike
existing_otel_usage's source-level import scan (Python-only today) -- it
doesn't confirm the package is actually imported/used anywhere in code, only
that it's a declared dependency. Kept in its own vendor_dependencies
category for exactly that reason: declared and confirmed are different
evidence tiers, and folding them into existing_otel_usage would overclaim
(docs/decisions/015).

Package names verified against each vendor's own npm/vendor-doc listing
before being hardcoded here, not guessed. Two deliberate scope limits,
named not silently dropped: only the repo root's package.json is scanned (a
monorepo's nested package.json files are a real, separate gap, not covered
here); Dynatrace in particular ships its real auto-instrumentation as a
host-level OneAgent process, not an npm dependency at all -- so
"@dynatrace/oneagent-sdk" absent from dependencies does NOT mean "no
Dynatrace," only that no *manual/custom* Dynatrace instrumentation was
declared. Splunk's "@splunk/otel" is itself a distribution of OpenTelemetry
JS -- deliberately classified as its own vendor identifier (splunk), not
folded into the opentelemetry bucket, since a repo choosing Splunk's
distribution over raw @opentelemetry/* is a real, distinct signal for S3's
gap model and E9's backend-target selection.
"""
import json
from pathlib import Path

# vendor identifier -> (category, exact package names, npm scope prefixes).
# category is one of: apm_tracing, error_tracking, logging, metrics.
_VENDOR_RULES = [
    ("opentelemetry", "apm_tracing", frozenset(), ("@opentelemetry/",)),
    ("dynatrace", "apm_tracing", frozenset({"@dynatrace/oneagent-sdk"}), ()),
    ("new_relic", "apm_tracing", frozenset({"newrelic"}), ()),
    ("splunk", "apm_tracing", frozenset({"@splunk/otel"}), ()),
    ("datadog", "apm_tracing", frozenset({"dd-trace"}), ()),
    ("sentry", "error_tracking", frozenset(), ("@sentry/",)),
    ("winston", "logging", frozenset({"winston"}), ()),
    ("pino", "logging", frozenset({"pino"}), ()),
    ("prometheus", "metrics", frozenset({"prom-client"}), ()),
    ("statsd", "metrics", frozenset({"hot-shots", "node-statsd", "statsd-client"}), ()),
]

_DEPENDENCY_KEYS = ("dependencies", "devDependencies", "optionalDependencies", "peerDependencies")


def _classify(package_name):
    for vendor, category, exact_names, prefixes in _VENDOR_RULES:
        if package_name in exact_names or any(package_name.startswith(p) for p in prefixes):
            return vendor, category
    return None, None


def _line_of_dependency(text, name):
    """Best-effort line number for name's own key in package.json's raw
    text -- a real file/line locator, same shape as every other S2 finding,
    just pointing at the manifest instead of a source import site. Falls
    back to line 1 (never crashes) for an atypically-formatted/minified
    package.json where the per-line key search finds nothing, since the
    dependency itself is already confirmed present via the parsed JSON."""
    needle = f'"{name}":'
    for i, line in enumerate(text.splitlines(), start=1):
        if needle in line:
            return i
    return 1


def scan_package_json(repo_root, ids):
    pkg_path = Path(repo_root) / "package.json"
    try:
        text = pkg_path.read_text()
    except OSError:
        return []
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, dict):
        return []

    deps = {}
    for key in _DEPENDENCY_KEYS:
        section = data.get(key)
        if isinstance(section, dict):
            deps.update(section)

    findings = []
    for name in sorted(deps):
        vendor, category = _classify(name)
        if vendor is None:
            continue
        findings.append({
            "id": ids.next("vendor"),
            "file": "package.json",
            "line": _line_of_dependency(text, name),
            "vendor": vendor,
            "package": name,
            "category": category,
        })
    return findings
