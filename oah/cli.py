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

import yaml

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
    """S1: deterministic pass, then real LLM disambiguation for whatever it
    couldn't resolve (oah.discovery.disambiguate — SP8's frontier-tier
    default, not a spike stand-in). Real run tracking: creates a run_id,
    writes run_manifest.json, and checkpoints both s1_scan and
    s1_disambiguate independently in the state DB — a crash between the two
    resumes from whichever finished, not from zero."""
    from oah.discovery.python_adapter import build_surface_map
    from oah.discovery.disambiguate import disambiguate, DisambiguationError, missing_credentials

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

        if db.is_checkpointed(run_id, "s1", "scan"):
            print(f"s1 scan already checkpointed for {run_id} — resuming from stored result.", file=sys.stderr)
            scan_result = db.get_checkpoint_result(run_id, "s1", "scan")
        else:
            surface_map, still_ambiguous = build_surface_map(args.target, git_sha=git_sha)
            scan_result = {"surface_map": surface_map, "still_ambiguous": still_ambiguous}
            db.checkpoint(run_id, "s1", "scan", scan_result, _now())

        still_ambiguous = scan_result["still_ambiguous"]
        disambiguated = None
        disambiguation_error = None

        if still_ambiguous and not args.no_disambiguate:
            if db.is_checkpointed(run_id, "s1", "disambiguate"):
                disambiguated = db.get_checkpoint_result(run_id, "s1", "disambiguate")
            else:
                reason = missing_credentials()
                if reason:
                    disambiguation_error = reason
                else:
                    try:
                        disambiguated = disambiguate(still_ambiguous)
                        db.checkpoint(run_id, "s1", "disambiguate", disambiguated, _now())
                    except DisambiguationError as e:
                        disambiguation_error = str(e)

        if disambiguated is not None:
            surface_map, still_ambiguous = build_surface_map(
                args.target, git_sha=git_sha, disambiguated=disambiguated
            )

        rm.mark_stage_completed(manifest, "s1")
        manifest["completed_at"] = _now()
        db.mark_run_status(run_id, "completed", manifest["completed_at"])

    rm.save(manifest)
    surface_map = scan_result["surface_map"] if disambiguated is None else surface_map

    if args.output:
        Path(args.output).write_text(json.dumps(surface_map, indent=2) + "\n")
        print(f"Wrote {args.output}")
    else:
        print(json.dumps(surface_map, indent=2))

    print(f"\nrun_id: {run_id}  (manifest: {rm.manifest_path(run_id)})", file=sys.stderr)

    if disambiguation_error:
        print(f"\nS1 disambiguation did not run: {disambiguation_error}", file=sys.stderr)
    if still_ambiguous:
        print(f"{len(still_ambiguous)} candidate(s) still need LLM disambiguation "
              f"— see the batch below.", file=sys.stderr)
        if args.output:
            ambiguous_path = Path(args.output).with_suffix(".ambiguous.json")
            ambiguous_path.write_text(
                json.dumps({"schema_version": "0.1.0", "candidates": still_ambiguous}, indent=2) + "\n"
            )
            print(f"Wrote {ambiguous_path}", file=sys.stderr)
    return 0


def cmd_inventory(args):
    """S2 deterministic pass: existing telemetry inventory."""
    from oah.discovery.telemetry_scanner import build_telemetry_inventory

    git_sha = _git_sha(args.target)
    if git_sha is None:
        print(f"error: {args.target} is not a git repository (or git is unavailable)", file=sys.stderr)
        return 1

    inventory = build_telemetry_inventory(args.target, git_sha=git_sha)

    if args.output:
        Path(args.output).write_text(json.dumps(inventory, indent=2) + "\n")
        print(f"Wrote {args.output}")
    else:
        print(json.dumps(inventory, indent=2))
    return 0


def cmd_gaps(args):
    """S3: join S1 x S2, classify coverage, and — if --context points at a
    context.yaml from `oah interview` — weight priority by the interviewed
    workflow criticality for any point whose workflow_hint matches."""
    from oah.discovery.python_adapter import build_surface_map
    from oah.discovery.telemetry_scanner import build_telemetry_inventory
    from oah.discovery.gap_model import build_gap_model

    git_sha = _git_sha(args.target)
    if git_sha is None:
        print(f"error: {args.target} is not a git repository (or git is unavailable)", file=sys.stderr)
        return 1

    context = None
    if args.context:
        context_data = yaml.safe_load(Path(args.context).read_text())
        from oah.schemas import validate
        validate("context", context_data)
        context = context_data

    surface_map, still_ambiguous = build_surface_map(args.target, git_sha=git_sha)
    inventory = build_telemetry_inventory(args.target, git_sha=git_sha)
    gaps = build_gap_model(surface_map, inventory, context=context)

    if args.output:
        Path(args.output).write_text(json.dumps(gaps, indent=2) + "\n")
        print(f"Wrote {args.output}")
    else:
        print(json.dumps(gaps, indent=2))

    if still_ambiguous:
        print(f"\nnote: {len(still_ambiguous)} S1 candidate(s) still need LLM disambiguation "
              f"and are excluded from this gap model — resolve them first for a complete picture.",
              file=sys.stderr)
    if context is None:
        print("\nnote: no --context given — priority reflects coverage status only, not business "
              "impact. Run `oah interview` and pass its output with --context to weight by "
              "workflow criticality.", file=sys.stderr)
    return 0


def cmd_interview(args):
    """S3's owner interview — real stdin prompts, not stub data. See
    oah/interview.py's module docstring for why this is genuinely
    interactive rather than something an LLM or scanner answers."""
    from oah.interview import run_interview

    git_sha = _git_sha(args.target)
    if git_sha is None:
        print(f"error: {args.target} is not a git repository (or git is unavailable)", file=sys.stderr)
        return 1

    context = run_interview(git_sha)
    yaml_text = yaml.safe_dump(context, sort_keys=False, allow_unicode=True)

    # Never auto-written into the target repo (same convention as every
    # other command here) -- context.yaml is OAH's own artifact, not the
    # target's; only `oah instrument --mode fix` (E5, not this stage) has
    # any business writing into a scanned repo's working tree.
    if args.output:
        Path(args.output).write_text(yaml_text)
        print(f"\nWrote {args.output}")
    else:
        print(f"\n{yaml_text}", end="")
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
    p_map.add_argument("--no-disambiguate", action="store_true",
                        help="Skip the LLM disambiguation pass; leave ambiguous candidates unresolved")
    p_map.set_defaults(func=cmd_map)

    p_inventory = sub.add_parser("inventory", help="S2 existing telemetry inventory")
    p_inventory.add_argument("target", help="Path to the target repository")
    p_inventory.add_argument("-o", "--output", default=None, help="Write telemetry_inventory.json here instead of stdout")
    p_inventory.set_defaults(func=cmd_inventory)

    p_gaps = sub.add_parser("gaps", help="S3: join S1 x S2, classify coverage, weight priority by --context")
    p_gaps.add_argument("target", help="Path to the target repository")
    p_gaps.add_argument("-o", "--output", default=None, help="Write gap_model.json here instead of stdout")
    p_gaps.add_argument("--context", default=None,
                         help="Path to a context.yaml from `oah interview` — weights priority by workflow criticality")
    p_gaps.set_defaults(func=cmd_gaps)

    p_interview = sub.add_parser("interview", help="S3 owner interview (interactive) -> context.yaml")
    p_interview.add_argument("target", help="Path to the target repository")
    p_interview.add_argument("-o", "--output", default=None,
                              help="Write context.yaml here instead of stdout (never auto-written into the target repo)")
    p_interview.set_defaults(func=cmd_interview)

    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
