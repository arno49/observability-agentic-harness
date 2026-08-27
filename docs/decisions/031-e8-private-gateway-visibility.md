# 031 — E8 phase 2: private-gateway mode is already real via LiteLLM — made visible

Status: landed. Advances E8 (`docs/security.md` T3).

## Context

E8's own scope names "private-gateway mode (base URL + mTLS)" as unbuilt.
Before writing any new code for it, the actual mechanism was verified
directly against litellm's own **installed source** (not its docs, not
assumed) — `oah/llm_client.py` delegates every real model call straight
to `litellm.completion(...)`, so whatever litellm itself supports is
already reachable, if it exists:

- `litellm.completion`'s own docstring (`main.py:465`) documents
  `api_base (str, optional): Base URL for the API`, passed through
  `**kwargs`. Grepped for where it's actually resolved: every provider
  branch in `main.py` does `api_base = api_base or litellm.api_base or
  get_secret(...)` — the Anthropic branch specifically reads
  `ANTHROPIC_API_BASE`/`ANTHROPIC_BASE_URL` from the environment. Since
  `claude-sonnet-5` (OAH's default model) routes through this branch, **a
  base-URL override already works today, via a plain environment
  variable, with zero OAH code involved.**
- `litellm/llms/custom_httpx/http_handler.py` (the shared HTTP transport
  every provider call goes through) does `cert: Final =
  os.getenv("SSL_CERTIFICATE", litellm.ssl_certificate)` and `ssl_verify =
  os.getenv("SSL_VERIFY", litellm.ssl_verify)`, passed straight to
  `httpx`'s own `cert`/`verify` parameters — `httpx.Client(cert=...)` is
  the standard mechanism for mTLS client certificates in Python's most
  common HTTP library. **mTLS also already works today, via
  `SSL_CERTIFICATE`/`SSL_VERIFY` environment variables, with zero OAH
  code involved.**

So the honest state of "private-gateway mode" wasn't "unbuilt" — it was
**built and working, entirely inside a dependency, and completely
undocumented and invisible from OAH's own side.** A user configuring an
enterprise gateway would have had to read litellm's own source to
discover this; nothing in OAH's docs or `oah doctor` output said so.

## Decision

**Do not re-implement what litellm already does correctly.** Writing
OAH-side `--base-url`/`--client-cert` CLI flags that thread through to
`litellm.completion(...)` kwargs would duplicate a mechanism litellm
already exposes via environment variables — the same variables an
enterprise's existing LiteLLM-based tooling (if any) likely already sets.
The real, missing piece was **visibility**, not mechanism:

- `oah/doctor.py` gained `_check_llm_gateway()` — informational, never
  blocking (matches `_check_llm_credentials`'s own posture), reporting
  whether `ANTHROPIC_API_BASE`/`ANTHROPIC_BASE_URL` and/or
  `SSL_CERTIFICATE`/`SSL_VERIFY` are set, and their values, before a run
  starts.
- `docs/security.md`'s T3 mitigation claim is now backed by a verified,
  cited mechanism instead of an aspirational one-liner.

## Consequences

- E8's "private-gateway mode" line item is now honestly `built` (via a
  verified dependency mechanism, made visible) rather than `unbuilt`. No
  new runtime behavior was added — the mechanism was already live before
  this phase; only its visibility changed.
- A real, named boundary: a `--model` other than the default routes
  through a *different* provider in litellm, whose own equivalent env var
  (`OPENAI_API_BASE`, etc.) is that provider's convention, not checked by
  `_check_llm_gateway()` — matching `missing_credentials()`'s own existing
  precedent of not guessing at every LiteLLM-supported provider's
  credential/config env-var name.
- `oah/instrument/executor.py`'s Claude Agent SDK calls (S10, Anthropic-
  pinned, not LiteLLM-routed) were **not investigated in this phase** —
  whether the Agent SDK has an equivalent native base-URL/mTLS mechanism
  is a real, separate question, named here rather than assumed answered.
