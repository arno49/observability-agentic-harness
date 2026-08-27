"""Regression tests for oah.discovery.typescript_adapter.

The real-world recall claim (100% on a 4-repo TS corpus, 3 detector shapes,
0 false positives) is proven and documented in
docs/decisions/004-sp10-multilang-architecture.md and
docs/decisions/013-sp12-ts-detector-shapes.md (against
spikes/sp10-multilang/ts-adapter/detect.js, the TypeScript-compiler-API
prototype) and re-verified for this module's own tree-sitter reimplementation
via manual smoke tests against the same real corpus shapes before this file
existed (docs/decisions/014). These tests don't re-clone that corpus on
every run -- their job is regression protection for the specific behaviors
those claims depend on, using small deterministic fixtures so CI never
depends on network access or an external repo's continued existence, same
discipline tests/test_python_adapter.py already uses.
"""
from oah.discovery.typescript_adapter import detect_file, detect_repo, build_surface_map
from oah.schemas import validate


def _write(tmp_path, name, content):
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


def _detect(tmp_path, content, filename="app.ts"):
    path = _write(tmp_path, filename, content)
    return detect_file(path, tmp_path)


def test_default_import_resolved(tmp_path):
    resolved = _detect(tmp_path, """
import Anthropic from "@anthropic-ai/sdk";
const client = new Anthropic();
async function run() {
  return client.messages.create({model: "x"});
}
""")
    assert len(resolved) == 1
    assert resolved[0]["kind"] == "llm_generation"
    assert resolved[0]["framework"] == "anthropic-sdk"
    assert resolved[0]["detection"] == "signature"
    assert resolved[0]["sync_nature"] == "async"


def test_named_aliased_import_resolved(tmp_path):
    """`import { Anthropic as A } from "@anthropic-ai/sdk"` -- the other
    real import form SP10's corpus needed a from-import counterpart for."""
    resolved = _detect(tmp_path, """
import { Anthropic as A } from "@anthropic-ai/sdk";
const client = new A();
async function run() {
  return client.messages.create({model: "x"});
}
""")
    assert len(resolved) == 1
    assert resolved[0]["kind"] == "llm_generation"


def test_beta_namespace_suffix_match(tmp_path):
    """client.beta.prompt_caching.messages.create -- suffix match on the
    last two segments, not the full dotted path."""
    resolved = _detect(tmp_path, """
import Anthropic from "@anthropic-ai/sdk";
const client = new Anthropic();
async function run() {
  return client.beta.prompt_caching.messages.create({model: "x"});
}
""")
    assert len(resolved) == 1


def test_class_property_receiver_resolved_via_type_annotation(tmp_path):
    resolved = _detect(tmp_path, """
import Anthropic from "@anthropic-ai/sdk";
class Foo {
  private client: Anthropic | null = null;
  init() {
    this.client = new Anthropic();
  }
  async run() {
    return this.client.messages.create({model: "x"});
  }
}
""")
    assert len(resolved) == 1
    assert "this.client" in resolved[0]["notes"]


def test_file_wide_not_class_scoped_cross_function_assignment(tmp_path):
    """The real wechatbot shape (SP10 finding 3): a module-level `let`
    assigned inside one function, read inside a completely different one,
    no class involved at all -- resolvable only with file-wide tracking."""
    resolved = _detect(tmp_path, """
import Anthropic from "@anthropic-ai/sdk";
let client: Anthropic | null = null;
function initLLM() {
  client = new Anthropic();
}
async function getResponse() {
  return client.messages.create({model: "x"});
}
""")
    assert len(resolved) == 1
    assert resolved[0]["symbol"] == "getResponse"


def test_unresolved_receiver_not_reported(tmp_path):
    """No LLM-disambiguation counterpart is wired up for this adapter yet
    (module's own stated scope boundary) -- an unresolved receiver is
    simply absent, never reported as a false-confidence guess."""
    resolved = _detect(tmp_path, """
const clients: Record<string, unknown> = {};
async function run() {
  return (clients["primary"] as any).messages.create({model: "x"});
}
""")
    assert resolved == []


def test_jsx_route_self_closing_with_static_path(tmp_path):
    resolved = _detect(tmp_path, """
function App() {
  return (
    <Routes>
      <Route path="/home" element={<Home />} />
    </Routes>
  );
}
""", filename="App.tsx")
    assert len(resolved) == 1
    assert resolved[0]["kind"] == "declarative_route"
    assert resolved[0]["has_path_parameter"] is False


def test_jsx_route_with_path_parameter_flagged(tmp_path):
    resolved = _detect(tmp_path, """
function App() {
  return <Route path="/property/:id" element={<Detail />} />;
}
""", filename="App.tsx")
    assert len(resolved) == 1
    assert resolved[0]["has_path_parameter"] is True
    assert "path parameter" in resolved[0]["notes"]


def test_jsx_route_wildcard_flagged_as_path_parameter(tmp_path):
    """A catch-all `path="*"` matches a variable set of underlying paths,
    the same cardinality-relevant property a real :param has -- a real
    finding from SP12's own corpus fixture (cocktail-app), not guessed."""
    resolved = _detect(tmp_path, """
function App() {
  return <Route path="*" element={<NotFound />} />;
}
""", filename="App.tsx")
    assert resolved[0]["has_path_parameter"] is True


def test_create_browser_router_route_object_array(tmp_path):
    resolved = _detect(tmp_path, """
import { createBrowserRouter } from "react-router-dom";
const router = createBrowserRouter([
  { path: "/", element: <Home /> },
  { path: "/search", element: <Search /> },
]);
""", filename="routes.tsx")
    assert len(resolved) == 2
    assert all(p["kind"] == "declarative_route" for p in resolved)
    assert all(p["has_path_parameter"] is False for p in resolved)


def test_global_fetch_call_detected(tmp_path):
    resolved = _detect(tmp_path, """
async function loadData() {
  const res = await fetch("/api/search");
  return res.json();
}
""")
    assert len(resolved) == 1
    assert resolved[0]["kind"] == "http_client_call"
    assert resolved[0]["framework"] == "fetch"


def test_fetch_nested_in_callback_still_found(tmp_path):
    """The real cocktail-app shape (SP12): a fetch() call nested inside
    .map(async (item) => ...), not just a top-level statement."""
    resolved = _detect(tmp_path, """
async function loadAll(items: number[]) {
  return Promise.all(items.map(async (item) => {
    const r = await fetch(`/api/item/${item}`);
    return r.json();
  }));
}
""")
    assert len(resolved) == 1
    assert resolved[0]["kind"] == "http_client_call"


def test_fetch_shadowed_by_parameter_in_own_scope_not_reported(tmp_path):
    """SP12's own regression test, ported: a function parameter named
    `fetch` shadows calls INSIDE that function only."""
    resolved = _detect(tmp_path, """
function wrappedFetch(fetch: typeof window.fetch) {
  return fetch("/shadowed");
}
""")
    assert resolved == []


def test_fetch_shadowing_is_scope_aware_not_file_wide(tmp_path):
    """SP12's own real bug, the regression test for its fix: a shadowed
    fetch in one function must NOT suppress an unrelated, genuinely-global
    fetch() call elsewhere in the same file."""
    resolved = _detect(tmp_path, """
function wrappedFetch(fetch: typeof window.fetch) {
  return fetch("/shadowed");
}
async function loadData() {
  return fetch("/api/real");
}
""")
    assert len(resolved) == 1
    assert resolved[0]["symbol"] == "loadData"


def test_fetch_imported_locally_suppresses_whole_file(tmp_path):
    """Unlike parameter/variable shadowing, an actual module-level import
    of a name `fetch` genuinely applies file-wide -- the one case where
    file-wide suppression is correct, not a bug."""
    resolved = _detect(tmp_path, """
import { fetch } from "cross-fetch";
async function run() {
  return fetch("/x");
}
""")
    assert resolved == []


def test_detect_repo_skips_node_modules_and_test_files(tmp_path):
    _write(tmp_path, "node_modules/pkg/index.ts", """
import Anthropic from "@anthropic-ai/sdk";
const c = new Anthropic();
c.messages.create({model: "x"});
""")
    _write(tmp_path, "app.test.ts", """
import Anthropic from "@anthropic-ai/sdk";
const c = new Anthropic();
c.messages.create({model: "x"});
""")
    _write(tmp_path, "app.ts", """
import Anthropic from "@anthropic-ai/sdk";
const c = new Anthropic();
c.messages.create({model: "x"});
""")
    resolved = detect_repo(tmp_path)
    assert len(resolved) == 1
    assert resolved[0]["file"] == "app.ts"


def test_detect_repo_assigns_unique_ids_across_files(tmp_path):
    for i in range(3):
        _write(tmp_path, f"mod{i}.ts", """
import Anthropic from "@anthropic-ai/sdk";
const c = new Anthropic();
c.messages.create({model: "x"});
""")
    resolved = detect_repo(tmp_path)
    assert len(resolved) == 3
    assert len({p["id"] for p in resolved}) == 3


def test_build_surface_map_end_to_end_validates_against_schema(tmp_path):
    _write(tmp_path, "app.ts", """
import Anthropic from "@anthropic-ai/sdk";
const client = new Anthropic();
async function run() {
  return client.messages.create({model: "x"});
}
""")
    surface_map, still_ambiguous = build_surface_map(tmp_path, git_sha="deadbeef")
    validate("surface_map", surface_map)  # raises on failure
    assert surface_map["repo"]["primary_language"] == "typescript"
    assert surface_map["coverage_stats"]["points_total"] == 1
    assert surface_map["points"][0]["kind"] == "llm_generation"
    assert still_ambiguous == []


def test_build_surface_map_no_points_found(tmp_path):
    _write(tmp_path, "app.ts", "export const x = 1;\n")
    surface_map, still_ambiguous = build_surface_map(tmp_path, git_sha="deadbeef")
    validate("surface_map", surface_map)
    assert surface_map["points"] == []
    assert surface_map["coverage_stats"]["points_total"] == 0
    assert still_ambiguous == []


# --- chain_hop: generic two-hop chained receiver resolution ---------------
# docs/decisions/028. A minimal synthetic pack, deliberately NOT amqplib
# (that real registry and its own regression tests live in
# tests/test_service_pack.py) -- this protects the GENERIC mechanism
# (known-name propagation through two chain_hop entries) independent of
# any one real SDK's shape.

_CHAIN_PACK = {
    "schema_version": "0.1.0", "name": "chain-test", "version": "0.1.0",
    "point_kinds": [{"kind": "widget_send", "dimension": "test", "detected_by": "registry"}],
    "registries": [
        {
            "framework": "widgetlib", "detector_shape": "chain_hop", "language": "typescript",
            "sdk_module": "widgetlib", "constructor_names": ["widgets"],
            "via_method": "open", "produces_module": "widgetlib#session",
        },
        {
            "framework": "widgetlib", "detector_shape": "chain_hop", "language": "typescript",
            "sdk_module": "widgetlib#session",
            "via_method": "handle", "produces_module": "widgetlib#handle",
        },
        {
            "framework": "widgetlib", "surface_kind": "widget_send", "language": "typescript",
            "sdk_module": "widgetlib#handle", "method_suffixes": [["send"]],
            "detector_shape": "receiver_method_suffix",
        },
    ],
    "lenses": [{"lens": "tracing", "skill": "s4-tracing", "target_kinds": None, "emits": ["design_fragment"]}],
    "semconv_namespaces": [{"namespace": "test", "stability": "unknown", "pin": "0"}],
}


def test_chain_pack_schema_is_itself_valid():
    validate("domain_pack", _CHAIN_PACK)  # raises on failure


def test_two_hop_chain_resolves_through_both_intermediate_variables(tmp_path):
    from oah.discovery.typescript_adapter import detect_file
    path = _write(tmp_path, "app2.ts", (
        'import widgets from "widgetlib";\n'
        "async function run() {\n"
        '  const session = await widgets.open("x");\n'
        "  const handle = await session.handle();\n"
        '  handle.send("payload");\n'
        "}\n"
    ))
    resolved = detect_file(path, tmp_path, pack=_CHAIN_PACK)
    assert len(resolved) == 1
    assert resolved[0]["kind"] == "widget_send"
    assert resolved[0]["framework"] == "widgetlib"


def test_chain_hop_intermediate_calls_produce_no_points(tmp_path):
    from oah.discovery.typescript_adapter import detect_file
    path = _write(tmp_path, "app3.ts", (
        'import widgets from "widgetlib";\n'
        "async function run() {\n"
        '  const session = await widgets.open("x");\n'
        "  const handle = await session.handle();\n"
        '  handle.send("payload");\n'
        "}\n"
    ))
    resolved = detect_file(path, tmp_path, pack=_CHAIN_PACK)
    assert len(resolved) == 1  # only "send" -- not "open" or "handle"


def test_skipping_the_first_hop_does_not_resolve(tmp_path):
    """Calling the final method directly on the module's own namespace
    (skipping both hops) must not resolve -- proves the chain is load-
    bearing, not just falling back to imported_namespace_method_call."""
    from oah.discovery.typescript_adapter import detect_file
    path = _write(tmp_path, "app4.ts", 'import widgets from "widgetlib";\nwidgets.send("payload");\n')
    resolved = detect_file(path, tmp_path, pack=_CHAIN_PACK)
    assert resolved == []


def test_chain_hop_without_await_also_resolves(tmp_path):
    """Not every real call in a chain need be awaited -- the mechanism
    itself (member-expression call on an already-known receiver) doesn't
    depend on await; only the peel-off needs to tolerate its absence."""
    from oah.discovery.typescript_adapter import detect_file
    path = _write(tmp_path, "app5.ts", (
        'import widgets from "widgetlib";\n'
        "function run() {\n"
        '  const session = widgets.open("x");\n'
        "  const handle = session.handle();\n"
        '  handle.send("payload");\n'
        "}\n"
    ))
    resolved = detect_file(path, tmp_path, pack=_CHAIN_PACK)
    assert len(resolved) == 1
    assert resolved[0]["kind"] == "widget_send"
