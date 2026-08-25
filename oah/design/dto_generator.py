"""S8 DTO generation — real LiteLLM call for the parts that need judgment
(anchor selection, preconditions, change type), deterministic post-
processing for the part that doesn't (rollout_step, assigned from
gap_model priority — a stand-in for real rollout_plan.md-driven,
workflow-criticality ordering, which isn't built yet; SKILL.md itself
instructs the model not to set this field).
"""
import json
from pathlib import Path

from jsonschema import Draft202012Validator

from oah.llm_client import missing_credentials
from oah.schemas import validate as validate_shared_schema

SKILLS_DIR = Path(__file__).parent.parent.parent / "skills"
SKILL_NAME = "s8-dto-generator"
DEFAULT_MODEL = "claude-sonnet-5"  # SP8: frontier default

# gap priority -> rollout_step ordering. Lower step number = earlier rollout.
_PRIORITY_TO_STEP_BASE = {"p0": 0, "p1": 1000, "p2": 2000, "p3": 3000}


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


def _assign_rollout_steps(dtos, gaps_by_id):
    """Deterministic: order by (gap priority, dto id) for a stable,
    reproducible step assignment given the same inputs — not by whatever
    order the model happened to list DTOs in."""
    def sort_key(dto):
        gap = gaps_by_id.get(dto["gap_id"])
        priority = gap["priority"] if gap else "p3"
        return (_PRIORITY_TO_STEP_BASE.get(priority, 9999), dto["id"])

    for step, dto in enumerate(sorted(dtos, key=sort_key), start=1):
        dto["rollout_step"] = step
    return dtos


def generate_dtos(event_schema, points, gaps, repo_git_sha, model=None, _completion_fn=None):
    """Returns a dict conforming to schemas/implementation_dto.schema.json
    (the real, shared schema — rollout_step included, assigned here, not
    by the model). Returns None if there are no points to generate for."""
    if not points:
        return None

    reason = missing_credentials()
    if reason and _completion_fn is None:
        raise DtoGenerationError(reason)

    model = model or DEFAULT_MODEL
    system_prompt = _load_skill_instructions()
    output_schema = _load_output_schema()
    batch = {
        "schema_version": "0.1.0", "repo_git_sha": repo_git_sha,
        "event_schema": event_schema, "points": points, "gaps": gaps,
    }

    completion_fn = _completion_fn
    if completion_fn is None:
        import litellm
        completion_fn = litellm.completion

    try:
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
    parsed["dtos"] = _assign_rollout_steps(parsed["dtos"], gaps_by_id)

    validate_shared_schema("implementation_dto", parsed)
    return parsed
