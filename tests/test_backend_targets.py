"""Regression tests for oah.backend_targets -- entirely deterministic,
no LLM/agent call anywhere in this module, so nothing here needs
mocking (the first fully-unmocked feature area this session)."""
import yaml
import pytest

from oah.backend_targets import SUPPORTED_BACKENDS, generate_collector_config, generate_compose_note


def test_both_backends_produce_valid_yaml():
    for backend in SUPPORTED_BACKENDS:
        parsed = yaml.safe_load(generate_collector_config(backend))
        assert "receivers" in parsed
        assert "exporters" in parsed
        assert "service" in parsed


def test_receivers_otlp_block_is_identical_across_backends():
    """The DoD's own claim (same repo instrumentable to both targets
    from the same DTOs) hinges on the receiver shape being shared --
    checked directly here, not assumed."""
    otel_only = yaml.safe_load(generate_collector_config("otel-only"))
    langfuse = yaml.safe_load(generate_collector_config("langfuse"))
    assert otel_only["receivers"] == langfuse["receivers"]


def test_only_exporters_and_pipelines_differ_between_backends():
    otel_only = yaml.safe_load(generate_collector_config("otel-only"))
    langfuse = yaml.safe_load(generate_collector_config("langfuse"))
    differing_keys = {k for k in otel_only if otel_only.get(k) != langfuse.get(k)}
    assert differing_keys == {"exporters", "service"}


def test_otel_only_uses_the_current_debug_exporter_name():
    """`logging` was deprecated and removed in collector v0.111.0 --
    `debug` is the current, correct name. A config using the old name
    looks plausible but silently doesn't work on a current collector."""
    config = yaml.safe_load(generate_collector_config("otel-only"))
    assert "debug" in config["exporters"]
    assert "logging" not in config["exporters"]


def test_langfuse_exporter_uses_http_not_grpc():
    """Self-hosted Langfuse's OTLP ingestion is HTTP-only -- an
    otlphttp exporter, not otlp (which defaults to grpc)."""
    config = yaml.safe_load(generate_collector_config("langfuse"))
    assert "otlphttp/langfuse" in config["exporters"]
    assert "otlp/langfuse" not in config["exporters"]


def test_langfuse_exporter_has_required_auth_headers():
    config = yaml.safe_load(generate_collector_config("langfuse"))
    headers = config["exporters"]["otlphttp/langfuse"]["headers"]
    assert headers["x-langfuse-ingestion-version"] == "4"
    assert "Basic" in headers["Authorization"]


def test_langfuse_config_never_invents_a_placeholder_secret():
    """Env var substitution only -- this module must never write a
    fake-looking credential value that could be mistaken for a real
    one (same discipline as this session's S1 secret-leakage fix)."""
    raw = generate_collector_config("langfuse")
    assert "pk-lf-" not in raw
    assert "sk-lf-" not in raw
    assert "${LANGFUSE_AUTH_BASE64}" in raw


def test_unsupported_backend_raises_value_error():
    with pytest.raises(ValueError, match="unsupported backend"):
        generate_collector_config("datadog")
    with pytest.raises(ValueError, match="unsupported backend"):
        generate_compose_note("datadog")


def test_compose_note_otel_only_is_none():
    assert generate_compose_note("otel-only") is None


def test_compose_note_langfuse_names_all_six_required_services():
    note = generate_compose_note("langfuse")
    for service in ["langfuse-web", "langfuse-worker", "postgres", "clickhouse", "redis", "minio"]:
        assert service in note
    assert "github.com/langfuse/langfuse" in note
