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
import re
from pathlib import Path

from jsonschema import Draft202012Validator

from oah.llm_client import missing_credentials  # noqa: F401 (re-exported — see that module's docstring)

SKILL_PATH = Path(__file__).parent.parent.parent / "skills" / "s1-surface-mapper"
DEFAULT_MODEL = "claude-sonnet-5"  # SP8: frontier default for S1 disambiguation, not light tier

# Found by adversarial review: SKILL.md states, as a Hard rule, "Never
# emit secrets, keys, or environment values ... in any field, including
# notes" -- but nothing enforced it. A mocked response whose notes/
# workflow_hint field echoed a source excerpt verbatim (including a
# literal API key) validated cleanly and flowed straight into the
# persisted surface_map.json. schemas add maxLength bounds (blast-radius
# limiting, not detection); this is the second, detection layer: a
# pattern match on well-known secret-key *shapes*, not a comprehensive
# secrets scanner -- stated as a real, bounded scope, not oversold.
_SECRET_PATTERNS = [
    re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}"),   # Anthropic API key
    re.compile(r"sk-[A-Za-z0-9]{20,}"),         # OpenAI-style API key
    re.compile(r"AKIA[0-9A-Z]{16}"),            # AWS access key ID
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),  # GitHub token (ghp_/gho_/ghu_/ghs_/ghr_)
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),  # Slack token
]


def _find_leaked_secret(text):
    if not text:
        return None
    for pattern in _SECRET_PATTERNS:
        match = pattern.search(text)
        if match:
            return match.group(0)
    return None


class DisambiguationError(Exception):
    """Raised on any failure to get a valid, schema-conformant result — a
    caller must treat this as 'candidate still unresolved', never catch it
    and fabricate a result."""


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

    for result in parsed["results"]:
        for field in ("notes", "workflow_hint", "framework"):
            leaked = _find_leaked_secret(result.get(field))
            if leaked:
                raise DisambiguationError(
                    f"result for candidate_id={result.get('candidate_id')!r} field {field!r} "
                    f"contains what looks like a real secret/API key — refusing to merge this "
                    f"batch into surface_map.json. This violates SKILL.md's own Hard rule "
                    f"('never emit secrets, keys, or environment values'); investigate the "
                    f"model response rather than retrying blindly."
                )

    return parsed["results"]
