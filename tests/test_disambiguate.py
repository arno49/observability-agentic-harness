"""Regression tests for oah.discovery.disambiguate — mocked, not live.

No ANTHROPIC_API_KEY or litellm network access is available in CI or this
dev environment, so `_completion_fn` stands in for litellm.completion
throughout. What's tested is real: prompt construction (the skill's actual
SKILL.md content, not a copy), response parsing, schema validation of
what comes back, and the specific failure modes a caller must not paper
over (missing credentials, invalid JSON, schema-invalid output, a partial
batch response) — not whether the live Anthropic API itself behaves as
documented, which no unit test can verify without a real key.
"""
import json
from types import SimpleNamespace

import pytest

from oah.discovery.disambiguate import disambiguate, DisambiguationError, missing_credentials


def _fake_response(payload):
    """Mimic litellm's OpenAI-compatible response shape closely enough for
    disambiguate()'s own parsing path (response.choices[0].message.content)."""
    message = SimpleNamespace(content=json.dumps(payload))
    choice = SimpleNamespace(message=message)
    return SimpleNamespace(choices=[choice])


CANDIDATE = {
    "candidate_id": "c1", "file": "app.py", "line": 10, "code_excerpt": "clients['x'].messages.create()",
    "scanner_kind": None, "scanner_confidence": 0.3, "imports": ["anthropic"],
}


def test_empty_batch_never_calls_the_model():
    calls = []
    result = disambiguate([], _completion_fn=lambda **kw: calls.append(kw))
    assert result == []
    assert calls == []


def test_missing_credentials_detected_without_a_call(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert missing_credentials() is not None
    with pytest.raises(DisambiguationError, match="ANTHROPIC_API_KEY"):
        # No _completion_fn override -> real credential check path runs.
        disambiguate([CANDIDATE])


def test_prompt_uses_real_skill_instructions_not_a_copy():
    captured = {}

    def fake_completion(**kwargs):
        captured.update(kwargs)
        return _fake_response({"schema_version": "0.1.0", "results": [
            {"candidate_id": "c1", "kind": "llm_generation", "confidence": 0.9, "detection": "llm_disambiguation"},
        ]})

    disambiguate([CANDIDATE], _completion_fn=fake_completion)
    system_msg = captured["messages"][0]["content"]
    # Pulled from the real file at call time -- this line only exists in
    # skills/s1-surface-mapper/SKILL.md, not hardcoded in disambiguate.py.
    assert "You resolve **only** the candidates the deterministic scanner could not classify" in system_msg
    user_msg = captured["messages"][1]["content"]
    sent = json.loads(user_msg)
    assert sent["candidates"][0]["candidate_id"] == "c1"


def test_valid_response_parsed_and_returned():
    def fake_completion(**kwargs):
        return _fake_response({"schema_version": "0.1.0", "results": [
            {"candidate_id": "c1", "kind": "llm_generation", "framework": "anthropic-sdk",
             "confidence": 0.9, "detection": "llm_disambiguation"},
        ]})

    results = disambiguate([CANDIDATE], _completion_fn=fake_completion)
    assert len(results) == 1
    assert results[0]["kind"] == "llm_generation"


def test_schema_invalid_response_raises_not_silently_accepted():
    def fake_completion(**kwargs):
        # Missing required "detection" field.
        return _fake_response({"schema_version": "0.1.0", "results": [
            {"candidate_id": "c1", "kind": "llm_generation", "confidence": 0.9},
        ]})

    with pytest.raises(DisambiguationError, match="schema validation"):
        disambiguate([CANDIDATE], _completion_fn=fake_completion)


def test_unparseable_response_raises():
    def fake_completion(**kwargs):
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="not json"))])

    with pytest.raises(DisambiguationError, match="could not parse"):
        disambiguate([CANDIDATE], _completion_fn=fake_completion)


def test_partial_batch_response_raises_not_silently_merged():
    """Two candidates sent, model returns a result for only one -- must not
    silently treat the other as resolved or drop it without saying so."""
    c2 = {**CANDIDATE, "candidate_id": "c2"}

    def fake_completion(**kwargs):
        return _fake_response({"schema_version": "0.1.0", "results": [
            {"candidate_id": "c1", "kind": "llm_generation", "confidence": 0.9, "detection": "llm_disambiguation"},
        ]})

    with pytest.raises(DisambiguationError, match="c2"):
        disambiguate([CANDIDATE, c2], _completion_fn=fake_completion)


def test_model_call_exception_wrapped_not_leaked_raw():
    def fake_completion(**kwargs):
        raise RuntimeError("connection reset")

    with pytest.raises(DisambiguationError, match="model call failed"):
        disambiguate([CANDIDATE], _completion_fn=fake_completion)


def test_rejection_kind_null_is_valid_output():
    """kind: null is a correct rejection per SKILL.md, not an error."""
    def fake_completion(**kwargs):
        return _fake_response({"schema_version": "0.1.0", "results": [
            {"candidate_id": "c1", "kind": None, "confidence": 0.9,
             "detection": "llm_disambiguation", "notes": "dead-code-candidate"},
        ]})

    results = disambiguate([CANDIDATE], _completion_fn=fake_completion)
    assert results[0]["kind"] is None
