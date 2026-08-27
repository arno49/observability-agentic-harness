"""Secret-pattern redaction (E8, docs/decisions/030): the harness's own
threat model (docs/security.md's T2) names "secret-pattern redaction on
everything the harness writes" as a stated mitigation -- this module is
its first real implementation, not just the design-doc claim.

Real, concrete first consumer: oah/discovery/python_adapter.py's `_excerpt`
copies raw surrounding source lines into an S1 "ambiguous candidate"
(`code_excerpt`) whenever a call site's receiver can't be resolved
deterministically. That candidate is both (a) sent to `disambiguate()`'s
LLM call (SP8) -- real data egress to a model provider, T3's own concern --
and (b) checkpointed verbatim into the harness's own state DB and any
`-o` output file -- T2's own concern. A hardcoded credential sitting near
an ambiguous call site (a real, plausible shape -- credential setup and
client construction are often adjacent) would today leak through both
paths unredacted. Named, deliberately NOT yet wired in here: S4-S9 skill
context, S6's adversarial panel, and oah/validate's own checkers may
extract source excerpts too -- a real, separate sweep, not attempted in
this phase (this module's own reusable `redact_secrets` is what a
follow-up phase would call from each of those sites, not a rewrite).

Patterns are the well-known, high-confidence, publicly documented secret
shapes every mainstream secret scanner (gitleaks, trufflehog, git-secrets)
also keys on -- not an attempt at gitleaks' full multi-hundred-rule
library. A generic "assignment to a secret-sounding variable name" rule
closes some of that gap at the cost of being pattern-shaped rather than
provider-specific; still real coverage, not none, and named honestly as
non-exhaustive rather than claimed complete.
"""
import re

_PLACEHOLDER = "[REDACTED:{name}]"

# (name, compiled pattern). Provider-specific patterns are tried before the
# generic catch-all so a real credential is tagged with its actual kind
# where recognizable, rather than falling through to the generic label.
_PROVIDER_PATTERNS = [
    ("aws_access_key_id", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("anthropic_api_key", re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}")),
    ("openai_api_key", re.compile(r"sk-[A-Za-z0-9]{20,}")),
    ("github_token", re.compile(r"gh[pousr]_[A-Za-z0-9]{36,}")),
    ("slack_token", re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}")),
    ("jwt", re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")),
    ("private_key_block", re.compile(
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.DOTALL)),
]

# `sk-ant-...` also matches the (broader) openai_api_key shape -- ordering
# above ensures anthropic_api_key's pattern.sub runs first and fully
# consumes the match, so a real Anthropic key is never left half-matched
# for the openai pattern to (harmlessly, but confusingly) also flag.

_GENERIC_ASSIGNMENT = re.compile(
    r"""(?i)\b(api[_-]?key|secret(?:[_-]?key)?|password|passwd|access[_-]?key|auth[_-]?token|token)\b"""
    r"""\s*[:=]\s*(['"])([^'"\n]{8,})\2""",
)


def redact_secrets(text):
    """Return `text` with recognizable secret-shaped substrings replaced by
    a `[REDACTED:<kind>]` placeholder. None/empty input is returned
    unchanged (matches every other `_text`-style helper in this codebase's
    own adapters, which never crash on an absent value)."""
    if not text:
        return text
    for name, pattern in _PROVIDER_PATTERNS:
        text = pattern.sub(_PLACEHOLDER.format(name=name), text)

    def _generic_sub(m):
        # A provider-specific pattern above may have already redacted this
        # exact value on the pass before this one -- re-matching it here
        # would just downgrade a specific label (e.g. anthropic_api_key)
        # to the generic one, real information loss for no real gain.
        if m.group(3).startswith("[REDACTED:"):
            return m.group(0)
        return f"{m.group(1)}={_PLACEHOLDER.format(name='possible_secret')}"

    return _GENERIC_ASSIGNMENT.sub(_generic_sub, text)
