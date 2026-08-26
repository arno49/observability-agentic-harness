"""S6 adversarial design panel — real LiteLLM calls against a persona
skill's own SKILL.md + io/ schemas. Same mechanics as oah/design/lens.py
(instructions loaded from the real skill file at runtime, output validated
against the skill's own schema, every failure mode raises), kept as a
parallel implementation rather than forcing lens.py to generalize over two
different batch shapes (S4 batches by `points`, S6 batches by
`design_fragments`) — matching how oah/discovery/disambiguate.py and
oah/design/lens.py are already separate, structurally similar modules
rather than one over-abstracted one.
"""
import json

from jsonschema import Draft202012Validator

from oah._resources import resolve_dir
from oah.llm_client import missing_credentials

SKILLS_DIR = resolve_dir("skills")
DEFAULT_MODEL = "claude-sonnet-5"  # SP8: frontier default


class PanelReviewError(Exception):
    """A caller must treat this as 'no verdict produced', never catch it
    and fabricate one."""


def _load_skill_instructions(skill_dir):
    text = (skill_dir / "SKILL.md").read_text()
    if text.startswith("---"):
        end = text.index("---", 3)
        text = text[end + 3:]
    return text.strip()


def _load_output_schema(skill_dir):
    return json.loads((skill_dir / "io" / "output.schema.json").read_text())


def run_persona(skill_name, design_fragments, repo_git_sha, context=None, model=None, _completion_fn=None):
    """design_fragments: whatever S4 lens outputs exist so far (at least
    one, or this never calls the model). Returns a panel_verdict dict
    conforming to the persona skill's own io/output.schema.json."""
    if not design_fragments:
        return None

    skill_dir = SKILLS_DIR / skill_name
    reason = missing_credentials()
    if reason and _completion_fn is None:
        raise PanelReviewError(reason)

    model = model or DEFAULT_MODEL
    system_prompt = _load_skill_instructions(skill_dir)
    output_schema = _load_output_schema(skill_dir)
    batch = {"schema_version": "0.1.0", "repo_git_sha": repo_git_sha, "design_fragments": design_fragments}
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
        raise PanelReviewError(f"model call failed: {e}") from e

    try:
        content = response.choices[0].message.content
        parsed = json.loads(content)
    except (KeyError, IndexError, AttributeError, TypeError, json.JSONDecodeError) as e:
        raise PanelReviewError(f"could not parse model response as JSON: {e}") from e

    errors = list(Draft202012Validator(output_schema).iter_errors(parsed))
    if errors:
        joined = "; ".join(f"{'/'.join(str(p) for p in e.path)}: {e.message}" for e in errors)
        raise PanelReviewError(f"model output failed schema validation: {joined}")

    expected_overall = _expected_overall(parsed["findings"])
    if parsed["overall"] != expected_overall:
        raise PanelReviewError(
            f"overall={parsed['overall']!r} is inconsistent with its own findings "
            f"(severities imply {expected_overall!r}) -- panel_verdict.schema.json's own rule: "
            f"pass has no error findings, pass_with_findings has only warnings, fail has at "
            f"least one error"
        )

    return parsed


def _expected_overall(findings):
    """panel_verdict.schema.json's own documented rule, recomputed and
    enforced rather than trusted from the model: 'pass: no findings at
    error severity. pass_with_findings: only warning-severity findings.
    fail: at least one error-severity finding.' Nothing previously checked
    that a persona's own `overall` field actually agreed with its own
    `findings` array -- found by adversarial review: a mocked SRE verdict
    with overall="pass" and one error-severity finding passed schema
    validation and every downstream S9 check cleanly, silently downgrading
    what should have been remediate_before_release."""
    if any(f["severity"] == "error" for f in findings):
        return "fail"
    if any(f["severity"] == "warning" for f in findings):
        return "pass_with_findings"
    return "pass"


def run_cost_skeptic(design_fragments, repo_git_sha, context=None, model=None, _completion_fn=None):
    return run_persona("s6-cost-skeptic", design_fragments, repo_git_sha, context, model, _completion_fn)


def run_sre(design_fragments, repo_git_sha, context=None, model=None, _completion_fn=None):
    return run_persona("s6-sre", design_fragments, repo_git_sha, context, model, _completion_fn)


def run_security(design_fragments, repo_git_sha, context=None, model=None, _completion_fn=None):
    return run_persona("s6-security", design_fragments, repo_git_sha, context, model, _completion_fn)
