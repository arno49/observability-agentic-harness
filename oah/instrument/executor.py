"""S10 instrumentation, report-only mode — real Claude Agent SDK calls
against the s10-instrumenter skill's own SKILL.md + io/ schemas. Same
"instructions loaded from the real skill file at runtime, output
validated against the skill's own schema, every real failure mode
surfaces rather than being papered over" discipline as
oah/design/lens.py, adapted to the Agent SDK's async streaming session
instead of a single litellm.completion() call.

Per-DTO failures never raise here -- unsupported/refused/failed are all
valid *results*, matching oah/cli.py's _design_all_lenses per-unit
posture: one bad DTO in a batch shouldn't abort the rest. A caller
iterating a whole implementation_dto.json should call
apply_dto_report_only once per DTO and collect results, same shape as
that existing loop.

The report-only guarantee is enforced by ClaudeAgentOptions(tools=["Read"])
in _real_agent_runner -- no Edit/Write tool exists in the session at all,
a hard, tool-level restriction per docs/security.md T4's "enforced
allowlist at the tool-execution layer", not a prompt-level one. The
agent returns the *complete proposed content* of the target file (never
a self-formatted diff) -- the actual diff is computed here via difflib
against the file this module already read itself, so nothing downstream
trusts the model's own patch formatting.

claude-agent-sdk is the optional `agent` extra (pip install oah[agent]) --
see get_agent_runner()'s import-time check, same pattern as
oah/llm_client.py's get_completion_fn() for the (separate) `llm` extra.

fix mode (real edits, git commit-per-DTO, rollback-on-failure) is not
built -- see skills/s10-instrumenter/SKILL.md and ROADMAP.md's E5 status.
The remaining 9 implementation_dto.schema.json change.type values
(collector config, compose services, and other infra-generating DTOs)
are also not built -- SUPPORTED_CHANGE_TYPES below is the honest,
current boundary, not the schema's full vocabulary.
"""
import asyncio
import difflib
import json
from pathlib import Path

from jsonschema import Draft202012Validator

from oah._resources import resolve_dir

SKILLS_DIR = resolve_dir("skills")
SKILL_NAME = "s10-instrumenter"
DEFAULT_MODEL = "claude-sonnet-5"  # SP8: frontier default, same value as every other stage

# implementation_dto.schema.json's change.type enum has 13 values; these 4
# are pure source-code edits with no dependency on infrastructure this
# harness hasn't designed yet (OTLP collector config, compose services --
# those depend on S11 decisions that don't exist). See this module's
# docstring and ROADMAP.md's E5 entry.
SUPPORTED_CHANGE_TYPES = frozenset({"wrap_call", "add_decorator", "insert_span", "propagate_context"})


class MissingAgentSDKError(Exception):
    """Raised when the optional `agent` extra isn't installed. Caught by
    apply_dto_report_only and turned into a 'failed' result for that DTO,
    never left to propagate as a raw ImportError -- same posture as
    oah.llm_client.MissingLLMDependencyError for the `llm` extra."""


def get_agent_runner():
    """Returns _real_agent_runner, or raises MissingAgentSDKError if the
    optional `agent` extra isn't installed."""
    try:
        import claude_agent_sdk  # noqa: F401
    except ImportError as e:
        raise MissingAgentSDKError(
            "S10 needs the optional `agent` extra: pip install 'oah[agent]'"
        ) from e
    return _real_agent_runner


def _load_skill_instructions():
    text = (SKILLS_DIR / SKILL_NAME / "SKILL.md").read_text()
    if text.startswith("---"):
        end = text.index("---", 3)
        text = text[end + 3:]
    return text.strip()


def _load_output_schema():
    return json.loads((SKILLS_DIR / SKILL_NAME / "io" / "output.schema.json").read_text())


def _check_syntax(patched_content):
    """ast.parse sanity check, Python targets only -- informational, not a
    gate (report-only never commits regardless). SP4's spike found a
    py_compile-equivalent check insufficient for semantic bugs (a typo
    that's valid syntax but breaks at runtime); this catches the syntactic
    half only, on purpose, not oversold as more than that."""
    import ast
    try:
        ast.parse(patched_content)
        return True
    except SyntaxError:
        return False


def _result(dto_id, status, diff=None, reason=None, syntax_valid=None):
    return {"dto_id": dto_id, "status": status, "diff": diff, "reason": reason, "syntax_valid": syntax_valid}


def _real_agent_runner(dto, target_repo, model):
    """Spawns one isolated Claude Agent SDK session (query()) scoped to
    target_repo with tools=["Read"] only -- no Edit/Write tool exists in
    this session, so a report-only guarantee holds even if the model
    tries to ignore its instructions. Returns the parsed final JSON
    response (io/output.schema.json shape, unvalidated -- the caller
    validates)."""
    import claude_agent_sdk

    async def _run():
        system_prompt = _load_skill_instructions()
        user_message = json.dumps({
            "schema_version": "0.1.0",
            "dto": dto,
        }, indent=2)
        options = claude_agent_sdk.ClaudeAgentOptions(
            tools=["Read"],
            permission_mode="bypassPermissions",
            cwd=str(target_repo),
            system_prompt=system_prompt,
            model=model,
            max_turns=10,
        )
        final_text = None
        async for message in claude_agent_sdk.query(prompt=user_message, options=options):
            if isinstance(message, claude_agent_sdk.AssistantMessage):
                for block in message.content:
                    if isinstance(block, claude_agent_sdk.TextBlock):
                        final_text = block.text
            elif isinstance(message, claude_agent_sdk.ResultMessage):
                if message.is_error:
                    raise claude_agent_sdk.ClaudeSDKError(
                        f"agent session ended in error (stop_reason={message.stop_reason})"
                    )
        if final_text is None:
            raise claude_agent_sdk.ClaudeSDKError("agent session produced no text response")
        return final_text

    final_text = asyncio.run(_run())
    text = final_text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    return json.loads(text)


def apply_dto_report_only(dto, target_repo, model=None, _agent_runner=None):
    """Returns one schemas/instrument_report.schema.json results[] item.
    Never raises for a per-DTO problem -- unsupported/refused/failed are
    all valid results (see this module's docstring); a caller batching a
    whole implementation_dto.json should call this once per DTO and
    collect results, never abort the batch on one bad DTO.

    `_agent_runner` is the same test-injection pattern used throughout
    this codebase (`_completion_fn` in disambiguate.py/lens.py/panel.py/
    dto_generator.py): a plain sync callable(dto, target_repo, model) ->
    dict matching io/output.schema.json's shape, standing in for the real
    Claude Agent SDK session so every code path here is unit-testable
    without a live API key."""
    dto_id = dto["id"]
    change_type = dto["change"]["type"]
    if change_type not in SUPPORTED_CHANGE_TYPES:
        return _result(
            dto_id, "unsupported",
            reason=f"change.type {change_type!r} is not yet supported by S10 report-only "
                   f"(covers {sorted(SUPPORTED_CHANGE_TYPES)})",
        )

    change_file = dto["change"]["file"]
    target_file = Path(target_repo) / change_file
    if not target_file.is_file():
        return _result(dto_id, "refused", reason=f"{change_file} does not exist in the target repo")
    original_content = target_file.read_text()

    model = model or DEFAULT_MODEL
    if _agent_runner is not None:
        agent_runner = _agent_runner
    else:
        try:
            agent_runner = get_agent_runner()
        except MissingAgentSDKError as e:
            return _result(dto_id, "failed", reason=str(e))

    try:
        raw = agent_runner(dto, target_repo, model)
    except Exception as e:
        return _result(dto_id, "failed", reason=f"agent session failed: {e}")

    errors = list(Draft202012Validator(_load_output_schema()).iter_errors(raw))
    if errors:
        joined = "; ".join(f"{'/'.join(str(p) for p in e.path)}: {e.message}" for e in errors)
        return _result(dto_id, "failed", reason=f"agent output failed schema validation: {joined}")

    if raw["status"] == "refused":
        return _result(dto_id, "refused", reason=raw["reason"])

    patched_content = raw["patched_content"]
    diff = "".join(difflib.unified_diff(
        original_content.splitlines(keepends=True),
        patched_content.splitlines(keepends=True),
        fromfile=change_file, tofile=change_file,
    ))
    syntax_valid = _check_syntax(patched_content) if change_file.endswith(".py") else None
    return _result(dto_id, "applied", diff=diff, syntax_valid=syntax_valid)
