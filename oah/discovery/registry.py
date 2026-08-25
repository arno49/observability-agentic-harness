"""Signature registries for S1's deterministic Python pass. Each entry
describes one SDK: its client-constructor names, its own dotted module
path (as it appears in an `import`/`from ... import` statement), and the
method-suffix shapes (the last N attribute-chain segments of a call, e.g.
`("messages", "create")` for `client.messages.create(...)`) that count as
a real call to that SDK — wired to one `surface_map.json` `kind`.

Three registries so far:

- **anthropic-sdk -> llm_generation** — S1's first target stack per
  ROADMAP.md E2 ("Python + raw Anthropic SDK"), carried over verbatim from
  the SP1 spike prototype (see module docstring history in
  oah/discovery/python_adapter.py). Suffix length 2
  (`client.messages.create`) because the SDK nests resources under the
  client.
- **pinecone -> retrieval** — the classic pre-v3 Pinecone SDK shape:
  `import pinecone; pinecone.init(...); index = pinecone.Index("name");
  index.query(...)`. `pinecone.Index(...)` is a direct, single-hop
  constructor call the existing receiver-tracking already handles, same
  as `anthropic.Anthropic()`. Deliberately NOT the v3+ `Pinecone()`
  client-object SDK (`pc = Pinecone(...); index = pc.Index("name")`) —
  that shape needs multi-hop receiver tracking (constructor -> a
  *method*-returned intermediate object, not a variable bound directly to
  a constructor call) that oah/discovery/python_adapter.py's detector
  doesn't do yet. Stated here as a real, current scope boundary, not
  glossed over — same discipline as every other partial-scope module in
  this codebase. Suffix length 1 (`index.query`) since Pinecone calls
  methods directly on the index object, unlike Anthropic's nested
  resources.
- **langsmith -> feedback_ingest** — `from langsmith import Client; client
  = Client(); client.create_feedback(run_id=..., key="...", score=...)`.
  A direct, single-hop constructor exactly like pinecone's, and
  `create_feedback` is LangSmith's own real method name for binding user
  feedback/reviewer verdicts to a trace/run ID — architecture.md's feedback
  lens description verbatim. Suffix length 1, and unlike pinecone's
  `query`, `create_feedback` is specific enough that it shouldn't meaningfully
  raise the ambiguous-candidate rate the way a generic verb would.

`_walk_calls` in python_adapter.py tries the longest declared suffix
length first when matching a call site's attribute chain, so a registry
with a longer, more specific suffix is preferred over one whose shorter
suffix happens to share a final segment.

Real tradeoff, stated not hidden: pinecone's suffix is a single common
word (`query`), unlike anthropic's two-segment, SDK-specific
`messages.create`. A `.query(...)` call on a receiver this detector can't
resolve (e.g. a SQLAlchemy `session.query(...)`) lands in the ambiguous
bucket for LLM disambiguation, not silently ignored and not silently
accepted -- disambiguation correctly returns `kind: null` for it, at the
cost of one more model call than a Pinecone-only corpus would need. This
is the same "never silently drop, never silently accept" posture S1 uses
for every genuinely unresolved receiver; adding a generic-verb suffix just
means more real-world call sites now fall into that bucket.
"""

ANTHROPIC = {
    "constructor_names": frozenset({"Anthropic", "AsyncAnthropic"}),
    "sdk_module": "anthropic",
    # Suffix match on the last two attribute-chain segments, not the full
    # dotted path — this is what let the SP1 prototype resolve
    # client.beta.prompt_caching.messages.create correctly without
    # enumerating every beta-namespace prefix by hand (see SP1 finding 3).
    "method_suffixes": frozenset({("messages", "create"), ("messages", "stream")}),
    "surface_kind": "llm_generation",
    "framework": "anthropic-sdk",
}

PINECONE = {
    "constructor_names": frozenset({"Index"}),
    "sdk_module": "pinecone",
    "method_suffixes": frozenset({("query",)}),
    "surface_kind": "retrieval",
    "framework": "pinecone-sdk",
}

LANGSMITH = {
    "constructor_names": frozenset({"Client"}),
    "sdk_module": "langsmith",
    "method_suffixes": frozenset({("create_feedback",)}),
    "surface_kind": "feedback_ingest",
    "framework": "langsmith-sdk",
}

REGISTRIES = [ANTHROPIC, PINECONE, LANGSMITH]

# Union across registries -- the resolver only needs to know "is this call
# constructing SOME tracked SDK client", the specific registry is looked
# up later via the resolved module name.
CONSTRUCTOR_NAMES = frozenset().union(*(r["constructor_names"] for r in REGISTRIES))

# Resolved module name -> its one registry entry. Assumes no two
# registries share an sdk_module -- true today, and a real invariant this
# structure depends on if a third registry is ever added for a module
# already present here.
MODULE_TO_REGISTRY = {r["sdk_module"]: r for r in REGISTRIES}

ALL_METHOD_SUFFIXES = frozenset().union(*(r["method_suffixes"] for r in REGISTRIES))

# Distinct suffix lengths across all registries, longest first, so
# _match_suffix tries the more specific pattern before a shorter one.
SUFFIX_LENGTHS = sorted({len(s) for r in REGISTRIES for s in r["method_suffixes"]}, reverse=True)
