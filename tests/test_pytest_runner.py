"""E6 R2 -- pytest_runner.py with a fake sandbox_runner injected, so
none of this needs real Docker. The real-Docker half of R2's coverage
lives in tests/test_sandbox_docker.py."""
from oah.validate.pytest_runner import detect_pytest_suite, run_pytest_suite


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
