"""`oah doctor` — environment sanity checks before a real run.

Per SP3's decision record (docs/decisions/007-sp3-dynamic-validation-feasibility.md):
runnability failures split into harness-environment brittleness (retriable,
not the target repo's fault) and target-repo reality (not retriable). This
command exists to surface the first category *before* a run starts, not
discover it mid-run the way SP3's own beacon test did.
"""
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""


def _check_python_version():
    major, minor = sys.version_info[:2]
    ok = (major, minor) >= (3, 10)
    return Check("python_version", ok, f"{major}.{minor} ({'>=3.10 required' if not ok else 'OK'})")


def _check_git():
    path = shutil.which("git")
    return Check("git", path is not None, path or "not found on PATH")


def _check_tree_sitter():
    try:
        import tree_sitter  # noqa: F401
        import tree_sitter_python  # noqa: F401
        return Check("tree_sitter", True, "tree-sitter + tree-sitter-python importable")
    except ImportError as e:
        return Check("tree_sitter", False, str(e))


def _check_jsonschema():
    try:
        import jsonschema  # noqa: F401
        return Check("jsonschema", True, "importable")
    except ImportError as e:
        return Check("jsonschema", False, str(e))


def _check_litellm():
    try:
        import litellm  # noqa: F401
        return Check("litellm", True, "importable")
    except ImportError as e:
        return Check("litellm", False, str(e))


def _check_llm_credentials():
    """Informational, not blocking — oah map --no-disambiguate, oah
    estimate, oah inventory, and oah gaps all work without it; only S1's
    LLM disambiguation pass needs it. Reported as ok=True either way so it
    never fails `oah doctor` on its own; the detail text is what matters."""
    from oah.discovery.disambiguate import missing_credentials
    reason = missing_credentials()
    if reason:
        return Check("llm_credentials", True,
                      f"optional, not configured (needed only for S1 LLM disambiguation): {reason}")
    return Check("llm_credentials", True, "configured — ANTHROPIC_API_KEY is set")


def _check_schemas_dir():
    from oah.schemas import SCHEMAS_DIR
    required = ["surface_map", "gap_model", "implementation_dto", "readiness_report", "run_manifest"]
    missing = [r for r in required if not (SCHEMAS_DIR / f"{r}.schema.json").is_file()]
    return Check("schemas_dir", not missing, "all present" if not missing else f"missing: {missing}")


def _check_target_repo(target_path):
    target_path = Path(target_path)
    if not target_path.is_dir():
        return Check("target_repo", False, f"{target_path} is not a directory")
    git_dir = target_path / ".git"
    if not git_dir.is_dir():
        return Check("target_repo", False, f"{target_path} has no .git — not a git repository")
    try:
        result = subprocess.run(
            ["git", "-C", str(target_path), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return Check("target_repo", False, f"git rev-parse failed: {result.stderr.strip()}")
        return Check("target_repo", True, f"HEAD={result.stdout.strip()[:12]}")
    except (subprocess.TimeoutExpired, OSError) as e:
        return Check("target_repo", False, str(e))


def run(target_path=None):
    checks = [
        _check_python_version(),
        _check_git(),
        _check_tree_sitter(),
        _check_jsonschema(),
        _check_litellm(),
        _check_llm_credentials(),
        _check_schemas_dir(),
    ]
    if target_path is not None:
        checks.append(_check_target_repo(target_path))
    return checks


def format_report(checks):
    lines = []
    all_ok = True
    for c in checks:
        mark = "OK" if c.ok else "FAIL"
        if not c.ok:
            all_ok = False
        lines.append(f"[{mark}] {c.name}: {c.detail}")
    lines.append("")
    lines.append("All checks passed." if all_ok else "One or more checks failed.")
    return "\n".join(lines), all_ok
