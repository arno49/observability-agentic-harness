"""S1 deterministic pass for TypeScript/TSX — tree-sitter based, per SP10's
decision (docs/decisions/004-sp10-multilang-architecture.md): a fresh
implementation of the three-phase shape SP10 validated on two real
languages, against `tree-sitter-typescript` instead of the TypeScript
compiler API SP10's own spike (`spikes/sp10-multilang/ts-adapter/detect.js`)
used. That spike is evidence and a comparison baseline, explicitly not a
component to carry into this module (SP10's own Decision section) — SP10
hit a real operational cost (a Node.js runtime dependency whose own
`typescript` npm package broke its documented API across a major version
with no warning) that tree-sitter avoids: a pure-Python dependency, no
second language runtime.

Mirrors oah/discovery/python_adapter.py's module shape and public API
(detect_file/detect_repo/build_surface_map — same signatures, same
surface_map.schema.json point shape) so a future CLI dispatch layer can
swap adapters without touching anything downstream of S1. One real
architectural difference, not an oversight: SP10 finding 3 found the
known-binding prescan needs to be file-wide here, never class-scoped --
`wechatbot`'s real corpus case (a module-level `let` assigned in one
function, read in a different one, no class involved) is exactly the shape
Python's own class-scoped self-attr prescan cannot express. There is no
Python-adapter equivalent of `KnownNames.self_attrs`/class prescan here by
design, not by gap.

Two more detector passes beyond the three-phase shape, from SP12
(docs/decisions/013-sp12-ts-detector-shapes.md), corpus-verified at 100%
recall (14/14, 0 false positives) across 4 real repos: declarative route
registration (JSX <Route> elements, createBrowserRouter-style route-object
arrays) and a global unimported callee (bare fetch(...), scope-aware
shadow suppression via a real node.parent walk -- available directly in
tree-sitter's Python bindings, unlike the JS bindings SP12 needed
setParentNodes: true for).

E11-TS's own scope boundary (docs/decisions/014): this module is real and
callable, at SP10/SP12's own measured recall, but is not yet wired into
oah/cli.py's command dispatch (every CLI command still hardcodes the
Python adapter) and has no corpus fixture vendored into corpus/ -- named
explicitly, not silently dropped.

One more real, named gap: the two SP12 passes emit `kind: "declarative_route"`
and `kind: "http_client_call"`, neither of which any loaded pack's
`point_kinds[]` declares today (the `genai` pack owns SPA routing and
generic HTTP calls no more than it owns database queries -- that vocabulary
belongs to the future service pack, E12). A point of an undeclared kind is
not a bug here: `oah/discovery/gap_model.py`'s own `kind_to_dim.get(kind)`
already treats any pack-unmapped kind as "not a gap this pass can classify"
and silently excludes it (the same behavior an unmapped kind has always had,
E13 `docs/decisions/011`) -- so today, feeding this module's output into S3
surfaces the receiver_method_suffix points and quietly drops the other two
shapes' points, honest but easy to miss. Naming it here rather than
papering over it with a guessed dimension.

`module_function_call` (docs/decisions/018): schemas/domain_pack.schema.json
and oah/discovery/registry.py both named this detector shape from E13
onward -- a receiver created via a bare factory call (`const app =
express()`) rather than `new X()` -- but no adapter actually implemented
it until now. `ImportResolver.resolve_factory_call` plus the known-name
prescan's new `call_expression` branch (mirroring the existing
`new_expression` branch exactly) is that implementation; once a receiver
is known, downstream suffix-matching is identical regardless of which
shape created it. First (and so far only) consumer: the service pack's
`express` registry entry (`domains/service/pack.json`), docs-grounded
against Express's own public API, not corpus-verified -- named explicitly
in that entry's own `confidence_note`, same honesty precedent as genai's
livekit registry.

`imported_namespace_method_call` (docs/decisions/024): a third receiver-
resolution shape, for a method called directly on the imported module
binding itself with no constructor/factory call at all (e.g.
`import cron from "node-cron"; cron.schedule(...)`). No new code path was
needed -- `ImportResolver.name_alias` already carries this (module, local)
mapping straight from the import statement (populated for every
constructor-based registry too); the only change is a fallback in the
call_expression receiver resolution that consults `name_alias` when
`known_names` (populated only by a real `new X()`/`X()` construction) has
no entry for the receiver. Safe by construction for every existing
constructor-based registry: calling a method directly on an unconstructed
SDK class (e.g. `Anthropic.messages.create(...)` instead of an instance)
is not valid real-world TypeScript, so the fallback only ever fires for
genuinely namespace-shaped SDKs.
"""
import re
from collections import namedtuple
from pathlib import Path

import tree_sitter_typescript as tstypescript
from tree_sitter import Language, Parser

from oah import __version__ as _OAH_VERSION
from oah.discovery.registry import build_registry_index, structural_pattern_registries
from oah.domains.loader import load_pack

_LANGUAGE = Language(tstypescript.language_tsx())  # a superset grammar of plain TS -- safe for .ts files too

# The registry data every detection call actually needs, bundled so it
# threads through _walk's recursion as one parameter instead of four.
# docs/decisions/018: this is the "re-parameterize per call instead of
# module-global" fix E13's own decision record named as deferred, real work
# once a second pack actually needed a different registry set -- the
# service pack's express entry is that second pack.
_RegistryContext = namedtuple(
    "_RegistryContext", ["constructor_names", "module_to_registry", "all_method_suffixes", "suffix_lengths"]
)


def _registry_context_for_pack(pack):
    _registries, constructor_names, module_to_registry, all_method_suffixes, suffix_lengths = build_registry_index(
        pack, language="typescript"
    )
    return _RegistryContext(constructor_names, module_to_registry, all_method_suffixes, suffix_lengths)


_GENAI_PACK = load_pack("genai")
# Module-level default: byte-identical behavior for every existing caller
# that doesn't pass pack= explicitly (E13's own guarantee, extended here to
# this module's newly pack-parameterized detection).
_DEFAULT_REGISTRY_CONTEXT = _registry_context_for_pack(_GENAI_PACK)
REGISTRIES, CONSTRUCTOR_NAMES, MODULE_TO_REGISTRY, ALL_METHOD_SUFFIXES, SUFFIX_LENGTHS = build_registry_index(
    _GENAI_PACK, language="typescript"
)
STRUCTURAL_PATTERN_REGISTRIES = structural_pattern_registries(_GENAI_PACK, language="typescript")


def _text(node, src):
    return src[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


def _line(node):
    return node.start_point[0] + 1  # tree-sitter rows are 0-indexed


def _drop_none(d):
    return {k: v for k, v in d.items() if v is not None}


class ImportResolver:
    """name_alias (local name -> (sdk_module, original_name)) tracks the
    SDK-constructor names this pack's registries actually care about,
    populated from `import X from "mod"` (default import) and
    `import { X as Y } from "mod"` (named import, with or without `as`).
    imported_names is broader -- every locally-bound import name in the
    file, regardless of whether it's a known SDK constructor -- needed
    separately because the global-fetch pass (SP12) has to ask "was ANY
    name called `fetch` imported from anywhere", not "was a known SDK
    constructor imported", a genuinely different question `name_alias`
    alone can't answer (it only ever populates entries already in
    constructor_names)."""

    def __init__(self, constructor_names=CONSTRUCTOR_NAMES):
        self.constructor_names = constructor_names
        self.name_alias = {}
        self.imported_names = set()

    def visit_import_statement(self, node, src):
        source_node = node.child_by_field_name("source")
        module = _text(source_node, src)[1:-1] if source_node is not None else ""  # strip quotes
        clause = next((c for c in node.children if c.type == "import_clause"), None)
        if clause is None:
            return
        for child in clause.children:
            if child.type == "identifier":
                # Default import: `import Anthropic from "@anthropic-ai/sdk"`
                # -- the bare local name IS the constructor name here (TS
                # SDKs export their client class as the default export),
                # tracked directly rather than needing a two-hop
                # module-then-attribute resolution the way Python's
                # `import anthropic; anthropic.Anthropic()` does.
                local = _text(child, src)
                self.imported_names.add(local)
                if local in self.constructor_names:
                    self.name_alias[local] = (module, local)
            elif child.type == "named_imports":
                for spec in child.named_children:
                    if spec.type != "import_specifier":
                        continue
                    name_node = spec.child_by_field_name("name")
                    alias_node = spec.child_by_field_name("alias")
                    if name_node is None:
                        continue
                    original = _text(name_node, src)
                    local = _text(alias_node, src) if alias_node is not None else original
                    self.imported_names.add(local)
                    if original in self.constructor_names:
                        self.name_alias[local] = (module, original)

    def resolve_constructor_call(self, new_expr_node, src):
        """Return (module, ctor_name) if new_expr_node (a new_expression)
        constructs a known SDK client, else None."""
        ctor = new_expr_node.child_by_field_name("constructor")
        if ctor is None or ctor.type != "identifier":
            return None
        return self.name_alias.get(_text(ctor, src))

    def resolve_factory_call(self, call_expr_node, src):
        """Return (module, name) if call_expr_node (a plain call_expression,
        NOT new_expression) calls a known SDK factory function directly by
        its bare imported name -- the module_function_call detector shape
        (schemas/domain_pack.schema.json), e.g. `const app = express()`,
        unlike a constructor-based SDK called via `new X()`. Reuses the
        same name_alias table resolve_constructor_call does -- a registry
        entry's own constructor_names is the vocabulary either shape draws
        from; only the AST node type checked differs."""
        func = call_expr_node.child_by_field_name("function")
        if func is None or func.type != "identifier":
            return None
        return self.name_alias.get(_text(func, src))

    def annotation_sdk(self, type_annotation_node, src):
        """Resolve a type_annotation (e.g. `: Anthropic | null`) to an SDK
        module name, else None. Handles a bare type_identifier and a
        union_type containing one (the `X | null`/`X | undefined` shape
        every real TS SDK-client property in this corpus used)."""
        if type_annotation_node is None:
            return None
        node = type_annotation_node
        if node.type == "type_annotation" and node.named_child_count == 1:
            node = node.named_children[0]
        candidates = node.named_children if node.type == "union_type" else [node]
        for c in candidates:
            if c.type == "type_identifier":
                hit = self.name_alias.get(_text(c, src))
                if hit:
                    return hit[0]
        return None


def _flatten_member_chain(node, src):
    """member_expression(member_expression(Id('client'),'messages'),'create')
    -> ('client', ['messages', 'create']). `this` is a distinct node type,
    reported as the literal string 'this' as the chain root, mirroring how
    Python's own resolver treats `self`."""
    parts = []
    while node.type == "member_expression":
        prop = node.child_by_field_name("property")
        obj = node.child_by_field_name("object")
        if prop is None or obj is None:
            return None, parts
        parts.append(_text(prop, src))
        node = obj
    parts.reverse()
    if node.type == "identifier":
        return _text(node, src), parts
    if node.type == "this":
        return "this", parts
    return None, parts


def _match_suffix(chain, registry_ctx):
    for length in registry_ctx.suffix_lengths:
        if len(chain) >= length and tuple(chain[-length:]) in registry_ctx.all_method_suffixes:
            return tuple(chain[-length:])
    return None


def _string_content(string_node, src):
    for c in string_node.children:
        if c.type == "string_fragment":
            return _text(c, src)
    return None


# React Router (and most JS routers) encode a path PARAMETER inside the
# string literal itself (":id" in "/property/:id"), not as a separate JS
# expression -- "is this a string literal" alone does not distinguish a
# static route from a parameterized one (SP12, docs/decisions/013 finding
# 3). Checked separately, surfaced as its own field rather than folded into
# confidence.
_PATH_PARAMETER_PATTERN = re.compile(r":[A-Za-z_$][A-Za-z0-9_$]*|\*")


def _has_path_parameter(literal):
    return literal is not None and bool(_PATH_PARAMETER_PATTERN.search(literal))


def _declarative_route_note(literal, prefix):
    """`prefix` names the syntactic form (e.g. 'JSX <Route> element',
    'createBrowserRouter route-object array entry') for a shared, readable
    note across both declarative_registration passes."""
    if literal is None:
        return f"{prefix} with a non-literal (dynamic) path -- template not statically recoverable"
    suffix = " containing a path parameter" if _has_path_parameter(literal) else ""
    return f"{prefix} with a static path literal{suffix}"


_FUNCTION_LIKE_TYPES = frozenset({"function_declaration", "function_expression", "arrow_function", "method_definition"})


def _is_shadowed_in_enclosing_scope(call_node, src):
    """Scope-aware shadow check for a global `fetch(...)` call site (SP12
    finding 4): a function PARAMETER or local variable named `fetch` only
    shadows calls inside ITS OWN enclosing scope, walked via the real
    parent chain (tree-sitter's Python bindings expose `.parent` directly,
    no setParentNodes-equivalent flag needed). Checking this file-wide
    instead -- an earlier draft's real bug, caught by SP12's own smoke test
    -- would suppress every genuine global fetch() call in a file that
    happens to also contain one unrelated function with a `fetch`
    parameter, which is a real recall regression for a negative gate,
    unlike Pass A's file-wide POSITIVE resolution (accepted there because
    it strictly increases recall)."""
    current = call_node.parent
    while current is not None:
        if current.type in _FUNCTION_LIKE_TYPES:
            params_node = current.child_by_field_name("parameters")
            single_param = current.child_by_field_name("parameter")  # no-parens single-arg arrow
            if single_param is not None and single_param.type == "identifier" and _text(single_param, src) == "fetch":
                return True
            if params_node is not None:
                for p in params_node.named_children:
                    pattern = p.child_by_field_name("pattern") if p.type in ("required_parameter", "optional_parameter") else p
                    if pattern is not None and pattern.type == "identifier" and _text(pattern, src) == "fetch":
                        return True
        if current.type in ("statement_block", "program"):
            for stmt in current.named_children:
                if stmt.type != "lexical_declaration" and stmt.type != "variable_declaration":
                    continue
                for decl in stmt.named_children:
                    if decl.type != "variable_declarator":
                        continue
                    name = decl.child_by_field_name("name")
                    if name is not None and name.type == "identifier" and _text(name, src) == "fetch":
                        return True
        current = current.parent
    return False


def _walk(node, src, resolver, known_names, symbol, class_name, resolved_points, rel_path, next_id,
          is_async=False, registry_ctx=_DEFAULT_REGISTRY_CONTEXT):
    for child in node.children:
        if child.type == "class_declaration":
            name_node = child.child_by_field_name("name")
            new_class = _text(name_node, src) if name_node is not None else class_name
            _walk(child, src, resolver, known_names, symbol, new_class, resolved_points, rel_path, next_id,
                  is_async, registry_ctx)
            continue

        if child.type in ("function_declaration", "function_expression", "method_definition", "arrow_function"):
            name_node = child.child_by_field_name("name")
            fn_name = _text(name_node, src) if name_node is not None else "<anonymous>"
            new_symbol = f"{class_name}.{fn_name}" if class_name else fn_name
            new_is_async = any(c.type == "async" for c in child.children)
            _walk(child, src, resolver, known_names, new_symbol, class_name, resolved_points, rel_path, next_id,
                  new_is_async, registry_ctx)
            continue

        if child.type == "public_field_definition":
            name_node = child.child_by_field_name("name")
            type_node = child.child_by_field_name("type")
            sdk = resolver.annotation_sdk(type_node, src)
            if sdk and name_node is not None:
                known_names[_text(name_node, src)] = sdk

        if child.type in ("lexical_declaration", "variable_declaration"):
            for decl in child.named_children:
                if decl.type != "variable_declarator":
                    continue
                name_node = decl.child_by_field_name("name")
                value_node = decl.child_by_field_name("value")
                type_node = decl.child_by_field_name("type")
                if name_node is None or name_node.type != "identifier":
                    continue
                if value_node is not None and value_node.type == "new_expression":
                    hit = resolver.resolve_constructor_call(value_node, src)
                    if hit:
                        known_names[_text(name_node, src)] = hit[0]
                        continue
                if value_node is not None and value_node.type == "call_expression":
                    hit = resolver.resolve_factory_call(value_node, src)
                    if hit:
                        known_names[_text(name_node, src)] = hit[0]
                        continue
                sdk = resolver.annotation_sdk(type_node, src)
                if sdk:
                    known_names[_text(name_node, src)] = sdk

        if child.type == "assignment_expression":
            left = child.child_by_field_name("left")
            right = child.child_by_field_name("right")
            if left is not None and right is not None and right.type in ("new_expression", "call_expression"):
                hit = (resolver.resolve_constructor_call(right, src) if right.type == "new_expression"
                       else resolver.resolve_factory_call(right, src))
                if hit:
                    if left.type == "identifier":
                        known_names[_text(left, src)] = hit[0]
                    elif left.type == "member_expression":
                        root, chain = _flatten_member_chain(left, src)
                        if root == "this" and len(chain) == 1:
                            known_names[f"this.{chain[0]}"] = hit[0]

        if child.type == "call_expression":
            func = child.child_by_field_name("function")
            if func is not None and func.type == "member_expression":
                root, chain = _flatten_member_chain(func, src)
                suffix = _match_suffix(chain, registry_ctx)
                if suffix is not None:
                    if root == "this" and chain:
                        # chain[0] is the receiver attribute name (e.g.
                        # "client" in this.client.messages.create) --
                        # tracked under the same "this.<attr>" key the
                        # assignment_expression branch above populates,
                        # mirroring python_adapter.py's own
                        # known.self_attrs[(class_name, chain[0])] pattern
                        # but file-wide, per SP10 finding 3.
                        receiver_key = f"this.{chain[0]}"
                        resolved = known_names.get(receiver_key)
                        receiver_desc = receiver_key
                    else:
                        resolved = known_names.get(root) if root else None
                        if resolved is None and root:
                            # imported_namespace_method_call (docs/decisions/024):
                            # the receiver is the imported module binding
                            # itself, with no constructor/factory call in
                            # between (e.g. `cron.schedule(...)` where
                            # `cron` is the default-imported module) --
                            # resolver.name_alias already carries this
                            # (module, local) mapping straight from the
                            # import statement, real for every existing
                            # constructor-based registry too, but only
                            # reachable here as a fallback since a real
                            # constructed instance (known_names) always
                            # wins when one exists.
                            hit = resolver.name_alias.get(root)
                            resolved = hit[0] if hit else None
                        receiver_desc = root or "<unresolved receiver expression>"

                    registry = registry_ctx.module_to_registry.get(resolved)
                    args_node = child.child_by_field_name("arguments")
                    args_count = len(args_node.named_children) if args_node is not None else 0
                    # Express's own documented dual-purpose method: app.get(name)
                    # (1 arg) reads a setting, app.get(path, ...handlers) (2+
                    # args) registers a route -- require 2+ args before
                    # treating any http_server_route suffix match as a real
                    # route registration, ruling out the settings-getter form.
                    is_settings_getter = registry is not None and registry["surface_kind"] == "http_server_route" and args_count < 2
                    if registry is not None and suffix in registry["method_suffixes"] and not is_settings_getter:
                        line = _line(child)
                        notes = f"receiver '{receiver_desc}' resolved via import/assignment/annotation tracking"
                        # http_server_route only: extract the route path
                        # literal (first call argument) the same way Pass B
                        # does for declarative_route -- conditional on kind
                        # so llm_generation/retrieval/etc points (whose
                        # first argument is never a route path) keep their
                        # exact pre-existing shape, not a spurious
                        # has_path_parameter: false field (E13's
                        # byte-identical guarantee).
                        extra = {}
                        if registry["surface_kind"] == "http_server_route":
                            first_arg = args_node.named_children[0] if args_node and args_node.named_children else None
                            literal = (_string_content(first_arg, src)
                                       if first_arg is not None and first_arg.type == "string" else None)
                            extra["has_path_parameter"] = _has_path_parameter(literal)
                            notes += f" -- {_declarative_route_note(literal, 'route registration')}"
                        resolved_points.append(_drop_none({
                            "id": f"sp-{next_id[0]:04d}",
                            "kind": registry["surface_kind"],
                            "file": rel_path,
                            "line": line,
                            "symbol": symbol,
                            "framework": registry["framework"],
                            "sync_nature": "async" if is_async else "sync",
                            "detection": "signature",
                            "confidence": 0.95,
                            "notes": notes,
                            **extra,
                        }))
                        next_id[0] += 1
                    # unresolved receivers are not reported here (unlike the
                    # Python adapter's ambiguous-candidate output) -- this
                    # module has no LLM-disambiguation counterpart wired up
                    # yet, named explicitly in this module's own docstring
                    # as part of E11-TS's stated scope boundary.

            # Declarative registration: createBrowserRouter/createHashRouter/
            # createMemoryRouter route-object array (SP12).
            elif func is not None and func.type == "identifier" and _text(func, src) in (
                "createBrowserRouter", "createHashRouter", "createMemoryRouter"
            ):
                args = child.child_by_field_name("arguments")
                first_arg = args.named_children[0] if args and args.named_children else None
                if first_arg is not None and first_arg.type == "array":
                    for element in first_arg.named_children:
                        if element.type != "object":
                            continue
                        path_pair = next(
                            (p for p in element.named_children
                             if p.type == "pair" and p.child_by_field_name("key") is not None
                             and _text(p.child_by_field_name("key"), src) == "path"),
                            None,
                        )
                        if path_pair is None:
                            continue
                        value_node = path_pair.child_by_field_name("value")
                        literal = _string_content(value_node, src) if value_node is not None and value_node.type == "string" else None
                        line = _line(path_pair)
                        callee = _text(func, src)
                        resolved_points.append(_drop_none({
                            "id": f"sp-{next_id[0]:04d}",
                            "kind": "declarative_route",
                            "file": rel_path,
                            "line": line,
                            "symbol": symbol,
                            "framework": "react-router",
                            "sync_nature": "sync",
                            "detection": "ast",
                            "confidence": 0.95 if literal is not None else 0.3,
                            "has_path_parameter": _has_path_parameter(literal),
                            "notes": _declarative_route_note(literal, f"{callee} route-object array entry"),
                        }))
                        next_id[0] += 1

            # Global unimported callee: bare fetch(...) (SP12).
            elif func is not None and func.type == "identifier" and _text(func, src) == "fetch":
                if "fetch" not in resolver.imported_names and not _is_shadowed_in_enclosing_scope(child, src):
                    line = _line(child)
                    resolved_points.append(_drop_none({
                        "id": f"sp-{next_id[0]:04d}",
                        "kind": "http_client_call",
                        "file": rel_path,
                        "line": line,
                        "symbol": symbol,
                        "framework": "fetch",
                        "sync_nature": "async" if is_async else "sync",
                        "detection": "ast",
                        "confidence": 0.95,
                        "notes": "bare global fetch() call, unshadowed in its enclosing scope -- no receiver to resolve, unambiguous by construction",
                    }))
                    next_id[0] += 1

        if child.type in ("jsx_self_closing_element", "jsx_opening_element"):
            name_node = child.child_by_field_name("name")
            if name_node is not None and name_node.type == "identifier" and _text(name_node, src) == "Route":
                attrs = [c for c in child.children if c.type == "jsx_attribute"]
                path_attr = next(
                    (a for a in attrs if a.named_children and a.named_children[0].type == "property_identifier"
                     and _text(a.named_children[0], src) == "path"),
                    None,
                )
                if path_attr is not None:
                    value_node = path_attr.children[-1] if len(path_attr.children) >= 3 else None
                    literal = None
                    if value_node is not None:
                        if value_node.type == "string":
                            literal = _string_content(value_node, src)
                        elif value_node.type == "jsx_expression" and value_node.named_child_count == 1:
                            inner = value_node.named_children[0]
                            literal = _string_content(inner, src) if inner.type == "string" else None
                    line = _line(child)
                    resolved_points.append(_drop_none({
                        "id": f"sp-{next_id[0]:04d}",
                        "kind": "declarative_route",
                        "file": rel_path,
                        "line": line,
                        "symbol": symbol,
                        "framework": "react-router",
                        "sync_nature": "sync",
                        "detection": "ast",
                        "confidence": 0.95 if literal is not None else 0.3,
                        "has_path_parameter": _has_path_parameter(literal),
                        "notes": _declarative_route_note(literal, "JSX <Route> element"),
                    }))
                    next_id[0] += 1

        # Imports are collected in the same walk (not a separate pass) --
        # a real, deliberate difference from python_adapter.py, which
        # pre-collects imports before walking calls. TS/JS import
        # statements are hoisted (always resolvable regardless of source
        # position within the module), so a single top-level pass over
        # `node.children` (this function is only ever called with a
        # function/class/program body, never recursing INTO expressions
        # looking for nested imports, which don't exist in JS grammar
        # anyway) sees every import before any call site in practice for
        # every real corpus file measured -- stated here as a real
        # simplification, not an oversight.
        if child.type == "import_statement":
            resolver.visit_import_statement(child, src)

        _walk(child, src, resolver, known_names, symbol, class_name, resolved_points, rel_path, next_id,
              is_async, registry_ctx)


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
    known_names = {}
    rel_path = str(path.relative_to(repo_root)) if repo_root else str(path)
    resolved_points = []
    if next_id is None:
        next_id = [1]
    _walk(tree.root_node, src, resolver, known_names, None, None, resolved_points, rel_path, next_id,
          False, registry_ctx)
    return resolved_points


def detect_repo(repo_root, pack=None):
    """Scan every .ts/.tsx file under repo_root, excluding node_modules,
    .git, dist, and test files -- the same exclusions detect.js already
    used, plus python_adapter.py's own tests/-directory skip. next_id is
    shared across the whole scan (via detect_file's own next_id param) so
    IDs stay unique per run, not per file -- matching python_adapter.py's
    own detect_repo/detect_file relationship exactly.

    `pack` (default None -- the genai pack, byte-identical to every caller
    before docs/decisions/018) selects which pack's registries[] entries
    this scan matches against -- e.g. load_pack("service") to also resolve
    Express route registrations. Only one pack's registries are consulted
    per call, matching the rest of this codebase's current single-pack-
    per-run architecture (oah/cli.py's commands all load exactly one pack
    today); merging more than one pack's registries in a single scan is a
    real, separate question this phase doesn't attempt."""
    repo_root = Path(repo_root)
    resolved_points = []
    next_id = [1]
    for f in sorted(repo_root.rglob("*.ts")) + sorted(repo_root.rglob("*.tsx")):
        rel = f.relative_to(repo_root)
        parts = rel.parts
        if "node_modules" in parts or ".git" in parts or "dist" in parts or "tests" in parts:
            continue
        if f.name.startswith("test_") or ".test." in f.name or ".spec." in f.name:
            continue
        resolved_points.extend(detect_file(f, repo_root, next_id, pack))
    return resolved_points


def build_surface_map(repo_root, git_sha, disambiguated=None, harness_version=_OAH_VERSION, pack=None):
    """Assemble the document conforming to schemas/surface_map.schema.json.
    Same shape as python_adapter.py's own build_surface_map, including the
    (surface_map, still_ambiguous) 2-tuple return -- a CLI dispatch layer
    can unpack either adapter's result identically. `disambiguated` is
    accepted for interface parity but unused today -- this module has no
    LLM-disambiguation counterpart wired up yet (E11-TS's own stated scope
    boundary); `still_ambiguous` is therefore always `[]` here, never a
    real pending-candidate list, since this module's own detect_repo never
    produces ambiguous candidates in the first place. `pack` (default None
    -- genai) is threaded straight through to detect_repo."""
    resolved_points = detect_repo(repo_root, pack)
    surface_map = {
        "schema_version": "0.1.0",
        "repo": {"path": str(repo_root), "git_sha": git_sha, "primary_language": "typescript"},
        "generated_by": {"harness_version": harness_version, "skill_versions": {}},
        "points": resolved_points,
        "coverage_stats": {
            "files_scanned": len(sorted(Path(repo_root).rglob("*.ts")) + sorted(Path(repo_root).rglob("*.tsx"))),
            "points_total": len(resolved_points),
            "points_llm_disambiguated": 0,
        },
    }
    return surface_map, []
