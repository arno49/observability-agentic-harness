"""oah/validate/tcr.py -- pure function, no I/O."""
from oah.validate.tcr import compute_tcr


def _span(name, trace_id, span_id, parent_span_id=None):
    return {"name": name, "attributes": {}, "trace_id": trace_id, "span_id": span_id, "parent_span_id": parent_span_id}


def test_no_spans_captured_gives_none_not_a_fabricated_number():
    result = compute_tcr([])
    assert result == {"traces_total": 0, "traces_complete": 0, "tcr": None, "incomplete_trace_ids": []}


def test_single_root_only_span_is_a_complete_trace():
    spans = [_span("s", "t1", "a")]
    result = compute_tcr(spans)
    assert result == {"traces_total": 1, "traces_complete": 1, "tcr": 1.0, "incomplete_trace_ids": []}


def test_real_parent_child_pair_both_captured_is_complete():
    spans = [_span("outer", "t1", "a"), _span("inner", "t1", "b", parent_span_id="a")]
    result = compute_tcr(spans)
    assert result == {"traces_total": 1, "traces_complete": 1, "tcr": 1.0, "incomplete_trace_ids": []}


def test_child_with_a_dangling_parent_reference_is_incomplete():
    """The parent span_id 'ghost' was never captured -- a real gap in the
    causal chain, exactly what TCR is meant to catch."""
    spans = [_span("inner", "t1", "b", parent_span_id="ghost")]
    result = compute_tcr(spans)
    assert result == {"traces_total": 1, "traces_complete": 0, "tcr": 0.0, "incomplete_trace_ids": ["t1"]}


def test_two_traces_one_complete_one_not_gives_exact_fraction():
    spans = [
        _span("s1", "t1", "a"),                              # t1: complete
        _span("s2", "t2", "b", parent_span_id="missing"),     # t2: incomplete
    ]
    result = compute_tcr(spans)
    assert result["traces_total"] == 2
    assert result["traces_complete"] == 1
    assert result["tcr"] == 0.5
    assert result["incomplete_trace_ids"] == ["t2"]


def test_parent_span_id_must_match_within_the_same_trace_not_globally():
    """A span_id that exists in a DIFFERENT trace must not satisfy a
    dangling parent reference -- proves grouping is per-trace, not a
    global span_id pool."""
    spans = [
        _span("other_trace_root", "t1", "shared_id"),
        _span("this_trace_child", "t2", "b", parent_span_id="shared_id"),
    ]
    result = compute_tcr(spans)
    assert result["traces_total"] == 2
    assert result["traces_complete"] == 1  # t1 alone is complete
    assert result["incomplete_trace_ids"] == ["t2"]


def test_multiple_complete_traces_all_count():
    spans = [_span("s1", "t1", "a"), _span("s2", "t2", "b"), _span("s3", "t3", "c")]
    result = compute_tcr(spans)
    assert result == {"traces_total": 3, "traces_complete": 3, "tcr": 1.0, "incomplete_trace_ids": []}
