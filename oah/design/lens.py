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
from oah.llm_client import missing_credentials

SKILLS_DIR = resolve_dir("skills")
DEFAULT_MODEL = "claude-sonnet-5"  # SP8: frontier default


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
    reason = missing_credentials()
    if reason and _completion_fn is None:
        raise LensDesignError(reason)

    model = model or DEFAULT_MODEL
    system_prompt = _load_skill_instructions(skill_dir)
    output_schema = _load_output_schema(skill_dir)
    batch = {"schema_version": "0.1.0", "repo_git_sha": repo_git_sha, "points": points}
    if context:
        batch["context"] = context

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
    llm_gen_points = [p for p in points if p.get("kind") == "llm_generation"]
    return design_lens("s4-generation-capture", llm_gen_points, repo_git_sha, context, model, _completion_fn)


def design_pii_governance(points, repo_git_sha, context=None, model=None, _completion_fn=None):
    llm_gen_points = [p for p in points if p.get("kind") == "llm_generation"]
    return design_lens("s4-pii-governance", llm_gen_points, repo_git_sha, context, model, _completion_fn)


def design_cost(points, repo_git_sha, context=None, model=None, _completion_fn=None):
    llm_gen_points = [p for p in points if p.get("kind") == "llm_generation"]
    return design_lens("s4-cost", llm_gen_points, repo_git_sha, context, model, _completion_fn)


def design_ops(points, repo_git_sha, context=None, model=None, _completion_fn=None):
    llm_gen_points = [p for p in points if p.get("kind") == "llm_generation"]
    return design_lens("s4-ops", llm_gen_points, repo_git_sha, context, model, _completion_fn)


def design_retrieval(points, repo_git_sha, context=None, model=None, _completion_fn=None):
    retrieval_points = [p for p in points if p.get("kind") == "retrieval"]
    return design_lens("s4-retrieval", retrieval_points, repo_git_sha, context, model, _completion_fn)


def design_feedback(points, repo_git_sha, context=None, model=None, _completion_fn=None):
    feedback_points = [p for p in points if p.get("kind") == "feedback_ingest"]
    return design_lens("s4-feedback", feedback_points, repo_git_sha, context, model, _completion_fn)


def design_realtime_multimodal(points, repo_git_sha, context=None, model=None, _completion_fn=None):
    realtime_points = [p for p in points if p.get("kind") == "realtime_session"]
    return design_lens("s4-realtime-multimodal", realtime_points, repo_git_sha, context, model, _completion_fn)


def design_tracing(points, repo_git_sha, context=None, model=None, _completion_fn=None):
    """Unlike every other lens's wrapper, this does not filter by kind --
    tracing is cross-cutting (architecture.md), so it designs a
    propagation-risk signal for points of any kind S1 has detected."""
    return design_lens("s4-tracing", points, repo_git_sha, context, model, _completion_fn)


def design_tools(points, repo_git_sha, context=None, model=None, _completion_fn=None):
    tool_points = [p for p in points if p.get("kind") == "tool_call"]
    return design_lens("s4-tools", tool_points, repo_git_sha, context, model, _completion_fn)
