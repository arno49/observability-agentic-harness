"""S7 (partial): event_schema.json emission, deterministic.

architecture.md lists S7 as *(skill: synthesizer)* — architecture.md
(prose) and rollout_plan.md genuinely need an LLM to write; event_schema.json
does not. Every attribute in it already exists, fully specified, in the S4
design_fragments that fed it (name, maps_to, sensitivity_tier,
surface_point_ids) — assembling those into one deduplicated, versioned
document is a merge, not a design decision, so it's built as pure code
here rather than a second LLM call for something the first one(s) already
decided.

Conflict handling is the one place this isn't pure bookkeeping: two
fragments (from different lenses, or the same lens run twice) can name the
same underlying `maps_to.attribute` with disagreeing `kind` or
`sensitivity_tier`. That's not this module's call to silently resolve —
raised as a real error, not merged by picking one arbitrarily.
"""


class EventSchemaConflictError(Exception):
    """Two fragments disagree about the same attribute's kind or
    sensitivity_tier. A caller must not silently pick one -- this needs a
    human or S6 to resolve, same principle as S5's own scope boundary
    around judgment calls."""


def build_event_schema(design_fragments, repo_git_sha, semconv_pin=None):
    by_attribute = {}

    for fragment in design_fragments:
        lens = fragment.get("lens", "unknown")
        for signal in fragment.get("signals", []):
            maps_to = signal["maps_to"]
            attribute = maps_to.get("attribute")
            if not attribute:
                continue  # a signal with no concrete attribute failed S5's own gate already; skip defensively
            kind = maps_to["kind"]
            tier = signal["sensitivity_tier"]

            if attribute not in by_attribute:
                by_attribute[attribute] = {
                    "name": attribute,
                    "kind": kind,
                    "stability": "development",
                    "deprecated_by": None,
                    "sensitivity_tier": tier,
                    "source_lenses": set(),
                    "surface_point_ids": set(),
                }
            existing = by_attribute[attribute]
            if existing["kind"] != kind:
                raise EventSchemaConflictError(
                    f"attribute {attribute!r} designed as kind={existing['kind']!r} by "
                    f"{sorted(existing['source_lenses'])} but kind={kind!r} by lens={lens!r}"
                )
            if existing["sensitivity_tier"] != tier:
                raise EventSchemaConflictError(
                    f"attribute {attribute!r} designed at sensitivity_tier={existing['sensitivity_tier']!r} "
                    f"by {sorted(existing['source_lenses'])} but tier={tier!r} by lens={lens!r}"
                )
            existing["source_lenses"].add(lens)
            existing["surface_point_ids"].update(signal["surface_point_ids"])

    attributes = []
    for attr in sorted(by_attribute.values(), key=lambda a: a["name"]):
        attributes.append({
            "name": attr["name"],
            "kind": attr["kind"],
            "stability": attr["stability"],
            "deprecated_by": attr["deprecated_by"],
            "sensitivity_tier": attr["sensitivity_tier"],
            "source_lenses": sorted(attr["source_lenses"]),
            "surface_point_ids": sorted(attr["surface_point_ids"]),
        })

    result = {
        "schema_version": "0.1.0",
        "repo_git_sha": repo_git_sha,
        "attributes": attributes,
        "summary": {
            "attribute_count": len(attributes),
            "otel_genai_count": sum(1 for a in attributes if a["kind"] == "otel_genai"),
            "oah_extension_count": sum(1 for a in attributes if a["kind"] == "oah_extension"),
            "lenses_included": sorted({lens for a in attributes for lens in a["source_lenses"]}),
        },
    }
    if semconv_pin:
        result["semconv_pin"] = semconv_pin
    return result
