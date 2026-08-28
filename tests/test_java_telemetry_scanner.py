"""Regression tests for oah.discovery.java_telemetry_scanner (S2, Java,
docs/decisions/037).

Motivated by a real target repo (legacy-code-transpilers, a ~4400-file
Java/Spring backend) that scored ZERO S2 findings before this module
existed, despite 668 files using real SLF4J logging -- no Java S2 scanner
had ever been written.
"""
from pathlib import Path

from oah.discovery.java_telemetry_scanner import build_telemetry_inventory, Ids, scan_file
from oah.schemas import validate


def _write(tmp_path, name, content):
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


def _scan(tmp_path, content, filename="App.java"):
    path = _write(tmp_path, filename, content)
    return scan_file(path, tmp_path, Ids())


def test_lombok_slf4j_annotation_resolves_synthesized_log_field(tmp_path):
    """The dominant real shape: @Slf4j generates a `log` field at compile
    time, never visible in source at all."""
    result = _scan(tmp_path, """
import lombok.extern.slf4j.Slf4j;

@Slf4j
public class Service {
    public void run() {
        log.error("failed");
        log.warn("careful");
        log.info("started");
    }
}
""")
    assert len(result["loggers"]) == 3
    assert all(l["logger_kind"] == "stdlib_logging" for l in result["loggers"])
    assert {l["level"] for l in result["loggers"]} == {"error", "warning", "info"}


def test_explicit_slf4j_logger_factory_field_resolved(tmp_path):
    result = _scan(tmp_path, """
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

public class Service {
    private static final Logger log = LoggerFactory.getLogger(Service.class);
    public void run() {
        log.debug("x");
    }
}
""")
    assert len(result["loggers"]) == 1
    assert result["loggers"][0]["logger_kind"] == "stdlib_logging"
    assert result["loggers"][0]["level"] == "debug"


def test_explicit_logger_field_can_be_named_anything(tmp_path):
    result = _scan(tmp_path, """
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

public class Service {
    private static final Logger LOGGER = LoggerFactory.getLogger(Service.class);
    public void run() {
        LOGGER.info("x");
    }
}
""")
    assert len(result["loggers"]) == 1


def test_two_classes_in_one_file_each_get_own_scoped_logger(tmp_path):
    """Java loggers are per-class by convention -- a field/annotation in
    one class must not leak into another class's own `log`/`LOGGER` name
    in the same file."""
    result = _scan(tmp_path, """
import lombok.extern.slf4j.Slf4j;

@Slf4j
class A {
    void run() { log.error("a"); }
}

class B {
    void run() { log.error("b"); }
}
""")
    assert len(result["loggers"]) == 1  # only A's log.error resolves -- B has no @Slf4j/declared logger


def test_system_out_and_err_println_detected_as_print(tmp_path):
    result = _scan(tmp_path, """
public class Service {
    void run() {
        System.out.println("hello");
        System.err.println("boom");
    }
}
""")
    assert len(result["loggers"]) == 2
    assert all(l["logger_kind"] == "print" for l in result["loggers"])


def test_otel_import_detected(tmp_path):
    result = _scan(tmp_path, "import io.opentelemetry.api.trace.Tracer;\n"
                              "public class Service {}\n")
    assert len(result["existing_otel_usage"]) == 1
    assert result["existing_otel_usage"][0]["package"] == "io.opentelemetry.api.trace.Tracer"


def test_unrelated_scoped_package_not_treated_as_otel(tmp_path):
    result = _scan(tmp_path, "import io.opentelemetryunrelated.Thing;\n"
                              "public class Service {}\n")
    assert result["existing_otel_usage"] == []


def test_metrics_library_import_detected(tmp_path):
    result = _scan(tmp_path, "import io.prometheus.client.Counter;\n"
                              "public class Service {}\n")
    assert len(result["metrics_libraries"]) == 1
    assert result["metrics_libraries"][0]["library"] == "prometheus_client"


def test_catch_with_throw_is_reraised_with_exception_type(tmp_path):
    result = _scan(tmp_path, """
public class Service {
    void run() {
        try {
            x();
        } catch (java.io.IOException e) {
            throw new RuntimeException(e);
        }
    }
}
""")
    assert len(result["error_handling"]) == 1
    assert result["error_handling"][0]["pattern"] == "reraised"
    assert result["error_handling"][0]["exception_type"] == "java.io.IOException"


def test_catch_with_log_call_is_logged(tmp_path):
    result = _scan(tmp_path, """
import lombok.extern.slf4j.Slf4j;
@Slf4j
public class Service {
    void run() {
        try { x(); } catch (Exception e) { log.error("failed", e); }
    }
}
""")
    assert result["error_handling"][0]["pattern"] == "logged"


def test_catch_with_only_println_is_swallowed(tmp_path):
    """A real precision point: println's method name isn't a recognized
    log-level name, so a catch body that only prints (no real leveled log
    call, no throw) is correctly classified as swallowed, not logged."""
    result = _scan(tmp_path, """
public class Service {
    void run() {
        try { x(); } catch (Exception e) { System.out.println("swallowed"); }
    }
}
""")
    assert result["error_handling"][0]["pattern"] == "swallowed"


def test_multi_catch_exception_type_captured_verbatim(tmp_path):
    result = _scan(tmp_path, """
public class Service {
    void run() {
        try {
            x();
        } catch (java.io.IOException | java.sql.SQLException e) {
            throw new RuntimeException(e);
        }
    }
}
""")
    assert "IOException" in result["error_handling"][0]["exception_type"]
    assert "SQLException" in result["error_handling"][0]["exception_type"]


def test_build_telemetry_inventory_schema_valid(tmp_path):
    _write(tmp_path, "Service.java", """
import lombok.extern.slf4j.Slf4j;
import io.opentelemetry.api.trace.Tracer;

@Slf4j
public class Service {
    public void run() {
        try {
            doThing();
        } catch (Exception e) {
            log.error("failed", e);
        }
    }
}
""")
    inventory = build_telemetry_inventory(tmp_path, git_sha="deadbeef")
    validate("telemetry_inventory", inventory)
    assert inventory["summary"]["files_scanned"] == 1
    assert inventory["summary"]["has_existing_otel"] is True


def test_build_telemetry_inventory_empty_repo_still_valid(tmp_path):
    inventory = build_telemetry_inventory(tmp_path, git_sha="deadbeef")
    validate("telemetry_inventory", inventory)
    assert inventory["summary"]["files_scanned"] == 0


def test_detect_repo_skips_test_sources_and_build_output(tmp_path):
    _write(tmp_path, "src/main/java/App.java", """
import lombok.extern.slf4j.Slf4j;
@Slf4j
public class App { void run() { log.error("x"); } }
""")
    _write(tmp_path, "src/test/java/AppTest.java", """
import lombok.extern.slf4j.Slf4j;
@Slf4j
public class AppTest { void run() { log.error("should not count"); } }
""")
    _write(tmp_path, "target/classes/Generated.java", """
import lombok.extern.slf4j.Slf4j;
@Slf4j
public class Generated { void run() { log.error("should not count either"); } }
""")
    inventory = build_telemetry_inventory(tmp_path, git_sha="deadbeef")
    assert inventory["summary"]["files_scanned"] == 1
    assert len(inventory["loggers"]) == 1
