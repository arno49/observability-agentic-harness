"""Signature registry for the raw Anthropic Python SDK — S1's first target
per ROADMAP.md E2 ("First target stack: Python + raw Anthropic SDK").

Design carried over verbatim from the SP1 spike prototype
(spikes/sp1-surface-mapping/registry.py), which validated it at 100% recall
against a real 3-repo corpus (see docs/decisions/003-sp1-ast-recall.md).
This is the production version: same registry, reimplemented against
tree-sitter per SP10's decision (docs/decisions/004-sp10-multilang-architecture.md)
instead of Python's stdlib `ast`, so the same registry can eventually back a
TypeScript plugin behind one adapter interface without redesigning the
signature list.
"""

CONSTRUCTOR_NAMES = frozenset({"Anthropic", "AsyncAnthropic"})

SDK_MODULE = "anthropic"

# Suffix match on the last two attribute-chain segments, not the full dotted
# path — this is what let the SP1 prototype resolve
# client.beta.prompt_caching.messages.create correctly without enumerating
# every beta-namespace prefix by hand (see SP1 finding 3).
METHOD_SUFFIXES = frozenset({
    ("messages", "create"),
    ("messages", "stream"),
})

# S1 output kind for a resolved Anthropic messages.create/stream call.
SURFACE_KIND = "llm_generation"
FRAMEWORK = "anthropic-sdk"
