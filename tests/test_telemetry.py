"""Regression tests for oah.telemetry -- real opentelemetry-sdk spans,
nothing mocked (no LLM/agent call involved at this layer at all)."""
import json

import pytest
from opentelemetry import trace
from opentelemetry.util._once import Once

from oah.telemetry import llm_span, setup_tracing


def _reset_global_tracer_provider():
    """set_tracer_provider() is guarded by a private, one-shot `Once`
    object (opentelemetry.trace._TRACER_PROVIDER_SET_ONCE) *separate*
    from the `_TRACER_PROVIDER` value itself -- resetting only the
    latter still leaves the former permanently "already done" and every
    later set_tracer_provider() call silently no-ops with a logged
    warning instead of taking effect. Found by a real test failure
    (test_setup_tracing_is_idempotent and others silently kept the
    *first* test's TracerProvider/exporter across the whole file), not
    assumed from reading the source alone. Both must be reset for tests
    to be independent."""
    trace._TRACER_PROVIDER = None
    trace._TRACER_PROVIDER_SET_ONCE = Once()


@pytest.fixture(autouse=True)
def _isolated_tracer_provider():
    """Every test in this file calls setup_tracing() itself and expects
    it to actually take effect -- without this, only the first test in
    the file would ever get a real TracerProvider; the rest would find
    set_tracer_provider() silently blocked by the previous test's Once
    guard and write no spans at all."""
    _reset_global_tracer_provider()
    yield
    _reset_global_tracer_provider()


def test_no_tracer_provider_configured_is_a_true_noop(tmp_path):
    """The state every existing cmd_* test runs in (main() never called):
    llm_span must be a real no-op -- no file, no exception, no behavior
    change to the wrapped code."""
    trace_file = tmp_path / "oah.jsonl"
    calls = []
    with llm_span("s4", "generation-capture", "claude-sonnet-5"):
        calls.append("ran")
    assert calls == ["ran"]
    assert not trace_file.exists()


def test_setup_tracing_writes_a_real_span_to_the_jsonl_file(tmp_path):
    trace_file = tmp_path / "oah.jsonl"
    setup_tracing(path=trace_file)

    with llm_span("s4", "generation-capture", "claude-sonnet-5"):
        pass

    lines = trace_file.read_text().strip().splitlines()
    assert len(lines) == 1
    span = json.loads(lines[0])
    assert span["name"] == "oah.s4.generation-capture"
    assert span["attributes"]["oah.stage"] == "s4"
    assert span["attributes"]["oah.lens_or_skill"] == "generation-capture"
    assert span["attributes"]["gen_ai.request.model"] == "claude-sonnet-5"
    assert span["status"] == "UNSET"  # no exception -> OTel leaves status unset, not "OK", unless explicitly set


def test_llm_span_records_exception_and_still_raises_it(tmp_path):
    trace_file = tmp_path / "oah.jsonl"
    setup_tracing(path=trace_file)

    with pytest.raises(RuntimeError, match="boom"):
        with llm_span("s10", "wrap_call", "claude-sonnet-5"):
            raise RuntimeError("boom")

    span = json.loads(trace_file.read_text().strip())
    assert span["status"] == "ERROR"
    assert span["events"][0]["name"] == "exception"
    assert span["events"][0]["attributes"]["exception.type"] == "RuntimeError"
    assert span["events"][0]["attributes"]["exception.message"] == "boom"


def test_setup_tracing_is_idempotent(tmp_path):
    """Calling setup_tracing() twice (e.g. a future main() refactor)
    must not double-attach exporters -- one span in, one line out,
    not two."""
    trace_file = tmp_path / "oah.jsonl"
    setup_tracing(path=trace_file)
    setup_tracing(path=tmp_path / "a-different-file-that-should-be-ignored.jsonl")

    with llm_span("s4", "generation-capture", "claude-sonnet-5"):
        pass

    lines = trace_file.read_text().strip().splitlines()
    assert len(lines) == 1


def test_jsonl_exporter_appends_across_multiple_spans(tmp_path):
    trace_file = tmp_path / "oah.jsonl"
    setup_tracing(path=trace_file)

    with llm_span("s4", "generation-capture", "claude-sonnet-5"):
        pass
    with llm_span("s6", "cost-skeptic", "claude-sonnet-5"):
        pass

    lines = trace_file.read_text().strip().splitlines()
    assert len(lines) == 2
    names = [json.loads(line)["name"] for line in lines]
    assert names == ["oah.s4.generation-capture", "oah.s6.cost-skeptic"]
