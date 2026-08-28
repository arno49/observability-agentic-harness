"""S2 deterministic pass for Java: existing telemetry inventory
(architecture.md S2), docs/decisions/037. Same four categories
`oah/discovery/telemetry_scanner.py`'s Python implementation and
`oah/discovery/ts_telemetry_scanner.py`'s TypeScript implementation both
cover (loggers, existing_otel_usage, metrics_libraries, error_handling),
same output shape (schemas/telemetry_inventory.schema.json), built against
real Java/Spring idioms rather than a blind port.

Motivated the same way `docs/decisions/033` motivated the TypeScript
scanner: running `oah gaps --language java` against a real ~4400-file
Java/Spring backend (`legacy-code-transpilers`, the service behind
mf-analyzer-web's own chat feature, docs/decisions/036) reported every
point dark, TCR 0% -- not because the repo has no logging (it has SLF4J
call sites in 668 of its files), but because no Java S2 scanner existed at
all; `build_telemetry_inventory` had never been written for this language.

Two real logger-field construction shapes found by reading the actual
source, not assumed:
- **Explicit SLF4J**: `private static final Logger log =
  LoggerFactory.getLogger(X.class);`, a `field_declaration` whose
  initializer is a `LoggerFactory.getLogger(...)` call, `LoggerFactory`
  imported from `org.slf4j`.
- **Lombok `@Slf4j`**: a class-level annotation that generates a `log`
  field of type `org.slf4j.Logger` at COMPILE TIME -- never visible in
  source at all (the same class of implicit construction
  `@RequiredArgsConstructor` already forced `java_adapter.py`'s own S1
  pass to handle, docs/decisions/029/036). Detected structurally: a
  `class_declaration` carrying a `@Slf4j` marker_annotation makes the bare
  name `log` a known SLF4J logger for every method in that class, exactly
  like an explicitly-declared field would.

Both resolve into the SAME class-scoped `self_attrs` mechanism
`java_adapter.py`'s own `KnownNames` already uses (a `(class_name,
field_name)` dict) -- Java loggers are per-class by convention, never a
cross-file shared singleton the way TS's logger/apiClient shapes were, so
no cross-file propagation is needed here at all.

`System.out.println`/`System.err.println` are Java's own weakest-tier
logging form, mirroring Python's `print()` and TS's `console.*` (kind
`print`). `try`/`catch` classification mirrors both siblings: reraised
(body contains a `throw` anywhere) > logged (body contains a call whose
method name is a recognized log-level name, receiver-agnostic, the same
coarse heuristic Python/TS both already use) > swallowed. Unlike TS,
Java's `catch` DOES carry real static exception-type information (`catch
(IOException e)`, even real multi-catch `catch (IOException | SQLException
e)`) -- `exception_type` is populated here, the same as Python's own
`except SomeError as e` handling, a real difference from TS's own
documented "not applicable."

Deliberately NOT covered, named rather than silently dropped: Log4j2
(`org.apache.logging.log4j`) -- only one real occurrence found in the
motivating repo (a log-level-agnostic library note, not real call-site
volume), not worth a second logger-construction shape for; an inline
`LoggerFactory.getLogger("name").debug(...)` chain with no intermediate
variable (one real occurrence found) -- the same "terminal buried
mid-chain, no assignment" shape `docs/decisions/029`'s own Java S1 adapter
already names as a boundary; and manifest-level vendor detection (a Maven
`pom.xml` scanner, the Java analogue of `manifest_scanner.py`'s
`package.json` reader) -- a real, separate, larger piece of work, not
attempted here.
"""
from pathlib import Path

import tree_sitter_java as tsjava
from tree_sitter import Language, Parser

from oah import __version__ as _OAH_VERSION

_LANGUAGE = Language(tsjava.language())

_LOG_METHOD_TO_LEVEL = {
    "error": "error", "warn": "warning", "info": "info",
    "debug": "debug", "trace": "debug",
}
OTEL_PACKAGE_PREFIX = "io.opentelemetry."
# Docs-grounded (real Java package names for each vendor), NOT verified
# against the motivating repo -- it uses none of these. Kept narrow and
# honest rather than guessed at further.
_METRICS_PACKAGE_PREFIXES = {
    "io.prometheus.client": "prometheus_client",
    "com.timgroup.statsd": "statsd",
}


def _text(node, src):
    return src[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


def _line(node):
    return node.start_point[0] + 1


class Ids:
    def __init__(self):
        self.n = 1

    def next(self, prefix):
        val = f"{prefix}-{self.n:04d}"
        self.n += 1
        return val


def _class_has_slf4j_annotation(class_decl, src):
    modifiers = next((c for c in class_decl.children if c.type == "modifiers"), None)
    if modifiers is None:
        return False
    for c in modifiers.children:
        if c.type not in ("marker_annotation", "annotation"):
            continue
        name_node = c.child_by_field_name("name")
        if name_node is not None and _text(name_node, src) == "Slf4j":
            return True
    return False


def _prescan_loggers(root, src, self_attrs):
    """Populates self_attrs[(class_name, field_name)] = True for every
    known SLF4J logger field in the file -- explicit
    `LoggerFactory.getLogger(...)` initializers and Lombok `@Slf4j`
    classes (whose synthesized field is always named `log`). A separate,
    order-independent pass, mirroring java_adapter.py's own
    KnownNames.prescan (a method using the field must resolve regardless
    of whether it's defined before or after the field/annotation that
    establishes it)."""
    def walk(node, class_name):
        local_class = class_name
        if node.type == "class_declaration":
            name_node = node.child_by_field_name("name")
            if name_node is not None:
                local_class = _text(name_node, src)
            if _class_has_slf4j_annotation(node, src) and local_class:
                self_attrs[(local_class, "log")] = True

        if node.type == "field_declaration" and class_name:
            declarator = node.child_by_field_name("declarator")
            if declarator is not None:
                name_node = declarator.child_by_field_name("name")
                value_node = declarator.child_by_field_name("value")
                if (name_node is not None and value_node is not None
                        and value_node.type == "method_invocation"):
                    obj = value_node.child_by_field_name("object")
                    method = value_node.child_by_field_name("name")
                    if (obj is not None and method is not None
                            and _text(obj, src) == "LoggerFactory" and _text(method, src) == "getLogger"):
                        self_attrs[(class_name, _text(name_node, src))] = True

        for c in node.children:
            walk(c, local_class)

    walk(root, None)


def _catch_pattern_and_type(catch_clause, src):
    """(pattern, exception_type). pattern mirrors Python/TS: reraised
    (body contains a throw anywhere) > logged (body contains a call whose
    method name is a recognized log-level name, receiver-agnostic) >
    swallowed. exception_type is real here (unlike TS) -- Java catch
    parameters carry real static types, including real multi-catch
    (`catch (IOException | SQLException e)`), reported as the catch_type
    node's own text verbatim."""
    param = next((c for c in catch_clause.children if c.type == "catch_formal_parameter"), None)
    exception_type = None
    if param is not None:
        type_node = next((c for c in param.children if c.type == "catch_type"), None)
        if type_node is not None:
            exception_type = _text(type_node, src)

    body = catch_clause.child_by_field_name("body")
    if body is None:
        return "swallowed", exception_type

    found_throw = [False]
    found_methods = []

    def walk(node):
        if node.type == "throw_statement":
            found_throw[0] = True
        if node.type == "method_invocation":
            name_node = node.child_by_field_name("name")
            if name_node is not None:
                found_methods.append(_text(name_node, src))
        for c in node.children:
            walk(c)

    walk(body)
    if found_throw[0]:
        return "reraised", exception_type
    if any(m in _LOG_METHOD_TO_LEVEL for m in found_methods):
        return "logged", exception_type
    return "swallowed", exception_type


def _scan_imports_otel_and_metrics(root, src, rel_path, ids, otel_usage, metrics):
    for child in root.children:
        if child.type != "import_declaration":
            continue
        scoped = next((c for c in child.children if c.type in ("scoped_identifier", "identifier")), None)
        if scoped is None:
            continue
        full = _text(scoped, src)
        if full.startswith(OTEL_PACKAGE_PREFIX) or full == OTEL_PACKAGE_PREFIX.rstrip("."):
            otel_usage.append({"id": ids.next("otel"), "file": rel_path, "line": _line(child), "package": full})
        for prefix, lib in _METRICS_PACKAGE_PREFIXES.items():
            if full.startswith(prefix):
                metrics.append({"id": ids.next("metrics"), "file": rel_path, "line": _line(child), "library": lib})
                break


def _scan_calls_and_catches(root, src, rel_path, class_name, self_attrs, ids, loggers, error_handling):
    def walk(node, current_class):
        local_class = current_class
        if node.type == "class_declaration":
            name_node = node.child_by_field_name("name")
            if name_node is not None:
                local_class = _text(name_node, src)

        if node.type == "method_invocation":
            obj = node.child_by_field_name("object")
            method_node = node.child_by_field_name("name")
            if obj is not None and method_node is not None:
                method = _text(method_node, src)
                if obj.type == "field_access":
                    inner_obj = obj.child_by_field_name("object")
                    field = obj.child_by_field_name("field")
                    if (inner_obj is not None and _text(inner_obj, src) == "System" and field is not None
                            and _text(field, src) in ("out", "err") and method in ("println", "print", "printf")):
                        loggers.append({
                            "id": ids.next("log"), "file": rel_path, "line": _line(node),
                            "level": "info", "logger_kind": "print",
                        })
                elif obj.type == "identifier" and method in _LOG_METHOD_TO_LEVEL:
                    obj_name = _text(obj, src)
                    if local_class and (local_class, obj_name) in self_attrs:
                        loggers.append({
                            "id": ids.next("log"), "file": rel_path, "line": _line(node),
                            "level": _LOG_METHOD_TO_LEVEL[method], "logger_kind": "stdlib_logging",
                        })

        if node.type == "catch_clause":
            pattern, exception_type = _catch_pattern_and_type(node, src)
            entry = {
                "id": ids.next("err"), "file": rel_path, "line": _line(node),
                "pattern": pattern,
            }
            if exception_type:
                entry["exception_type"] = exception_type
            error_handling.append(entry)

        for c in node.children:
            walk(c, local_class)

    walk(root, class_name)


def _empty_result():
    return {"loggers": [], "existing_otel_usage": [], "metrics_libraries": [], "error_handling": []}


def scan_file(path, repo_root, ids):
    path = Path(path)
    try:
        src = path.read_bytes()
    except OSError:
        return _empty_result()
    parser = Parser(_LANGUAGE)
    try:
        tree = parser.parse(src)
    except Exception:
        return _empty_result()

    root = tree.root_node
    rel_path = str(path.relative_to(repo_root)) if repo_root else str(path)

    self_attrs = {}
    _prescan_loggers(root, src, self_attrs)

    loggers, otel_usage, metrics, error_handling = [], [], [], []
    _scan_imports_otel_and_metrics(root, src, rel_path, ids, otel_usage, metrics)
    _scan_calls_and_catches(root, src, rel_path, None, self_attrs, ids, loggers, error_handling)

    return {
        "loggers": loggers, "existing_otel_usage": otel_usage,
        "metrics_libraries": metrics, "error_handling": error_handling,
    }


def _scannable_files(repo_root):
    """Mirrors java_adapter.py's own detect_repo exclusions exactly:
    Maven/Gradle build output (target/, build/), .git, and test source
    roots (a `test` path segment -- Maven/Gradle convention `src/test/
    java/...`, the singular form, unlike Python's own plural `tests/`)."""
    files = []
    for f in sorted(Path(repo_root).rglob("*.java")):
        rel = f.relative_to(repo_root)
        parts = rel.parts
        if "target" in parts or "build" in parts or ".git" in parts or "test" in parts:
            continue
        if f.name.startswith("Test") or f.name.endswith("Test.java"):
            continue
        files.append(f)
    return files


def build_telemetry_inventory(repo_root, git_sha, harness_version=_OAH_VERSION):
    repo_root = Path(repo_root)
    files = _scannable_files(repo_root)

    ids = Ids()
    loggers, otel_usage, metrics, error_handling = [], [], [], []
    for f in files:
        result = scan_file(f, repo_root, ids)
        loggers.extend(result["loggers"])
        otel_usage.extend(result["existing_otel_usage"])
        metrics.extend(result["metrics_libraries"])
        error_handling.extend(result["error_handling"])

    # Manifest-declared vendor detection has no Java equivalent yet (no
    # pom.xml scanner exists) -- a real, separate, named gap, not silently
    # claimed by reusing the package.json-only scan_package_json here.
    vendor_dependencies = []

    return {
        "schema_version": "0.1.0",
        "repo": {"path": str(repo_root), "git_sha": git_sha},
        "generated_by": {"harness_version": harness_version},
        "loggers": loggers,
        "existing_otel_usage": otel_usage,
        "metrics_libraries": metrics,
        "error_handling": error_handling,
        "vendor_dependencies": vendor_dependencies,
        "summary": {
            "files_scanned": len(files),
            "logger_call_sites": len(loggers),
            "swallowed_exceptions": sum(1 for e in error_handling if e["pattern"] == "swallowed"),
            "has_existing_otel": len(otel_usage) > 0,
            "vendor_dependencies_count": len(vendor_dependencies),
            "has_commercial_apm": False,
        },
    }
