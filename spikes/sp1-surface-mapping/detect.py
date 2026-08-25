#!/usr/bin/env python3
"""AST + signature-registry detector for raw-Anthropic-SDK call sites.

Spike prototype for SP1 (ROADMAP.md) — see README.md. Not E2's production
S1 implementation.

Usage:
    python3 detect.py <file_or_directory> [<file_or_directory> ...]

Prints one JSON object per line to stdout, one per candidate call site:
    {"file": ..., "line": ..., "confidence": "high"|"low",
     "resolved_sdk": "anthropic"|null, "chain": "...", "reason": "..."}

Design (see decision record for the reasoning, not just the mechanism):

1. Resolve import aliases (`import anthropic as X`, `from anthropic import
   Anthropic as Y`) so `X.Anthropic(...)` and `Y(...)` are both recognized
   as SDK constructors regardless of local naming.
2. Track which names are "known clients" of which SDK, via a single
   deliberately lightweight data-flow pass — not full type inference:
   - `name = <constructor>()` at module or function scope,
   - `self.attr = <constructor>()` anywhere in a class body (pre-scanned
     once per class, so method definition order doesn't matter),
   - a function/method parameter annotated with a constructor name.
   A name resolves to whichever SDK's constructor it was last assigned
   from in this pass — including SDKs *other* than Anthropic, so a call
   shaped like `client.messages.create(...)` where `client` is provably an
   `ollama.AsyncClient` resolves to "ollama", not "anthropic", and is
   correctly excluded rather than reported as a false positive.
3. Walk every Call node. If its attribute chain's last two segments match
   a registered method suffix (suffix match, not exact path — see
   registry.py), resolve the receiver:
   - resolves to "anthropic" -> high confidence, reported;
   - resolves to something else -> excluded, not reported;
   - unresolved (no assignment or annotation found for that name in this
     file) -> low confidence, reported with resolved_sdk: null, meant to
     route to the LLM disambiguation pass.
"""
import ast
import json
import sys
from pathlib import Path

from registry import CONSTRUCTOR_NAMES, METHOD_SUFFIXES, SDK_MODULE


def _flatten_attribute_chain(node):
    """Attribute(Attribute(Name('client'),'a'),'b') -> ('client', ['a','b'])."""
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    parts.reverse()
    if isinstance(node, ast.Name):
        return node.id, parts
    return None, parts


class ImportResolver:
    """Maps local names to (sdk_module, constructor_name) for constructor calls."""

    def __init__(self):
        # local_name -> sdk module name, for `import anthropic [as X]`
        self.module_alias = {}
        # local_name -> (sdk_module, constructor_name), for
        # `from anthropic import Anthropic [as Y]`
        self.name_alias = {}

    def visit_import(self, node):
        for alias in node.names:
            self.module_alias[alias.asname or alias.name] = alias.name

    def visit_import_from(self, node):
        module = node.module or ""
        for alias in node.names:
            local = alias.asname or alias.name
            if alias.name in CONSTRUCTOR_NAMES:
                self.name_alias[local] = (module, alias.name)

    def resolve_constructor_call(self, call_node):
        """Return (sdk_module, constructor_name) if call_node constructs a
        known SDK client, else None. Handles both `anthropic.Anthropic(...)`
        and `Anthropic(...)` (from-import) forms, plus arbitrary import
        aliases for either."""
        func = call_node.func
        if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
            module = self.module_alias.get(func.value.id)
            if module and func.attr in CONSTRUCTOR_NAMES:
                return (module, func.attr)
        elif isinstance(func, ast.Name):
            hit = self.name_alias.get(func.id)
            if hit:
                return hit
        return None


class KnownNames:
    """Tracks which local names / self-attrs resolve to which SDK, per file."""

    def __init__(self):
        self.module_scope = {}          # name -> sdk_module
        self.self_attrs = {}            # (class_name, attr_name) -> sdk_module

    def prescan_self_attrs(self, tree, resolver):
        """Class body pre-scan: `self.X = <constructor>()` anywhere in a
        class's methods registers (class, X) regardless of method order."""
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            for sub in ast.walk(node):
                if not isinstance(sub, ast.Assign):
                    continue
                if not isinstance(sub.value, ast.Call):
                    continue
                hit = resolver.resolve_constructor_call(sub.value)
                if not hit:
                    continue
                sdk_module, _ctor = hit
                for target in sub.targets:
                    if (
                        isinstance(target, ast.Attribute)
                        and isinstance(target.value, ast.Name)
                        and target.value.id == "self"
                    ):
                        self.self_attrs[(node.name, target.attr)] = sdk_module


def _annotation_sdk(annotation, resolver):
    """Resolve a parameter annotation like `anthropic.Anthropic` or
    `Anthropic` to an SDK module name, else None."""
    if annotation is None:
        return None
    if isinstance(annotation, ast.Attribute) and isinstance(annotation.value, ast.Name):
        module = resolver.module_alias.get(annotation.value.id)
        if module and annotation.attr in CONSTRUCTOR_NAMES:
            return module
    elif isinstance(annotation, ast.Name):
        hit = resolver.name_alias.get(annotation.id)
        if hit:
            return hit[0]
    return None


def detect_file(path):
    """Yield candidate dicts for one Python source file."""
    try:
        source = Path(path).read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
    except (SyntaxError, UnicodeDecodeError):
        return

    resolver = ImportResolver()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            resolver.visit_import(node)
        elif isinstance(node, ast.ImportFrom):
            resolver.visit_import_from(node)

    known = KnownNames()
    known.prescan_self_attrs(tree, resolver)

    def walk_scope(node, class_name, local_scope):
        """Recursive walk carrying a local-scope dict (name -> sdk_module)
        that shadows module_scope, and the enclosing class name (for
        `self.attr` resolution) — a real, if intentionally shallow,
        scoping model rather than one flat namespace."""
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef):
                yield from walk_scope(child, child.name, dict(local_scope))
                continue

            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                fn_scope = dict(local_scope)
                for arg in list(child.args.args) + list(child.args.kwonlyargs):
                    sdk = _annotation_sdk(arg.annotation, resolver)
                    if sdk:
                        fn_scope[arg.arg] = sdk
                yield from walk_scope(child, class_name, fn_scope)
                continue

            if isinstance(child, ast.Assign) and isinstance(child.value, ast.Call):
                hit = resolver.resolve_constructor_call(child.value)
                if hit:
                    sdk_module, _ctor = hit
                    for target in child.targets:
                        if isinstance(target, ast.Name):
                            local_scope[target.id] = sdk_module

            if isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute):
                root, chain = _flatten_attribute_chain(child.func)
                if len(chain) >= 2 and tuple(chain[-2:]) in METHOD_SUFFIXES:
                    if root is None:
                        # Receiver isn't a plain name/self-attr — e.g. a
                        # subscript (`clients["primary"].messages.create`)
                        # or a call result. The method-name suffix still
                        # matches, so this is reported, not silently
                        # dropped — just unresolvable at low confidence
                        # rather than excluded as a different SDK.
                        resolved = None
                        receiver_desc = "<unresolved receiver expression>"
                    elif root == "self" and chain:
                        # self.<attr>.<...method suffix>: the receiver is
                        # the self-attribute, not `self` itself.
                        receiver_attr = chain[0]
                        resolved = known.self_attrs.get((class_name, receiver_attr)) if class_name else None
                        receiver_desc = f"self.{receiver_attr}"
                    else:
                        resolved = local_scope.get(root)
                        receiver_desc = root

                    dotted = ".".join([root or "<expr>"] + chain)
                    if resolved == SDK_MODULE:
                        yield {
                            "file": str(path),
                            "line": child.lineno,
                            "confidence": "high",
                            "resolved_sdk": resolved,
                            "chain": dotted,
                            "reason": f"receiver '{receiver_desc}' resolved to {SDK_MODULE} via assignment/annotation tracking",
                        }
                    elif resolved is not None:
                        pass  # resolved to a different SDK -> true negative, not reported
                    else:
                        yield {
                            "file": str(path),
                            "line": child.lineno,
                            "confidence": "low",
                            "resolved_sdk": None,
                            "chain": dotted,
                            "reason": f"receiver '{receiver_desc}' type unresolved in this file -> needs LLM disambiguation",
                        }

            yield from walk_scope(child, class_name, local_scope)

    yield from walk_scope(tree, None, known.module_scope)


def detect_path(target):
    target = Path(target)
    files = [target] if target.is_file() else sorted(target.rglob("*.py"))
    for f in files:
        if "/tests/" in str(f) or f.name.startswith("test_"):
            continue
        yield from detect_file(f)


if __name__ == "__main__":
    for arg in sys.argv[1:]:
        for candidate in detect_path(arg):
            print(json.dumps(candidate))
