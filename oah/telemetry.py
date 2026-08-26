"""E10 — dogfooding (design principle #8: "every OAH run emits a trace
of its own stages in the very schema it installs for clients"). Wraps
each of OAH's own 5 real LLM/Agent-SDK call sites (S1 disambiguation, S4
lens design, S6 panel review, S8 DTO generation, S10 instrumentation) in
a real `opentelemetry-sdk` span, attributed per docs/event-model.md's
Generation entity: `gen_ai.*` where GenAI semantic conventions define
it, `oah.*` extensions for stage/lens context they don't.

Exported to a local JSONL file (`.oah/traces/oah.jsonl`, one line per
span) via a small custom SpanExporter -- no OTLP collector exists yet
(that's E6 R1-R3's job, not built), so this is the "always works, no
collector needed" floor, same posture as S10/S11's own scoped-down
first slices.

`setup_tracing()` is called once from cli.py's `main()`, not from
individual `cmd_*` functions -- every existing test that calls
`cmd_design`/`cmd_dtos`/etc. directly bypasses `main()`, so with no
tracer provider ever configured, `llm_span()` is a documented OTel
no-op: zero file writes, zero behavior change, no test updates needed
for that reason alone.
"""
import json
import os
from contextlib import contextmanager
from pathlib import Path

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExporter, SpanExportResult

TRACE_FILE = Path(".oah") / "traces" / "oah.jsonl"


class JsonlFileSpanExporter(SpanExporter):
    """Appends one JSON line per finished span to `path`. Real OTel
    export machinery (SimpleSpanProcessor calls this synchronously on
    every span end, so nothing is lost if the CLI process exits right
    after) -- just a file instead of a network collector."""

    def __init__(self, path=TRACE_FILE):
        self._path = Path(path)

    def export(self, spans):
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a") as f:
            for span in spans:
                f.write(json.dumps(self._span_to_dict(span)) + "\n")
        return SpanExportResult.SUCCESS

    def shutdown(self):
        pass

    @staticmethod
    def _span_to_dict(span):
        events = [
            {"name": e.name, "attributes": dict(e.attributes)}
            for e in span.events
        ]
        return {
            "name": span.name,
            "attributes": dict(span.attributes) if span.attributes else {},
            "status": span.status.status_code.name,
            "status_description": span.status.description,
            "start_time_unix_nano": span.start_time,
            "end_time_unix_nano": span.end_time,
            "events": events,
        }


def setup_tracing(path=TRACE_FILE):
    """Configures the global TracerProvider with a JsonlFileSpanExporter.
    Idempotent -- calling more than once (e.g. a future `main()` refactor)
    doesn't double-attach exporters or crash; the first call wins, same
    as OTel's own SDK behavior when a TracerProvider is already the
    global one. Not called anywhere except cli.py's main() -- see this
    module's docstring for why that matters for the test suite."""
    if isinstance(trace.get_tracer_provider(), TracerProvider):
        return
    provider = TracerProvider(resource=Resource.create({"service.name": "oah"}))
    provider.add_span_processor(SimpleSpanProcessor(JsonlFileSpanExporter(path)))
    trace.set_tracer_provider(provider)


@contextmanager
def llm_span(stage, name, model):
    """Wraps one real LLM/Agent-SDK call. `stage` is the pipeline stage
    id ("s1", "s4", "s6", "s8", "s10"); `name` is the skill/lens/change-type
    identifying which one. Exceptions raised inside the `with` block are
    recorded by OTel's own span context-manager machinery (record_exception
    + ERROR status) and re-raised unchanged -- callers' existing
    try/except -> raise *SpecificError* behavior is untouched.

    Calls trace.get_tracer() fresh here rather than caching it at module
    level: opentelemetry.trace.ProxyTracer resolves and permanently
    caches whichever TracerProvider is live the *first* time it's used
    (see its own source -- `if self._real_tracer: return self._real_tracer`,
    never re-checked). A module-level tracer would be safe in real usage
    (setup_tracing() runs once in main(), before any span), but broke
    this module's own test suite, where multiple tests each call
    setup_tracing() with their own fresh provider -- found by a real
    test failure (only the first test to touch a real provider ever got
    one), not assumed from reading the source."""
    tracer = trace.get_tracer("oah")
    with tracer.start_as_current_span(
        f"oah.{stage}.{name}",
        attributes={"oah.stage": stage, "oah.lens_or_skill": name, "gen_ai.request.model": model or ""},
    ) as span:
        yield span
