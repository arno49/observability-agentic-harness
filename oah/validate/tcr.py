"""R1's own primary metric (`docs/architecture.md`: "Primary metric. TCR --
share of exercised user requests reconstructable end-to-end with no
missing spans. Reported per run and per workflow."). Not the "behavioral
rates" metric (fallback/clarification/escalation/restricted-attempt)
`docs/validation.md`'s Metrics section separately names -- that's a
materially different, still domain-specific rate this module doesn't
attempt.

A trace (spans sharing one `trace_id`, from
`oah/validate/live_sandbox.py`'s `run_live_sandbox`) is complete when
every one of its spans' `parent_span_id` -- when it has one -- points at
a `span_id` that was also captured within that *same* trace. A dangling
parent reference (the referenced span was never captured -- dropped,
lost, or never sent) is exactly what "reconstructable end-to-end with no
missing spans" excludes.
"""


def compute_tcr(spans):
    """Returns {"traces_total", "traces_complete", "tcr", "incomplete_trace_ids"}.
    `tcr` is `traces_complete / traces_total`, or None when no traces were
    captured at all -- never a fabricated 0.0 or 1.0 for "nothing to
    measure"."""
    traces = {}
    for span in spans:
        traces.setdefault(span["trace_id"], []).append(span)

    incomplete_trace_ids = []
    for trace_id, trace_spans in traces.items():
        span_ids = {s["span_id"] for s in trace_spans}
        if any(s["parent_span_id"] is not None and s["parent_span_id"] not in span_ids for s in trace_spans):
            incomplete_trace_ids.append(trace_id)

    traces_total = len(traces)
    traces_complete = traces_total - len(incomplete_trace_ids)
    return {
        "traces_total": traces_total,
        "traces_complete": traces_complete,
        "tcr": (traces_complete / traces_total) if traces_total else None,
        "incomplete_trace_ids": sorted(incomplete_trace_ids),
    }
