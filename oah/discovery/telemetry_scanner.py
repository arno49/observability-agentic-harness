"""S2 deterministic pass: existing telemetry inventory (architecture.md S2).

Same tree-sitter/Python foundation as S1's python_adapter.py, not a
different tool per file type — a repo gets parsed once conceptually per
adapter, same grammar. Detects: logger call sites (stdlib `logging` and a
lightweight "custom wrapper" heuristic — a module-level name bound from a
function literally named get_logger/getLogger), existing OTel package
imports, known metrics-library imports, and error-handling classification
(swallowed / logged / reraised) for every `except` clause in the repo.

LOG_LEVELS / METRICS_LIBRARIES / OTEL_PACKAGE_PREFIXES are the S2 analogue
of S1's registry.py — a short, explicit list, not an attempt at exhaustive
coverage; extending it is a one-line change, not a design change.
"""
from pathlib import Path

import tree_sitter_python as tspython
from tree_sitter import Language, Parser

_LANGUAGE = Language(tspython.language())

LOG_LEVELS = {"debug", "info", "warning", "error", "critical", "exception"}
METRICS_LIBRARIES = {"prometheus_client", "statsd", "datadog", "ddtrace"}
OTEL_PACKAGE_PREFIX = "opentelemetry"


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


def _find_logger_bindings(root, src):
    """Names bound to a logger, either stdlib (`logging.getLogger(...)`) or
    a custom wrapper (any call to a function literally named
    get_logger/getLogger, imported from elsewhere — the module it came from
    is recorded, not assumed)."""
    bindings = {}  # local name -> ("stdlib_logging"|"custom_wrapper", module_or_None)
    wrapper_import_module = {}  # local func name -> module it was imported from

    def scan_imports(node):
        if node.type == "import_from_statement":
            module_node = node.child_by_field_name("module_name")
            module = _text(module_node, src) if module_node is not None else ""
            for child in node.named_children:
                # `is` doesn't work here — see python_adapter.py's identical
                # comment; tree-sitter-python creates a fresh wrapper object
                # per access, so `==` is required for same-node comparison.
                if child == module_node:
                    continue
                if child.type == "dotted_name":
                    name = _text(child, src)
                    if name in ("get_logger", "getLogger"):
                        wrapper_import_module[name] = module
                elif child.type == "aliased_import":
                    name_node = child.child_by_field_name("name")
                    alias_node = child.child_by_field_name("alias")
                    if name_node is not None and _text(name_node, src) in ("get_logger", "getLogger"):
                        wrapper_import_module[_text(alias_node, src)] = module
        for c in node.children:
            scan_imports(c)

    scan_imports(root)

    def scan_assignments(node):
        if node.type == "assignment":
            left = node.child_by_field_name("left")
            right = node.child_by_field_name("right")
            if left is not None and right is not None and right.type == "call" and left.type == "identifier":
                func = right.child_by_field_name("function")
                if func is not None:
                    if func.type == "attribute":
                        obj = func.child_by_field_name("object")
                        attr = func.child_by_field_name("attribute")
                        if (obj is not None and attr is not None
                                and _text(obj, src) == "logging" and _text(attr, src) == "getLogger"):
                            bindings[_text(left, src)] = ("stdlib_logging", None)
                    elif func.type == "identifier":
                        fname = _text(func, src)
                        if fname in wrapper_import_module:
                            bindings[_text(left, src)] = ("custom_wrapper", wrapper_import_module[fname])
        for c in node.children:
            scan_assignments(c)

    scan_assignments(root)
    return bindings


def _except_pattern(except_clause, src):
    """Classify one except_clause's body: reraised > logged > swallowed."""
    block = None
    for c in except_clause.children:
        if c.type == "block":
            block = c
    if block is None:
        return "swallowed"

    found_raise = [False]
    found_call = []

    def walk(node):
        if node.type == "raise_statement":
            found_raise[0] = True
        if node.type == "call":
            func = node.child_by_field_name("function")
            if func is not None and func.type == "attribute":
                attr = func.child_by_field_name("attribute")
                if attr is not None:
                    found_call.append(_text(attr, src))
        for c in node.children:
            walk(c)

    walk(block)
    if found_raise[0]:
        return "reraised"
    if any(name in LOG_LEVELS or name == "warn" for name in found_call):
        return "logged"
    return "swallowed"


def _exception_type_text(except_clause, src):
    for c in except_clause.named_children:
        if c.type == "identifier":
            return _text(c, src)
        if c.type == "as_pattern":
            inner = c.named_children[0] if c.named_children else None
            return _text(inner, src) if inner is not None else None
        if c.type == "tuple":
            return _text(c, src)
    return None


def scan_file(path, repo_root, ids):
    path = Path(path)
    try:
        src = path.read_bytes()
    except OSError:
        return {"loggers": [], "existing_otel_usage": [], "metrics_libraries": [], "error_handling": []}
    parser = Parser(_LANGUAGE)
    try:
        tree = parser.parse(src)
    except Exception:
        return {"loggers": [], "existing_otel_usage": [], "metrics_libraries": [], "error_handling": []}

    rel_path = str(path.relative_to(repo_root)) if repo_root else str(path)
    logger_bindings = _find_logger_bindings(tree.root_node, src)

    loggers, otel_usage, metrics, error_handling = [], [], [], []

    def enclosing_symbol_stack(node):
        # Not tracked here for S2 (kept intentionally simpler than S1's
        # scope tracking) — file/line is enough to locate a finding.
        return None

    def walk(node):
        if node.type in ("import_statement", "import_from_statement"):
            module_node = node.child_by_field_name("module_name") if node.type == "import_from_statement" else None
            targets = [module_node] if module_node is not None else []
            for c in node.named_children:
                if c == module_node:
                    continue
                if c.type == "dotted_name":
                    targets.append(c)
                elif c.type == "aliased_import":
                    name_node = c.child_by_field_name("name")
                    if name_node is not None:
                        targets.append(name_node)
            for t in targets:
                text = _text(t, src)
                if text.startswith(OTEL_PACKAGE_PREFIX):
                    otel_usage.append({
                        "id": ids.next("otel"), "file": rel_path, "line": _line(node), "package": text,
                    })
                top = text.split(".")[0]
                if top in METRICS_LIBRARIES:
                    metrics.append({
                        "id": ids.next("metrics"), "file": rel_path, "line": _line(node), "library": top,
                    })

        if node.type == "call":
            func = node.child_by_field_name("function")
            if func is not None and func.type == "attribute":
                obj = func.child_by_field_name("object")
                attr = func.child_by_field_name("attribute")
                if obj is not None and obj.type == "identifier" and attr is not None:
                    obj_name, level = _text(obj, src), _text(attr, src)
                    if level in LOG_LEVELS and obj_name in logger_bindings:
                        kind, wrapper_module = logger_bindings[obj_name]
                        entry = {
                            "id": ids.next("log"), "file": rel_path, "line": _line(node),
                            "level": level, "logger_kind": kind,
                        }
                        if wrapper_module:
                            entry["wrapper_module"] = wrapper_module
                        loggers.append(entry)
            elif func is not None and func.type == "identifier" and _text(func, src) == "print":
                loggers.append({
                    "id": ids.next("log"), "file": rel_path, "line": _line(node),
                    "level": "info", "logger_kind": "print",
                })

        if node.type == "except_clause":
            entry = {
                "id": ids.next("err"), "file": rel_path, "line": _line(node),
                "pattern": _except_pattern(node, src),
            }
            exc_type = _exception_type_text(node, src)
            if exc_type:
                entry["exception_type"] = exc_type
            error_handling.append(entry)

        for c in node.children:
            walk(c)

    walk(tree.root_node)
    return {
        "loggers": loggers, "existing_otel_usage": otel_usage,
        "metrics_libraries": metrics, "error_handling": error_handling,
    }


def build_telemetry_inventory(repo_root, git_sha, harness_version="0.1.0"):
    repo_root = Path(repo_root)
    ids = Ids()
    loggers, otel_usage, metrics, error_handling = [], [], [], []
    files_scanned = 0
    for f in sorted(repo_root.rglob("*.py")):
        if "/tests/" in str(f) or f.name.startswith("test_"):
            continue
        files_scanned += 1
        result = scan_file(f, repo_root, ids)
        loggers.extend(result["loggers"])
        otel_usage.extend(result["existing_otel_usage"])
        metrics.extend(result["metrics_libraries"])
        error_handling.extend(result["error_handling"])

    return {
        "schema_version": "0.1.0",
        "repo": {"path": str(repo_root), "git_sha": git_sha},
        "generated_by": {"harness_version": harness_version},
        "loggers": loggers,
        "existing_otel_usage": otel_usage,
        "metrics_libraries": metrics,
        "error_handling": error_handling,
        "summary": {
            "files_scanned": files_scanned,
            "logger_call_sites": len(loggers),
            "swallowed_exceptions": sum(1 for e in error_handling if e["pattern"] == "swallowed"),
            "has_existing_otel": len(otel_usage) > 0,
        },
    }
