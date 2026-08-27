"""Regression tests for oah.validate.event_assertion.summarize_provenance
(docs/decisions/027)."""
from oah.validate.event_assertion import summarize_provenance


def test_all_zero_when_nothing_observed():
    assert summarize_provenance([]) == {"auto_instrumentation": 0, "harness_instrumented": 0, "unknown": 0}


def test_counts_across_a_single_list():
    event_assertions = [
        {"dto_id": "d1", "status": "observed", "reason": None, "provenance": ["auto_instrumentation"]},
        {"dto_id": "d2", "status": "observed", "reason": None, "provenance": ["harness_instrumented"]},
        {"dto_id": "d3", "status": "not_observed", "reason": "x"},
    ]
    assert summarize_provenance(event_assertions) == {
        "auto_instrumentation": 1, "harness_instrumented": 1, "unknown": 0,
    }


def test_combines_multiple_lists_dynamic_and_live():
    dynamic = [{"dto_id": "d1", "status": "observed", "reason": None, "provenance": ["unknown"]}]
    live = [{"dto_id": "d1", "status": "observed", "reason": None, "provenance": ["harness_instrumented"]}]
    assert summarize_provenance(dynamic, live) == {
        "auto_instrumentation": 0, "harness_instrumented": 1, "unknown": 1,
    }


def test_a_dto_observed_via_both_provenances_counts_toward_both():
    event_assertions = [
        {"dto_id": "d1", "status": "observed", "reason": None,
         "provenance": ["auto_instrumentation", "harness_instrumented"]},
    ]
    assert summarize_provenance(event_assertions) == {
        "auto_instrumentation": 1, "harness_instrumented": 1, "unknown": 0,
    }
