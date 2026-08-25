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


def cmd_design(args):
    """S4 (partial: generation-capture only, one of nine listed lenses) +
    S5's deterministic gates + S6 (partial: cost-skeptic persona only, one
    of three). Not `oah design`'s full scope per architecture.md -- runs
    what exists and says so explicitly, rather than silently producing an
    incomplete design as if it were complete. architecture.md: 'Design
    iterates S4->S6 until pass' -- S6 runs on whatever fragment S4 produced
    regardless of S5's own verdict, since both are real signal for that
    iteration, not a strict pipeline where S6 only runs after S5 is clean."""
    from oah.discovery.python_adapter import build_surface_map
    from oah.design.lens import design_generation_capture, LensDesignError
    from oah.design.gates import run_gates, gates_passed
    from oah.design.panel import run_cost_skeptic, PanelReviewError
    from oah.schemas import validate

    git_sha = _git_sha(args.target)
    if git_sha is None:
        print(f"error: {args.target} is not a git repository (or git is unavailable)", file=sys.stderr)
        return 1

    context = None
    if args.context:
        context_data = yaml.safe_load(Path(args.context).read_text())
        validate("context", context_data)
        context = context_data

    surface_map, still_ambiguous = build_surface_map(args.target, git_sha=git_sha)
    if not surface_map["points"]:
        print("No surface points found (or all still ambiguous) — nothing to design for.", file=sys.stderr)
        return 0

    try:
        fragment = design_generation_capture(surface_map["points"], git_sha, context=context)
    except LensDesignError as e:
        print(f"error: generation-capture lens design failed: {e}", file=sys.stderr)
        return 1

    if fragment is None:
        print("No llm_generation points to design for.", file=sys.stderr)
        return 0

    point_ids = [p["id"] for p in surface_map["points"] if p["kind"] == "llm_generation"]
    findings = run_gates(fragment, surface_map_point_ids=point_ids)
    s5_passed = gates_passed(findings)

    panel_error = None
    verdict = None
    try:
        verdict = run_cost_skeptic([fragment], git_sha, context=context)
    except PanelReviewError as e:
        panel_error = str(e)

    s6_passed = verdict is None or verdict["overall"] != "fail"

    output = {
        "design_fragment": fragment,
        "gate_findings": [f.__dict__ for f in findings],
        "gates_passed": s5_passed,
        "panel_verdicts": [verdict] if verdict else [],
    }
    if args.output:
        Path(args.output).write_text(json.dumps(output, indent=2) + "\n")
        print(f"Wrote {args.output}")
    else:
        print(json.dumps(output, indent=2))

    for f in findings:
        if not f.passed:
            marker = "ERROR" if f.severity == "error" else "WARN"
            print(f"[{marker}] S5 {f.gate}: {f.reason}", file=sys.stderr)
    print(f"S5 gates: {'PASSED' if s5_passed else 'FAILED'}", file=sys.stderr)

    if panel_error:
        print(f"S6 cost-skeptic panel did not run: {panel_error}", file=sys.stderr)
    elif verdict is not None:
        for f in verdict["findings"]:
            marker = "ERROR" if f["severity"] == "error" else "WARN"
            print(f"[{marker}] S6 cost_skeptic {f['gate']}: {f['summary']}", file=sys.stderr)
        print(f"S6 cost_skeptic: {verdict['overall'].upper()}", file=sys.stderr)

    print("\nnote: only the generation-capture lens (of nine) and the cost_skeptic persona "
          "(of three) are built — this is a partial design/review, not the full S4/S6 output.",
          file=sys.stderr)
    return 0 if (s5_passed and s6_passed) else 1


def cmd_event_schema(args):
    """S7 (partial): event_schema.json only, deterministic merge of
    whatever S4 design fragments exist -- architecture.md's other S7
    outputs (architecture.md prose, rollout_plan.md, runbook.md) need an
    LLM and aren't built yet. Currently runs generation-capture only,
    matching S4's own current scope."""
    from oah.discovery.python_adapter import build_surface_map
    from oah.design.lens import design_generation_capture, LensDesignError
    from oah.design.event_schema import build_event_schema, EventSchemaConflictError

    git_sha = _git_sha(args.target)
    if git_sha is None:
        print(f"error: {args.target} is not a git repository (or git is unavailable)", file=sys.stderr)
        return 1

    surface_map, still_ambiguous = build_surface_map(args.target, git_sha=git_sha)
    if not surface_map["points"]:
        print("No surface points found — nothing to build an event schema from.", file=sys.stderr)
        return 0

    try:
        fragment = design_generation_capture(surface_map["points"], git_sha)
    except LensDesignError as e:
        print(f"error: generation-capture lens design failed: {e}", file=sys.stderr)
        return 1

    fragments = [fragment] if fragment else []
    if not fragments:
        print("No llm_generation points to build an event schema from.", file=sys.stderr)
        return 0

    try:
        schema = build_event_schema(fragments, git_sha)
    except EventSchemaConflictError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    if args.output:
        Path(args.output).write_text(json.dumps(schema, indent=2) + "\n")
        print(f"Wrote {args.output}")
    else:
        print(json.dumps(schema, indent=2))

    print(f"\nnote: only generation-capture's attributes are included (1 of 9 S4 lenses built) — "
          f"this is a partial event schema.", file=sys.stderr)
    return 0


def cmd_dtos(args):
    """S8 (partial): implementation_dto.json generation from whatever
    event_schema.json + gap_model.json exist so far. Requires a real model
    call (anchor/precondition/change-type judgment) but rollout_step is
    assigned deterministically by gap priority, not by the model -- a
    stand-in for real rollout_plan.md ordering, which isn't built yet."""
    from oah.discovery.python_adapter import build_surface_map
    from oah.discovery.telemetry_scanner import build_telemetry_inventory
    from oah.discovery.gap_model import build_gap_model
    from oah.design.lens import design_generation_capture, LensDesignError
    from oah.design.event_schema import build_event_schema, EventSchemaConflictError
    from oah.design.dto_generator import generate_dtos, DtoGenerationError

    git_sha = _git_sha(args.target)
    if git_sha is None:
        print(f"error: {args.target} is not a git repository (or git is unavailable)", file=sys.stderr)
        return 1

    surface_map, still_ambiguous = build_surface_map(args.target, git_sha=git_sha)
    if not surface_map["points"]:
        print("No surface points found — nothing to generate DTOs for.", file=sys.stderr)
        return 0

    try:
        fragment = design_generation_capture(surface_map["points"], git_sha)
    except LensDesignError as e:
        print(f"error: generation-capture lens design failed: {e}", file=sys.stderr)
        return 1
    if fragment is None:
        print("No llm_generation points to generate DTOs for.", file=sys.stderr)
        return 0

    try:
        event_schema = build_event_schema([fragment], git_sha)
    except EventSchemaConflictError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    inventory = build_telemetry_inventory(args.target, git_sha=git_sha)
    gap_model = build_gap_model(surface_map, inventory)

    covered_point_ids = {pid for a in event_schema["attributes"] for pid in a["surface_point_ids"]}
    points = [p for p in surface_map["points"] if p["id"] in covered_point_ids]
    relevant_gap_ids = {g["id"] for g in gap_model["gaps"]
                         if any(pid in covered_point_ids for pid in g["surface_point_ids"])}
    gaps = [g for g in gap_model["gaps"] if g["id"] in relevant_gap_ids]

    try:
        dtos = generate_dtos(event_schema, points, gaps, git_sha)
    except DtoGenerationError as e:
        print(f"error: DTO generation failed: {e}", file=sys.stderr)
        return 1

    if dtos is None:
        print("No DTOs to generate.", file=sys.stderr)
        return 0

    if args.output:
        Path(args.output).write_text(json.dumps(dtos, indent=2) + "\n")
        print(f"Wrote {args.output}")
    else:
        print(json.dumps(dtos, indent=2))

    print(f"\nnote: rollout_step is ordered by gap priority only (p0 first) — a stand-in for "
          f"real rollout_plan.md workflow-criticality ordering, not built yet. Only "
          f"generation-capture's attributes are covered (1 of 9 S4 lenses).", file=sys.stderr)
    return 0


def cmd_readiness(args):
    """S9: production readiness report, deterministic assembly (no model
    call -- architecture.md marks S9 explicitly '(deterministic assembly)',
    unlike every other stage in this chain). Runs the full S1-S8 chain
    built so far and assembles what's mechanically derivable; everything
    else is stated as genuinely unknown, not fabricated."""
    from oah.discovery.python_adapter import build_surface_map
    from oah.discovery.telemetry_scanner import build_telemetry_inventory
    from oah.discovery.gap_model import build_gap_model
    from oah.design.lens import design_generation_capture, LensDesignError
    from oah.design.gates import run_gates
    from oah.design.panel import run_cost_skeptic, PanelReviewError
    from oah.design.event_schema import build_event_schema, EventSchemaConflictError
    from oah.design.dto_generator import generate_dtos, DtoGenerationError
    from oah.design.readiness_report import build_readiness_report
    from oah.schemas import validate

    git_sha = _git_sha(args.target)
    if git_sha is None:
        print(f"error: {args.target} is not a git repository (or git is unavailable)", file=sys.stderr)
        return 1

    context = None
    if args.context:
        context_data = yaml.safe_load(Path(args.context).read_text())
        validate("context", context_data)
        context = context_data

    surface_map, still_ambiguous = build_surface_map(args.target, git_sha=git_sha)
    inventory = build_telemetry_inventory(args.target, git_sha=git_sha)
    gap_model = build_gap_model(surface_map, inventory, context=context)

    gate_findings = []
    panel_verdicts = []
    event_schema = {"schema_version": "0.1.0", "repo_git_sha": git_sha, "attributes": [],
                     "summary": {"attribute_count": 0, "otel_genai_count": 0, "oah_extension_count": 0, "lenses_included": []}}
    dtos = {"schema_version": "0.1.0", "dtos": []}

    if surface_map["points"]:
        try:
            fragment = design_generation_capture(surface_map["points"], git_sha, context=context)
        except LensDesignError as e:
            print(f"warning: generation-capture lens design failed, continuing with no design fragment: {e}",
                  file=sys.stderr)
            fragment = None

        if fragment:
            point_ids = [p["id"] for p in surface_map["points"] if p["kind"] == "llm_generation"]
            gate_findings = [f.__dict__ for f in run_gates(fragment, surface_map_point_ids=point_ids)]

            try:
                verdict = run_cost_skeptic([fragment], git_sha, context=context)
                if verdict:
                    panel_verdicts = [verdict]
            except PanelReviewError as e:
                print(f"warning: S6 cost-skeptic panel did not run: {e}", file=sys.stderr)

            try:
                event_schema = build_event_schema([fragment], git_sha)
            except EventSchemaConflictError as e:
                print(f"warning: event schema build failed: {e}", file=sys.stderr)

            covered_point_ids = {pid for a in event_schema["attributes"] for pid in a["surface_point_ids"]}
            points = [p for p in surface_map["points"] if p["id"] in covered_point_ids]
            relevant_gap_ids = {g["id"] for g in gap_model["gaps"]
                                 if any(pid in covered_point_ids for pid in g["surface_point_ids"])}
            gaps_for_dtos = [g for g in gap_model["gaps"] if g["id"] in relevant_gap_ids]
            if points:
                try:
                    generated = generate_dtos(event_schema, points, gaps_for_dtos, git_sha)
                    if generated:
                        dtos = generated
                except DtoGenerationError as e:
                    print(f"warning: S8 DTO generation did not run: {e}", file=sys.stderr)

    report = build_readiness_report(
        gap_model, gate_findings, panel_verdicts, event_schema, dtos,
        context=context, repo_git_sha=git_sha,
    )
    validate("readiness_report", report)

    if args.output:
        Path(args.output).write_text(json.dumps(report, indent=2) + "\n")
        print(f"Wrote {args.output}")
    else:
        print(json.dumps(report, indent=2))

    print(f"\nrecommendation: {report['recommendation']['decision']}", file=sys.stderr)
    print(f"rationale: {report['recommendation']['rationale']}", file=sys.stderr)
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

    p_design = sub.add_parser("design", help="S4 (generation-capture only so far) + S5 gates")
    p_design.add_argument("target", help="Path to the target repository")
    p_design.add_argument("-o", "--output", default=None, help="Write the design fragment + gate findings here instead of stdout")
    p_design.add_argument("--context", default=None, help="Path to a context.yaml from `oah interview`")
    p_design.set_defaults(func=cmd_design)

    p_event_schema = sub.add_parser("event-schema", help="S7 (partial): deterministic event_schema.json merge")
    p_event_schema.add_argument("target", help="Path to the target repository")
    p_event_schema.add_argument("-o", "--output", default=None, help="Write event_schema.json here instead of stdout")
    p_event_schema.set_defaults(func=cmd_event_schema)

    p_dtos = sub.add_parser("dtos", help="S8 (partial): implementation_dto.json generation")
    p_dtos.add_argument("target", help="Path to the target repository")
    p_dtos.add_argument("-o", "--output", default=None, help="Write implementation_dto.json here instead of stdout")
    p_dtos.set_defaults(func=cmd_dtos)

    p_readiness = sub.add_parser("readiness", help="S9: production readiness report (deterministic assembly)")
    p_readiness.add_argument("target", help="Path to the target repository")
    p_readiness.add_argument("--context", default=None, help="Path to a context.yaml from `oah interview`")
    p_readiness.add_argument("-o", "--output", default=None, help="Write readiness_report.json here instead of stdout")
    p_readiness.set_defaults(func=cmd_readiness)

    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
