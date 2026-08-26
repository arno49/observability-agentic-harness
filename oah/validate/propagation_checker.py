"""Real R2's second defining check: for `propagate_context` DTOs, a
static check of trace-ID propagation across the async/queue boundary
(`docs/validation.md`'s own wording for R2's second half, alongside real
R2's other half in oah/validate/event_assertion.py).

`change.description` is free text (implementation_dto.schema.json has no
structured boundary-type field), and `skills/s10-instrumenter/SKILL.md`
teaches exactly three boundary shapes with different required code per
shape (`asyncio.create_task` needs none -- contextvars already propagate
automatically; a thread-pool submit needs an explicit
context.get_current()/context.attach() pair; a Celery/queue dispatch
crossing a real wire needs opentelemetry.propagate.inject()/extract()).
This module classifies which shape applies by keyword search over
`change.description`, then looks for that shape's own evidence markers in
the patched file -- a genuine heuristic, not real control-flow analysis.
A description this search can't classify is honestly `skipped` ("needs
manual review"), never guessed at.

Per-DTO failures never raise here -- not_applicable/skipped/present/absent
are all valid *results*, matching oah.validate.checker's own posture.
"""
from pathlib import Path

_THREAD_MARKERS = ("context.get_current(", "context.attach(", "otel_context.get_current(", "otel_context.attach(")
_QUEUE_MARKERS = ("propagate.inject(", "propagate.extract(", "tracecontexttextmappropagator")


def _result(dto_id, status, reason=None):
    return {"dto_id": dto_id, "status": status, "reason": reason}


def _classify_boundary(description):
    description = (description or "").lower()
    if "create_task" in description or "asyncio" in description:
        return "asyncio"
    if "thread" in description:
        return "thread"
    if "celery" in description or "queue" in description or "dispatch" in description:
        return "queue"
    return None


def check_dto_propagation(dto, instrument_result, target_repo):
    """`instrument_result` is the matching entry from instrument_report.json's
    results[] (or None if this DTO isn't in it at all) -- same contract as
    oah.validate.checker.check_dto_static."""
    dto_id = dto["id"]
    change = dto["change"]

    if change["type"] != "propagate_context":
        return _result(dto_id, "not_applicable", reason="this checker only evaluates propagate_context DTOs")

    if instrument_result is None:
        return _result(dto_id, "skipped", reason="not present in the given instrument report")
    if instrument_result["status"] != "applied":
        return _result(
            dto_id, "skipped",
            reason=f"instrument report status is {instrument_result['status']!r}, not 'applied' -- nothing to check",
        )

    target_file = Path(target_repo) / change["file"]
    if not target_file.is_file():
        return _result(dto_id, "skipped", reason=f"{change['file']} does not exist in the target repo")

    lines = target_file.read_text().splitlines()
    anchor = change.get("anchor")
    anchor_line = next((i for i, line in enumerate(lines) if anchor and anchor in line), None)
    if anchor_line is None:
        return _result(
            dto_id, "skipped",
            reason=f"anchor {anchor!r} no longer found in {change['file']} -- can't tell where to check "
                   f"(the file may have changed since S10 applied this DTO; see oah check-drift)",
        )
    searchable = "\n".join(lines[anchor_line:]).lower()

    category = _classify_boundary(change.get("description"))
    if category is None:
        return _result(
            dto_id, "skipped",
            reason="could not classify the propagation boundary from change.description -- needs manual review",
        )

    if category == "asyncio":
        # skills/s10-instrumenter/SKILL.md: asyncio.create_task already
        # propagates the current span via Python's own contextvars, no
        # explicit code needed -- the anchor itself being intact (already
        # confirmed above) is the whole check.
        return _result(dto_id, "present")

    markers = _THREAD_MARKERS if category == "thread" else _QUEUE_MARKERS
    if any(marker in searchable for marker in markers):
        return _result(dto_id, "present")
    return _result(
        dto_id, "absent",
        reason=f"classified as a {category!r} boundary but none of {markers!r} were found after the anchor",
    )
