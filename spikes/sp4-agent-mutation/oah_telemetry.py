"""Stub telemetry helper for the SP4 instrumentation-mutation demo.

Not real OTel wiring -- OAH's event schema isn't designed yet (pre-M0). This
stands in for "the DTO's target call" so the demo can check whether an
applied DTO's edit is syntactically valid and structurally correct, without
needing a real collector.
"""
def emit(event_name, **fields):
    print(f"[oah_telemetry] {event_name} {fields}")
