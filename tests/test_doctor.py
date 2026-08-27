"""Regression tests for oah.doctor's optional-dependency checks --
litellm (`llm` extra) and claude-agent-sdk (`agent` extra), so a real
install missing either is a valid, working install for the commands that
don't need it, not a failed one. Before litellm's fix, _check_litellm
reported ok=False on a missing import, which would make `oah doctor`
claim "One or more checks failed" for a perfectly healthy
deterministic-only install -- _check_claude_agent_sdk is built with that
non-blocking posture from the start."""
import sys

from oah.doctor import _check_claude_agent_sdk, _check_litellm, _check_llm_gateway, format_report


def test_litellm_installed_reports_ok():
    check = _check_litellm()
    assert check.ok is True
    assert check.detail == "importable"


def test_litellm_missing_is_still_ok_not_a_failure(monkeypatch):
    monkeypatch.setitem(sys.modules, "litellm", None)
    check = _check_litellm()
    assert check.ok is True
    assert "optional, not installed" in check.detail
    assert "pip install 'oah[llm]'" in check.detail


def test_missing_litellm_does_not_fail_the_overall_report(monkeypatch):
    monkeypatch.setitem(sys.modules, "litellm", None)
    _, all_ok = format_report([_check_litellm()])
    assert all_ok is True


def test_claude_agent_sdk_installed_reports_ok():
    check = _check_claude_agent_sdk()
    assert check.ok is True
    assert check.detail == "importable"


def test_claude_agent_sdk_missing_is_still_ok_not_a_failure(monkeypatch):
    monkeypatch.setitem(sys.modules, "claude_agent_sdk", None)
    check = _check_claude_agent_sdk()
    assert check.ok is True
    assert "optional, not installed" in check.detail
    assert "pip install 'oah[agent]'" in check.detail


def test_llm_gateway_default_when_no_override_set(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_BASE", raising=False)
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    monkeypatch.delenv("SSL_CERTIFICATE", raising=False)
    monkeypatch.delenv("SSL_VERIFY", raising=False)
    check = _check_llm_gateway()
    assert check.ok is True
    assert "no private-gateway override" in check.detail


def test_llm_gateway_reports_base_url_override(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_BASE", "https://llm-gateway.internal.example.com")
    monkeypatch.delenv("SSL_CERTIFICATE", raising=False)
    check = _check_llm_gateway()
    assert check.ok is True
    assert "private gateway active" in check.detail
    assert "api_base=https://llm-gateway.internal.example.com" in check.detail


def test_llm_gateway_reports_mtls_client_cert(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_BASE", raising=False)
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    monkeypatch.setenv("SSL_CERTIFICATE", "/etc/oah/client.pem")
    check = _check_llm_gateway()
    assert check.ok is True
    assert "client_cert=/etc/oah/client.pem" in check.detail


def test_llm_gateway_never_fails_the_overall_report(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_BASE", "https://llm-gateway.internal.example.com")
    _, all_ok = format_report([_check_llm_gateway()])
    assert all_ok is True
