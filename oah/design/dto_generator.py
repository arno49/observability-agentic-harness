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

# architecture.md S7: "tracing + generation capture first, feedback loop
# second, auto-scoring third." Only three dimension names are named by
# that rule; schemas/gap_model.schema.json's dimension enum has no
# auto_scoring member yet (no lens/point-kind produces one), so rank 2
# ("auto-scoring third") is never actually reachable today -- stated here,
# not silently assumed. Every other real dimension (retrieval, tools,
# pii_governance, cost, operations, error_taxonomy, self_telemetry,
# realtime_multimodal) gets the stated default rank between the two
# named tiers, not a fabricated
# more-specific one architecture.md never assigned it.
_DIMENSION_ROLLOUT_RANK = {
    "tracing": 0,
    "generation_capture": 0,
    "feedback": 2,
}
_DEFAULT_DIMENSION_RANK = 1

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


def _assign_rollout_steps(dtos, gaps_by_id, context=None):
    """Deterministic, real workflow-criticality-and-dimension ordering
    (architecture.md S7), not a gap-priority-only stand-in: groups by
    workflow criticality first (most critical workflow's DTOs all roll
    out before the next workflow's), then by workflow identity (so two
    same-criticality workflows don't interleave), then by the named
    dimension tiering, then gap priority, then dto id for full
    determinism given the same inputs."""
    def sort_key(dto):
        gap = gaps_by_id.get(dto["gap_id"])
        workflow_name = gap.get("workflow") if gap else None
        dimension = gap["dimension"] if gap else None
        priority = gap["priority"] if gap else "p3"
        return (
            _workflow_criticality_rank(workflow_name, context),
            workflow_name or "",
            _DIMENSION_ROLLOUT_RANK.get(dimension, _DEFAULT_DIMENSION_RANK),
            _PRIORITY_RANK.get(priority, 9999),
            dto["id"],
        )

    for step, dto in enumerate(sorted(dtos, key=sort_key), start=1):
        dto["rollout_step"] = step
    return dtos


def generate_dtos(event_schema, points, gaps, repo_git_sha, context=None, model=None, _completion_fn=None):
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

    gaps_by_id = {g["id"]: g for g in gaps}
    parsed["dtos"] = _assign_rollout_steps(parsed["dtos"], gaps_by_id, context=context)

    validate_shared_schema("implementation_dto", parsed)
    return parsed
