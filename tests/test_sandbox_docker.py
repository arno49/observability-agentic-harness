"""E6 R2 -- real Docker containers, not mocked. This is the actual
proof that sandbox.py's isolation/cleanup/timeout claims hold against
a live daemon, not just that the mocked call sites in
test_pytest_runner.py are internally consistent.

Skips cleanly (not a failure) in any environment without a reachable
Docker daemon -- this environment has one, so it runs for real here.
"""
import subprocess
import textwrap

import pytest

from oah.validate.pytest_runner import run_pytest_suite
from oah.validate.sandbox import docker_available, run_in_sandbox

pytestmark = pytest.mark.skipif(
    not docker_available(),
    reason="docker is not available (not on PATH, or the daemon is unreachable)",
)


def _images():
    result = subprocess.run(["docker", "image", "ls", "-q", "--filter", "reference=oah-sandbox-*"],
                             capture_output=True, text=True)
    return set(result.stdout.split())


def _containers():
    result = subprocess.run(["docker", "ps", "-a", "-q", "--filter", "name=oah-sandbox-run-"],
                             capture_output=True, text=True)
    return set(result.stdout.split())


def _make_target_repo(tmp_path, test_body, extra_files=None):
    repo = tmp_path / "target_repo"
    (repo / "tests").mkdir(parents=True)
    (repo / "tests" / "test_it.py").write_text(textwrap.dedent(test_body))
    for name, content in (extra_files or {}).items():
        (repo / name).write_text(content)
    return repo


def test_a_real_passing_suite_reports_passed_and_cleans_up(tmp_path):
    repo = _make_target_repo(tmp_path, """
        def test_ok():
            assert 1 + 1 == 2
    """)

    images_before, containers_before = _images(), _containers()
    result = run_pytest_suite(repo, sandbox_runner=run_in_sandbox, timeout_s=120)
    assert result["status"] == "passed", result

    assert _images() == images_before
    assert _containers() == containers_before


def test_a_real_failing_test_reports_failed_with_output_captured(tmp_path):
    repo = _make_target_repo(tmp_path, """
        def test_fails():
            assert 1 == 2, "deliberately wrong"
    """)

    result = run_pytest_suite(repo, sandbox_runner=run_in_sandbox, timeout_s=120)
    assert result["status"] == "failed", result
    assert "deliberately wrong" in (result["stdout"] + result["stderr"])


def test_network_is_actually_unreachable_from_inside_the_sandbox(tmp_path):
    repo = tmp_path / "net_target"
    repo.mkdir()

    script = (
        "python3 -c \"import socket; "
        "socket.setdefaulttimeout(3); "
        "socket.create_connection(('8.8.8.8', 53))\""
    )
    result = run_in_sandbox(repo, script, timeout_s=30)
    # A real network attempt must fail (non-zero exit) or hang until our
    # own wall-clock timeout -- either way, it must NOT succeed.
    assert result["exit_code"] != 0 or result["timed_out"]


def test_a_real_timeout_kills_the_container_and_leaves_nothing_behind(tmp_path):
    repo = tmp_path / "slow_target"
    repo.mkdir()

    containers_before = _containers()
    result = run_in_sandbox(repo, "sleep 60", timeout_s=3)

    assert result["timed_out"] is True
    assert result["exit_code"] is None
    assert _containers() == containers_before


def test_cleanup_leaves_no_image_behind_even_on_a_real_failure(tmp_path):
    repo = _make_target_repo(tmp_path, """
        def test_fails():
            assert False
    """)

    images_before = _images()
    run_pytest_suite(repo, sandbox_runner=run_in_sandbox, timeout_s=120)
    assert _images() == images_before
