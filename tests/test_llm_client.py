"""Regression tests for oah.llm_client.get_completion_fn() -- litellm is
the optional `llm` extra (pip install oah[llm]), and get_completion_fn()
is the one place that imports it, so every LLM-calling stage fails with
one clear, actionable message instead of four different raw
ModuleNotFoundErrors when the extra isn't installed."""
import sys

import pytest

from oah.llm_client import DEFAULT_MODEL, MissingLLMDependencyError, get_completion_fn, missing_credentials


def test_returns_litellm_completion_when_installed():
    # litellm is a real dev-time dependency in this environment (see
    # pyproject.toml's dev extra) -- this exercises the actual import.
    import litellm

    assert get_completion_fn() is litellm.completion


def test_raises_actionable_error_when_litellm_not_installed(monkeypatch):
    monkeypatch.setitem(sys.modules, "litellm", None)
    with pytest.raises(MissingLLMDependencyError, match=r"pip install 'oah\[llm\]'"):
        get_completion_fn()


def test_default_model_still_requires_anthropic_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert missing_credentials() is not None
    assert missing_credentials(DEFAULT_MODEL) is not None


def test_non_default_model_skips_the_anthropic_check(monkeypatch):
    # --model openai/gpt-4o (or ollama/llama3, or any other provider) is the
    # caller's own credential/endpoint to have configured -- oah has no
    # business demanding ANTHROPIC_API_KEY for a call that was never going
    # to use Anthropic. Real breakage in the chosen provider's own auth
    # surfaces from the live call itself, not a pre-check here.
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert missing_credentials("openai/gpt-4o") is None
    assert missing_credentials("ollama/llama3") is None
