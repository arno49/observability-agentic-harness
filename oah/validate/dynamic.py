"""Orchestrates `oah validate --dynamic`'s two dynamic checks --
oah/validate/regression_gate.py's deterministic regression gate and
oah/validate/event_assertion.py's per-DTO event-emission assertion --
over exactly one real sandboxed run, not two. Both checks want the same
evidence (a real `run_pytest_suite(capture_spans=True)` result), so this
module makes that one call and derives both from it -- spinning up the
sandbox twice per `oah validate --dynamic` invocation would be pure waste
and, worse, could observe two different runs of a possibly-flaky suite.
"""
from oah.validate.event_assertion import check_dto_dynamic
from oah.validate.pytest_runner import run_pytest_suite
from oah.validate.regression_gate import check_regression_gate
from oah.validate.sandbox import docker_available, run_in_sandbox


def _event_assertion_result(dto_id, status, reason=None):
    return {"dto_id": dto_id, "status": status, "reason": reason}


def run_dynamic_validation(target_repo, dtos, *, dynamic, sandbox_runner=run_in_sandbox, **sandbox_kwargs):
    """Returns {"regression_gate": {...}, "event_assertions": [...]}
    (one event_assertions entry per DTO, same order as `dtos`)."""
    if not dynamic:
        return {
            "regression_gate": {"status": "not_attempted", "reason": None},
            "event_assertions": [_event_assertion_result(dto["id"], "not_attempted") for dto in dtos],
        }

    if not docker_available():
        reason = ("docker is not available (not on PATH, or the daemon is unreachable) -- "
                  "--dynamic requires a real sandbox")
        return {
            "regression_gate": {"status": "skipped", "reason": reason},
            "event_assertions": [_event_assertion_result(dto["id"], "skipped", reason) for dto in dtos],
        }

    result = run_pytest_suite(target_repo, sandbox_runner=sandbox_runner, capture_spans=True, **sandbox_kwargs)
    regression_gate = check_regression_gate(target_repo, dynamic=True, _pytest_result=result)

    if result["status"] in ("no_tests_found", "install_failed"):
        # The suite never actually ran -- "skipped" (we never looked),
        # not "not_observed" (which would wrongly imply we looked and
        # found nothing).
        event_assertions = [
            _event_assertion_result(dto["id"], "skipped", regression_gate["reason"]) for dto in dtos
        ]
    else:
        event_assertions = [check_dto_dynamic(dto, result["spans"]) for dto in dtos]

    return {"regression_gate": regression_gate, "event_assertions": event_assertions}
