"""Signature registry for the raw Anthropic Python SDK.

Spike prototype for SP1 — see README.md. Scope is deliberately narrow: one
provider, one language, the call shapes actually observed in the SP1 corpus
(sync/async client construction, .messages.create/.stream, and the beta
namespace variants such as .beta.prompt_caching.messages.create).
"""

# Importing any of these names from the "anthropic" package (or accessing
# them as anthropic.<name>) marks the assigned variable as a client of this
# SDK once called as a constructor.
CONSTRUCTOR_NAMES = frozenset({"Anthropic", "AsyncAnthropic"})

SDK_MODULE = "anthropic"

# A call counts as an inference call if the tail of its attribute chain
# (the last two segments) matches one of these pairs. Suffix match, not
# exact path match: client.messages.create and
# client.beta.prompt_caching.messages.create both end in ("messages",
# "create") and are both real inference calls (see decision record, finding
# on claude-engineer's beta namespace usage) — enumerating every namespace
# prefix by hand would be a maintenance trap that breaks the day the SDK
# adds another beta path.
METHOD_SUFFIXES = frozenset({
    ("messages", "create"),
    ("messages", "stream"),
})
