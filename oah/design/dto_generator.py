"""S8 DTO generation — real LiteLLM call for the parts that need judgment
(anchor selection, preconditions, change type), deterministic post-
processing for the part that doesn't: rollout_step, assigned by
architecture.md S7's real ordering rule ("first workflow = most critical
one, tracing + generation capture first, feedback loop second,
auto-scoring third"), not the model (SKILL.md itself instructs the model
not to set this field).
"""
import json

from jsonschema import Draft202012Validator

from oah._resources import resolve_dir
from oah.domains.loader import load_pack
from oah.llm_client import DEFAULT_MODEL, MissingLLMDependencyError, get_completion_fn, missing_credentials
from oah.schemas import validate as validate_shared_schema
from oah.telemetry import llm_span

SKILLS_DIR = resolve_dir("skills")
SKILL_NAME = "s8-dto-generator"

# architecture.md S7: "first workflow = most critical one" -- the primary
# rollout ordering key. Lower rank rolls out first. A gap whose point had
# no resolvable workflow_hint (or no context.yaml at all) sorts last, not
# first and not interleaved with known-critical workflows -- known beats
# unknown, same principle as gap_model.py's own priority-driver honesty.
_CRITICALITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}
_UNKNOWN_WORKFLOW_RANK = 4

_DEFAULT_DIMENSION_RANK = 1


def dimension_rollout_rank(pack):
    """{dimension: rollout_rank} from the loaded pack's point_kinds
    (docs/decisions/011) -- replaces the literal _DIMENSION_ROLLOUT_RANK
    dict. architecture.md S7: 'tracing + generation capture first, feedback
    loop second, auto-scoring third' -- the genai pack's own point_kinds
    reproduce the two reachable ranks (generation_capture: 0, feedback: 2)
    exactly; 'tracing' has no point kind (it's cross-cutting, not tied to
    one) so its rank-0 entry was already unreachable before extraction (no
    gap ever has dimension='tracing') and isn't reproduced here -- dropping
    genuinely dead code, not a behavior change on any real gap."""
    return {pk["dimension"]: pk.get("rollout_rank", _DEFAULT_DIMENSION_RANK) for pk in pack["point_kinds"]}


_GENAI_PACK = load_pack("genai")
# Default: byte-identical to the pre-extraction literal for every reachable
# dimension (generation_capture: 0, feedback: 2, everything else the stated
# default of 1).
_DIMENSION_ROLLOUT_RANK = dimension_rollout_rank(_GENAI_PACK)

# Gap priority (p0 first) as the final tiebreak -- meaningful on its own
# (severity + coverage status) even without context.yaml, so it still
# orders DTOs sensibly when no workflow is resolvable for any of them,
# rather than falling through to an arbitrary dto-id-only order.
_PRIORITY_RANK = {"p0": 0, "p1": 1, "p2": 2, "p3": 3}


class DtoGenerationError(Exception):
    """A caller must treat this as 'no DTOs produced', never catch it and
    fabricate some."""


def _load_skill_instructions():
    text = (SKILLS_DIR / SKILL_NAME / "SKILL.md").read_text()
    if text.startswith("---"):
        end = text.index("---", 3)
        text = text[end + 3:]
    return text.strip()


def _load_output_schema():
    return json.loads((SKILLS_DIR / SKILL_NAME / "io" / "output.schema.json").read_text())


def _workflow_criticality_rank(workflow_name, context):
    if not workflow_name or not context:
        return _UNKNOWN_WORKFLOW_RANK
    for wf in context.get("workflows", []):
        if wf["name"] == workflow_name:
            return _CRITICALITY_RANK.get(wf["criticality"], _UNKNOWN_WORKFLOW_RANK)
    return _UNKNOWN_WORKFLOW_RANK


def _baseline_covered_attributes(pack):
    """Flat set of attribute names schemas/domain_pack.schema.json's
    auto_instrumentation_baseline.covered_signals declares -- what
    zero-code auto-instrumentation already emits for this pack's domain.
    A pack that declares no baseline (every pack before the service pack)
    returns an empty set, so the redundancy check below never fires --
    zero behavior change for genai."""
    if pack is None:
        return set()
    baseline = pack.get("auto_instrumentation_baseline")
    if not baseline:
        return set()
    return {s["attribute"] for s in baseline.get("covered_signals", [])}


def _is_redundant_with_baseline(dto, baseline_attributes):
    """True if this DTO's only effect would be to re-emit attribute(s)
    zero-code auto-instrumentation already provides (docs/decisions/011
    Finding 2; E12 DoD (d)) -- every required_attributes entry across
    every one of this DTO's expected_events is already in the baseline.
    A DTO with no required_attributes anywhere makes no attribute claim
    to check, so it is never refused on that basis alone."""
    all_attrs = [a for event in dto["expected_events"] for a in event.get("required_attributes", [])]
    if not all_attrs:
        return False
    return all(a in baseline_attributes for a in all_attrs)


def _assign_rollout_steps(dtos, gaps_by_id, context=None, pack=None):
    """Deterministic, real workflow-criticality-and-dimension ordering
    (architecture.md S7), not a gap-priority-only stand-in: groups by
    workflow criticality first (most critical workflow's DTOs all roll
    out before the next workflow's), then by workflow identity (so two
    same-criticality workflows don't interleave), then by the named
    dimension tiering, then gap priority, then dto id for full
    determinism given the same inputs."""
    dimension_rank = dimension_rollout_rank(pack) if pack is not None else _DIMENSION_ROLLOUT_RANK

    def sort_key(dto):
        gap = gaps_by_id.get(dto["gap_id"])
        workflow_name = gap.get("workflow") if gap else None
        dimension = gap["dimension"] if gap else None
        priority = gap["priority"] if gap else "p3"
        return (
            _workflow_criticality_rank(workflow_name, context),
            workflow_name or "",
            dimension_rank.get(dimension, _DEFAULT_DIMENSION_RANK),
            _PRIORITY_RANK.get(priority, 9999),
            dto["id"],
        )

    for step, dto in enumerate(sorted(dtos, key=sort_key), start=1):
        dto["rollout_step"] = step
    return dtos


def generate_dtos(event_schema, points, gaps, repo_git_sha, context=None, model=None, _completion_fn=None, pack=None):
    """Returns a dict conforming to schemas/implementation_dto.schema.json
    (the real, shared schema — rollout_step included, assigned here, not
    by the model). `context` (context.yaml, if an interview has run) is
    used only for the deterministic rollout_step ordering below, never
    sent to the model -- the model makes no workflow-criticality judgment
    of its own, matching s8-dto-generator/io/input.schema.json, which has
    no context field at all. Returns None if there are no points to
    generate for."""
    if not points:
        return None

    model = model or DEFAULT_MODEL
    reason = missing_credentials(model)
    if reason and _completion_fn is None:
        raise DtoGenerationError(reason)

    system_prompt = _load_skill_instructions()
    output_schema = _load_output_schema()
    batch = {
        "schema_version": "0.1.0", "repo_git_sha": repo_git_sha,
        "event_schema": event_schema, "points": points, "gaps": gaps,
    }

    completion_fn = _completion_fn
    if completion_fn is None:
        try:
            completion_fn = get_completion_fn()
        except MissingLLMDependencyError as e:
            raise DtoGenerationError(str(e)) from e

    try:
        with llm_span("s8", "dto-generator", model):
            response = completion_fn(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": json.dumps(batch, indent=2)},
                ],
                response_format={
                    "type": "json_schema",
                    "json_schema": {"name": f"{SKILL_NAME}_output", "schema": output_schema, "strict": True},
                },
            )
    except Exception as e:
        raise DtoGenerationError(f"model call failed: {e}") from e

    try:
        content = response.choices[0].message.content
        parsed = json.loads(content)
    except (KeyError, IndexError, AttributeError, TypeError, json.JSONDecodeError) as e:
        raise DtoGenerationError(f"could not parse model response as JSON: {e}") from e

    errors = list(Draft202012Validator(output_schema).iter_errors(parsed))
    if errors:
        joined = "; ".join(f"{'/'.join(str(p) for p in e.path)}: {e.message}" for e in errors)
        raise DtoGenerationError(f"model output failed schema validation: {joined}")

    known_attributes = {a["name"] for a in event_schema.get("attributes", [])}
    for dto in parsed["dtos"]:
        for event in dto["expected_events"]:
            unknown = [a for a in event.get("required_attributes", []) if a not in known_attributes]
            if unknown:
                raise DtoGenerationError(
                    f"DTO {dto['id']!r} references attribute(s) not in event_schema: {unknown}"
                )

    baseline_attributes = _baseline_covered_attributes(pack)
    if baseline_attributes:
        kept, refused = [], []
        for dto in parsed["dtos"]:
            (refused if _is_redundant_with_baseline(dto, baseline_attributes) else kept).append(dto)
        parsed["dtos"] = kept
        if refused:
            parsed["refused_dtos"] = [
                {"id": d["id"], "gap_id": d["gap_id"], "reason": "redundant_with_auto_instrumentation"}
                for d in refused
            ]

    gaps_by_id = {g["id"]: g for g in gaps}
    parsed["dtos"] = _assign_rollout_steps(parsed["dtos"], gaps_by_id, context=context, pack=pack)

    validate_shared_schema("implementation_dto", parsed)
    return parsed
