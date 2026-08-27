"""Unit tests for oah.security.redaction — E8 (docs/decisions/030).

Patterns are the well-known, publicly documented secret shapes real
providers issue (AWS's own AKIA prefix, Anthropic's own sk-ant- prefix,
GitHub's own gh[pousr]_ prefixes, ...) — not an attempt at exhaustive
coverage (see the module's own docstring for the named scope boundary).
"""
from oah.security.redaction import redact_secrets


def test_none_and_empty_pass_through_unchanged():
    assert redact_secrets(None) is None
    assert redact_secrets("") == ""


def test_plain_code_untouched():
    text = "def foo(x, y):\n    return x + y  # nothing secret here\n"
    assert redact_secrets(text) == text


def test_aws_access_key_id_redacted():
    out = redact_secrets('aws_key = "AKIAIOSFODNN7EXAMPLE"')
    assert "AKIAIOSFODNN7EXAMPLE" not in out
    assert "[REDACTED:aws_access_key_id]" in out


def test_anthropic_api_key_redacted_with_specific_label():
    out = redact_secrets(
        'client = Anthropic(api_key="sk-ant-api03-abcdefghijklmnopqrstuvwxyz0123456789")'
    )
    assert "sk-ant-api03" not in out
    assert "[REDACTED:anthropic_api_key]" in out
    # the generic catch-all must not downgrade the specific label
    assert "possible_secret" not in out


def test_openai_api_key_redacted():
    out = redact_secrets('openai_key = "sk-1234567890abcdefghijklmnopqrst"')
    assert "sk-1234567890" not in out
    assert "[REDACTED:openai_api_key]" in out


def test_github_token_redacted():
    out = redact_secrets('token = "ghp_abcdefghijklmnopqrstuvwxyz0123456789"')
    assert "ghp_abcdefgh" not in out
    assert "[REDACTED:github_token]" in out


def test_slack_token_redacted():
    out = redact_secrets('SLACK_TOKEN = "xoxb-1234567890-abcdefghij"')
    assert "xoxb-1234567890" not in out
    assert "[REDACTED:slack_token]" in out


def test_jwt_redacted():
    jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"
    out = redact_secrets(f'token = "{jwt}"')
    assert jwt not in out
    assert "[REDACTED:jwt]" in out


def test_private_key_block_redacted():
    block = "-----BEGIN RSA PRIVATE KEY-----\nMIIEpAIBAAKCAQEA...\n-----END RSA PRIVATE KEY-----"
    out = redact_secrets(f"key = '''{block}'''")
    assert "MIIEpAIBAAKCAQEA" not in out
    assert "[REDACTED:private_key_block]" in out


def test_generic_secret_assignment_redacted():
    out = redact_secrets('password = "hunter2isnotreal"')
    assert "hunter2isnotreal" not in out
    assert "[REDACTED:possible_secret]" in out


def test_short_generic_value_not_flagged():
    """The generic rule requires an 8+ char value -- a short, clearly
    non-secret placeholder like `token = "x"` shouldn't be flagged, real
    precision guard against over-redacting ordinary short strings."""
    out = redact_secrets('token = "x"')
    assert out == 'token = "x"'


def test_variable_name_alone_not_flagged():
    """A bare mention of a secret-sounding word with no assigned literal
    value (e.g. a comment or a function parameter name) is not redacted --
    only an actual `name = "value"` assignment shape is."""
    text = "def get_api_key(): pass  # api_key helper, no literal here"
    assert redact_secrets(text) == text
