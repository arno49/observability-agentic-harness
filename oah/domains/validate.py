"""Runtime pack-membership checks for the fields whose schema once carried a
closed JSON Schema `enum` (kind, dimension, lens, maps_to.kind, event_type --
see docs/decisions/011). Those schemas now accept any well-formed identifier
string, so a value's real validity -- "is this one of THIS pack's declared
values" -- is checked here instead, against the loaded pack that produced or
consumes it, rather than a fixed list. Most of the fields below are already
enforced structurally elsewhere by construction (S1 only emits pack-declared
kinds; oah/cli.py only ever invokes pack-declared lenses; S5's gate 4 checks
maps_to.kind against the pack directly) -- these helpers exist for the one
place that lost real protection when its schema's enum was relaxed: a live
LLM's disambiguation output, which no longer has a fixed vocabulary to be
schema-rejected against.
"""


def known_kinds(pack):
    return {pk["kind"] for pk in pack["point_kinds"]}


def known_dimensions(pack):
    return {pk["dimension"] for pk in pack["point_kinds"]}


def known_lenses(pack):
    return {entry["lens"] for entry in pack["lenses"]}


def known_attribute_kinds(pack):
    return set(pack["attribute_kind_values"])


def known_event_types(pack):
    return set(pack.get("event_types", []))


def is_known_kind(pack, kind):
    return kind in known_kinds(pack)
