"""Regression tests for oah.discovery.java_adapter.

Real, verified detector-shape grounding (docs/decisions/029): the official
Anthropic Java SDK (`com.anthropic:anthropic-java`) constructs its client
via a static builder method chain (`AnthropicOkHttpClient.builder()
.apiKey(...).build()` or `.fromEnv()`), never `new X()` -- confirmed via a
background research agent against the SDK's own README before this module
was designed, not guessed. These tests are regression protection for the
specific behaviors that finding (and the tree-sitter-java grammar,
independently verified against real parse trees before writing this
module) depends on, using small deterministic fixtures -- no network, no
corpus clone, matching tests/test_python_adapter.py's and
tests/test_typescript_adapter.py's own discipline.
"""
from oah.discovery.java_adapter import detect_file, detect_repo, build_surface_map
from oah.schemas import validate


def _write(tmp_path, name, content):
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


def _detect(tmp_path, content, filename="App.java"):
    path = _write(tmp_path, filename, content)
    return detect_file(path, tmp_path)


def test_from_env_static_builder_terminal_resolved(tmp_path):
    resolved = _detect(tmp_path, """
import com.anthropic.client.okhttp.AnthropicOkHttpClient;

public class App {
    void run() {
        var client = AnthropicOkHttpClient.fromEnv();
        client.messages().create(null);
    }
}
""")
    assert len(resolved) == 1
    assert resolved[0]["kind"] == "llm_generation"
    assert resolved[0]["framework"] == "anthropic-sdk"
    assert resolved[0]["detection"] == "signature"
    assert resolved[0]["sync_nature"] == "sync"


def test_full_builder_chain_with_intermediate_config_calls_resolved(tmp_path):
    """`.apiKey(...)` between `.builder()` and `.build()` is arbitrary
    configuration -- only the root class and the terminal method matter."""
    resolved = _detect(tmp_path, """
import com.anthropic.client.AnthropicClient;
import com.anthropic.client.okhttp.AnthropicOkHttpClient;

public class App {
    void run() {
        AnthropicClient client = AnthropicOkHttpClient.builder().apiKey("x").timeout(30).build();
        client.messages().create(null);
    }
}
""")
    assert len(resolved) == 1
    assert resolved[0]["kind"] == "llm_generation"


def test_async_hop_flags_sync_nature_async(tmp_path):
    """client.async().messages().create(...) -- suffix matching only looks
    at the chain's tail, so the extra .async() hop doesn't block the match,
    and its presence is what flips sync_nature (Java has no async/await
    syntax to key off, unlike Python/TS)."""
    resolved = _detect(tmp_path, """
import com.anthropic.client.okhttp.AnthropicOkHttpClient;

public class App {
    void run() {
        var client = AnthropicOkHttpClient.fromEnv();
        client.async().messages().create(null);
    }
}
""")
    assert len(resolved) == 1
    assert resolved[0]["sync_nature"] == "async"


def test_unqualified_field_access_resolved_javas_own_idiom(tmp_path):
    """`client.messages().create(...)` with no `this.` qualifier at all --
    Java's own real idiom (implicit `this.` for instance fields), which
    neither Python (always explicit self.) nor TS/JS (always explicit
    this.) needs an equivalent fallback for."""
    resolved = _detect(tmp_path, """
import com.anthropic.client.AnthropicClient;
import com.anthropic.client.okhttp.AnthropicOkHttpClient;

public class Service {
    private AnthropicClient client;

    public Service() {
        this.client = AnthropicOkHttpClient.fromEnv();
    }

    public void run() {
        client.messages().create(null);
    }
}
""")
    assert len(resolved) == 1
    assert resolved[0]["notes"].startswith("receiver 'client'")


def test_explicit_this_field_access_also_resolved(tmp_path):
    resolved = _detect(tmp_path, """
import com.anthropic.client.AnthropicClient;
import com.anthropic.client.okhttp.AnthropicOkHttpClient;

public class Service {
    private AnthropicClient client;

    public Service() {
        this.client = AnthropicOkHttpClient.fromEnv();
    }

    public void run() {
        this.client.messages().create(null);
    }
}
""")
    assert len(resolved) == 1


def test_method_definition_order_does_not_matter(tmp_path):
    """The real point of a separate self_attrs prescan pass (mirroring
    python_adapter.py's own KnownNames.prescan_self_attrs): a method that
    USES the field, defined textually BEFORE the constructor that
    establishes it, must still resolve."""
    resolved = _detect(tmp_path, """
import com.anthropic.client.AnthropicClient;
import com.anthropic.client.okhttp.AnthropicOkHttpClient;

public class Service {
    private AnthropicClient client;

    public void run() {
        client.messages().create(null);
    }

    public Service() {
        this.client = AnthropicOkHttpClient.fromEnv();
    }
}
""")
    assert len(resolved) == 1


def test_field_declared_type_alone_resolves_constructor_injected_client(tmp_path):
    """A field typed AnthropicClient with no visible construction in this
    file (constructor-injected) still resolves via its declared type --
    the same trust every adapter already extends to a typed parameter."""
    resolved = _detect(tmp_path, """
import com.anthropic.client.AnthropicClient;

public class Service {
    private final AnthropicClient client;

    public Service(AnthropicClient client) {
        this.client = client;
    }

    public void run() {
        client.messages().create(null);
    }
}
""")
    assert len(resolved) == 1


def test_typed_constructor_parameter_resolved_directly(tmp_path):
    resolved = _detect(tmp_path, """
import com.anthropic.client.AnthropicClient;

public class Service {
    public void run(AnthropicClient injected) {
        injected.messages().create(null);
    }
}
""")
    assert len(resolved) == 1


def test_lambda_body_still_resolves_enclosing_local_scope(tmp_path):
    resolved = _detect(tmp_path, """
import com.anthropic.client.okhttp.AnthropicOkHttpClient;

public class App {
    void run() {
        var client = AnthropicOkHttpClient.fromEnv();
        Runnable r = () -> {
            client.messages().create(null);
        };
    }
}
""")
    assert len(resolved) == 1


def test_local_variable_shadows_field_of_same_name(tmp_path):
    """A local variable named `client` (unrelated to the field) must win
    over the class field of the same name within its own scope -- Java's
    own real shadowing rule."""
    resolved = _detect(tmp_path, """
import com.anthropic.client.AnthropicClient;

public class Service {
    private AnthropicClient client;

    public void run() {
        Object client = new Object();
        client.toString();
    }
}
""")
    assert resolved == []


def test_unresolved_receiver_not_reported(tmp_path):
    """No LLM-disambiguation counterpart is wired up for this adapter yet
    (E11-TS's own precedent, matched here) -- an unresolved receiver is
    simply absent, never reported as a false-confidence guess."""
    resolved = _detect(tmp_path, """
public class App {
    void run(Object clients) {
        ((SomeClient) clients).messages().create(null);
    }
}
""")
    assert resolved == []


def test_unrelated_builder_chain_produces_no_spurious_point(tmp_path):
    """MessageCreateParams.builder()...build() is a real, unrelated static
    builder chain in the same file -- its root class isn't in any
    registry's constructor_names, so it must not resolve to anything."""
    resolved = _detect(tmp_path, """
import com.anthropic.client.okhttp.AnthropicOkHttpClient;
import com.anthropic.models.messages.MessageCreateParams;

public class App {
    void run() {
        var client = AnthropicOkHttpClient.fromEnv();
        var params = MessageCreateParams.builder().model("x").build();
        client.messages().create(params);
    }
}
""")
    assert len(resolved) == 1  # only the real client.messages().create() call


_APP_JAVA = """
import com.anthropic.client.okhttp.AnthropicOkHttpClient;
public class App {
    void run() {
        var client = AnthropicOkHttpClient.fromEnv();
        client.messages().create(null);
    }
}
"""


def test_direct_chain_with_no_intermediate_assignment_is_a_named_gap(tmp_path):
    """`X.fromEnv().messages().create(...)` in ONE expression, with no
    intermediate variable holding the constructed client, is NOT resolved
    -- _resolve_static_builder only recognizes a chain whose LAST segment
    is a terminal method (the assign-then-call shape every real SDK
    README example this module was verified against actually uses,
    docs/decisions/029); a terminal method buried mid-chain, with real
    suffix-matchable calls appended after it, is a real, deliberately
    out-of-scope gap for this phase, not silently guessed at."""
    resolved = _detect(tmp_path, """
import com.anthropic.client.okhttp.AnthropicOkHttpClient;
public class App {
    void run() {
        AnthropicOkHttpClient.fromEnv().messages().create(null);
    }
}
""")
    assert resolved == []


def test_detect_repo_skips_build_output_and_test_sources(tmp_path):
    _write(tmp_path, "target/generated/App.java", _APP_JAVA)
    _write(tmp_path, "src/test/java/AppTest.java", _APP_JAVA)
    _write(tmp_path, "src/main/java/App.java", _APP_JAVA)
    resolved = detect_repo(tmp_path)
    assert len(resolved) == 1
    assert resolved[0]["file"] == "src/main/java/App.java"


def test_detect_repo_assigns_unique_ids_across_files(tmp_path):
    for i in range(3):
        _write(tmp_path, f"Mod{i}.java", _APP_JAVA.replace("class App", f"class Mod{i}"))
    resolved = detect_repo(tmp_path)
    assert len(resolved) == 3
    assert len({p["id"] for p in resolved}) == 3


def test_build_surface_map_end_to_end_validates_against_schema(tmp_path):
    _write(tmp_path, "App.java", """
import com.anthropic.client.okhttp.AnthropicOkHttpClient;
public class App {
    void run() {
        var client = AnthropicOkHttpClient.fromEnv();
        client.messages().create(null);
    }
}
""")
    surface_map, still_ambiguous = build_surface_map(tmp_path, git_sha="deadbeef")
    validate("surface_map", surface_map)  # raises on failure
    assert surface_map["repo"]["primary_language"] == "java"
    assert surface_map["coverage_stats"]["points_total"] == 1
    assert surface_map["points"][0]["kind"] == "llm_generation"
    assert still_ambiguous == []


def test_build_surface_map_no_points_found(tmp_path):
    _write(tmp_path, "App.java", "public class App { void run() {} }\n")
    surface_map, still_ambiguous = build_surface_map(tmp_path, git_sha="deadbeef")
    validate("surface_map", surface_map)
    assert surface_map["points"] == []
    assert surface_map["coverage_stats"]["points_total"] == 0
    assert still_ambiguous == []


# --- object_creation_expression (new X()): real, general mechanism, not
# exercised by genai's own real registry (which needs static_builder_chain
# instead) -- proven here against a minimal synthetic pack, mirroring how
# tests/test_typescript_adapter.py's own chain_hop tests protect a
# mechanism independent of any one real SDK's shape.

_NEW_EXPR_PACK = {
    "schema_version": "0.1.0", "name": "new-expr-test", "version": "0.1.0",
    "point_kinds": [{"kind": "widget_send", "dimension": "test", "detected_by": "registry"}],
    "registries": [
        {
            "framework": "widgetlib", "surface_kind": "widget_send", "language": "java",
            "sdk_module": "com.example.widgetlib", "constructor_names": ["WidgetClient"],
            "method_suffixes": [["send"]], "detector_shape": "receiver_method_suffix",
        },
    ],
    "lenses": [{"lens": "tracing", "skill": "s4-tracing", "target_kinds": None, "emits": ["design_fragment"]}],
    "semconv_namespaces": [{"namespace": "test", "stability": "unknown", "pin": "0"}],
}


def test_new_expr_pack_schema_is_itself_valid():
    validate("domain_pack", _NEW_EXPR_PACK)  # raises on failure


def test_object_creation_expression_receiver_resolved(tmp_path):
    path = _write(tmp_path, "App.java", """
import com.example.widgetlib.WidgetClient;

public class App {
    void run() {
        WidgetClient w = new WidgetClient();
        w.send("payload");
    }
}
""")
    resolved = detect_file(path, tmp_path, pack=_NEW_EXPR_PACK)
    assert len(resolved) == 1
    assert resolved[0]["kind"] == "widget_send"


def test_default_pack_never_detects_synthetic_widgetlib(tmp_path):
    path = _write(tmp_path, "App.java", """
import com.example.widgetlib.WidgetClient;
public class App { void run() { new WidgetClient().send("x"); } }
""")
    assert detect_file(path, tmp_path) == []
