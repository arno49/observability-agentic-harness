"""S2 deterministic pass for TypeScript/TSX: existing telemetry inventory
(architecture.md S2), docs/decisions/033. Same four categories
`oah/discovery/telemetry_scanner.py`'s Python implementation already
covers (loggers, existing_otel_usage, metrics_libraries, error_handling),
same output shape (schemas/telemetry_inventory.schema.json), but built
against real TS/JS idioms rather than a blind port of Python's own
vocabulary -- `except`/`logging` have no TS equivalent; `try`/`catch` and
`console`/a hand-rolled logger class do.

Motivated by running `oah inventory` against a real EPAM target repo
(mf-analyzer-web, the same one that drove docs/decisions/032): it reported
ZERO findings on a real ~450-file app, because `telemetry_scanner.py`'s
`build_telemetry_inventory` only ever scanned `*.py` files -- a real,
previously named gap (docs/decisions/032's own retrospective). That repo's
own actual shape, found by reading it: a hand-rolled `class Logger {
error()/warn()/info()/debug() {...} }` singleton, `export const logger =
new Logger()`, imported into ~140 different consumer files with ~790 real
call sites -- the exact same shared-singleton-module pattern that forced
docs/decisions/032's cross-file mechanism for axios, now needed a second
time for a different concern. Rather than re-implement it, the
cross-file module-graph resolution (`_collect_export_map`,
`_load_path_aliases`, `_resolve_module_specifier`) was extracted out of
`typescript_adapter.py` into `oah/discovery/ts_module_resolution.py`
(docs/decisions/033) and is reused here unchanged -- it is detector-
agnostic by construction: it only ever propagates whatever value a
caller's own known-names dict holds, never inspecting what that value
means.

Two real, named heuristic decisions, not exhaustive vocabulary:
- A locally-defined class or object literal is treated as a logger
  wrapper once its OWN method/property names intersect
  {error, warn, info, debug, log, trace} on at least two names
  (`_MIN_LOGGER_SHAPED_METHODS`) -- two, not one, to avoid a false hit on
  an unrelated class that happens to define a single method named e.g.
  "info". Grounded in the one real shape found so far, not exhaustive:
  other real shapes (a plain function-based logger, a Proxy-based one)
  are not recognized -- named gaps, not silently claimed.
- `winston`/`pino` are the only external logging packages recognized for
  source-level custom_wrapper detection, matching
  `oah/discovery/manifest_scanner.py`'s own existing `_VENDOR_RULES`
  vocabulary exactly (bunyan/loglevel are real alternatives but have no
  existing vendor-table entry to stay consistent with, so weren't added
  here either -- a real, separate extension, not guessed at).

`catch_clause`'s classification (swallowed/logged/reraised) mirrors
Python's own `_except_pattern` exactly in spirit: reraised if the body
contains a `throw` anywhere, logged if it contains a call whose method
name is a recognized log-level name (receiver-agnostic, same coarse
heuristic Python's own version already uses), else swallowed. TS/JS catch
bindings carry no real exception-type information the way Python's
`except SomeError as e` does (a `: unknown`/`: any` annotation, when
present, is not a real type) -- `exception_type` is therefore never
populated here, a real "not applicable" rather than a missing field.
"""
from pathlib import Path

import tree_sitter_typescript as tstypescript
from tree_sitter import Language, Parser

from oah import __version__ as _OAH_VERSION
from oah.discovery.manifest_scanner import scan_package_json
from oah.discovery.ts_module_resolution import collect_export_map, load_path_aliases, resolve_module_specifier

_LANGUAGE = Language(tstypescript.language_tsx())

_LOG_METHOD_TO_LEVEL = {
    "error": "error", "warn": "warning", "warning": "warning",
    "info": "info", "debug": "debug", "log": "info", "trace": "debug",
}
_LOGGER_SHAPED_METHODS = frozenset(_LOG_METHOD_TO_LEVEL)
_MIN_LOGGER_SHAPED_METHODS = 2

# Matches manifest_scanner.py's own _VENDOR_RULES vocabulary -- only
# winston/pino have an existing vendor-table entry there.
_KNOWN_LOGGING_PACKAGES = {"winston", "pino"}

OTEL_PACKAGE_PREFIX = "@opentelemetry/"
# npm package name -> the SAME vendor-level identifier
# manifest_scanner.py's own _VENDOR_RULES already uses, so a source-
# confirmed finding and a manifest-declared finding for the same real
# library report under one shared name, not two spellings of one concept.
_METRICS_PACKAGES = {
    "prom-client": "prometheus_client",
    "hot-shots": "statsd",
    "node-statsd": "statsd",
    "statsd-client": "statsd",
    "dd-trace": "ddtrace",
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


def _collect_imports(root, src):
    """Every top-level import statement's (local, original_or_None_for_
    default, module, is_default) -- TS/JS imports are only ever valid at
    the top level, unlike Python's, so no recursive walk is needed."""
    imports = []
    for child in root.children:
        if child.type != "import_statement":
            continue
        source_node = child.child_by_field_name("source")
        module = _text(source_node, src)[1:-1] if source_node is not None else ""
        clause = next((c for c in child.children if c.type == "import_clause"), None)
        if clause is None:
            continue
        for c in clause.children:
            if c.type == "identifier":
                imports.append((_text(c, src), None, module, True))
            elif c.type == "named_imports":
                for spec in c.named_children:
                    if spec.type != "import_specifier":
                        continue
                    name_node = spec.child_by_field_name("name")
                    alias_node = spec.child_by_field_name("alias")
                    if name_node is None:
                        continue
                    original = _text(name_node, src)
                    local = _text(alias_node, src) if alias_node is not None else original
                    imports.append((local, original, module, False))
    return imports


def _class_method_names(class_body, src):
    return {
        _text(c.child_by_field_name("name"), src)
        for c in class_body.named_children
        if c.type == "method_definition" and c.child_by_field_name("name") is not None
    }


def _object_property_names(object_node, src):
    names = set()
    for c in object_node.named_children:
        if c.type == "method_definition":
            name_node = c.child_by_field_name("name")
        elif c.type == "pair":
            name_node = c.child_by_field_name("key")
        else:
            continue
        if name_node is not None and name_node.type in ("property_identifier", "identifier"):
            names.add(_text(name_node, src))
    return names


def _is_logger_shaped(names):
    return len(names & _LOGGER_SHAPED_METHODS) >= _MIN_LOGGER_SHAPED_METHODS


def _prescan_logger_shapes(root, src, rel_path, imports, known_loggers):
    """Populates known_loggers (local name -> ("custom_wrapper",
    wrapper_module)) from three real shapes: a locally-defined logger-
    shaped class, instantiated via `new X()`; a locally-defined logger-
    shaped object literal, assigned directly (no instantiation step);
    and a winston/pino-imported name, called directly (`pino()`) or via
    `.createLogger(...)`. wrapper_module is this file's own relative path
    for the first two (there is no package name -- the wrapper is
    in-repo), or the actual npm package for the third."""
    local_logging_import = {local for local, _original, module, _default in imports
                             if module in _KNOWN_LOGGING_PACKAGES}
    import_module = {local: module for local, _original, module, _default in imports}
    logger_classes = set()

    def walk(node):
        if node.type == "class_declaration":
            name_node = node.child_by_field_name("name")
            body = node.child_by_field_name("body")
            if name_node is not None and body is not None and _is_logger_shaped(_class_method_names(body, src)):
                logger_classes.add(_text(name_node, src))

        if node.type in ("lexical_declaration", "variable_declaration"):
            for decl in node.named_children:
                if decl.type != "variable_declarator":
                    continue
                name_node = decl.child_by_field_name("name")
                value_node = decl.child_by_field_name("value")
                if name_node is None or name_node.type != "identifier" or value_node is None:
                    continue
                local = _text(name_node, src)

                if value_node.type == "object" and _is_logger_shaped(_object_property_names(value_node, src)):
                    known_loggers[local] = ("custom_wrapper", rel_path)
                    continue

                if value_node.type == "new_expression":
                    ctor = value_node.child_by_field_name("constructor")
                    if ctor is not None and ctor.type == "identifier" and _text(ctor, src) in logger_classes:
                        known_loggers[local] = ("custom_wrapper", rel_path)
                    continue

                if value_node.type == "call_expression":
                    func = value_node.child_by_field_name("function")
                    if func is None:
                        continue
                    if func.type == "identifier" and _text(func, src) in local_logging_import:
                        # e.g. `const logger = pino();` or a named-imported
                        # `createLogger()` called directly.
                        known_loggers[local] = ("custom_wrapper", import_module[_text(func, src)])
                    elif func.type == "member_expression":
                        obj = func.child_by_field_name("object")
                        prop = func.child_by_field_name("property")
                        if (obj is not None and obj.type == "identifier" and _text(obj, src) in local_logging_import
                                and prop is not None and _text(prop, src) == "createLogger"):
                            # e.g. `const logger = winston.createLogger(...);`
                            known_loggers[local] = ("custom_wrapper", import_module[_text(obj, src)])

        for c in node.children:
            walk(c)

    walk(root)


def _scan_otel_and_metrics(root, src, rel_path, ids, otel_usage, metrics):
    for child in root.children:
        if child.type != "import_statement":
            continue
        source_node = child.child_by_field_name("source")
        if source_node is None:
            continue
        module = _text(source_node, src)[1:-1]
        if module.startswith(OTEL_PACKAGE_PREFIX):
            otel_usage.append({"id": ids.next("otel"), "file": rel_path, "line": _line(child), "package": module})
        norm = _METRICS_PACKAGES.get(module)
        if norm:
            metrics.append({"id": ids.next("metrics"), "file": rel_path, "line": _line(child), "library": norm})


def _catch_pattern(catch_clause, src):
    """reraised > logged > swallowed, same precedence Python's own
    _except_pattern uses. Receiver-agnostic on purpose (mirrors Python):
    ANY call whose method name is a recognized log-level name counts,
    whether or not the receiver itself resolved to a tracked logger --
    the existing telemetry_scanner.py module already accepts this same
    coarseness for `except` bodies."""
    body = catch_clause.child_by_field_name("body")
    if body is None:
        return "swallowed"

    found_throw = [False]
    found_methods = []

    def walk(node):
        if node.type == "throw_statement":
            found_throw[0] = True
        if node.type == "call_expression":
            func = node.child_by_field_name("function")
            if func is not None and func.type == "member_expression":
                prop = func.child_by_field_name("property")
                if prop is not None:
                    found_methods.append(_text(prop, src))
        for c in node.children:
            walk(c)

    walk(body)
    if found_throw[0]:
        return "reraised"
    if any(m in _LOG_METHOD_TO_LEVEL for m in found_methods):
        return "logged"
    return "swallowed"


def _scan_calls_and_catches(root, src, rel_path, known_loggers, ids, loggers, error_handling):
    def walk(node):
        if node.type == "call_expression":
            func = node.child_by_field_name("function")
            if func is not None and func.type == "member_expression":
                obj = func.child_by_field_name("object")
                prop = func.child_by_field_name("property")
                if obj is not None and prop is not None and obj.type == "identifier":
                    obj_name = _text(obj, src)
                    method = _text(prop, src)
                    if obj_name == "console" and method in _LOG_METHOD_TO_LEVEL:
                        loggers.append({
                            "id": ids.next("log"), "file": rel_path, "line": _line(node),
                            "level": _LOG_METHOD_TO_LEVEL[method], "logger_kind": "print",
                        })
                    elif obj_name in known_loggers and method in _LOG_METHOD_TO_LEVEL:
                        kind, wrapper_module = known_loggers[obj_name]
                        entry = {
                            "id": ids.next("log"), "file": rel_path, "line": _line(node),
                            "level": _LOG_METHOD_TO_LEVEL[method], "logger_kind": kind,
                        }
                        if wrapper_module:
                            entry["wrapper_module"] = wrapper_module
                        loggers.append(entry)

        if node.type == "catch_clause":
            error_handling.append({
                "id": ids.next("err"), "file": rel_path, "line": _line(node),
                "pattern": _catch_pattern(node, src),
            })

        for c in node.children:
            walk(c)

    walk(root)


def _empty_result(collect_exports):
    empty = {"loggers": [], "existing_otel_usage": [], "metrics_libraries": [], "error_handling": []}
    return (empty, {}, []) if collect_exports else empty


def scan_file(path, repo_root, ids, seed_known_loggers=None, collect_exports=False):
    """`seed_known_loggers`/`collect_exports` mirror
    typescript_adapter.py's `detect_file` exactly (docs/decisions/032/033):
    the former pre-seeds cross-file-resolved logger bindings before this
    file's own scan runs, the latter additionally returns this file's own
    export_map and raw import list for build_telemetry_inventory's own
    two-pass repo scan."""
    path = Path(path)
    try:
        src = path.read_bytes()
    except OSError:
        return _empty_result(collect_exports)
    parser = Parser(_LANGUAGE)
    try:
        tree = parser.parse(src)
    except Exception:
        return _empty_result(collect_exports)

    root = tree.root_node
    rel_path = str(path.relative_to(repo_root)) if repo_root else str(path)
    imports = _collect_imports(root, src)
    known_loggers = dict(seed_known_loggers) if seed_known_loggers else {}
    _prescan_logger_shapes(root, src, rel_path, imports, known_loggers)

    loggers, otel_usage, metrics, error_handling = [], [], [], []
    _scan_otel_and_metrics(root, src, rel_path, ids, otel_usage, metrics)
    _scan_calls_and_catches(root, src, rel_path, known_loggers, ids, loggers, error_handling)

    result = {
        "loggers": loggers, "existing_otel_usage": otel_usage,
        "metrics_libraries": metrics, "error_handling": error_handling,
    }
    if collect_exports:
        return result, collect_export_map(root, src, known_loggers), imports
    return result


def _scannable_files(repo_root):
    """Same exclusions typescript_adapter.py's own _scannable_files uses
    (node_modules/.git/dist/tests, test-named files) -- kept as an
    independent copy rather than a shared import, since S1 and S2 have
    genuinely separate reasons to exclude the same directories and no
    actual coupling between the two lists."""
    files = []
    for f in sorted(Path(repo_root).rglob("*.ts")) + sorted(Path(repo_root).rglob("*.tsx")):
        rel = f.relative_to(repo_root)
        parts = rel.parts
        if "node_modules" in parts or ".git" in parts or "dist" in parts or "tests" in parts:
            continue
        if f.name.startswith("test_") or ".test." in f.name or ".spec." in f.name:
            continue
        files.append(f)
    return files


def build_telemetry_inventory(repo_root, git_sha, harness_version=_OAH_VERSION):
    """Two-pass repo scan, same shape as typescript_adapter.py's
    detect_repo (docs/decisions/032): pass 1 builds a repo-wide
    {resolved_file: export_map} index plus each file's own raw imports
    (its own loggers/etc. thrown away -- pass 1 exists only to see far
    enough into each file's known_loggers to resolve its exports); pass 2
    resolves each file's imports against that index, seeds any hit, and
    runs the real scan."""
    repo_root = Path(repo_root)
    files = _scannable_files(repo_root)
    base_url, paths = load_path_aliases(repo_root)

    exports_index = {}
    imports_by_file = {}
    for f in files:
        _, export_map, import_specs = scan_file(f, repo_root, Ids(), collect_exports=True)
        imports_by_file[f] = import_specs
        if export_map:
            exports_index[f.resolve()] = export_map

    ids = Ids()
    loggers, otel_usage, metrics, error_handling = [], [], [], []
    for f in files:
        seed = {}
        for local, original, module_spec, is_default in imports_by_file[f]:
            resolved_file = resolve_module_specifier(module_spec, f, repo_root, base_url, paths)
            if resolved_file is None:
                continue
            export_map = exports_index.get(resolved_file)
            if export_map is None:
                continue
            hit = export_map.get("default" if is_default else original)
            if hit is not None:
                seed[local] = hit
        result = scan_file(f, repo_root, ids, seed_known_loggers=seed)
        loggers.extend(result["loggers"])
        otel_usage.extend(result["existing_otel_usage"])
        metrics.extend(result["metrics_libraries"])
        error_handling.extend(result["error_handling"])

    # Manifest-declared, not source-confirmed -- same separate evidence
    # tier telemetry_scanner.py's own build_telemetry_inventory documents.
    vendor_dependencies = scan_package_json(repo_root, ids)

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
            "has_commercial_apm": any(
                v["category"] == "apm_tracing" and v["vendor"] != "opentelemetry"
                for v in vendor_dependencies
            ),
        },
    }
