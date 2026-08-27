"""Derives S1's deterministic-pass lookup structures from a loaded domain
pack's `registries[]`, instead of holding them as literal dicts (E13,
docs/decisions/011). Two detector shapes exist:

- **receiver_method_suffix** (and `module_function_call`,
  `imported_namespace_method_call`) — a resolved receiver (tracked via
  import/assignment/annotation) whose call's last N attribute-chain
  segments match a declared suffix, e.g. `client.messages.create(...)`.
  `imported_namespace_method_call` (docs/decisions/024) resolves the
  receiver directly from the import binding itself, with no
  constructor/factory call in between (e.g. `cron.schedule(...)` where
  `cron` is the default-imported module). `build_registry_index(pack)` derives
  `REGISTRIES`/`CONSTRUCTOR_NAMES`/`MODULE_TO_REGISTRY`/`ALL_METHOD_SUFFIXES`/
  `SUFFIX_LENGTHS` from this shape's entries — the exact five names
  `oah/discovery/python_adapter.py` already consumed before extraction, now
  pack-derived rather than four literal dicts (`ANTHROPIC`, `PINECONE`,
  `LANGSMITH`, `LIVEKIT`).
- **structural_pattern** — a content-signal match (`<expr>.<attribute> ==
  "value"`) with no resolved receiver at all, because there is no outbound
  SDK call to match a client-constructor-plus-method-suffix against (the
  tool_use-dispatch check: application code reacting to a response's own
  content, not a call into a client). `structural_pattern_registries(pack)`
  derives `STRUCTURAL_PATTERN_REGISTRIES` from this shape's entries.

Module-level constants below (`REGISTRIES` etc.) are this module's default —
built from the `genai` pack at import time, so `python_adapter.py`'s
zero-argument call sites stay exactly as they were before this file held
data instead of literals. `build_registry_index`/`structural_pattern_registries`
are the pack-parameterized functions a second pack's registries would be
derived through.

`_walk_calls` in python_adapter.py tries the longest declared suffix length
first when matching a call site's attribute chain, so a registry with a
longer, more specific suffix is preferred over one whose shorter suffix
happens to share a final segment.
"""
from oah.domains.loader import load_pack

_RECEIVER_SHAPES = ("receiver_method_suffix", "module_function_call", "imported_namespace_method_call",
                     "static_builder_chain")

# A registry entry with no "language" field predates E11-TS's TypeScript
# adapter (docs/decisions/014) and was always implicitly Python-only --
# this default keeps every pack that existed before that field was added
# byte-identical (E13's own guarantee), not a new assumption.
_DEFAULT_LANGUAGE = "python"


def _receiver_entries(pack, language):
    return [
        r for r in pack.get("registries", [])
        if r["detector_shape"] in _RECEIVER_SHAPES and r.get("language", _DEFAULT_LANGUAGE) == language
    ]


def _chain_hop_entries(pack, language):
    """chain_hop entries (docs/decisions/028): not a receiver+method-suffix
    surface point themselves, but a rule for propagating a KNOWN receiver's
    resolved module through one more hop of (optionally awaited)
    assignment -- e.g. amqplib's `const channel = await
    conn.createChannel()`, where `conn` is already known as the module's
    own "connection" stage and this hop says calling `.createChannel()` on
    it produces a "channel"-stage receiver. Deliberately excluded from
    _receiver_entries/build_registry_index's own registries[]/
    module_to_registry/all_method_suffixes -- a chain_hop entry must never
    be treated as a directly-detectable surface point (there is no
    dimension/surface_kind a raw `.connect()`/`.createChannel()` call would
    even map to), only as known-name propagation data consumed by
    chain_hop_index."""
    return [
        r for r in pack.get("registries", [])
        if r["detector_shape"] == "chain_hop" and r.get("language", _DEFAULT_LANGUAGE) == language
    ]


def build_registry_index(pack, language=_DEFAULT_LANGUAGE):
    """Returns (registries, constructor_names, module_to_registry,
    all_method_suffixes, suffix_lengths) for the receiver/method-suffix
    detector, derived from `pack`'s entries for `language` instead of a
    fixed literal list. Assumes no two same-language registries in the pack
    share an sdk_module -- MODULE_TO_REGISTRY depends on that, same
    invariant this module always had (a Python and a TypeScript registry
    MAY share an sdk_module string in principle, but never collide in
    practice since each language's MODULE_TO_REGISTRY is built and consumed
    separately). Exception, real and intentional (docs/decisions/028): two
    receiver_method_suffix entries MAY share a sdk_module that is itself a
    chain_hop's produces_module (e.g. amqplib's queue_producer/
    queue_consumer entries both keying off "amqplib#channel") -- callers
    that need to disambiguate those must not rely on this function's own
    module_to_registry (last-entry-wins on a shared key) and instead group
    `registries` by sdk_module themselves, same as
    oah/discovery/typescript_adapter.py's own `_RegistryContext.
    module_to_registries` does.

    constructor_names also folds in every chain_hop entry's own
    constructor_names for this language -- the first hop of a chain (e.g.
    amqplib's own `connect`, called on the raw imported module) is resolved
    exactly like imported_namespace_method_call's receiver, via
    ImportResolver.name_alias, which is only ever populated for a name
    already in constructor_names."""
    registries = [
        {
            "constructor_names": frozenset(r.get("constructor_names") or []),
            "sdk_module": r["sdk_module"],
            "method_suffixes": frozenset(tuple(s) for s in (r.get("method_suffixes") or [])),
            "surface_kind": r["surface_kind"],
            "framework": r["framework"],
        }
        for r in _receiver_entries(pack, language)
    ]
    hop_entries = _chain_hop_entries(pack, language)
    constructor_names = frozenset().union(
        *(r["constructor_names"] for r in registries),
        *(frozenset(r.get("constructor_names") or []) for r in hop_entries),
    )
    module_to_registry = {r["sdk_module"]: r for r in registries}
    all_method_suffixes = frozenset().union(*(r["method_suffixes"] for r in registries)) if registries else frozenset()
    suffix_lengths = sorted({len(s) for r in registries for s in r["method_suffixes"]}, reverse=True)
    return registries, constructor_names, module_to_registry, all_method_suffixes, suffix_lengths


def chain_hop_index(pack, language=_DEFAULT_LANGUAGE):
    """{(resolved_module, method_name): produces_module} from this pack's
    chain_hop entries for `language` -- e.g. {("amqplib", "connect"):
    "amqplib#connection", ("amqplib#connection", "createChannel"):
    "amqplib#channel"}. produces_module is a synthetic module string
    (never a real sdk_module any import statement could resolve to), so
    that once a variable is known under it, the EXISTING
    receiver_method_suffix machinery (module_to_registry/
    all_method_suffixes) handles the eventual method-suffix match with no
    new code path -- the only genuinely new mechanism is this table plus
    the language adapter's own known-name-propagation-through-one-more-hop
    step."""
    return {
        (r["sdk_module"], r["via_method"]): r["produces_module"]
        for r in _chain_hop_entries(pack, language)
    }


def java_static_builder_index(pack, language="java"):
    """{class_simple_name: (sdk_module, frozenset(terminal_methods))} from
    this pack's static_builder_chain entries -- Java's own real GenAI SDK
    shape (docs/decisions/029): the real Anthropic/OpenAI Java SDKs
    construct their client via a static method chain rooted at a known,
    IMPORTED CLASS NAME (`AnthropicOkHttpClient.builder().apiKey(...)
    .build()` or `.fromEnv()`), not `new X()` or a module-level factory.
    The language adapter checks a chain's ROOT against this index's keys
    and, if found, its LAST segment against that entry's terminal_methods
    -- everything in between is arbitrary builder configuration, not
    matched. Once resolved, sdk_module flows through the same
    receiver_method_suffix machinery build_registry_index already derives
    (static_builder_chain is one of _RECEIVER_SHAPES) -- this index only
    answers the construction-recognition half."""
    index = {}
    for r in pack.get("registries", []):
        if r["detector_shape"] != "static_builder_chain" or r.get("language", _DEFAULT_LANGUAGE) != language:
            continue
        terminals = frozenset(r.get("terminal_methods") or [])
        for name in r.get("constructor_names") or []:
            index[name] = (r["sdk_module"], terminals)
    return index


def structural_pattern_registries(pack, language=_DEFAULT_LANGUAGE):
    """registries[] entries shaped for the structural content-signal
    detector (detector_shape == structural_pattern) for `language`, each
    carrying content_signal (attribute_path, equals_value), the
    surface_kind/emits_kind to report, and the framework label -- e.g. the
    tool_use-dispatch check (attribute_path=["type"], equals_value=
    "tool_use", emits kind "tool_call")."""
    return [
        r for r in pack.get("registries", [])
        if r["detector_shape"] == "structural_pattern" and r.get("language", _DEFAULT_LANGUAGE) == language
    ]


_GENAI_PACK = load_pack("genai")
REGISTRIES, CONSTRUCTOR_NAMES, MODULE_TO_REGISTRY, ALL_METHOD_SUFFIXES, SUFFIX_LENGTHS = build_registry_index(_GENAI_PACK)
STRUCTURAL_PATTERN_REGISTRIES = structural_pattern_registries(_GENAI_PACK)
