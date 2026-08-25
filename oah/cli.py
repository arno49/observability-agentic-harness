"""oah CLI entry point. Real commands only — no stubs pretending to be
implemented; a command not built yet isn't registered rather than
registered-and-broken."""
import argparse
import json
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from oah.doctor import run as run_doctor, format_report
from oah.estimate import estimate as run_estimate
from oah.state_db import open_state_db
from oah import run_manifest as rm


def _now():
    return datetime.now(timezone.utc).isoformat()


def _git_sha(path):
    try:
        result = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=10,
        )
        return result.stdout.strip() if result.returncode == 0 else None
    except (subprocess.TimeoutExpired, OSError):
        return None


def cmd_doctor(args):
    checks = run_doctor(args.target)
    report, all_ok = format_report(checks)
    print(report)
    return 0 if all_ok else 1


def cmd_estimate(args):
    result = run_estimate(args.target, workflows=args.workflows)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        dc = result["driver_counts"]
        print(f"Target: {args.target}")
        print(f"Candidate call sites: {dc['candidate_call_sites']} "
              f"({dc['ambiguous_candidates']} need LLM disambiguation)")
        print(f"Estimated DTOs: {dc['estimated_dtos']}  "
              f"Workflows: {dc['workflows']}{' (assumed)' if dc['workflows_assumed'] else ''}")
        print()
        for stage, cost in result["per_stage_usd"].items():
            if cost > 0:
                print(f"  {stage}: ${cost:.4f}")
        lo, hi = result["range_usd_at_40pct"]
        print()
        print(f"Total: ${result['total_usd']:.2f}  (range at ±40%: ${lo:.2f}-${hi:.2f})")
        print(f"\n{result['calibration_note']}")
    return 0


def cmd_map(args):
    """S1 deterministic pass only — no LLM disambiguation wired yet
    (tracked separately; this command doesn't pretend that stage exists).
    Real run tracking: creates a run_id, writes run_manifest.json, and
    checkpoints S1 as completed in the state DB — the actual E1/E2
    integration point, not just two commands that happen to coexist."""
    from oah.discovery.python_adapter import build_surface_map

    git_sha = _git_sha(args.target)
    if git_sha is None:
        print(f"error: {args.target} is not a git repository (or git is unavailable)", file=sys.stderr)
        return 1

    run_id = args.run_id or f"run-{uuid.uuid4().hex[:12]}"

    # Resuming an existing run_id must pick up its own manifest, not start a
    # fresh one — otherwise resume would silently discard started_at and
    # any stages_completed recorded by a prior (possibly crashed) attempt.
    if rm.manifest_path(run_id).is_file():
        manifest = rm.load(run_id)
    else:
        manifest = rm.new_manifest(run_id, args.target, git_sha, _now(), primary_language="python")
        rm.save(manifest)  # persisted immediately, before any work — a crash after this still resumes correctly

    with open_state_db(args.target) as db:
        db.create_run(run_id, args.target, git_sha, manifest["started_at"])
        if db.is_checkpointed(run_id, "s1", "full_scan"):
            print(f"s1 already checkpointed for {run_id} — resuming from stored result.", file=sys.stderr)
            surface_map = db.get_checkpoint_result(run_id, "s1", "full_scan")
            still_ambiguous = []
        else:
            surface_map, still_ambiguous = build_surface_map(args.target, git_sha=git_sha)
            db.checkpoint(run_id, "s1", "full_scan", surface_map, _now())
        rm.mark_stage_completed(manifest, "s1")
        manifest["completed_at"] = _now()
        db.mark_run_status(run_id, "completed", manifest["completed_at"])

    rm.save(manifest)

    if args.output:
        Path(args.output).write_text(json.dumps(surface_map, indent=2) + "\n")
        print(f"Wrote {args.output}")
    else:
        print(json.dumps(surface_map, indent=2))

    print(f"\nrun_id: {run_id}  (manifest: {rm.manifest_path(run_id)})", file=sys.stderr)

    if still_ambiguous:
        print(f"{len(still_ambiguous)} candidate(s) need LLM disambiguation "
              f"(not yet wired into this command) — see the batch below.", file=sys.stderr)
        if args.output:
            ambiguous_path = Path(args.output).with_suffix(".ambiguous.json")
            ambiguous_path.write_text(
                json.dumps({"schema_version": "0.1.0", "candidates": still_ambiguous}, indent=2) + "\n"
            )
            print(f"Wrote {ambiguous_path}", file=sys.stderr)
    return 0


def build_parser():
    parser = argparse.ArgumentParser(prog="oah", description="Observability Agentic Harness")
    sub = parser.add_subparsers(dest="command", required=True)

    p_doctor = sub.add_parser("doctor", help="Check the harness's own environment is ready to run")
    p_doctor.add_argument("target", nargs="?", default=None, help="Optional target repo to also check")
    p_doctor.set_defaults(func=cmd_doctor)

    p_estimate = sub.add_parser("estimate", help="Predict run cost before spending (SP5's formula)")
    p_estimate.add_argument("target", help="Path to the target repository")
    p_estimate.add_argument("--workflows", type=int, default=None,
                              help="Known workflow count, if you have it (default: assumed)")
    p_estimate.add_argument("--json", action="store_true", help="Machine-readable output")
    p_estimate.set_defaults(func=cmd_estimate)

    p_map = sub.add_parser("map", help="S1 deterministic surface mapping (no LLM disambiguation yet)")
    p_map.add_argument("target", help="Path to the target repository")
    p_map.add_argument("-o", "--output", default=None, help="Write surface_map.json here instead of stdout")
    p_map.add_argument("--run-id", default=None, help="Resume this run_id if already checkpointed, else start it")
    p_map.set_defaults(func=cmd_map)

    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
