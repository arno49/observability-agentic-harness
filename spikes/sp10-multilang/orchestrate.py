#!/usr/bin/env python3
"""SP10 prototype: one orchestrator, two language adapters.

Proves the actual claim SP10 needs proven — not "these two detectors both
exist" but "one caller can drive both through the same interface without
knowing which language it's looking at." See README.md for the interface
contract and the decision record for what this did and didn't end up
requiring per language.

Usage:
    python3 orchestrate.py <path>   # auto-detects python vs typescript by extension mix
"""
import json
import subprocess
import sys
from pathlib import Path

SP1_DIR = Path(__file__).parent.parent / "sp1-surface-mapping"
TS_ADAPTER = Path(__file__).parent / "ts-adapter" / "detect.js"

sys.path.insert(0, str(SP1_DIR))
import detect as python_detect  # noqa: E402  (SP1's prototype, reused not duplicated)


class LanguageAdapter:
    """The interface both adapters conform to. Not an ABC on purpose — this
    is a spike proving the shape works, not committing to a Python runtime
    mechanism (E2's real interface is SP10's decision record's job, once
    SP10's other findings are folded in — this file is evidence for that
    decision, not the decision itself)."""

    language = None

    def detect(self, target_path):
        """Yield candidate dicts: file, line, confidence, resolved_sdk,
        chain, reason, language — the same seven keys regardless of adapter.
        The TS adapter also adds `shape` (SP12, docs/decisions/013) naming
        which detection pass produced a candidate, and `has_path_parameter`
        on declarative_registration candidates only -- both additive, so
        eval.py's exact (file, line) scoring is unaffected either way."""
        raise NotImplementedError


class PythonAdapter(LanguageAdapter):
    language = "python"

    def detect(self, target_path):
        for candidate in python_detect.detect_path(target_path):
            candidate = dict(candidate)
            candidate["language"] = "python"
            yield candidate


class TypeScriptAdapter(LanguageAdapter):
    language = "typescript"

    def detect(self, target_path):
        result = subprocess.run(
            ["node", str(TS_ADAPTER), str(target_path)],
            capture_output=True, text=True, check=True,
        )
        for line in result.stdout.splitlines():
            if line.strip():
                yield json.loads(line)


ADAPTERS = {"python": PythonAdapter(), "typescript": TypeScriptAdapter()}


def guess_language(target_path):
    target_path = Path(target_path)
    py = len(list(target_path.rglob("*.py")))
    ts = len(list(target_path.rglob("*.ts"))) + len(list(target_path.rglob("*.tsx")))
    return "python" if py >= ts else "typescript"


def detect(target_path, language=None):
    """The one function real pipeline code would call — same call shape,
    same output shape, regardless of language."""
    language = language or guess_language(target_path)
    return list(ADAPTERS[language].detect(target_path))


if __name__ == "__main__":
    for path in sys.argv[1:]:
        for candidate in detect(path):
            print(json.dumps(candidate))
