"""S11, R4 (static-only) — docs/validation.md's ladder. "Schema
conformance of code-level emission points only": for each DTO S10's
`fix` mode actually applied, does its `change.file` contain every
`expected_events[].required_attributes` string, at or after the line
`change.anchor` appears on? A code-level presence claim only -- this
never runs the target, never claims the telemetry actually fires or is
well-formed at runtime (that needs R1's real running product + OTLP
collector, neither of which exist yet; see this module's callers).

Reads the target file's *current* content, not the content at the DTO's
own `commit_sha` from the instrument report -- if the file changed since
S10 applied it, that's a staleness question `oah check-drift` is meant
to eventually answer, not this module's job.

Per-DTO failures never raise here -- present/absent/skipped are all
valid *results*, matching oah.instrument.executor's posture: one bad DTO
in a batch shouldn't abort the rest.
"""
from pathlib import Path


def _result(dto_id, status, missing_attributes=None, reason=None):
    return {"dto_id": dto_id, "status": status, "missing_attributes": missing_attributes, "reason": reason}


def check_dto_static(dto, instrument_result, target_repo):
    """`instrument_result` is the matching entry from instrument_report.json's
    results[] (or None if this DTO isn't in it at all)."""
    dto_id = dto["id"]

    if instrument_result is None:
        return _result(dto_id, "skipped", reason="not present in the given instrument report")
    if instrument_result["status"] != "applied":
        return _result(
            dto_id, "skipped",
            reason=f"instrument report status is {instrument_result['status']!r}, not 'applied' -- nothing to check",
        )

    change = dto["change"]
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

    searchable = "\n".join(lines[anchor_line:])
    required_attributes = [
        attr
        for event in dto.get("expected_events", [])
        for attr in event.get("required_attributes", [])
    ]
    missing = [attr for attr in required_attributes if attr not in searchable]
    if missing:
        return _result(dto_id, "absent", missing_attributes=missing)
    return _result(dto_id, "present")
