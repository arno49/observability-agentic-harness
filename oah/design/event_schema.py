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
raised as a real error, not merged by picking one arbitrarily. A signal's
optional `health_thresholds` (docs/decisions/039) gets the identical
treatment when two fragments both declare one for the same attribute and
disagree -- docs/decisions/039 named this Phase D as an explicitly
deferred open question at design time; resolved the same way as
`sensitivity_tier` rather than merged/picked arbitrarily, for the same
reason. A fragment that declares no `health_thresholds` for an attribute
another fragment does is not a conflict -- silence isn't a competing
claim.

A real Sonnet run against `mf-analyzer-web`'s full 375-point batch (this
same day) found Phase D's own first implementation was too strict: two
`telemetry-cost` signals legitimately shared one unnamespaced attribute
(same `state`/`condition` per tier, correctly *not* split per Option B
since their `sensitivity_tier` genuinely agreed) but disagreed on
`health_thresholds[].rationale` -- free prose grounded in each signal's
own distinct evidence (`"portfolio CRUD calls..."` vs `"57 axios call
sites..."`), never meant to be identical across point groups. Comparing
the raw threshold list (rationale included) raised a false-positive
conflict that blocked S7/S8 entirely for the whole run -- exactly the
failure mode this ADR family exists to prevent, self-inflicted. Fixed:
conflict comparison now ignores `rationale` (documented reasoning, not a
factual claim) and compares only the `(state, condition, basis)` triple
per tier -- a real disagreement on where the line is drawn, or on
evidence basis, still raises; two signals reaching the same classification
through different reasoning does not.
"""
from oah.domains.loader import load_pack

_GENAI_PACK = load_pack("genai")


def _health_thresholds_signature(thresholds):
    """The comparable part of a health_thresholds list for conflict
    detection -- (state, condition, basis) per tier, sorted by state.
    Deliberately excludes `rationale`: free prose grounded in whatever
    points a given signal covers, expected to differ even when two
    signals agree on the actual classification (docs/decisions/040's own
    real false-positive, found and fixed the same day)."""
    return tuple(sorted((t["state"], t["condition"], t["basis"]) for t in thresholds))


class EventSchemaConflictError(Exception):
    """Two fragments disagree about the same attribute's kind,
    sensitivity_tier, or health_thresholds. A caller must not silently
    pick one -- this needs a human or S6 to resolve, same principle as
    S5's own scope boundary around judgment calls."""


def build_event_schema(design_fragments, repo_git_sha, semconv_pin=None, pack=None):
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
                    "health_thresholds": None,
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
            thresholds = signal.get("health_thresholds")
            if thresholds:
                if existing["health_thresholds"] is None:
                    existing["health_thresholds"] = thresholds
                elif _health_thresholds_signature(existing["health_thresholds"]) != _health_thresholds_signature(thresholds):
                    raise EventSchemaConflictError(
                        f"attribute {attribute!r} designed with health_thresholds="
                        f"{existing['health_thresholds']!r} by {sorted(existing['source_lenses'])} but "
                        f"health_thresholds={thresholds!r} by lens={lens!r}"
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

    # Replaces the two literal otel_genai_count/oah_extension_count keys
    # (docs/decisions/011): one {value}_count key per the loaded pack's own
    # attribute_kind_values. `pack` omitted means the genai pack, whose two
    # values (otel_genai, oah_extension) produce byte-identical key names to
    # before extraction.
    kind_counts = {
        f"{value}_count": sum(1 for a in attributes if a["kind"] == value)
        for value in (pack or _GENAI_PACK)["attribute_kind_values"]
    }

    result = {
        "schema_version": "0.1.0",
        "repo_git_sha": repo_git_sha,
        "attributes": attributes,
        "summary": {
            "attribute_count": len(attributes),
            **kind_counts,
            "lenses_included": sorted({lens for a in attributes for lens in a["source_lenses"]}),
        },
    }
    if semconv_pin:
        result["semconv_pin"] = semconv_pin
    return result
