"""E6 R2's target-facing half: detect whether a target repo has a
pytest suite at all, and if so, run it inside sandbox.py's isolated
container via the install-fallback ladder grounded in
docs/runnability-matrix.md's real `beacon` finding -- an editable
install (`pip install -e ".[dev]"`) is the obvious first attempt but
fails for reasons that have nothing to do with the target repo being
broken (flat-layout package-discovery ambiguity, in beacon's case);
falling back to a plain `pip install -r requirements.txt` + running
pytest directly (no editable install) is what actually worked there.

Both attempts run as one `setup_script`, at `docker build` time (see
sandbox.py) -- install needs network, which the *running* container
deliberately doesn't have; baking install into the image build means
whichever branch of the ladder actually worked, `python -m pytest`
then runs network-isolated against a container that already has
everything it needs, no install step (or its network access) exposed
to the target's own test code as it executes.

Python only, matching S1's own surface-detection scope today -- see
this module's own docstring note in the R2 plan for why non-Python
targets aren't attempted here.
"""
import re
from pathlib import Path

from oah.validate.sandbox import run_in_sandbox

_PYTEST_CONFIG_MARKERS = {
    "pytest.ini": None,
    "pyproject.toml": "[tool.pytest.ini_options]",
    "setup.cfg": "[tool:pytest]",
}

# Two-step, not one combined regex: pytest's summary is always exactly
# one line ("===== 1 failed, 2 passed in 0.12s =====", MULTILINE-anchored
# so it can't span into neighboring lines), matched first in isolation;
# counts are then pulled from just that line's own text. A single regex
# spanning both concerns previously used \s* between the failed/passed
# groups, which matches '\n' -- letting the match silently drift onto an
# unrelated earlier line (e.g. a stray "== 2" inside a traceback) and
# report a fabricated 0/0 instead of the real counts. Caught only by a
# real Docker run, not by the mocked test suite.
_SUMMARY_LINE_RE = re.compile(r"^=+ (.+ in [\d.]+s.*) =+$", re.MULTILINE)
_COUNT_RE = re.compile(r"(\d+) (failed|passed)")

_INSTALL_SCRIPT = """
set -e
if pip install -e ".[dev]" >/tmp/oah_install.log 2>&1; then
    exit 0
fi
echo "--- editable install failed, falling back ---" >&2
cat /tmp/oah_install.log >&2
if [ -f requirements.txt ]; then
    pip install -r requirements.txt
fi
pip install pytest
""".strip()

_TEST_SCRIPT = "python -m pytest"


def detect_pytest_suite(target_repo):
    """Cheap, real precondition check -- no container spun up for this.
    A `tests/` directory, `pytest.ini`, or a pytest section inside
    `pyproject.toml`/`setup.cfg` all count; matches pytest's own
    discovery conventions closely enough for a yes/no gate."""
    repo = Path(target_repo)
    if (repo / "tests").is_dir():
        return True
    for filename, section_marker in _PYTEST_CONFIG_MARKERS.items():
        path = repo / filename
        if not path.is_file():
            continue
        if section_marker is None:
            return True
        if section_marker in path.read_text():
            return True
    return False


def _parse_summary(output):
    """Best-effort extraction of pytest's own final summary line counts.
    Returns None (never a fabricated 0) when the line isn't found or
    doesn't match the expected shape -- e.g. install_failed output,
    or a pytest version whose summary format doesn't match."""
    line_match = _SUMMARY_LINE_RE.search(output)
    if not line_match:
        return None
    counts = {"failed": 0, "passed": 0}
    for count, kind in _COUNT_RE.findall(line_match.group(1)):
        counts[kind] = int(count)
    return counts


def _runner_result(status, exit_code=None, stdout="", stderr="", summary=None):
    return {"status": status, "exit_code": exit_code, "stdout": stdout, "stderr": stderr, "summary": summary}


def run_pytest_suite(target_repo, sandbox_runner=run_in_sandbox, **sandbox_kwargs):
    """Returns one of exactly four honest outcomes: `no_tests_found`
    (never spins up a container), `install_failed` (neither the
    editable install nor the fallback got far enough to invoke pytest
    at all), `passed`, `failed`. `sandbox_runner` is the same
    injection-point pattern as `_agent_runner`/`_completion_fn`
    elsewhere in this codebase -- most tests fake it; a smaller,
    separately-marked set uses the real sandbox.run_in_sandbox."""
    if not detect_pytest_suite(target_repo):
        return _runner_result("no_tests_found")

    result = sandbox_runner(target_repo, _TEST_SCRIPT, setup_script=_INSTALL_SCRIPT, **sandbox_kwargs)
    output = result["stdout"] + result["stderr"]

    if result["exit_code"] is None:
        return _runner_result("install_failed", stdout=result["stdout"], stderr=result["stderr"])

    summary = _parse_summary(output)
    if summary is None:
        # pytest's own summary line never appeared -- neither install
        # attempt got far enough for pytest to run at all, or it
        # crashed before printing one. Never guess pass/fail here.
        return _runner_result("install_failed", exit_code=result["exit_code"],
                               stdout=result["stdout"], stderr=result["stderr"])

    status = "passed" if result["exit_code"] == 0 else "failed"
    return _runner_result(status, exit_code=result["exit_code"],
                           stdout=result["stdout"], stderr=result["stderr"], summary=summary)
