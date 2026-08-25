"""Regression tests for oah.discovery.telemetry_scanner (S2)."""
from oah.discovery.telemetry_scanner import build_telemetry_inventory, Ids, scan_file
from oah.schemas import validate


def _scan(tmp_path, content, filename="app.py"):
    path = tmp_path / filename
    path.write_text(content)
    return scan_file(path, tmp_path, Ids())


def test_stdlib_logger_detected(tmp_path):
    result = _scan(tmp_path, """
import logging
logger = logging.getLogger(__name__)
logger.info("hello")
logger.error("boom")
""")
    assert len(result["loggers"]) == 2
    assert all(l["logger_kind"] == "stdlib_logging" for l in result["loggers"])
    levels = {l["level"] for l in result["loggers"]}
    assert levels == {"info", "error"}


def test_custom_wrapper_logger_detected(tmp_path):
    """Real pattern from beacon's corpus repo: a local get_logger() wrapper,
    not stdlib logging.getLogger directly."""
    result = _scan(tmp_path, """
from beacon_logging import get_logger
_logger = get_logger("app")
_logger.warning("careful")
""")
    assert len(result["loggers"]) == 1
    assert result["loggers"][0]["logger_kind"] == "custom_wrapper"
    assert result["loggers"][0]["wrapper_module"] == "beacon_logging"


def test_print_detected_as_weakest_telemetry_form(tmp_path):
    result = _scan(tmp_path, 'print("debug output")\n')
    assert len(result["loggers"]) == 1
    assert result["loggers"][0]["logger_kind"] == "print"


def test_swallowed_exception(tmp_path):
    """Real pattern from beacon: except with no log call and no re-raise."""
    result = _scan(tmp_path, """
try:
    x = risky()
except Exception:
    x = 0
""")
    assert len(result["error_handling"]) == 1
    assert result["error_handling"][0]["pattern"] == "swallowed"
    assert result["error_handling"][0]["exception_type"] == "Exception"


def test_reraised_exception_not_swallowed(tmp_path):
    result = _scan(tmp_path, """
try:
    x = risky()
except ValueError:
    raise
""")
    assert result["error_handling"][0]["pattern"] == "reraised"


def test_logged_exception_not_swallowed(tmp_path):
    result = _scan(tmp_path, """
import logging
logger = logging.getLogger(__name__)
try:
    x = risky()
except Exception as exc:
    logger.error("failed: %s", exc)
""")
    error_entries = [e for e in result["error_handling"]]
    assert len(error_entries) == 1
    assert error_entries[0]["pattern"] == "logged"


def test_tuple_exception_type_captured(tmp_path):
    """Real pattern from beacon: except (TypeError, ValueError): — a tree-
    sitter `tuple` node, not `tuple_pattern` (an earlier, wrong guess this
    test pins against regressing back to)."""
    result = _scan(tmp_path, """
try:
    x = risky()
except (TypeError, ValueError):
    x = None
""")
    assert result["error_handling"][0]["exception_type"] == "(TypeError, ValueError)"


def test_existing_otel_usage_detected(tmp_path):
    result = _scan(tmp_path, "from opentelemetry import trace\n")
    assert len(result["existing_otel_usage"]) == 1
    assert result["existing_otel_usage"][0]["package"] == "opentelemetry"


def test_metrics_library_detected(tmp_path):
    result = _scan(tmp_path, "import prometheus_client\n")
    assert len(result["metrics_libraries"]) == 1
    assert result["metrics_libraries"][0]["library"] == "prometheus_client"


def test_build_telemetry_inventory_validates_against_schema(tmp_path):
    (tmp_path / "app.py").write_text("""
import logging
logger = logging.getLogger(__name__)
try:
    logger.info("start")
except Exception:
    pass
""")
    inventory = build_telemetry_inventory(tmp_path, git_sha="deadbeef")
    validate("telemetry_inventory", inventory)
    assert inventory["summary"]["logger_call_sites"] == 1
    assert inventory["summary"]["swallowed_exceptions"] == 1
    assert inventory["summary"]["has_existing_otel"] is False
