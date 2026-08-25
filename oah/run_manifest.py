"""run_manifest.json — one per run, validated against schemas/run_manifest.schema.json.

Fields beyond the base set trace back to spike decision records, not
invented here: cost to SP5, semconv_pin to SP6, environment to SP9 — see
the schema file's own description for the exact pointers.
"""
import json
from pathlib import Path

from oah import __version__ as TOOL_VERSION
from oah.schemas import validate

DEFAULT_MANIFEST_DIR = Path(".oah") / "runs"


def new_manifest(run_id, target_path, target_git_sha, started_at, primary_language=None,
                  model_roles=None, config_hash=None, environment=None):
    manifest = {
        "schema_version": "0.1.0",
        "run_id": run_id,
        "tool_version": TOOL_VERSION,
        "target": {
            "path": str(target_path),
            "git_sha": target_git_sha,
            **({"primary_language": primary_language} if primary_language else {}),
        },
        "started_at": started_at,
        "completed_at": None,
        "stages_completed": [],
    }
    if model_roles:
        manifest["model_roles"] = model_roles
    if config_hash:
        manifest["config_hash"] = config_hash
    if environment:
        manifest["environment"] = environment
    return validate("run_manifest", manifest)


def manifest_path(run_id):
    return Path.cwd() / DEFAULT_MANIFEST_DIR / f"{run_id}.json"


def save(manifest):
    validate("run_manifest", manifest)
    path = manifest_path(manifest["run_id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2) + "\n")
    return path


def load(run_id):
    path = manifest_path(run_id)
    return validate("run_manifest", json.loads(path.read_text()))


def mark_stage_completed(manifest, stage_id):
    if stage_id not in manifest["stages_completed"]:
        manifest["stages_completed"].append(stage_id)
    return manifest


def record_stage_cost(manifest, stage_id, estimated_usd=None, actual_usd=None,
                       input_tokens=None, output_tokens=None):
    manifest.setdefault("cost", {}).setdefault("per_stage", {})
    entry = manifest["cost"]["per_stage"].setdefault(stage_id, {})
    if estimated_usd is not None:
        entry["estimated_usd"] = estimated_usd
    if actual_usd is not None:
        entry["actual_usd"] = actual_usd
    if input_tokens is not None:
        entry["input_tokens"] = input_tokens
    if output_tokens is not None:
        entry["output_tokens"] = output_tokens
    return manifest
