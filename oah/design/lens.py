"""S4 lens invocation — real LiteLLM calls against a lens skill's own
SKILL.md + io/ schemas, generalized once so each S4 lens reuses the same
wiring instead of duplicating oah/discovery/disambiguate.py's pattern per
lens as more of them get built. Same design as that module: frontier tier
by default (SP8), instructions loaded from the real skill file at runtime,
response validated against the skill's own output schema before being
accepted, every real failure mode raises rather than being papered over.
"""
import json

from jsonschema import Draft202012Validator

from oah._resources import resolve_dir
from oah.llm_client import DEFAULT_MODEL, MissingLLMDependencyError, get_completion_fn, missing_credentials
from oah.telemetry import llm_span

SKILLS_DIR = resolve_dir("skills")


class LensDesignError(Exception):
    """A caller must treat this as 'no design fragment produced', never
    catch it and fabricate one."""


def _load_skill_instructions(skill_dir):
    text = (skill_dir / "SKILL.md").read_text()
    if text.startswith("---"):
        end = text.index("---", 3)
        text = text[end + 3:]
    return text.strip()


def _load_output_schema(skill_dir):
    return json.loads((skill_dir / "io" / "output.schema.json").read_text())


def design_lens(skill_name, points, repo_git_sha, context=None, model=None, _completion_fn=None):
    """points: surface_map points already filtered to this lens's relevant
    kind(s) by the caller — the lens skill itself refuses to design for
    points outside its own batch (SKILL.md's own hard rule), so filtering
    is the caller's job, not something to rely on the model to do.

    Returns a design_fragment dict conforming to the lens skill's own
    io/output.schema.json, or None if there were no points to design for
    (never calls the model with an empty batch).
    """
    if not points:
        return None

    skill_dir = SKILLS_DIR / skill_name
    model = model or DEFAULT_MODEL
    reason = missing_credentials(model)
    if reason and _completion_fn is None:
        raise LensDesignError(reason)

    system_prompt = _load_skill_instructions(skill_dir)
    output_schema = _load_output_schema(skill_dir)
    batch = {"schema_version": "0.1.0", "repo_git_sha": repo_git_sha, "points": points}
    if context:
        batch["context"] = context

    completion_fn = _completion_fn
    if completion_fn is None:
        try:
            completion_fn = get_completion_fn()
        except MissingLLMDependencyError as e:
            raise LensDesignError(str(e)) from e

    try:
        with llm_span("s4", skill_name, model):
            response = completion_fn(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": json.dumps(batch, indent=2)},
                ],
                response_format={
                    "type": "json_schema",
                    "json_schema": {"name": f"{skill_name}_output", "schema": output_schema, "strict": True},
                },
            )
    except Exception as e:
        raise LensDesignError(f"model call failed: {e}") from e

    try:
        content = response.choices[0].message.content
        parsed = json.loads(content)
    except (KeyError, IndexError, AttributeError, TypeError, json.JSONDecodeError) as e:
        raise LensDesignError(f"could not parse model response as JSON: {e}") from e

    errors = list(Draft202012Validator(output_schema).iter_errors(parsed))
    if errors:
        joined = "; ".join(f"{'/'.join(str(p) for p in e.path)}: {e.message}" for e in errors)
        raise LensDesignError(f"model output failed schema validation: {joined}")

    return parsed


def design_generation_capture(points, repo_git_sha, context=None, model=None, _completion_fn=None):
    return design_lens("s4-generation-capture", points, repo_git_sha, context, model, _completion_fn)


def design_pii_governance(points, repo_git_sha, context=None, model=None, _completion_fn=None):
    return design_lens("s4-pii-governance", points, repo_git_sha, context, model, _completion_fn)


def design_pii_governance_route(points, repo_git_sha, context=None, model=None, _completion_fn=None):
    """The service pack's own pii-governance variant (docs/decisions/041)
    -- NOT the same skill as design_pii_governance above. That one governs
    content captured at an llm_generation point; this one governs request/
    response parameters and query bind values at http_server_route,
    declarative_route, and db_query points, a genuinely different referent
    that a real Sonnet call found the genai-framed SKILL.md could not
    coherently handle (empty signals, or fabricated llm_generation content
    for points that were never llm_generation). Both share the same
    `lens: "pii-governance"` output value -- S7/S9 aggregate by lens name,
    not by skill directory, and a target only ever loads one domain pack's
    worth of lenses at a time, so the two never collide in one run."""
    return design_lens("s4-pii-governance-route", points, repo_git_sha, context, model, _completion_fn)


def design_cost(points, repo_git_sha, context=None, model=None, _completion_fn=None):
    return design_lens("s4-cost", points, repo_git_sha, context, model, _completion_fn)


def design_telemetry_cost(points, repo_git_sha, context=None, model=None, _completion_fn=None):
    """The service pack's own adaptation of design_cost (docs/decisions/011,
    docs/decisions/019): token accounting becomes cardinality, sampling and
    retention accounting. Cross-cutting like design_tracing/design_ops --
    telemetry cost applies to any point kind that emits a span/metric/log,
    not one SDK's call sites."""
    return design_lens("s4-telemetry-cost", points, repo_git_sha, context, model, _completion_fn)


def design_ops(points, repo_git_sha, context=None, model=None, _completion_fn=None):
    return design_lens("s4-ops", points, repo_git_sha, context, model, _completion_fn)


def design_retrieval(points, repo_git_sha, context=None, model=None, _completion_fn=None):
    return design_lens("s4-retrieval", points, repo_git_sha, context, model, _completion_fn)


def design_feedback(points, repo_git_sha, context=None, model=None, _completion_fn=None):
    return design_lens("s4-feedback", points, repo_git_sha, context, model, _completion_fn)


def design_realtime_multimodal(points, repo_git_sha, context=None, model=None, _completion_fn=None):
    return design_lens("s4-realtime-multimodal", points, repo_git_sha, context, model, _completion_fn)


def design_tracing(points, repo_git_sha, context=None, model=None, _completion_fn=None):
    return design_lens("s4-tracing", points, repo_git_sha, context, model, _completion_fn)


def design_tools(points, repo_git_sha, context=None, model=None, _completion_fn=None):
    return design_lens("s4-tools", points, repo_git_sha, context, model, _completion_fn)


def design_slo(points, repo_git_sha, context=None, model=None, _completion_fn=None):
    """The service pack's own new lens (docs/decisions/011, docs/decisions/020)
    -- no genai-pack equivalent. Unlike every other design_* function, its
    return value is NOT a bare design_fragment: s4-slo/io/output.schema.json
    requires a wrapper {design_fragment, slo_spec}, since an SLO structure
    (indicator/objective/alert-tiers/error-budget-policy) isn't expressible
    as a flat signal list. design_lens() itself needs no change to support
    this -- it already just validates+returns whatever the skill's own
    output schema declares; oah/cli.py's _design_all_lenses is what
    unpacks the wrapper, driven by this lens's own pack-declared
    lenses[].emits (["design_fragment", "slo_spec"])."""
    return design_lens("s4-slo", points, repo_git_sha, context, model, _completion_fn)


def design_dependency(points, repo_git_sha, context=None, model=None, _completion_fn=None):
    """The service pack's own last new lens (docs/decisions/011,
    docs/decisions/021) -- no genai-pack equivalent. Like design_slo, its
    return value is a wrapper {design_fragment, dependency_model}, not a
    bare design_fragment -- edge criticality, the extra-nine rule, and a
    budget split aren't expressible as a flat signal list."""
    return design_lens("s4-dependency", points, repo_git_sha, context, model, _completion_fn)


# Every design_* wrapper above design_slo is a pure pass-through -- NONE of them
# filter by point kind internally. That used to be a per-function hardcoded
# literal (design_ops filtered to kind == "llm_generation", etc.), found by
# E12's own "prove the split with a second real pack" effort to be a real,
# latent bug in E13's own extraction: those literals never came from a
# pack's own lenses[].target_kinds at all, so a lens designed for a second
# pack whose target_kinds differ from genai's (or is an empty match) would
# silently receive zero relevant points and return None, no matter what the
# pack manifest declared (docs/decisions/016). target_kinds filtering now
# happens exactly once, in oah/cli.py's _design_all_lenses, driven by the
# loaded pack's own data -- the same place _point_ids_for_fragment already
# reads it from, for the same reason. design_tracing was already correct by
# construction (cross-cutting, target_kinds: null, never filtered) and is
# now simply consistent with every other lens's contract instead of a
# documented exception to it.
