"""oah/validate/event_assertion.py -- pure function, no sandbox, no I/O.
Real-Docker end-to-end coverage (skill-taught pattern -> real capture ->
this checker) lives in tests/test_cli_validate_dynamic.py."""
from oah.validate.event_assertion import check_dto_dynamic

DTO = {
    "id": "dto-0001",
    "expected_events": [{"event_type": "generation", "required_attributes": ["gen_ai.usage.input_tokens"]}],
}


def test_observed_when_a_single_span_has_all_required_attributes():
    spans = [{"name": "llm.generate", "attributes": {"gen_ai.usage.input_tokens": 42}}]
    result = check_dto_dynamic(DTO, spans)
    assert result == {"dto_id": "dto-0001", "status": "observed", "reason": None, "provenance": ["unknown"]}


def test_not_observed_when_no_span_was_captured_at_all():
    result = check_dto_dynamic(DTO, [])
    assert result["status"] == "not_observed"
    assert "gen_ai.usage.input_tokens" in result["reason"]


def test_not_observed_when_the_attribute_is_on_a_different_unrelated_span():
    spans = [{"name": "unrelated.span", "attributes": {"some.other.attr": 1}}]
    result = check_dto_dynamic(DTO, spans)
    assert result["status"] == "not_observed"


def test_not_observed_when_required_attributes_are_split_across_two_spans():
    """The same-span co-occurrence requirement is real, not accidental:
    two spans each having HALF the required set must not be conflated
    into "it was observed"."""
    dto = {
        "id": "dto-0002",
        "expected_events": [{"event_type": "generation",
                              "required_attributes": ["gen_ai.usage.input_tokens", "gen_ai.request.model"]}],
    }
    spans = [
        {"name": "span.a", "attributes": {"gen_ai.usage.input_tokens": 42}},
        {"name": "span.b", "attributes": {"gen_ai.request.model": "claude-x"}},
    ]
    result = check_dto_dynamic(dto, spans)
    assert result["status"] == "not_observed"


def test_observed_when_one_span_has_extra_attributes_beyond_what_is_required():
    spans = [{"name": "llm.generate", "attributes": {
        "gen_ai.usage.input_tokens": 42, "gen_ai.request.model": "claude-x", "extra.unrelated": True,
    }}]
    result = check_dto_dynamic(DTO, spans)
    assert result["status"] == "observed"


def test_dto_with_multiple_expected_events_needs_every_entry_satisfied():
    dto = {
        "id": "dto-0003",
        "expected_events": [
            {"event_type": "generation", "required_attributes": ["attr.a"]},
            {"event_type": "span", "required_attributes": ["attr.b"]},
        ],
    }
    both_satisfied = [
        {"name": "s1", "attributes": {"attr.a": 1}},
        {"name": "s2", "attributes": {"attr.b": 2}},
    ]
    assert check_dto_dynamic(dto, both_satisfied)["status"] == "observed"

    only_one_satisfied = [{"name": "s1", "attributes": {"attr.a": 1}}]
    result = check_dto_dynamic(dto, only_one_satisfied)
    assert result["status"] == "not_observed"
    assert "attr.b" in result["reason"]


def test_dto_with_no_required_attributes_at_all_is_not_observed_not_a_crash():
    dto = {"id": "dto-0004", "expected_events": [{"event_type": "trace"}]}
    result = check_dto_dynamic(dto, [{"name": "s1", "attributes": {}}])
    assert result["status"] == "not_observed"


# --- Signal provenance (docs/decisions/025) -------------------------------

def test_provenance_classified_from_python_auto_instrumentation_scope():
    """Verified against a real live Python SDK capture (not assumed):
    opentelemetry-instrumentation-flask's own spans carry
    instrumentation_scope.name == "opentelemetry.instrumentation.flask"."""
    spans = [{"name": "llm.generate", "attributes": {"gen_ai.usage.input_tokens": 42},
              "instrumentation_scope": "opentelemetry.instrumentation.flask"}]
    result = check_dto_dynamic(DTO, spans)
    assert result["provenance"] == ["auto_instrumentation"]


def test_provenance_classified_from_js_auto_instrumentation_scope():
    spans = [{"name": "llm.generate", "attributes": {"gen_ai.usage.input_tokens": 42},
              "instrumentation_scope": "@opentelemetry/instrumentation-http"}]
    result = check_dto_dynamic(DTO, spans)
    assert result["provenance"] == ["auto_instrumentation"]


def test_provenance_classified_as_harness_instrumented_for_target_module_scope():
    """Verified against a real live Python SDK capture: a manual
    `tracer = trace.get_tracer(__name__)` span (skills/s10-instrumenter/SKILL.md's
    own taught pattern) carries the CALLING module's own name as its
    instrumentation_scope, never an opentelemetry.instrumentation.* prefix."""
    spans = [{"name": "llm.generate", "attributes": {"gen_ai.usage.input_tokens": 42},
              "instrumentation_scope": "app.chat"}]
    result = check_dto_dynamic(DTO, spans)
    assert result["provenance"] == ["harness_instrumented"]


def test_provenance_unknown_when_instrumentation_scope_is_absent():
    """--dynamic's own ConsoleSpanExporter-based capture never carries this
    field at all -- a real, structural limit of that mechanism, not a bug."""
    spans = [{"name": "llm.generate", "attributes": {"gen_ai.usage.input_tokens": 42}}]
    result = check_dto_dynamic(DTO, spans)
    assert result["provenance"] == ["unknown"]


def test_provenance_deduplicated_and_sorted_across_multiple_matching_spans():
    spans = [
        {"name": "s1", "attributes": {"gen_ai.usage.input_tokens": 42},
         "instrumentation_scope": "opentelemetry.instrumentation.flask"},
        {"name": "s2", "attributes": {"gen_ai.usage.input_tokens": 43},
         "instrumentation_scope": "opentelemetry.instrumentation.requests"},
    ]
    result = check_dto_dynamic(DTO, spans)
    # Both spans classify as auto_instrumentation -- deduplicated to one entry.
    assert result["provenance"] == ["auto_instrumentation"]


def test_provenance_absent_entirely_when_not_observed():
    result = check_dto_dynamic(DTO, [])
    assert "provenance" not in result
