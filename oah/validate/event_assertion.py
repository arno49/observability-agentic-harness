"""Real R2's own defining check, first half: given the real OTel spans
`oah/validate/pytest_runner.py`'s `run_pytest_suite(capture_spans=True)`
actually captured during a sandboxed test run, does each DTO's expected
telemetry event actually show up?

Deliberately a same-span co-occurrence requirement, not "these attribute
names appear somewhere across all captured spans combined": dynamic
capture has real span boundaries to use, unlike oah/validate/checker.py's
static text search (which has no such boundary and so, more leniently,
accepts the union of an entire file). Two attribute names that happened on
two different, unrelated spans were never actually observed *together* as
one real event, and asserting otherwise would be exactly the kind of
overclaim this whole phase exists to avoid.

Per-DTO failures never raise here -- observed/not_observed are both valid
*results*, matching oah.validate.checker's own posture: one DTO with no
real evidence shouldn't abort checking the rest.
"""


def _result(dto_id, status, reason=None):
    return {"dto_id": dto_id, "status": status, "reason": reason}


def check_dto_dynamic(dto, spans):
    """`spans` is a list of captured span dicts (each with `name` and
    `attributes`, per pytest_runner.parse_captured_spans's shape) from a
    single real sandboxed run -- not scoped to this one DTO; call sites
    are responsible for handing in the whole run's spans, since nothing
    in a real captured span identifies which DTO it belongs to."""
    dto_id = dto["id"]

    required_attribute_sets = [
        set(event.get("required_attributes", []))
        for event in dto.get("expected_events", [])
    ]
    required_attribute_sets = [s for s in required_attribute_sets if s]
    if not required_attribute_sets:
        return _result(dto_id, "not_observed", reason="this DTO's expected_events name no required_attributes to look for")

    never_observed = []
    for required in required_attribute_sets:
        if not any(required.issubset(span.get("attributes", {}).keys()) for span in spans):
            never_observed.append(sorted(required))

    if never_observed:
        return _result(
            dto_id, "not_observed",
            reason="no single captured span had all of: " + "; ".join(", ".join(attrs) for attrs in never_observed),
        )
    return _result(dto_id, "observed")
