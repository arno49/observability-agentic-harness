"""E9 — backend target config generation. Entirely deterministic: no
LLM, no agent, nothing to mock in this module's own tests -- the
content is fully known once a backend is chosen, so there's no
judgment call to delegate to a model.

architecture.md's S7 lists backend selection as "justified against
context.yaml constraints" via LLM synthesis, but that synthesis
(architecture.md prose generation) isn't built yet -- see README's own
statement that S7's LLM-driven outputs (architecture.md prose,
rollout_plan.md, runbook.md) don't exist, only the deterministic
event_schema.json merge does. So this module takes an explicit
`backend` choice rather than inferring one; --backend is a manual flag
today, not yet constraint-driven.

Config content verified against real, current, cited sources before
writing this module, not assumed:
- opentelemetry.io/docs/collector/configuration/ for the OTLP receiver
  shape and the `debug` exporter name (`logging` was deprecated and
  removed in collector v0.111.0 -- an easy way to write a config that
  looks right but silently doesn't work on a current collector).
- langfuse.com/integrations/native/opentelemetry for self-hosted
  Langfuse's OTLP ingestion: HTTP only (no grpc), `/api/public/otel`,
  Basic Auth (base64 pk-lf-...:sk-lf-...) plus an
  `x-langfuse-ingestion-version: 4` header.

Both backends share the identical `receivers.otlp` block -- they only
differ in `exporters`/`service.pipelines`, which is this module's own
verifiable claim (see tests/test_backend_targets.py), not just an
assertion in this docstring.
"""
import yaml

SUPPORTED_BACKENDS = frozenset({"otel-only", "langfuse"})

_OTLP_RECEIVER = {
    "otlp": {
        "protocols": {
            "grpc": {"endpoint": "0.0.0.0:4317"},
            "http": {"endpoint": "0.0.0.0:4318"},
        },
    },
}


def generate_collector_config(backend):
    """Returns a real otel-collector-config.yaml as a string. Raises
    ValueError for an unsupported backend -- never silently falls back
    to one target's config for a name that doesn't match."""
    if backend not in SUPPORTED_BACKENDS:
        raise ValueError(f"unsupported backend {backend!r} (supported: {sorted(SUPPORTED_BACKENDS)})")

    if backend == "otel-only":
        config = {
            "receivers": _OTLP_RECEIVER,
            "exporters": {"debug": {"verbosity": "detailed"}},
            "service": {
                "pipelines": {
                    "traces": {"receivers": ["otlp"], "exporters": ["debug"]},
                    "metrics": {"receivers": ["otlp"], "exporters": ["debug"]},
                    "logs": {"receivers": ["otlp"], "exporters": ["debug"]},
                },
            },
        }
    else:  # langfuse
        config = {
            "receivers": _OTLP_RECEIVER,
            "exporters": {
                "otlphttp/langfuse": {
                    # Env var substitution, not a placeholder secret -- this
                    # module never invents credential-shaped values (see
                    # this session's own S1 secret-leakage precedent).
                    "endpoint": "${LANGFUSE_HOST}/api/public/otel",
                    "headers": {
                        "Authorization": "Basic ${LANGFUSE_AUTH_BASE64}",
                        "x-langfuse-ingestion-version": "4",
                    },
                },
            },
            "service": {
                "pipelines": {
                    "traces": {"receivers": ["otlp"], "exporters": ["otlphttp/langfuse"]},
                },
            },
        }
    return yaml.safe_dump(config, sort_keys=False)


def generate_compose_note(backend):
    """None for otel-only -- a bare collector container is enough, no
    compose stack needed. For langfuse: a short pointer at Langfuse's
    own actively-maintained docker-compose.yml rather than a vendored
    copy that would drift the moment they change it (6 required
    services today: langfuse-web, langfuse-worker, postgres, clickhouse,
    redis, minio -- none optional in current versions)."""
    if backend not in SUPPORTED_BACKENDS:
        raise ValueError(f"unsupported backend {backend!r} (supported: {sorted(SUPPORTED_BACKENDS)})")
    if backend == "otel-only":
        return None
    return (
        "Self-hosted Langfuse needs its own docker-compose stack (6 required services: "
        "langfuse-web, langfuse-worker, postgres, clickhouse, redis, minio) -- not vendored "
        "here since Langfuse maintains it themselves and it would drift. Canonical source: "
        "https://github.com/langfuse/langfuse/blob/main/docker-compose.yml"
    )
