"""Shared LiteLLM credential check — used by every stage that makes a real
model call (S1 disambiguation, S4 lens design, more as they're built).
Lives here, not inside any one stage's module, since it was originally
written for S1 alone and importing it from oah.discovery.disambiguate into
oah.design.lens was already a layering smell by the time a second caller
showed up.

litellm itself is an optional dependency (`pip install oah[llm]`) --
deterministic-only commands (doctor, estimate, map --no-disambiguate,
inventory, gaps, interview) never need it, and its transitive dependency
tree (openai, boto3, tiktoken, huggingface-hub, aiohttp, pydantic, ...) is
large enough that forcing it on every install was worth avoiding. Every
stage's own `import litellm` therefore goes through get_completion_fn()
so a missing extra fails with one clear message instead of four different
raw ModuleNotFoundErrors.
"""
import os

DEFAULT_MODEL = "claude-sonnet-5"  # SP8: frontier default; every stage's own
                                    # DEFAULT_MODEL imports this rather than
                                    # restating the literal.


class MissingLLMDependencyError(Exception):
    """Raised when a stage needs litellm but the optional `llm` extra isn't
    installed. Every caller catches this and re-raises as its own
    stage-specific error type (LensDesignError, PanelReviewError, ...) --
    never let this or a raw ImportError reach the CLI directly."""


def missing_credentials(model=None):
    """Returns a human-readable reason a live call would fail, or None if
    credentials look present. Checked before spending a call attempt, not
    just caught after — the same "check before you spend" spirit as
    oah estimate (SP5) and oah doctor (SP3).

    Only enforces ANTHROPIC_API_KEY for the default model. An explicitly
    chosen non-default model (--model openai/gpt-4o, --model
    ollama/llama3, ...) is the caller's own provider/endpoint to have
    configured -- guessing every LiteLLM-supported provider's credential
    env-var name here would be both incomplete and wrong for local models
    that need no credential at all; the live call itself surfaces that
    provider's real error if something's missing."""
    if model is not None and model != DEFAULT_MODEL:
        return None
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return ("ANTHROPIC_API_KEY is not set — this stage needs it (or another "
                "LiteLLM-supported credential for the configured model) to make a live model call.")
    return None


def get_completion_fn():
    """Returns litellm.completion, or raises MissingLLMDependencyError if
    the optional `llm` extra isn't installed."""
    try:
        import litellm
    except ImportError as e:
        raise MissingLLMDependencyError(
            "this stage needs the optional `llm` extra: pip install 'oah[llm]'"
        ) from e
    return litellm.completion
