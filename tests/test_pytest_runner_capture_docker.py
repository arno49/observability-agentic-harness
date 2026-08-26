"""E6 R2, part 2 -- real Docker containers, not mocked. Formalizes the
spike that grounded this phase's plan: code using exactly the pattern
skills/s10-instrumenter/SKILL.md now teaches
(`tracer = trace.get_tracer(__name__)` +
`with tracer.start_as_current_span(...) as span: span.set_attribute(...)`)
is actually captured by run_pytest_suite(capture_spans=True) end to end,
against a real container -- not assumed from the mocked unit tests in
test_pytest_runner.py alone.

Skips cleanly (not a failure) wherever no Docker daemon is reachable;
runs for real here and in CI (Docker preinstalled on ubuntu-latest,
already confirmed by the earlier sandbox-mechanism phase)."""
import pytest

from oah.validate.pytest_runner import run_pytest_suite
from oah.validate.sandbox import docker_available, run_in_sandbox

pytestmark = pytest.mark.skipif(
    not docker_available(),
    reason="docker is not available (not on PATH, or the daemon is unreachable)",
)

_APP_PY = '''
from opentelemetry import trace
tracer = trace.get_tracer(__name__)

def do_work():
    with tracer.start_as_current_span("llm.generate") as span:
        span.set_attribute("gen_ai.usage.input_tokens", 42)
        span.set_attribute("gen_ai.request.model", "claude-x")
        return "ok"
'''

_TEST_PY = '''
from app import do_work

def test_do_work():
    assert do_work() == "ok"
'''


def _make_flat_instrumented_target(tmp_path):
    """app.py sits at the repo root (not inside tests/) so pytest's own
    rootdir-relative import (with no package __init__.py anywhere) makes
    the test's plain `from app import do_work` -- matching the S10
    skill's own example shape -- resolve without any import-path
    ceremony."""
    repo = tmp_path / "target_repo"
    (repo / "tests").mkdir(parents=True)
    (repo / "app.py").write_text(_APP_PY)
    (repo / "tests" / "test_app.py").write_text(_TEST_PY)
    return repo


def test_real_span_is_captured_with_correct_name_and_attributes(tmp_path):
    repo = _make_flat_instrumented_target(tmp_path)

    result = run_pytest_suite(repo, sandbox_runner=run_in_sandbox, capture_spans=True, timeout_s=120)

    assert result["status"] == "passed", result
    assert len(result["spans"]) == 1
    span = result["spans"][0]
    assert span["name"] == "llm.generate"
    assert span["attributes"] == {
        "gen_ai.usage.input_tokens": 42,
        "gen_ai.request.model": "claude-x",
    }


def test_capture_spans_false_never_captures_even_though_the_code_emits(tmp_path):
    """The mechanism is opt-in -- a plain run_pytest_suite() call (as
    regression_gate.py already makes) must not pay the capture
    dependencies/instrumentation cost or return spans, even against a
    target that would emit them if asked."""
    repo = _make_flat_instrumented_target(tmp_path)

    result = run_pytest_suite(repo, sandbox_runner=run_in_sandbox, timeout_s=120)

    assert result["status"] == "passed", result
    assert result["spans"] == []


def test_uninstrumented_target_captures_no_spans(tmp_path):
    repo = tmp_path / "target_repo"
    (repo / "tests").mkdir(parents=True)
    (repo / "tests" / "test_it.py").write_text("def test_ok():\n    assert 1 + 1 == 2\n")

    result = run_pytest_suite(repo, sandbox_runner=run_in_sandbox, capture_spans=True, timeout_s=120)

    assert result["status"] == "passed", result
    assert result["spans"] == []
