# 030 — E8 phase 1: secret-pattern redaction on the harness's own outputs

Status: landed. Advances E8 (`docs/security.md`, `docs/security-threat-model.md`,
SP7's own named consequence, `docs/decisions/008`).

## Context

E8's own one-line scope names four things: secret-redaction in the
harness's own logs, a directory allowlist, prompt-injection resistance
(treat repo content as data), and private-gateway mode. Auditing what
actually existed in code before this phase (not what the design doc
claimed): the threat model and SP7's four red-team fixtures were real and
landed (`docs/decisions/008`); S10's tool-execution allowlist was real
(`oah/instrument/executor.py`'s agent session has no Edit/Write tool at
all — a structural restriction, not a prompt-level one); but **secret
redaction had zero implementation** — `docs/security.md`'s T2 mitigation
("secret-pattern redaction on everything the harness writes") was a
design claim with no code behind it, and grepping the codebase for
`redact`/`secret` turned up nothing beyond the docs themselves.

A concrete, real leak path exists today, not hypothetical:
`oah/discovery/python_adapter.py`'s `_excerpt` copies raw surrounding
source lines into an S1 "ambiguous candidate" (`code_excerpt`) whenever a
call site's receiver can't be resolved deterministically. That candidate
is (a) sent to `disambiguate()`'s LLM call (SP8) — real data egress to a
model provider — and (b) checkpointed verbatim into the harness's own
state DB and any `-o` output file. A hardcoded credential sitting near an
ambiguous call site is a plausible real shape (credential setup and
client construction are often textually adjacent), and today it would
leak through both paths unredacted.

## What was built

- **`oah/security/redaction.py`** (new module): `redact_secrets(text)`.
  Provider-specific patterns for the well-known, publicly documented
  secret shapes real providers issue — AWS's own `AKIA` access-key-ID
  prefix, Anthropic's own `sk-ant-` prefix, OpenAI's `sk-` prefix,
  GitHub's `gh[pousr]_` token prefixes, Slack's `xox[baprs]-` token
  prefixes, JWTs (`eyJ...` base64-encoded header), PEM private-key
  blocks — run first, followed by a generic
  `<secret-sounding-name> = "<8+ char value>"` catch-all for anything the
  specific patterns miss. **Not an attempt at gitleaks' full multi-hundred-
  rule library** — named explicitly as real-but-non-exhaustive coverage,
  not claimed complete.
- **A real bug found and fixed while building, not after**: the generic
  catch-all originally re-matched a value a provider-specific pattern had
  *already* redacted on the pass before it (the placeholder text
  `[REDACTED:anthropic_api_key]` is itself 8+ characters, so the generic
  rule's own regex matched it), downgrading a specific label to the
  generic one — real information loss for zero gain. Fixed by checking
  whether the captured value already starts with `[REDACTED:` before
  relabeling it.
- Wired into `_excerpt`, the one real place today that copies raw
  target-repo source into an artifact both LLM-sent and disk-persisted —
  `oah/discovery/typescript_adapter.py` and `oah/discovery/java_adapter.py`
  have no ambiguous-candidate/LLM-disambiguation path yet (both modules'
  own stated scope boundary), so neither has an equivalent excerpt to
  redact.
- Real tests: `tests/test_redaction.py` (12 cases, one per pattern plus
  the none/empty/plain-code passthrough and the two precision guards —
  short values not flagged, a bare secret-sounding word with no assigned
  literal not flagged) and a regression test in `tests/test_python_adapter.py`
  proving a real hardcoded Anthropic key near an ambiguous call site is
  redacted in the actual `code_excerpt` an ambiguous candidate carries,
  with the specific `anthropic_api_key` label surviving (not downgraded
  by the generic catch-all).

## Decision

**Scoped to the one real, already-identified leak path, not a sweep
across every stage that reads source.** S4-S9's own skill context, S6's
adversarial panel, and `oah/validate`'s checkers may extract source
excerpts too — each is a real, separate site this phase does not touch,
named here rather than silently assumed covered. The redaction function
itself is written as reusable, general infrastructure specifically so a
follow-up phase calls it from each of those sites rather than needing a
second implementation.

## Consequences

- `docs/security.md`'s T2 mitigation claim is now backed by real,
  tested code at its highest-value site, not just a design-doc statement.
- E8's remaining real gaps: sweeping redaction into S4-S9/S6/validate's
  own source-reading paths; a directory allowlist for S1-S9's *read*
  scope specifically (S10's write-side allowlist is real; whether S1-S9's
  `rglob`-under-`repo_root` pattern needs an explicit enforced boundary
  beyond what path construction already implies, e.g. against symlink
  escapes, is a real, separate question not investigated here);
  private-gateway mode (`base_url` override + mTLS client certs) for
  `oah/llm_client.py` and `oah/instrument/executor.py`'s Agent SDK calls —
  named, not started; the red-team-exercise DoD itself, which needs a
  larger seeded corpus than SP7's own four fixtures (SP7's own
  Consequences section already named this scaling path).
