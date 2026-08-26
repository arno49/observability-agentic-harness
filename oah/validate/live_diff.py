"""Part of wiring E6 R1's execution mechanism (`live_sandbox.py`) into
`oah validate --live`: given the real spans a live run actually captured,
does every attribute name they carry appear in `event_schema.json`'s own
declared attribute list?

This is *not* `docs/validation.md`'s full deterministic-layer event-capture
check -- that also calls for semantic invariant checks (orphan generations,
missing release identifiers or ownership attributes), which
`event_schema.json`'s own schema has no structured field to express yet.
Only unknown-attribute-*name* detection is built here; the rest is named as
deferred in ROADMAP.md, not silently implied by this module's existence.

Per-DTO event-emission assertion against these same captured spans reuses
`oah/validate/event_assertion.py`'s existing `check_dto_dynamic` directly
(same {name, attributes} span shape `live_sandbox.run_live_sandbox`
already returns) -- not duplicated here.
"""


def check_unknown_attributes(spans, event_schema):
    """`event_schema` is an event_schema.json document (or None, when
    --event-schema wasn't given -- returns `not_attempted`, never a guess
    at whether captured attributes are "known"). Returns
    {"status": "not_attempted"|"clean"|"unknown_attributes_found",
    "unknown": [...], "reason": str|None}."""
    if event_schema is None:
        return {"status": "not_attempted", "unknown": [], "reason": None}

    known_names = {attr["name"] for attr in event_schema.get("attributes", [])}
    captured_names = {name for span in spans for name in span.get("attributes", {}).keys()}
    unknown = sorted(captured_names - known_names)

    if unknown:
        return {
            "status": "unknown_attributes_found", "unknown": unknown,
            "reason": f"{len(unknown)} captured attribute name(s) are not declared in event_schema.json: {', '.join(unknown)}",
        }
    return {"status": "clean", "unknown": [], "reason": None}
