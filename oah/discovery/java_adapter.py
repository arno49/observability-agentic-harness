"""S1 deterministic pass for Java -- tree-sitter based, per SP10's decision
(docs/decisions/004-sp10-multilang-architecture.md): a fresh implementation
of the three-phase shape SP10 validated on two real languages, against
`tree-sitter-java` (verified installable and explored directly against real
Java grammar shapes before designing this module, matching this whole
project's "verify before building" discipline -- not carried over from any
prior spike, since E11's own priority order named Java second, after
TypeScript).

Architecturally closer to oah/discovery/python_adapter.py than to
oah/discovery/typescript_adapter.py: Java's own OOP shape -- explicit class
and field declarations, no closures capturing outer-function locals the way
JS's file-wide model needed (SP10 finding 3 was JS/TS-specific) -- means a
class-scoped known-name prescan (mirroring Python's `KnownNames.self_attrs`)
is the right model here, not TS's file-wide one. One real addition beyond a
blind Python port: Java allows a field to be accessed UNQUALIFIED from
within its own class's instance methods (`client.foo()` inside a method of
the class declaring `private Client client` implicitly means
`this.client.foo()`) -- Python has no equivalent (always explicit `self.`)
and TS/JS classes require explicit `this.` too. `_resolve_root` checks
`known.self_attrs` as a fallback for a bare identifier root not found in
`local_scope`, not just for an explicit `this.<attr>` chain.

Grammar verified directly against `tree_sitter_java` before designing
against it:
- `import_declaration`: a `scoped_identifier` (or bare `identifier` for a
  single-segment import) whose own TEXT is already the dotted path -- no
  structural flattening needed, unlike TS's member-expression chains.
  Carries an optional `static` token child (static-imported members, not
  attempted here) and an optional trailing `.` + `asterisk` (wildcard
  imports, no specific class to resolve -- both are real, named gaps, the
  same honesty precedent as every other adapter's own require()/wildcard
  exclusions).
- `object_creation_expression.type` (`type_identifier` for `new Foo()`,
  `scoped_type_identifier` for `new pkg.Foo()`) + `.arguments`.
- `method_invocation.object`/`.name`/`.arguments` -- Java represents a call
  CHAIN as NESTED method_invocation nodes (`.object` is the inner call),
  not a separate member-expression-then-call split the way JS does, so
  `_flatten_invocation_chain` walks `.object` directly instead of needing
  TS's two-node-type dance.
- `field_declaration`/`local_variable_declaration` both expose `.type` +
  one or more `variable_declarator` children (`.name`/`.value`).
- `field_access.object`/`.field`, with a dedicated `this` node type as a
  valid `.object` value (mirrors TS's own dedicated `this` node type).
- `formal_parameter.type`/`.name` -- Java parameters are always typed
  (no untyped-parameter form to worry about, unlike TS/Python).

Real, verified Java SDK finding that shaped this module's own detector
shapes (a background research agent against the Anthropic/OpenAI Java
SDKs' own README/docs, docs/decisions/029): both construct their client via
a STATIC BUILDER METHOD CHAIN rooted at a known class name
(`AnthropicOkHttpClient.builder().apiKey(...).build()` or `.fromEnv()`),
never `new X()`. `object_creation_expression` support is still real,
general adapter infrastructure (useful for any future SDK that DOES use a
plain constructor), but the first real registry entry needs
`static_builder_chain` (`_resolve_static_builder`), not
`receiver_method_suffix` alone.

One real, named gap found while testing, not silently guessed at:
`_resolve_static_builder` only recognizes a chain whose LAST segment is a
terminal method -- the assign-then-call shape the real SDKs' own README
examples actually use (`AnthropicClient client = AnthropicOkHttpClient
.fromEnv(); ... client.messages().create(params);`). A single, unassigned
expression chaining construction AND the eventual call together
(`AnthropicOkHttpClient.fromEnv().messages().create(params)`, terminal
buried mid-chain rather than at the end) is not resolved -- a real,
deliberately out-of-scope gap for this phase (see
tests/test_java_adapter.py's own regression test for it), not a phase-1
blocker.
"""
from collections import namedtuple
from pathlib import Path

import tree_sitter_java as tsjava
from tree_sitter import Language, Parser

from oah import __version__ as _OAH_VERSION
from oah.discovery.registry import build_registry_index, java_static_builder_index, structural_pattern_registries
from oah.domains.loader import load_pack

_LANGUAGE = Language(tsjava.language())

_RegistryContext = namedtuple(
    "_RegistryContext",
    ["constructor_names", "module_to_registry", "all_method_suffixes", "suffix_lengths", "static_builders"],
)


def _registry_context_for_pack(pack):
    registries, constructor_names, module_to_registry, all_method_suffixes, suffix_lengths = build_registry_index(
        pack, language="java"
    )
    static_builders = java_static_builder_index(pack, language="java")
    return _RegistryContext(constructor_names, module_to_registry, all_method_suffixes, suffix_lengths,
                             static_builders)


_GENAI_PACK = load_pack("genai")
_DEFAULT_REGISTRY_CONTEXT = _registry_context_for_pack(_GENAI_PACK)
REGISTRIES, CONSTRUCTOR_NAMES, MODULE_TO_REGISTRY, ALL_METHOD_SUFFIXES, SUFFIX_LENGTHS = build_registry_index(
    _GENAI_PACK, language="java"
)
STRUCTURAL_PATTERN_REGISTRIES = structural_pattern_registries(_GENAI_PACK, language="java")


def _text(node, src):
    return src[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


def _line(node):
    return node.start_point[0] + 1  # tree-sitter rows are 0-indexed


def _drop_none(d):
    return {k: v for k, v in d.items() if v is not None}


class ImportResolver:
    """name_alias (simple class name -> (package, simple_name)) tracks the
    SDK classes this pack's registries actually care about. Java has no
    import-aliasing syntax (unlike Python's `as`/TS's `as`) -- a class is
    always imported under its own simple name, so this is a single dict,
    simpler than either other adapter's ImportResolver."""

    def __init__(self, constructor_names=CONSTRUCTOR_NAMES):
        self.constructor_names = constructor_names
        self.name_alias = {}

    def visit_import_declaration(self, node, src):
        if any(c.type == "static" for c in node.children):
            return  # static-imported members -- a different resolution problem, not attempted
        if any(c.type == "asterisk" for c in node.children):
            return  # wildcard import -- no specific class to resolve, named gap
        scoped = next((c for c in node.children if c.type in ("scoped_identifier", "identifier")), None)
        if scoped is None:
            return
        fqn = _text(scoped, src)
        simple = fqn.rsplit(".", 1)[-1]
        package = fqn.rsplit(".", 1)[0] if "." in fqn else ""
        if simple in self.constructor_names:
            self.name_alias[simple] = (package, simple)

    def resolve_constructor_call(self, obj_creation_node, src):
        """Return (module, simple_name) if obj_creation_node (an
        object_creation_expression, `new X()`) constructs a known SDK
        client, else None. Real, general adapter infrastructure -- no
        registry in this pack's first real entry actually uses it (the
        real Anthropic/OpenAI Java SDKs are builder-constructed, see
        docs/decisions/029), but a plain-constructor SDK is a real,
        plausible future registry shape this doesn't have to be rebuilt for."""
        type_node = obj_creation_node.child_by_field_name("type")
        if type_node is None:
            return None
        if type_node.type == "type_identifier":
            simple = _text(type_node, src)
        elif type_node.type == "scoped_type_identifier":
            simple = _text(type_node, src).rsplit(".", 1)[-1]
        else:
            return None
        return self.name_alias.get(simple)

    def annotation_sdk(self, type_node, src):
        """Resolve a field/parameter's declared type to an SDK module name,
        else None. Handles a bare `type_identifier` and a package-qualified
        `scoped_type_identifier` (unusual for a field type but real)."""
        if type_node is None:
            return None
        if type_node.type == "type_identifier":
            simple = _text(type_node, src)
        elif type_node.type == "scoped_type_identifier":
            simple = _text(type_node, src).rsplit(".", 1)[-1]
        else:
            return None  # generic_type (e.g. CompletableFuture<X>) and others: not attempted
        hit = self.name_alias.get(simple)
        return hit[0] if hit else None


def _flatten_invocation_chain(node, src):
    """method_invocation(method_invocation(Id('client'),'messages'),'create')
    -> ('client', ['messages', 'create']). Java represents a call chain as
    NESTED method_invocation nodes (`.object` is the inner call), unlike
    JS's member-expression-then-call split -- this walks `.object` directly.
    Returns (None, parts) for an unqualified call (`.object` absent, e.g. a
    bare same-class or statically-imported method call) or a receiver this
    module doesn't resolve (a deeper field_access chain, an array access,
    another method_invocation as object with no name, ...)."""
    parts = []
    while node.type == "method_invocation":
        name = node.child_by_field_name("name")
        obj = node.child_by_field_name("object")
        if name is None:
            return None, parts
        parts.append(_text(name, src))
        if obj is None:
            return None, parts
        node = obj
    parts.reverse()
    if node.type == "identifier":
        return _text(node, src), parts
    if node.type == "field_access":
        obj = node.child_by_field_name("object")
        field = node.child_by_field_name("field")
        if obj is not None and obj.type == "this" and field is not None:
            return f"this.{_text(field, src)}", parts
        return None, parts
    return None, parts


def _match_suffix(chain, registry_ctx):
    for length in registry_ctx.suffix_lengths:
        if len(chain) >= length and tuple(chain[-length:]) in registry_ctx.all_method_suffixes:
            return tuple(chain[-length:])
    return None


def _resolve_root(root, local_scope, known, class_name):
    """Two-tier lookup, longest-lived binding first: a local variable/
    parameter (local_scope) wins over a class field (known.self_attrs),
    matching Java's own shadowing rule (a local variable of the same name
    as a field hides the field within its own scope). Handles both an
    explicit `this.<attr>` chain root and Java's own unqualified-field-
    access idiom (a bare identifier that isn't a local resolves against the
    CURRENT class's own self_attrs -- no Python or TS/JS adapter needs this
    fallback, since neither language allows a bare unqualified instance-
    field reference)."""
    if root is None:
        return None, "<unresolved receiver expression>"
    if root.startswith("this."):
        field = root[len("this."):]
        resolved = known.self_attrs.get((class_name, field)) if class_name else None
        return resolved, root
    if root in local_scope:
        return local_scope[root], root
    if class_name and (class_name, root) in known.self_attrs:
        return known.self_attrs[(class_name, root)], root
    return None, root


def _resolve_static_builder(root, chain, resolver, registry_ctx):
    """If `root` is a known class name (imported, tracked in
    resolver.name_alias) with a static_builder_chain registry entry, and
    `chain`'s LAST segment is one of that entry's terminal_methods, return
    the sdk_module the resulting variable should be known as -- e.g.
    `AnthropicOkHttpClient.builder().apiKey("x").build()` (root=
    "AnthropicOkHttpClient", chain=["builder","apiKey","build"]) resolves
    via terminal "build". Everything in `chain` before the terminal is
    arbitrary builder configuration, not matched at all -- only the root
    and the final segment matter (docs/decisions/029)."""
    if not root or not chain:
        return None
    hit = resolver.name_alias.get(root)
    if hit is None:
        return None
    _package, simple = hit
    entry = registry_ctx.static_builders.get(simple)
    if entry is None:
        return None
    module, terminal_methods = entry
    return module if chain[-1] in terminal_methods else None


class KnownNames:
    def __init__(self):
        self.self_attrs = {}  # (class_name, field_name) -> sdk_module

    def prescan(self, root, resolver, src, registry_ctx):
        """A separate, order-independent pass over the WHOLE tree before
        the main call-site walk -- mirrors python_adapter.py's own
        `prescan_self_attrs` exactly, and for the same reason: a method
        that USES a field must resolve correctly regardless of whether it
        is defined before or after the field/constructor that establishes
        the field's SDK type. Two ways a field becomes known, checked in
        one pass: its OWN DECLARED TYPE (`private AnthropicClient client;`
        -- trusted immediately, the same way every adapter trusts a typed
        parameter/property annotation) and a `this.<field> = new X()` (or
        a static-builder-chain) assignment for an untyped/interface-typed
        field."""
        def walk(node, class_name):
            local_class = class_name
            if node.type == "class_declaration":
                name_node = node.child_by_field_name("name")
                if name_node is not None:
                    local_class = _text(name_node, src)

            if node.type == "field_declaration" and local_class:
                type_node = node.child_by_field_name("type")
                sdk = resolver.annotation_sdk(type_node, src)
                if sdk:
                    for decl in node.named_children:
                        if decl.type != "variable_declarator":
                            continue
                        name_node = decl.child_by_field_name("name")
                        if name_node is not None:
                            self.self_attrs[(local_class, _text(name_node, src))] = sdk

            if node.type == "assignment_expression" and local_class:
                left = node.child_by_field_name("left")
                right = node.child_by_field_name("right")
                if left is not None and right is not None and left.type == "field_access":
                    obj = left.child_by_field_name("object")
                    field = left.child_by_field_name("field")
                    if obj is not None and obj.type == "this" and field is not None:
                        resolved = None
                        if right.type == "object_creation_expression":
                            hit = resolver.resolve_constructor_call(right, src)
                            resolved = hit[0] if hit else None
                        elif right.type == "method_invocation":
                            croot, chain = _flatten_invocation_chain(right, src)
                            resolved = _resolve_static_builder(croot, chain, resolver, registry_ctx)
                        if resolved:
                            self.self_attrs[(local_class, _text(field, src))] = resolved

            for child in node.children:
                walk(child, local_class)

        walk(root, None)


def _walk(node, src, resolver, known, class_name, symbol, local_scope,
          resolved_points, rel_path, next_id, registry_ctx):
    for child in node.children:
        if child.type == "class_declaration":
            name_node = child.child_by_field_name("name")
            new_class = _text(name_node, src) if name_node is not None else class_name
            _walk(child, src, resolver, known, new_class, symbol, {}, resolved_points, rel_path, next_id, registry_ctx)
            continue

        if child.type in ("method_declaration", "constructor_declaration"):
            fn_scope = dict(local_scope)
            name_node = child.child_by_field_name("name")
            fn_name = _text(name_node, src) if name_node is not None else "<init>"
            new_symbol = f"{class_name}.{fn_name}" if class_name else fn_name
            params = child.child_by_field_name("parameters")
            if params is not None:
                for p in params.named_children:
                    if p.type != "formal_parameter":
                        continue
                    type_node = p.child_by_field_name("type")
                    pname_node = p.child_by_field_name("name")
                    sdk = resolver.annotation_sdk(type_node, src)
                    if sdk and pname_node is not None:
                        fn_scope[_text(pname_node, src)] = sdk
            _walk(child, src, resolver, known, class_name, new_symbol, fn_scope, resolved_points, rel_path, next_id,
                  registry_ctx)
            continue

        if child.type == "lambda_expression":
            _walk(child, src, resolver, known, class_name, symbol, dict(local_scope), resolved_points, rel_path,
                  next_id, registry_ctx)
            continue

        if child.type == "local_variable_declaration":
            type_node = child.child_by_field_name("type")
            for decl in child.named_children:
                if decl.type != "variable_declarator":
                    continue
                name_node = decl.child_by_field_name("name")
                value_node = decl.child_by_field_name("value")
                if name_node is None:
                    continue
                if value_node is not None and value_node.type == "object_creation_expression":
                    hit = resolver.resolve_constructor_call(value_node, src)
                    if hit:
                        local_scope[_text(name_node, src)] = hit[0]
                        continue
                if value_node is not None and value_node.type == "method_invocation":
                    croot, chain = _flatten_invocation_chain(value_node, src)
                    hop_module = _resolve_static_builder(croot, chain, resolver, registry_ctx)
                    if hop_module:
                        local_scope[_text(name_node, src)] = hop_module
                        continue
                sdk = resolver.annotation_sdk(type_node, src)
                if sdk:
                    local_scope[_text(name_node, src)] = sdk

        if child.type == "assignment_expression":
            left = child.child_by_field_name("left")
            right = child.child_by_field_name("right")
            if left is not None and right is not None and left.type == "identifier":
                resolved_module = None
                if right.type == "object_creation_expression":
                    hit = resolver.resolve_constructor_call(right, src)
                    resolved_module = hit[0] if hit else None
                elif right.type == "method_invocation":
                    croot, chain = _flatten_invocation_chain(right, src)
                    resolved_module = _resolve_static_builder(croot, chain, resolver, registry_ctx)
                if resolved_module:
                    local_scope[_text(left, src)] = resolved_module
            # this.<field> = ... assignments are handled by KnownNames.prescan
            # (a separate, order-independent pass), not here.

        if child.type == "method_invocation":
            root, chain = _flatten_invocation_chain(child, src)
            suffix = _match_suffix(chain, registry_ctx)
            if suffix is not None:
                resolved, receiver_desc = _resolve_root(root, local_scope, known, class_name)
                registry = registry_ctx.module_to_registry.get(resolved)
                if registry is not None and suffix in registry["method_suffixes"]:
                    line = _line(child)
                    resolved_points.append(_drop_none({
                        "id": f"sp-{next_id[0]:04d}",
                        "kind": registry["surface_kind"],
                        "file": rel_path,
                        "line": line,
                        "symbol": symbol,
                        "framework": registry["framework"],
                        # Java has no async/await syntax -- the real
                        # Anthropic/OpenAI Java SDKs expose a genuinely
                        # separate async client/call surface instead
                        # (docs/decisions/029), reachable via `.async()`
                        # inserted as an extra hop in the same call chain
                        # (e.g. `client.async().messages().create(...)`).
                        # _match_suffix only looks at the chain's TAIL, so
                        # that hop doesn't interfere with matching --
                        # checking for it here is what lets this field be
                        # real instead of a blind "sync" default.
                        "sync_nature": "async" if "async" in chain else "sync",
                        "detection": "signature",
                        "confidence": 0.95,
                        "notes": f"receiver '{receiver_desc}' resolved via import/assignment/field-type tracking",
                    }))
                    next_id[0] += 1

        if child.type == "import_declaration":
            resolver.visit_import_declaration(child, src)

        _walk(child, src, resolver, known, class_name, symbol, local_scope, resolved_points, rel_path, next_id,
              registry_ctx)


def detect_file(path, repo_root, next_id=None, pack=None):
    path = Path(path)
    try:
        src = path.read_bytes()
    except OSError:
        return []
    parser = Parser(_LANGUAGE)
    try:
        tree = parser.parse(src)
    except Exception:
        return []

    registry_ctx = _DEFAULT_REGISTRY_CONTEXT if pack is None else _registry_context_for_pack(pack)
    resolver = ImportResolver(registry_ctx.constructor_names)

    # Imports are always top-level in Java (never nested inside a class or
    # method, a real grammar guarantee unlike JS) -- a shallow scan of the
    # file's own direct children is enough. Must run BEFORE the prescan
    # below, whose own resolver calls (resolve_constructor_call,
    # _resolve_static_builder) depend on name_alias already being populated.
    for child in tree.root_node.children:
        if child.type == "import_declaration":
            resolver.visit_import_declaration(child, src)

    known = KnownNames()
    known.prescan(tree.root_node, resolver, src, registry_ctx)

    rel_path = str(path.relative_to(repo_root)) if repo_root else str(path)
    resolved_points = []
    if next_id is None:
        next_id = [1]
    _walk(tree.root_node, src, resolver, known, None, None, {}, resolved_points, rel_path, next_id, registry_ctx)
    return resolved_points


def detect_repo(repo_root, pack=None):
    """Scan every .java file under repo_root, excluding common build output
    (Maven's target/, Gradle's build/), .git, and test source roots
    (Maven/Gradle convention: `src/test/java/...`, a `test` path segment --
    the singular form, unlike Python's own plural `tests/` convention)."""
    repo_root = Path(repo_root)
    resolved_points = []
    next_id = [1]
    for f in sorted(repo_root.rglob("*.java")):
        rel = f.relative_to(repo_root)
        parts = rel.parts
        if "target" in parts or "build" in parts or ".git" in parts or "test" in parts:
            continue
        if f.name.endswith("Test.java") or f.name.startswith("Test"):
            continue
        resolved_points.extend(detect_file(f, repo_root, next_id, pack))
    return resolved_points


def build_surface_map(repo_root, git_sha, disambiguated=None, harness_version=_OAH_VERSION, pack=None):
    """Assemble the document conforming to schemas/surface_map.schema.json.
    Same (surface_map, still_ambiguous) 2-tuple shape the other two
    adapters return; `still_ambiguous` is always `[]` here -- this module
    has no LLM-disambiguation counterpart yet, the same E11-TS-precedent
    scope boundary (`disambiguated` accepted for interface parity only)."""
    resolved_points = detect_repo(repo_root, pack)
    surface_map = {
        "schema_version": "0.1.0",
        "repo": {"path": str(repo_root), "git_sha": git_sha, "primary_language": "java"},
        "generated_by": {"harness_version": harness_version, "skill_versions": {}},
        "points": resolved_points,
        "coverage_stats": {
            "files_scanned": len(sorted(Path(repo_root).rglob("*.java"))),
            "points_total": len(resolved_points),
            "points_llm_disambiguated": 0,
        },
    }
    return surface_map, []
