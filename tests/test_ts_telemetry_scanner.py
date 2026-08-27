"""Regression tests for oah.discovery.ts_telemetry_scanner (S2, TypeScript,
docs/decisions/033).

Motivated by a real target repo (mf-analyzer-web) that scored ZERO S2
findings before this module existed -- telemetry_scanner.py's
build_telemetry_inventory only ever scanned *.py files. That repo's own
real shape (a hand-rolled Logger class singleton, exported once, imported
into ~140 consumer files) is the basis for the cross-file tests below, not
an invented fixture.
"""
from pathlib import Path

from oah.discovery.ts_telemetry_scanner import build_telemetry_inventory, Ids, scan_file
from oah.schemas import validate


def _write(tmp_path, name, content):
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


def _scan(tmp_path, content, filename="app.ts"):
    path = _write(tmp_path, filename, content)
    return scan_file(path, tmp_path, Ids())


def test_console_calls_detected_as_print(tmp_path):
    result = _scan(tmp_path, (
        'console.log("hello");\n'
        'console.error("boom");\n'
        'console.warn("careful");\n'
        'console.debug("trace");\n'
    ))
    assert len(result["loggers"]) == 4
    assert all(l["logger_kind"] == "print" for l in result["loggers"])
    levels = {l["level"] for l in result["loggers"]}
    assert levels == {"info", "error", "warning", "debug"}


def test_locally_defined_logger_class_detected_same_file(tmp_path):
    """The real shape found on mf-analyzer-web: a hand-rolled class whose
    own methods are logger-shaped, instantiated and used in one file."""
    result = _scan(tmp_path, (
        "class Logger {\n"
        "  error(msg) { console.error(msg); }\n"
        "  warn(msg) { console.warn(msg); }\n"
        "  info(msg) { console.info(msg); }\n"
        "}\n"
        "const logger = new Logger();\n"
        'logger.error("failed");\n'
        'logger.info("started");\n'
    ))
    custom = [l for l in result["loggers"] if l["logger_kind"] == "custom_wrapper"]
    assert len(custom) == 2
    assert all(l["wrapper_module"] == "app.ts" for l in custom)
    assert {l["level"] for l in custom} == {"error", "info"}


def test_class_with_only_one_logger_shaped_method_not_treated_as_a_logger(tmp_path):
    """Precision guard: a class that happens to define ONE method named
    like a log level (e.g. a generic event emitter's own `.info()`) must
    not be treated as a logger wrapper -- two names required."""
    result = _scan(tmp_path, (
        "class Thing {\n"
        "  info(msg) { return msg; }\n"
        "}\n"
        "const t = new Thing();\n"
        "t.info(1);\n"
    ))
    assert result["loggers"] == []


def test_object_literal_logger_detected(tmp_path):
    result = _scan(tmp_path, (
        "const logger = {\n"
        "  error(msg) { console.error(msg); },\n"
        "  warn: (msg) => console.warn(msg),\n"
        "};\n"
        'logger.error("x");\n'
    ))
    custom = [l for l in result["loggers"] if l["logger_kind"] == "custom_wrapper"]
    assert len(custom) == 1
    assert custom[0]["wrapper_module"] == "app.ts"


def test_winston_create_logger_detected(tmp_path):
    result = _scan(tmp_path, (
        'import winston from "winston";\n'
        "const logger = winston.createLogger({});\n"
        'logger.error("x");\n'
    ))
    custom = [l for l in result["loggers"] if l["logger_kind"] == "custom_wrapper"]
    assert len(custom) == 1
    assert custom[0]["wrapper_module"] == "winston"


def test_pino_factory_call_detected(tmp_path):
    result = _scan(tmp_path, (
        'import pino from "pino";\n'
        "const logger = pino();\n"
        'logger.info("x");\n'
    ))
    custom = [l for l in result["loggers"] if l["logger_kind"] == "custom_wrapper"]
    assert len(custom) == 1
    assert custom[0]["wrapper_module"] == "pino"


def test_otel_import_detected(tmp_path):
    result = _scan(tmp_path, 'import { trace } from "@opentelemetry/api";\n')
    assert len(result["existing_otel_usage"]) == 1
    assert result["existing_otel_usage"][0]["package"] == "@opentelemetry/api"


def test_unrelated_scoped_package_not_treated_as_otel(tmp_path):
    """Precision guard mirroring Python's own exact-boundary check
    (docs/decisions -- a bare startswith would misflag an unrelated
    package sharing the prefix as OTel usage)."""
    result = _scan(tmp_path, 'import x from "@opentelemetry-unrelated/thing";\n')
    assert result["existing_otel_usage"] == []


def test_metrics_libraries_detected_and_normalized(tmp_path):
    result = _scan(tmp_path, (
        'import client from "prom-client";\n'
        'import statsd from "hot-shots";\n'
    ))
    libs = {m["library"] for m in result["metrics_libraries"]}
    assert libs == {"prometheus_client", "statsd"}


def test_catch_with_throw_is_reraised(tmp_path):
    result = _scan(tmp_path, "try {\n  x();\n} catch (e) {\n  throw e;\n}\n")
    assert len(result["error_handling"]) == 1
    assert result["error_handling"][0]["pattern"] == "reraised"


def test_catch_with_log_call_is_logged(tmp_path):
    result = _scan(tmp_path, 'try {\n  x();\n} catch (e) {\n  console.error(e);\n}\n')
    assert result["error_handling"][0]["pattern"] == "logged"


def test_catch_with_neither_is_swallowed(tmp_path):
    result = _scan(tmp_path, "try {\n  x();\n} catch (e) {\n  doNothingWith(e);\n}\n")
    assert result["error_handling"][0]["pattern"] == "swallowed"


def test_parameterless_catch_does_not_crash(tmp_path):
    result = _scan(tmp_path, "try {\n  x();\n} catch {\n  console.log(1);\n}\n")
    assert result["error_handling"][0]["pattern"] == "logged"


def test_exception_type_never_populated(tmp_path):
    """TS/JS catch bindings carry no real static exception-type information
    the way Python's `except SomeError as e` does -- deliberately never
    populated, not a missing field."""
    result = _scan(tmp_path, "try {\n  x();\n} catch (e) {\n  throw e;\n}\n")
    assert "exception_type" not in result["error_handling"][0]


# --- Cross-file logger resolution (docs/decisions/033) ---------------------
# The real shape that motivated this module: a logger singleton built and
# exported in one file, imported into many consumer files.

def test_cross_file_logger_resolved_through_default_export(tmp_path):
    _write(tmp_path, "utils/logger.ts", (
        "class Logger {\n"
        "  error(msg) { console.error(msg); }\n"
        "  warn(msg) { console.warn(msg); }\n"
        "}\n"
        "export const logger = new Logger();\n"
    ))
    _write(tmp_path, "consumer.ts", (
        'import { logger } from "./utils/logger";\n'
        'logger.error("failed");\n'
    ))
    inventory = build_telemetry_inventory(tmp_path, git_sha="deadbeef")
    custom = [l for l in inventory["loggers"] if l["logger_kind"] == "custom_wrapper"]
    assert len(custom) == 1
    assert custom[0]["file"] == "consumer.ts"
    assert custom[0]["wrapper_module"] == "utils/logger.ts"


def test_cross_file_logger_resolved_via_tsconfig_path_alias(tmp_path):
    _write(tmp_path, "tsconfig.json", '{"compilerOptions": {"baseUrl": ".", "paths": {"@/*": ["src/*"]}}}\n')
    _write(tmp_path, "src/utils/logger.ts", (
        "class Logger {\n"
        "  error(msg) { console.error(msg); }\n"
        "  warn(msg) { console.warn(msg); }\n"
        "}\n"
        "export const logger = new Logger();\n"
    ))
    _write(tmp_path, "src/consumer.ts", (
        'import { logger } from "@/utils/logger";\n'
        'logger.warn("careful");\n'
    ))
    inventory = build_telemetry_inventory(tmp_path, git_sha="deadbeef")
    custom = [l for l in inventory["loggers"] if l["logger_kind"] == "custom_wrapper"]
    assert len(custom) == 1
    assert custom[0]["level"] == "warning"


def test_build_telemetry_inventory_schema_valid_on_real_shape(tmp_path):
    _write(tmp_path, "utils/logger.ts", (
        "class Logger {\n"
        "  error(msg) { console.error(msg); }\n"
        "  warn(msg) { console.warn(msg); }\n"
        "}\n"
        "export const logger = new Logger();\n"
    ))
    _write(tmp_path, "consumer.ts", (
        'import { logger } from "./utils/logger";\n'
        'import { trace } from "@opentelemetry/api";\n'
        "async function run() {\n"
        "  try {\n"
        "    await doThing();\n"
        "  } catch (e) {\n"
        '    logger.error("failed", e);\n'
        "  }\n"
        "}\n"
    ))
    inventory = build_telemetry_inventory(tmp_path, git_sha="deadbeef")
    validate("telemetry_inventory", inventory)  # raises on failure
    assert inventory["summary"]["files_scanned"] == 2
    assert inventory["summary"]["has_existing_otel"] is True


def test_build_telemetry_inventory_empty_repo_still_valid(tmp_path):
    inventory = build_telemetry_inventory(tmp_path, git_sha="deadbeef")
    validate("telemetry_inventory", inventory)
    assert inventory["summary"]["files_scanned"] == 0
