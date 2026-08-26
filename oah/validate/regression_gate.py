"""Wires E6 R2's sandbox mechanism (sandbox.py/pytest_runner.py) into
`oah validate` as `docs/validation.md`'s own "Deterministic layer (runs
first, always)" step 1: "Target's own test suite -- instrumentation
must not break the product (regression gate; hard fail ->
validation_failed)." This is NOT R2 itself -- R2's own defining check
(per-DTO event-emission assertion, static trace-ID-propagation check)
still needs skills/s10-instrumenter/SKILL.md to name a concrete
telemetry API before it can be built honestly; see ROADMAP.md's E6
entry. This module only reuses R2's already-proven execution mechanism
for the regression gate the ladder itself treats as independent of rung.

Never fabricates a pass/fail it doesn't have: Docker unavailable, no
tests found, or a broken install ladder are all `skipped` -- genuinely
inconclusive, not evidence the target is broken -- and never affect the
overall verdict. Only a real `failed` (tests actually ran and some
actually failed) does.
"""
from oah.validate.pytest_runner import run_pytest_suite
from oah.validate.sandbox import docker_available, run_in_sandbox


def _gate_result(status, reason=None):
    return {"status": status, "reason": reason}


def check_regression_gate(target_repo, *, dynamic, sandbox_runner=run_in_sandbox, **sandbox_kwargs):
    if not dynamic:
        return _gate_result("not_attempted")

    if not docker_available():
        return _gate_result("skipped", reason="docker is not available (not on PATH, or the daemon "
                                               "is unreachable) -- --dynamic requires a real sandbox")

    result = run_pytest_suite(target_repo, sandbox_runner=sandbox_runner, **sandbox_kwargs)

    if result["status"] == "no_tests_found":
        return _gate_result("skipped", reason="no pytest suite found in the target repo")
    if result["status"] == "install_failed":
        return _gate_result("skipped", reason="could not install the target's dependencies in the "
                                               "sandbox -- inconclusive, not evidence the target is broken")
    if result["status"] == "passed":
        return _gate_result("passed")

    summary = result.get("summary")
    if summary:
        reason = f"target's own test suite failed after instrumentation: {summary['failed']} failed, {summary['passed']} passed"
    else:
        reason = "target's own test suite failed after instrumentation"
    return _gate_result("failed", reason=reason)
