"""E6 R2 -- pytest_runner.py with a fake sandbox_runner injected, so
none of this needs real Docker. The real-Docker half of R2's coverage
lives in tests/test_sandbox_docker.py (regression gate) and
tests/test_pytest_runner_capture_docker.py (span capture)."""
from oah.validate.pytest_runner import detect_pytest_suite, parse_captured_spans, run_pytest_suite

# A realistic combined-stdout sample: pytest's own progress dot, a test's
# own print(), the summary line, and two ConsoleSpanExporter JSON dumps,
# all interleaved -- captured from a real Docker run during this phase's
# own spike, not hand-guessed.
_REALISTIC_CAPTURE_OUTPUT = """\
some test-level print output too
..
============================== 2 passed in 0.00s ==============================
{
    "name": "llm.generate.1",
    "context": {
        "trace_id": "0x95d164f498c05fb6d37e01011aa57e81",
        "span_id": "0xa32bb2a931f32c28",
        "trace_state": "[]"
    },
    "kind": "SpanKind.INTERNAL",
    "parent_id": null,
    "attributes": {
        "gen_ai.usage.input_tokens": 43
    },
    "events": [],
    "links": []
}
{
    "name": "llm.generate.2",
    "context": {
        "trace_id": "0x4cc6c9c0722e5ada89052fb62dfba96c",
        "span_id": "0xd8de73cdeba56ddf",
        "trace_state": "[]"
    },
    "kind": "SpanKind.INTERNAL",
    "parent_id": null,
    "attributes": {
        "gen_ai.usage.input_tokens": 44
    },
    "events": [],
    "links": []
}
"""


def _fake_sandbox(exit_code, stdout="", stderr=""):
    def runner(target_repo, script, **kwargs):
        return {"exit_code": exit_code, "stdout": stdout, "stderr": stderr, "timed_out": False}
    return runner


def test_detect_pytest_suite_finds_a_tests_directory(tmp_path):
    (tmp_path / "tests").mkdir()
    assert detect_pytest_suite(tmp_path) is True


def test_detect_pytest_suite_finds_pytest_ini(tmp_path):
    (tmp_path / "pytest.ini").write_text("[pytest]\n")
    assert detect_pytest_suite(tmp_path) is True


def test_detect_pytest_suite_finds_pyproject_section(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[tool.pytest.ini_options]\naddopts = '-q'\n")
    assert detect_pytest_suite(tmp_path) is True


def test_detect_pytest_suite_ignores_pyproject_without_pytest_section(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[tool.black]\nline-length = 100\n")
    assert detect_pytest_suite(tmp_path) is False


def test_detect_pytest_suite_finds_setup_cfg_section(tmp_path):
    (tmp_path / "setup.cfg").write_text("[tool:pytest]\ntestpaths = tests\n")
    assert detect_pytest_suite(tmp_path) is True


def test_detect_pytest_suite_false_when_nothing_present(tmp_path):
    assert detect_pytest_suite(tmp_path) is False


def test_no_tests_found_never_calls_the_sandbox_runner(tmp_path):
    calls = []

    def runner(target_repo, script, **kwargs):
        calls.append(1)
        return {"exit_code": 0, "stdout": "", "stderr": "", "timed_out": False}

    result = run_pytest_suite(tmp_path, sandbox_runner=runner)
    assert result["status"] == "no_tests_found"
    assert calls == []


def test_passed_status_from_a_real_exit_code_zero_and_summary_line(tmp_path):
    (tmp_path / "tests").mkdir()
    stdout = "collected 3 items\n===== 3 passed in 0.12s ====="
    result = run_pytest_suite(tmp_path, sandbox_runner=_fake_sandbox(0, stdout=stdout))
    assert result["status"] == "passed"
    assert result["summary"] == {"failed": 0, "passed": 3}


def test_failed_status_when_tests_ran_but_some_failed(tmp_path):
    (tmp_path / "tests").mkdir()
    stdout = "collected 3 items\n===== 1 failed, 2 passed in 0.20s ====="
    result = run_pytest_suite(tmp_path, sandbox_runner=_fake_sandbox(1, stdout=stdout))
    assert result["status"] == "failed"
    assert result["summary"] == {"failed": 1, "passed": 2}


def test_install_failed_when_pytest_summary_line_never_appears(tmp_path):
    (tmp_path / "tests").mkdir()
    stderr = "--- editable install failed, falling back ---\nERROR: no matching distribution\n"
    result = run_pytest_suite(tmp_path, sandbox_runner=_fake_sandbox(1, stderr=stderr))
    assert result["status"] == "install_failed"
    assert result["summary"] is None


def test_install_failed_when_sandbox_itself_never_ran_the_script(tmp_path):
    """exit_code is None -- Docker unavailable / build failed, distinct
    from a real non-zero exit code from a script that did run."""
    (tmp_path / "tests").mkdir()
    result = run_pytest_suite(tmp_path, sandbox_runner=_fake_sandbox(None, stderr="docker build failed"))
    assert result["status"] == "install_failed"
    assert result["exit_code"] is None


def test_fallback_ladder_still_reports_passed_after_editable_install_failure(tmp_path):
    """The fallback path (no editable install, plain requirements.txt +
    pytest) succeeding is indistinguishable in outcome from the
    editable path succeeding -- both are real 'passed' results."""
    (tmp_path / "tests").mkdir()
    stdout = "--- editable install failed, falling back ---\ncollected 2 items\n===== 2 passed in 0.09s ====="
    result = run_pytest_suite(tmp_path, sandbox_runner=_fake_sandbox(0, stdout=stdout))
    assert result["status"] == "passed"
    assert result["summary"] == {"failed": 0, "passed": 2}


def test_install_ladder_runs_as_setup_script_not_the_run_time_script(tmp_path):
    """The install-fallback ladder must go in via setup_script (build
    time, has network) -- never as part of the run-time script, which
    the sandbox runs network-isolated."""
    (tmp_path / "tests").mkdir()
    seen = {}

    def runner(target_repo, script, setup_script=None, **kwargs):
        seen["script"] = script
        seen["setup_script"] = setup_script
        return {"exit_code": 0, "stdout": "===== 1 passed in 0.01s =====", "stderr": "", "timed_out": False}

    run_pytest_suite(tmp_path, sandbox_runner=runner)
    assert "pytest" in seen["script"]
    assert "pip install" in seen["setup_script"]
    assert seen["script"] != seen["setup_script"]


def test_sandbox_kwargs_are_forwarded_to_the_runner(tmp_path):
    (tmp_path / "tests").mkdir()
    seen_kwargs = {}

    def runner(target_repo, script, **kwargs):
        seen_kwargs.update(kwargs)
        return {"exit_code": 0, "stdout": "===== 1 passed in 0.01s =====", "stderr": "", "timed_out": False}

    run_pytest_suite(tmp_path, sandbox_runner=runner, timeout_s=60, memory="256m")
    assert seen_kwargs["timeout_s"] == 60
    assert seen_kwargs["memory"] == "256m"


def test_parse_captured_spans_extracts_both_spans_from_realistic_output():
    spans = parse_captured_spans(_REALISTIC_CAPTURE_OUTPUT)
    assert len(spans) == 2
    assert spans[0]["name"] == "llm.generate.1"
    assert spans[0]["attributes"] == {"gen_ai.usage.input_tokens": 43}
    assert spans[1]["name"] == "llm.generate.2"
    assert spans[1]["attributes"] == {"gen_ai.usage.input_tokens": 44}


def test_parse_captured_spans_ignores_unrelated_json_without_span_shape():
    text = '{"just": "some unrelated json the target printed"}\nno spans here at all\n'
    assert parse_captured_spans(text) == []


def test_parse_captured_spans_empty_on_plain_text():
    assert parse_captured_spans("no json here, just plain pytest text\n") == []


def test_run_pytest_suite_without_capture_spans_returns_empty_spans_list(tmp_path):
    (tmp_path / "tests").mkdir()
    result = run_pytest_suite(tmp_path, sandbox_runner=_fake_sandbox(0, stdout="===== 1 passed in 0.01s ====="))
    assert result["spans"] == []


def test_run_pytest_suite_with_capture_spans_true_parses_real_spans(tmp_path):
    (tmp_path / "tests").mkdir()
    result = run_pytest_suite(
        tmp_path, sandbox_runner=_fake_sandbox(0, stdout=_REALISTIC_CAPTURE_OUTPUT),
        capture_spans=True,
    )
    assert result["status"] == "passed"
    assert len(result["spans"]) == 2
    assert result["spans"][0]["name"] == "llm.generate.1"


def test_capture_spans_true_installs_the_otel_capture_dependencies(tmp_path):
    (tmp_path / "tests").mkdir()
    seen = {}

    def runner(target_repo, script, setup_script=None, **kwargs):
        seen["script"] = script
        seen["setup_script"] = setup_script
        return {"exit_code": 0, "stdout": "===== 1 passed in 0.01s =====", "stderr": "", "timed_out": False}

    run_pytest_suite(tmp_path, sandbox_runner=runner, capture_spans=True)
    assert "opentelemetry-distro" in seen["setup_script"]
    assert "opentelemetry-instrument" in seen["script"]
    assert "-s" in seen["script"]


def test_capture_spans_false_never_installs_otel_capture_dependencies(tmp_path):
    (tmp_path / "tests").mkdir()
    seen = {}

    def runner(target_repo, script, setup_script=None, **kwargs):
        seen["script"] = script
        seen["setup_script"] = setup_script
        return {"exit_code": 0, "stdout": "===== 1 passed in 0.01s =====", "stderr": "", "timed_out": False}

    run_pytest_suite(tmp_path, sandbox_runner=runner)
    assert "opentelemetry-distro" not in seen["setup_script"]
    assert "opentelemetry-instrument" not in seen["script"]


def test_no_tests_found_never_populates_spans_even_with_capture_requested(tmp_path):
    result = run_pytest_suite(tmp_path, sandbox_runner=_fake_sandbox(0), capture_spans=True)
    assert result["status"] == "no_tests_found"
    assert result["spans"] == []


def test_install_failed_never_populates_spans_even_with_capture_requested(tmp_path):
    (tmp_path / "tests").mkdir()
    result = run_pytest_suite(tmp_path, sandbox_runner=_fake_sandbox(1, stderr="no summary line"),
                               capture_spans=True)
    assert result["status"] == "install_failed"
    assert result["spans"] == []
