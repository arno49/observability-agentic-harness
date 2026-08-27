"""Docker-free unit tests for oah.validate.live_sandbox._parse_span_file --
real-Docker end-to-end coverage of the whole live-sandbox mechanism lives
in tests/test_live_sandbox.py; this file is scoped to the pure OTLP-JSON
parsing logic itself, including instrumentation_scope extraction
(docs/decisions/025, S11 signal provenance)."""
import json

from oah.validate.live_sandbox import _parse_span_file


def _otlp_doc(scope_name, span_name, attributes=None, trace_id="abc", span_id="1", parent_span_id=None):
    attrs = []
    for key, value in (attributes or {}).items():
        attrs.append({"key": key, "value": {"intValue": value} if isinstance(value, int) else {"stringValue": value}})
    span = {"name": span_name, "traceId": trace_id, "spanId": span_id, "attributes": attrs}
    if parent_span_id:
        span["parentSpanId"] = parent_span_id
    return {
        "resourceSpans": [{
            "resource": {"attributes": []},
            "scopeSpans": [{"scope": {"name": scope_name}, "spans": [span]}],
        }]
    }


def test_instrumentation_scope_extracted_from_otlp_json(tmp_path):
    path = tmp_path / "spans.jsonl"
    path.write_text(json.dumps(_otlp_doc("opentelemetry.instrumentation.flask", "GET /booking")) + "\n")
    spans = _parse_span_file(path)
    assert len(spans) == 1
    assert spans[0]["instrumentation_scope"] == "opentelemetry.instrumentation.flask"


def test_harness_instrumented_scope_extracted(tmp_path):
    path = tmp_path / "spans.jsonl"
    path.write_text(json.dumps(_otlp_doc("app", "handle_booking")) + "\n")
    spans = _parse_span_file(path)
    assert spans[0]["instrumentation_scope"] == "app"


def test_missing_scope_field_is_none_not_a_crash(tmp_path):
    doc = _otlp_doc("x", "y")
    del doc["resourceSpans"][0]["scopeSpans"][0]["scope"]
    path = tmp_path / "spans.jsonl"
    path.write_text(json.dumps(doc) + "\n")
    spans = _parse_span_file(path)
    assert spans[0]["instrumentation_scope"] is None


def test_multiple_scopes_in_one_file_each_kept_separately(tmp_path):
    doc1 = _otlp_doc("opentelemetry.instrumentation.flask", "GET /a", trace_id="t1", span_id="s1")
    doc2 = _otlp_doc("app", "manual_span", trace_id="t2", span_id="s2")
    path = tmp_path / "spans.jsonl"
    path.write_text(json.dumps(doc1) + "\n" + json.dumps(doc2) + "\n")
    spans = _parse_span_file(path)
    assert len(spans) == 2
    scopes = {s["name"]: s["instrumentation_scope"] for s in spans}
    assert scopes == {"GET /a": "opentelemetry.instrumentation.flask", "manual_span": "app"}
