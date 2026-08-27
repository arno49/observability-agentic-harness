"""Cross-file TypeScript/TSX module resolution, shared between S1's
`typescript_adapter.py` and S2's `ts_telemetry_scanner.py` (docs/decisions/033).
Extracted from `typescript_adapter.py` (docs/decisions/032, where it was
built and first proven -- against a real target repo's axios usage) once
S2's own TypeScript scanner needed the identical mechanism for a different
kind of cross-file known-name: a logger singleton (`export const logger =
new Logger()`) exported from one file and imported into ~140 others on the
same real repo, not a coincidence -- a shared client/service module built
once and re-exported is evidently a common real-world TS/JS shape, not
specific to any one detector.

Deliberately detector-agnostic: `collect_export_map` doesn't know or care
what a "known name" represents (an S1 resolved SDK module string, or an S2
logger-kind tuple) -- it only ever copies whatever value a caller's own
known-names dict already holds for a locally-resolved identifier onto that
identifier's export name. Each caller supplies its own known-names dict,
built by its own resolution logic; this module supplies only the parts that
don't depend on what's being resolved: reading the module graph
(tsconfig path aliases, relative imports) and reading which top-level names
a file exports.
"""
import json
from pathlib import Path


def collect_export_map(root, src, known_names):
    """Scans root's OWN top-level children (ES module exports are never
    valid anywhere else) for the three real export shapes that reference an
    already-resolved local name: `export default <identifier>`,
    `export const <name> = ...` (the declaration itself already put <name>
    in known_names via the caller's own ordinary walk -- export_statement
    doesn't need special-casing there for this shape), and
    `export { <name> [as <alias>] }`. Returns {exported_name: resolved_value}
    for only the names that actually resolved -- an export of an unresolved
    name is simply absent, not an error. `export default function/class ...`,
    `export function/class X`, and re-export-from (`export { x } from './y'`,
    `export * from './y'`) are real, named gaps: none reference a plain
    identifier already in known_names the way the three handled shapes do."""
    export_map = {}
    for child in root.children:
        if child.type != "export_statement":
            continue
        value = child.child_by_field_name("value")
        if (value is not None and value.type == "identifier"
                and any(c.type == "default" for c in child.children)):
            name = src[value.start_byte:value.end_byte].decode("utf-8", errors="replace")
            if name in known_names:
                export_map["default"] = known_names[name]
            continue
        decl = next((c for c in child.children if c.type in ("lexical_declaration", "variable_declaration")), None)
        if decl is not None:
            for d in decl.named_children:
                if d.type != "variable_declarator":
                    continue
                name_node = d.child_by_field_name("name")
                if name_node is not None and name_node.type == "identifier":
                    name = src[name_node.start_byte:name_node.end_byte].decode("utf-8", errors="replace")
                    if name in known_names:
                        export_map[name] = known_names[name]
            continue
        clause = next((c for c in child.children if c.type == "export_clause"), None)
        if clause is None:
            continue
        for spec in clause.named_children:
            if spec.type != "export_specifier":
                continue
            name_node = spec.child_by_field_name("name")
            alias_node = spec.child_by_field_name("alias")
            if name_node is None:
                continue
            local = src[name_node.start_byte:name_node.end_byte].decode("utf-8", errors="replace")
            exported_as = (src[alias_node.start_byte:alias_node.end_byte].decode("utf-8", errors="replace")
                           if alias_node is not None else local)
            if local in known_names:
                export_map[exported_as] = known_names[local]
    return export_map


def load_path_aliases(repo_root):
    """Reads tsconfig.json's compilerOptions.baseUrl/paths for cross-file
    import-specifier resolution. Best-effort: a missing file, JSON this
    stdlib parser can't handle (tsconfig.json commonly permits // comments
    and trailing commas real TS tooling accepts but `json.loads` does not),
    or an absent compilerOptions all resolve to "no aliases" -- alias-based
    imports (e.g. "@/x") then simply never cross-file-resolve; relative
    imports are unaffected either way. Does not follow a tsconfig "extends"
    chain -- a real, separate gap, named here rather than guessed at."""
    tsconfig_path = Path(repo_root) / "tsconfig.json"
    if not tsconfig_path.is_file():
        return ".", {}
    try:
        data = json.loads(tsconfig_path.read_text())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return ".", {}
    opts = data.get("compilerOptions") or {}
    return opts.get("baseUrl") or ".", opts.get("paths") or {}


def substitute_alias(spec, pattern, target):
    """tsconfig `paths` entries are wildcard patterns (`"@/*": ["src/*"]`),
    not exact strings, per TS's own documented path-mapping syntax."""
    if pattern.endswith("*"):
        prefix = pattern[:-1]
        if not spec.startswith(prefix) or not target.endswith("*"):
            return None
        return target[:-1] + spec[len(prefix):]
    return target if spec == pattern else None


def resolve_module_specifier(spec, importing_file, repo_root, base_url, paths):
    """Resolves an import's module specifier to an actual .ts/.tsx file on
    disk. Relative specifiers (`./x`, `../a/b`) resolve against the
    importing file's own directory; anything else is checked against
    tsconfig's path aliases. A bare package specifier (no leading "." and
    no matching alias, e.g. "axios", "react") returns None -- external
    packages are handled by each caller's own detection logic directly,
    never by this mechanism."""
    if spec.startswith("."):
        candidate = importing_file.parent / spec
    else:
        resolved_rel = None
        for pattern, targets in (paths or {}).items():
            for target in targets or []:
                resolved_rel = substitute_alias(spec, pattern, target)
                if resolved_rel is not None:
                    break
            if resolved_rel is not None:
                break
        if resolved_rel is None:
            return None
        candidate = Path(repo_root) / base_url / resolved_rel
    for suffix in (".ts", ".tsx", "/index.ts", "/index.tsx"):
        p = Path(str(candidate) + suffix)
        if p.is_file():
            return p.resolve()
    return None
