"""Real R2's own defining check, first half: given the real OTel spans
`oah/validate/pytest_runner.py`'s `run_pytest_suite(capture_spans=True)`
actually captured during a sandboxed test run, does each DTO's expected
telemetry event actually show up?

Deliberately a same-span co-occurrence requirement, not "these attribute
names appear somewhere across all captured spans combined": dynamic
capture has real span boundaries to use, unlike oah/validate/checker.py's
static text search (which has no such boundary and so, more leniently,
accepts the union of an entire file). Two attribute names that happened on
two different, unrelated spans were never actually observed *together* as
one real event, and asserting otherwise would be exactly the kind of
overclaim this whole phase exists to avoid.

Per-DTO failures never raise here -- observed/not_observed are both valid
*results*, matching oah.validate.checker's own posture: one DTO with no
real evidence shouldn't abort checking the rest.

Signal provenance (docs/decisions/025, docs/decisions/011's own S11
addition): ladder_rung answers how much was run; environment answers
against what; provenance answers by whose instrumentation -- whether the
observed span came from zero-code auto-instrumentation or from code S10
actually edited. Verified for real (not assumed) against a live Python
SDK capture: an auto-instrumented span's own `instrumentation_scope.name`
is the instrumenting *library's* name (e.g.
"opentelemetry.instrumentation.flask"), while a span from
`tracer = trace.get_tracer(__name__)` (the exact pattern
skills/s10-instrumenter/SKILL.md teaches) carries the *target's own*
module name instead. Only available on spans that carry an
`instrumentation_scope` field at all -- `--live`'s OTLP-JSON capture
(oah/validate/live_sandbox.py) does; `--dynamic`'s ConsoleSpanExporter
pretty-print scrape (oah/validate/pytest_runner.py) does not expose this
field in its own printed format, a real, structural limit of that capture
mechanism, not a gap this module could close by trying harder --
provenance is honestly "unknown" for spans without it, never guessed.
"""

_AUTO_INSTRUMENTATION_SCOPE_PREFIXES = (
    "opentelemetry.instrumentation.",  # Python auto-instrumentation packages
    "@opentelemetry/instrumentation-",  # JS/TS auto-instrumentation packages
)


def _classify_provenance(instrumentation_scope):
    if not instrumentation_scope:
        return "unknown"
    if any(instrumentation_scope.startswith(p) for p in _AUTO_INSTRUMENTATION_SCOPE_PREFIXES):
        return "auto_instrumentation"
    return "harness_instrumented"


def _result(dto_id, status, reason=None, provenance=None):
    result = {"dto_id": dto_id, "status": status, "reason": reason}
    if provenance is not None:
        result["provenance"] = provenance
    return result


def check_dto_dynamic(dto, spans):
    """`spans` is a list of captured span dicts (each with `name` and
    `attributes`, per pytest_runner.parse_captured_spans's shape) from a
    single real sandboxed run -- not scoped to this one DTO; call sites
    are responsible for handing in the whole run's spans, since nothing
    in a real captured span identifies which DTO it belongs to."""
    dto_id = dto["id"]

    required_attribute_sets = [
        set(event.get("required_attributes", []))
        for event in dto.get("expected_events", [])
    ]
    required_attribute_sets = [s for s in required_attribute_sets if s]
    if not required_attribute_sets:
        return _result(dto_id, "not_observed", reason="this DTO's expected_events name no required_attributes to look for")

    never_observed = []
    matching_spans = []
    for required in required_attribute_sets:
        matches = [span for span in spans if required.issubset(span.get("attributes", {}).keys())]
        if not matches:
            never_observed.append(sorted(required))
        else:
            matching_spans.extend(matches)

    if never_observed:
        return _result(
            dto_id, "not_observed",
            reason="no single captured span had all of: " + "; ".join(", ".join(attrs) for attrs in never_observed),
        )
    # Provenance of the actual observation: every matching span's own
    # instrumentation_scope, classified and deduplicated -- a DTO whose
    # expected event shows up on both an auto-instrumented span AND a
    # harness-instrumented one (a real, if unusual, shape) reports both,
    # not just the first one found.
    provenances = sorted({_classify_provenance(span.get("instrumentation_scope")) for span in matching_spans})
    return _result(dto_id, "observed", provenance=provenances)
