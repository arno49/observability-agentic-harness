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

`capture_spans=True` additionally captures what the target's own
(S10-instrumented) code actually emits at runtime, via OpenTelemetry's
own official zero-code-change bootstrap tool, `opentelemetry-instrument`
-- verified against a real container before relying on it: it silently
no-ops unless `opentelemetry-distro` is installed alongside
`-api`/`-sdk`/`-instrumentation` (no Configurator registered otherwise),
and pytest's default fd-level capture swallows the exporter's
background-thread writes unless run with `-s`. The `ConsoleSpanExporter`
prints one pretty-printed JSON object per span, back to back, interleaved
with pytest's own text -- not one parseable document -- so
`parse_captured_spans` scans for each individually via
`json.JSONDecoder.raw_decode`, filtering to objects that actually look
like a real span so unrelated JSON the target's own tests might print
can't be mistaken for one.
"""
import json
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
    pip install opentelemetry-api
    exit 0
fi
echo "--- editable install failed, falling back ---" >&2
cat /tmp/oah_install.log >&2
if [ -f requirements.txt ]; then
    pip install -r requirements.txt
fi
pip install pytest opentelemetry-api
""".strip()

_TEST_SCRIPT = "python -m pytest"

# opentelemetry-api alone is always installed above (not gated on
# capture_spans): S10-instrumented target code now unconditionally does
# `from opentelemetry import trace` (per skills/s10-instrumenter/SKILL.md),
# and the api package alone is enough for that import and every
# tracer.start_as_current_span/set_attribute call to work as real no-ops
# -- without it, ANY --dynamic run against a real S10-instrumented target
# would fail to even import, a real regression a Docker-only test caught
# (test_pytest_runner_capture_docker.py), not the mocked unit tests.
# -sdk/-instrumentation/-distro turn those no-ops into real, exported,
# capturable spans -- only needed when capture_spans=True.
_CAPTURE_SETUP_ADDITION = (
    "\npip install opentelemetry-sdk opentelemetry-instrumentation opentelemetry-distro"
)
_CAPTURE_TEST_SCRIPT = (
    "OTEL_TRACES_EXPORTER=console OTEL_METRICS_EXPORTER=none "
    "OTEL_LOGS_EXPORTER=none opentelemetry-instrument python -m pytest -s"
)

_REQUIRED_SPAN_KEYS = {"name", "context", "attributes"}


def parse_captured_spans(output):
    """Scans `output` for `ConsoleSpanExporter`'s pretty-printed JSON span
    objects, one at a time via `raw_decode` (multiple top-level JSON
    objects back to back, interleaved with pytest's own text, is not one
    parseable document). Only objects that actually look like a real span
    (name/context/attributes keys all present) are kept -- unrelated JSON
    the target's own test output happens to print is silently skipped,
    never mistaken for a span. Returns [] when nothing real was found,
    never raises on malformed fragments."""
    decoder = json.JSONDecoder()
    spans = []
    i = 0
    while i < len(output):
        if output[i] == "{":
            try:
                obj, end = decoder.raw_decode(output, i)
            except json.JSONDecodeError:
                i += 1
                continue
            if isinstance(obj, dict) and _REQUIRED_SPAN_KEYS.issubset(obj.keys()):
                spans.append(obj)
            i = end
            continue
        i += 1
    return spans


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


def _runner_result(status, exit_code=None, stdout="", stderr="", summary=None, spans=None):
    return {"status": status, "exit_code": exit_code, "stdout": stdout, "stderr": stderr,
            "summary": summary, "spans": spans if spans is not None else []}


def run_pytest_suite(target_repo, sandbox_runner=run_in_sandbox, *, capture_spans=False, **sandbox_kwargs):
    """Returns one of exactly four honest outcomes: `no_tests_found`
    (never spins up a container), `install_failed` (neither the
    editable install nor the fallback got far enough to invoke pytest
    at all), `passed`, `failed`. `sandbox_runner` is the same
    injection-point pattern as `_agent_runner`/`_completion_fn`
    elsewhere in this codebase -- most tests fake it; a smaller,
    separately-marked set uses the real sandbox.run_in_sandbox.

    `capture_spans=True` additionally captures real OTel spans the
    target's own (S10-instrumented) code emits during the run -- see
    this module's own docstring for the mechanism. `spans` is always []
    when False, or when the run never reached `python -m pytest` at all
    (`install_failed`/`no_tests_found`)."""
    if not detect_pytest_suite(target_repo):
        return _runner_result("no_tests_found")

    test_script = _CAPTURE_TEST_SCRIPT if capture_spans else _TEST_SCRIPT
    setup_script = _INSTALL_SCRIPT + _CAPTURE_SETUP_ADDITION if capture_spans else _INSTALL_SCRIPT
    result = sandbox_runner(target_repo, test_script, setup_script=setup_script, **sandbox_kwargs)
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
    spans = parse_captured_spans(output) if capture_spans else []
    return _runner_result(status, exit_code=result["exit_code"],
                           stdout=result["stdout"], stderr=result["stderr"], summary=summary, spans=spans)
