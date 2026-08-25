"""S1 deterministic pass for Python — tree-sitter based, per SP10's decision
(docs/decisions/004-sp10-multilang-architecture.md): pure-Python dependency,
no second language runtime, at the cost of a small per-language grammar
profile rather than reusing one AST module across languages.

Three-phase design validated at 100% recall in the SP1 spike
(docs/decisions/003-sp1-ast-recall.md) against a real 3-repo corpus, carried
over here unchanged in shape, reimplemented against tree-sitter's node API:

1. Resolve import aliases (both `import X [as Y]` and `from X import Y [as Z]`).
2. Prescan "known client" bindings: module/function-scope assignments and
   class-scoped `self.attr` constructions (SP1's class prescan trick — done
   once per class so method definition order doesn't matter).
3. Walk call sites; suffix-match the last two attribute-chain segments
   against the registry, then resolve the receiver through phases 1-2.

Uses NO generators (`yield from`) — SP1's prototype had a real bug where two
recursive calls were missing `yield from` and silently dropped every result
found inside a function or class body. Accumulating into a plain list
instead removes that entire bug class structurally, not just fixes the one
instance.
"""
from pathlib import Path

import tree_sitter_python as tspython
from tree_sitter import Language, Parser

from oah.discovery.registry import (
    CONSTRUCTOR_NAMES, SDK_MODULE, METHOD_SUFFIXES, SURFACE_KIND, FRAMEWORK,
)

_LANGUAGE = Language(tspython.language())


def _text(node, src):
    return src[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


def _line(node):
    return node.start_point[0] + 1  # tree-sitter rows are 0-indexed


class ImportResolver:
    def __init__(self):
        self.module_alias = {}   # local name -> dotted module path
        self.name_alias = {}     # local name -> (module, original_name)

    def visit_import_statement(self, node, src):
        for child in node.named_children:
            if child.type == "dotted_name":
                text = _text(child, src)
                self.module_alias[text.split(".")[0]] = text
            elif child.type == "aliased_import":
                name_node = child.child_by_field_name("name")
                alias_node = child.child_by_field_name("alias")
                if name_node is not None and alias_node is not None:
                    self.module_alias[_text(alias_node, src)] = _text(name_node, src)

    def visit_import_from_statement(self, node, src):
        module_node = node.child_by_field_name("module_name")
        module = _text(module_node, src) if module_node is not None else ""
        for child in node.named_children:
            # `is` doesn't work here: tree-sitter's Python bindings create a
            # fresh wrapper object per access, so the same underlying node
            # reached via child_by_field_name() vs. named_children iteration
            # compares unequal by identity. `==` compares correctly (verified
            # directly against this binding, not assumed).
            if child == module_node:
                continue
            if child.type == "dotted_name":
                name = _text(child, src)
                if name in CONSTRUCTOR_NAMES:
                    self.name_alias[name] = (module, name)
            elif child.type == "aliased_import":
                name_node = child.child_by_field_name("name")
                alias_node = child.child_by_field_name("alias")
                if name_node is None or alias_node is None:
                    continue
                original = _text(name_node, src)
                if original in CONSTRUCTOR_NAMES:
                    self.name_alias[_text(alias_node, src)] = (module, original)

    def resolve_constructor_call(self, call_node, src):
        """Return (module, ctor_name) if call_node constructs a known SDK
        client via either import form, else None."""
        func = call_node.child_by_field_name("function")
        if func is None:
            return None
        if func.type == "attribute":
            obj = func.child_by_field_name("object")
            attr = func.child_by_field_name("attribute")
            if obj is not None and obj.type == "identifier" and attr is not None:
                module = self.module_alias.get(_text(obj, src))
                attr_text = _text(attr, src)
                if module and attr_text in CONSTRUCTOR_NAMES:
                    return (module, attr_text)
        elif func.type == "identifier":
            hit = self.name_alias.get(_text(func, src))
            if hit:
                return hit
        return None

    def annotation_sdk(self, type_node, src):
        """Resolve a `typed_parameter`'s type expression to an SDK module
        name, else None. Handles `anthropic.Anthropic` and bare `Anthropic`
        (from-import) forms."""
        if type_node is None:
            return None
        # `type` wraps the actual expression; unwrap if present.
        node = type_node
        if node.type == "type" and node.named_child_count == 1:
            node = node.named_children[0]
        if node.type == "attribute":
            obj = node.child_by_field_name("object")
            attr = node.child_by_field_name("attribute")
            if obj is not None and obj.type == "identifier" and attr is not None:
                module = self.module_alias.get(_text(obj, src))
                if module and _text(attr, src) in CONSTRUCTOR_NAMES:
                    return module
        elif node.type == "identifier":
            hit = self.name_alias.get(_text(node, src))
            if hit:
                return hit[0]
        return None


def _flatten_attribute_chain(node, src):
    """attribute(attribute(Name('client'),'messages'),'create') ->
    ('client', ['messages', 'create'])."""
    parts = []
    while node.type == "attribute":
        attr = node.child_by_field_name("attribute")
        obj = node.child_by_field_name("object")
        if attr is None or obj is None:
            return None, parts
        parts.append(_text(attr, src))
        node = obj
    parts.reverse()
    if node.type == "identifier":
        return _text(node, src), parts
    return None, parts


class KnownNames:
    def __init__(self):
        self.module_scope = {}
        self.self_attrs = {}  # (class_name, attr_name) -> sdk_module

    def prescan_self_attrs(self, root, resolver, src):
        def walk(node, class_name):
            local_class = class_name
            if node.type == "class_definition":
                name_node = node.child_by_field_name("name")
                if name_node is not None:
                    local_class = _text(name_node, src)
            if node.type == "assignment":
                left = node.child_by_field_name("left")
                right = node.child_by_field_name("right")
                if left is not None and right is not None and right.type == "call":
                    hit = resolver.resolve_constructor_call(right, src)
                    if hit and hit[0] == SDK_MODULE and left.type == "attribute":
                        obj = left.child_by_field_name("object")
                        attr = left.child_by_field_name("attribute")
                        if (
                            obj is not None and obj.type == "identifier"
                            and _text(obj, src) == "self"
                            and attr is not None and local_class
                        ):
                            self.self_attrs[(local_class, _text(attr, src))] = hit[0]
            for child in node.children:
                walk(child, local_class)

        walk(root, None)


def _drop_none(d):
    """schemas/surface_map.schema.json's optional fields are typed as plain
    `string` (not `["string","null"]`) — a Python None serializes to JSON
    null, which fails validation. Omitting the key is the schema-correct
    way to say "unknown", not including it as null."""
    return {k: v for k, v in d.items() if v is not None}


def _excerpt(src_lines, line, before=3, after=3):
    """Bounded surrounding code around `line` (1-indexed) — data for the LLM
    disambiguation pass, never instructions (skills/s1-surface-mapper/SKILL.md's
    own hard rule; this function exists so that boundary is enforced by what
    gets extracted, not left to the skill to self-police)."""
    start = max(0, line - 1 - before)
    end = min(len(src_lines), line + after)
    return "\n".join(src_lines[start:end])


def _walk_calls(node, src, src_lines, resolver, known, class_name, symbol, local_scope,
                 resolved_points, ambiguous, rel_path, next_id, imports):
    """Depth-first walk accumulating into two separate lists — no generators,
    so there is no `yield from` to forget (see module docstring).

    Two outputs, not one, because schemas/surface_map.schema.json's `kind`
    enum has no `null` member: a genuinely unresolved candidate is not a
    surface_map point with a null kind, it's an item for the LLM
    disambiguation pass (skills/s1-surface-mapper), whose own
    io/output.schema.json is where `kind: null` is a valid, meaningful
    answer ("genuinely none of these"). Conflating the two would either
    violate the schema or silently smuggle an unresolved candidate into the
    pipeline's source-of-truth artifact as if S1 were done with it.
    """
    for child in node.children:
        if child.type == "class_definition":
            name_node = child.child_by_field_name("name")
            new_class = _text(name_node, src) if name_node is not None else class_name
            _walk_calls(child, src, src_lines, resolver, known, new_class, symbol, dict(local_scope),
                        resolved_points, ambiguous, rel_path, next_id, imports)
            continue

        if child.type == "function_definition":
            fn_scope = dict(local_scope)
            name_node = child.child_by_field_name("name")
            fn_name = _text(name_node, src) if name_node is not None else "<anonymous>"
            new_symbol = f"{class_name}.{fn_name}" if class_name else fn_name
            params = child.child_by_field_name("parameters")
            if params is not None:
                for p in params.named_children:
                    if p.type == "typed_parameter":
                        name_node = p.named_children[0] if p.named_children else None
                        type_node = p.child_by_field_name("type")
                        sdk = resolver.annotation_sdk(type_node, src)
                        if sdk and name_node is not None:
                            fn_scope[_text(name_node, src)] = sdk
            _walk_calls(child, src, src_lines, resolver, known, class_name, new_symbol, fn_scope,
                        resolved_points, ambiguous, rel_path, next_id, imports)
            continue

        if child.type == "assignment":
            left = child.child_by_field_name("left")
            right = child.child_by_field_name("right")
            if left is not None and right is not None and right.type == "call":
                hit = resolver.resolve_constructor_call(right, src)
                if hit and left.type == "identifier":
                    local_scope[_text(left, src)] = hit[0]

        if child.type == "call":
            func = child.child_by_field_name("function")
            if func is not None and func.type == "attribute":
                root, chain = _flatten_attribute_chain(func, src)
                if len(chain) >= 2 and tuple(chain[-2:]) in METHOD_SUFFIXES:
                    if root is None:
                        resolved, receiver_desc = None, "<unresolved receiver expression>"
                    elif root == "self" and chain:
                        receiver_attr = chain[0]
                        resolved = known.self_attrs.get((class_name, receiver_attr)) if class_name else None
                        receiver_desc = f"self.{receiver_attr}"
                    else:
                        resolved = local_scope.get(root)
                        receiver_desc = root

                    line = _line(child)
                    candidate_id = f"sp-{next_id[0]:04d}"
                    if resolved == SDK_MODULE:
                        resolved_points.append(_drop_none({
                            "id": candidate_id,
                            "kind": SURFACE_KIND,
                            "file": rel_path,
                            "line": line,
                            "symbol": symbol,
                            "framework": FRAMEWORK,
                            "detection": "signature",
                            "confidence": 0.95,
                            "notes": f"receiver '{receiver_desc}' resolved via import/assignment/annotation tracking",
                        }))
                        next_id[0] += 1
                    elif resolved is None:
                        candidate = {
                            "candidate_id": candidate_id,
                            "file": rel_path,
                            "line": line,
                            "code_excerpt": _excerpt(src_lines, line),
                            "scanner_kind": None,
                            "scanner_confidence": 0.3,
                            "imports": imports,
                        }
                        if symbol is not None:
                            candidate["symbol"] = symbol
                        ambiguous.append(candidate)
                        next_id[0] += 1
                    # resolved to a different SDK -> true negative, not reported.

        _walk_calls(child, src, src_lines, resolver, known, class_name, symbol, local_scope,
                    resolved_points, ambiguous, rel_path, next_id, imports)


def detect_file(path, repo_root, next_id):
    """Return (resolved_points, ambiguous_candidates) for one Python file.

    resolved_points are already surface_map-point-shaped (kind is never
    null). ambiguous_candidates match skills/s1-surface-mapper/io/input.schema.json
    exactly — the batch a real disambiguation pass would consume."""
    path = Path(path)
    try:
        src = path.read_bytes()
    except OSError:
        return [], []
    parser = Parser(_LANGUAGE)
    try:
        tree = parser.parse(src)
    except Exception:
        return [], []

    resolver = ImportResolver()

    def collect_imports(node):
        if node.type == "import_statement":
            resolver.visit_import_statement(node, src)
        elif node.type == "import_from_statement":
            resolver.visit_import_from_statement(node, src)
        for child in node.children:
            collect_imports(child)

    collect_imports(tree.root_node)

    known = KnownNames()
    known.prescan_self_attrs(tree.root_node, resolver, src)

    rel_path = str(path.relative_to(repo_root)) if repo_root else str(path)
    src_lines = src.decode("utf-8", errors="replace").split("\n")
    imports = sorted(set(resolver.module_alias.values()) | {m for m, _ in resolver.name_alias.values()})

    resolved_points, ambiguous = [], []
    _walk_calls(tree.root_node, src, src_lines, resolver, known, None, None, known.module_scope,
                resolved_points, ambiguous, rel_path, next_id, imports)
    return resolved_points, ambiguous


def detect_repo(repo_root):
    """Scan every .py file under repo_root (excluding tests/, matching SP1's
    exclusion). Returns (resolved_points, ambiguous_candidates) across the
    whole repo."""
    repo_root = Path(repo_root)
    next_id = [1]
    resolved_points, ambiguous = [], []
    for f in sorted(repo_root.rglob("*.py")):
        if "/tests/" in str(f) or f.name.startswith("test_"):
            continue
        r, a = detect_file(f, repo_root, next_id)
        resolved_points.extend(r)
        ambiguous.extend(a)
    return resolved_points, ambiguous


def build_surface_map(repo_root, git_sha, disambiguated=None, harness_version="0.1.0"):
    """Assemble the document conforming to schemas/surface_map.schema.json.

    `disambiguated`, if given, is a list of skills/s1-surface-mapper's
    io/output.schema.json `results` entries (candidate_id, kind, ...) for
    the ambiguous candidates this run's disambiguation pass resolved —
    merged in as points, skipping any the skill itself rejected (kind: null
    is a correct answer there, but per schemas/surface_map.schema.json's
    enum, still not a valid surface_map point). Candidates with no matching
    disambiguation result yet are simply absent from `points` — S1 isn't
    done with them, and the surface_map correctly doesn't claim it is.
    """
    resolved_points, ambiguous = detect_repo(repo_root)
    ambiguous_by_id = {c["candidate_id"]: c for c in ambiguous}

    # Every candidate_id disambiguation actually returned a verdict for is
    # "processed" regardless of accept/reject — a rejection (kind: null) is
    # a correct, final answer (SKILL.md), not a reason to keep resending the
    # same candidate. Only candidates disambiguation never saw stay pending.
    processed_ids = set()
    if disambiguated:
        for result in disambiguated:
            candidate = ambiguous_by_id.get(result["candidate_id"])
            if candidate is None:
                continue
            processed_ids.add(result["candidate_id"])
            if result.get("kind") is None:
                continue
            resolved_points.append(_drop_none({
                "id": result["candidate_id"],
                "kind": result["kind"],
                "file": candidate["file"],
                "line": candidate["line"],
                "symbol": candidate.get("symbol"),
                "framework": result.get("framework"),
                "sync_nature": result.get("sync_nature"),
                "detection": "llm_disambiguation",
                "confidence": result["confidence"],
                "notes": result.get("notes"),
                "workflow_hint": result.get("workflow_hint"),
            }))

    still_ambiguous = [c for c in ambiguous if c["candidate_id"] not in processed_ids]

    files_scanned = sum(
        1 for f in Path(repo_root).rglob("*.py")
        if "/tests/" not in str(f) and not f.name.startswith("test_")
    )
    surface_map = {
        "schema_version": "0.1.0",
        "repo": {"path": str(repo_root), "git_sha": git_sha, "primary_language": "python"},
        "generated_by": {
            "harness_version": harness_version,
            "skill_versions": {"s1-surface-mapper": "0.1.0"},
        },
        "points": resolved_points,
        "coverage_stats": {
            "files_scanned": files_scanned,
            "points_total": len(resolved_points),
            "points_llm_disambiguated": sum(1 for p in resolved_points if p["detection"] == "llm_disambiguation"),
        },
    }
    return surface_map, still_ambiguous
