"""Shared LiteLLM credential check — used by every stage that makes a real
model call (S1 disambiguation, S4 lens design, more as they're built).
Lives here, not inside any one stage's module, since it was originally
written for S1 alone and importing it from oah.discovery.disambiguate into
oah.design.lens was already a layering smell by the time a second caller
showed up.
"""
import os


def missing_credentials():
    """Returns a human-readable reason a live call would fail, or None if
    credentials look present. Checked before spending a call attempt, not
    just caught after — the same "check before you spend" spirit as
    oah estimate (SP5) and oah doctor (SP3)."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return ("ANTHROPIC_API_KEY is not set — this stage needs it (or another "
                "LiteLLM-supported credential for the configured model) to make a live model call.")
    return None
