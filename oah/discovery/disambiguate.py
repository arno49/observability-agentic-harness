"""S1 LLM disambiguation pass — the real thing, not a spike stand-in.

SP1's and SP8's spikes used Claude Code's own agent mechanism to exercise
the s1-surface-mapper skill (a reasonable stand-in for testing, stated as
such in both decision records). This module is what `oah`'s own standalone
process actually calls at runtime: LiteLLM (SP8's decision:
docs/decisions/009-sp8-litellm-model-abstraction.md), frontier tier by
default for this role specifically because SP8's own comparison found
light tier confidently wrong on exactly the kind of cross-referencing
judgment this role exists to do.

The skill's instructions are loaded from skills/s1-surface-mapper/SKILL.md
at runtime, not copied here — this can never drift from what
docs/SKILLS.md documents as the skill of record.
"""
import json
import os
from pathlib import Path

from jsonschema import Draft202012Validator

SKILL_PATH = Path(__file__).parent.parent.parent / "skills" / "s1-surface-mapper"
DEFAULT_MODEL = "claude-sonnet-5"  # SP8: frontier default for S1 disambiguation, not light tier


class DisambiguationError(Exception):
    """Raised on any failure to get a valid, schema-conformant result — a
    caller must treat this as 'candidate still unresolved', never catch it
    and fabricate a result."""


def missing_credentials():
    """Returns a human-readable reason a live call would fail, or None if
    credentials look present. Checked before spending a call attempt, not
    just caught after — the same "check before you spend" spirit as
    oah estimate (SP5) and oah doctor (SP3)."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return "ANTHROPIC_API_KEY is not set — S1 disambiguation needs it (or another LiteLLM-supported credential for the configured model)."
    return None


def _load_skill_instructions():
    """Strip YAML frontmatter, return the skill's Markdown body as the
    system prompt."""
    text = (SKILL_PATH / "SKILL.md").read_text()
    if text.startswith("---"):
        end = text.index("---", 3)
        text = text[end + 3:]
    return text.strip()


def _load_output_schema():
    return json.loads((SKILL_PATH / "io" / "output.schema.json").read_text())


def disambiguate(candidates, model=None, _completion_fn=None):
    """candidates: list matching skills/s1-surface-mapper/io/input.schema.json's
    `candidates` items. Returns a list matching that skill's
    io/output.schema.json `results` items.

    `_completion_fn` is an injection point for tests (a stand-in for
    litellm.completion) — never used in real invocations, where it's None
    and the real litellm client is imported and called.
    """
    if not candidates:
        return []

    reason = missing_credentials()
    if reason and _completion_fn is None:
        raise DisambiguationError(reason)

    model = model or DEFAULT_MODEL
    system_prompt = _load_skill_instructions()
    output_schema = _load_output_schema()
    batch = {"schema_version": "0.1.0", "candidates": candidates}

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
                "json_schema": {
                    "name": "s1_disambiguation_output",
                    "schema": output_schema,
                    "strict": True,
                },
            },
        )
    except Exception as e:
        raise DisambiguationError(f"model call failed: {e}") from e

    try:
        content = response.choices[0].message.content
        parsed = json.loads(content)
    except (KeyError, IndexError, AttributeError, TypeError, json.JSONDecodeError) as e:
        raise DisambiguationError(f"could not parse model response as JSON: {e}") from e

    errors = list(Draft202012Validator(output_schema).iter_errors(parsed))
    if errors:
        joined = "; ".join(f"{'/'.join(str(p) for p in e.path)}: {e.message}" for e in errors)
        raise DisambiguationError(f"model output failed schema validation: {joined}")

    returned_ids = {r["candidate_id"] for r in parsed["results"]}
    sent_ids = {c["candidate_id"] for c in candidates}
    missing = sent_ids - returned_ids
    if missing:
        raise DisambiguationError(
            f"model returned results for only {len(returned_ids)}/{len(sent_ids)} "
            f"candidates sent — missing: {sorted(missing)}. Not merging a partial "
            f"batch silently; retry or investigate."
        )

    return parsed["results"]
