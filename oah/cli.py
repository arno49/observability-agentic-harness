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


class ContextLoadError(Exception):
    """A caller must catch this and print+return 1, the same clean
    'error: ...' treatment every other input-validation failure in this
    CLI already gets. Found by adversarial review: 5 of the 6 --context-
    accepting commands read and validated the file with no error handling
    at all, so a missing file or malformed YAML (an everyday mistake --
    hand-editing oah interview's own output.yaml is a real workflow, not
    an adversarial input) produced a raw traceback instead."""


def _load_context(path):
    from oah.schemas import validate, SchemaValidationError
    try:
        text = Path(path).read_text()
    except OSError as e:
        raise ContextLoadError(f"could not read --context file {path!r}: {e}") from e
    try:
        context_data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise ContextLoadError(f"--context file {path!r} is not valid YAML: {e}") from e
    try:
        validate("context", context_data)
    except SchemaValidationError as e:
        raise ContextLoadError(f"--context file {path!r} does not match context.schema.json: {e}") from e
    return context_data


# Which surface_map.json point `kind` each built S4 lens targets. S5's
_MODEL_HELP = (
    "LiteLLM model string to use instead of the default (claude-sonnet-5). "
    "Examples: openai/gpt-4o (needs OPENAI_API_KEY), ollama/llama3 (local, needs "
    "OLLAMA_API_BASE if not on the default port), vertex_ai/gemini-... -- see "
    "https://docs.litellm.ai/docs/providers for the full model-string catalog and "
    "each provider's own credential/endpoint env vars. Only the default model's "
    "ANTHROPIC_API_KEY is pre-checked; any other model's own auth error surfaces "
    "from the live call itself."
)

# Deliberately NOT _MODEL_HELP: S10 goes through the Claude Agent SDK, not
# LiteLLM (architecture.md: Anthropic-pinned, a non-Anthropic role is refused
# rather than degraded) -- a LiteLLM-provider model string like openai/gpt-4o
# doesn't apply here, so this needs its own accurate wording.
_AGENT_MODEL_HELP = (
    "Claude Agent SDK model name/alias to use instead of the default "
    "(claude-sonnet-5), e.g. a specific dated model ID. Anthropic-only -- "
    "S10 is pinned to the Claude Agent SDK (architecture.md), unlike every "
    "LiteLLM-routed stage's --model."
)

# check_every_surface_point_has_decision gate needs, per fragment, the
# full set of points that fragment is expected to cover -- that set
# differs by lens now that retrieval is a second target kind alongside
# llm_generation, so it must be looked up per fragment via its own
# "lens" field, not assumed to be a single hardcoded kind across all of
# them (a bug the first version of this mapping's absence would have
# produced silently: every retrieval fragment checked against
# llm_generation point IDs it was never designed to cover).
# "tracing" maps to None, not a kind string -- architecture.md is explicit
# it's cross-cutting, not scoped to one surface_map kind the way every
# other lens is (see design_tracing()'s own docstring in
# oah/design/lens.py). _point_ids_for_fragment treats None as "every
# point in the surface_map, regardless of kind."
LENS_TO_POINT_KIND = {
    "generation-capture": "llm_generation",
    "pii-governance": "llm_generation",
    "cost": "llm_generation",
    "ops": "llm_generation",
    "retrieval": "retrieval",
    "feedback": "feedback_ingest",
    "realtime-multimodal": "realtime_session",
    "tracing": None,
    "tools": "tool_call",
}


def _point_ids_for_fragment(fragment, surface_map):
    kind = LENS_TO_POINT_KIND[fragment["lens"]]
    if kind is None:
        return [p["id"] for p in surface_map["points"]]
    return [p["id"] for p in surface_map["points"] if p["kind"] == kind]


_ALL_PERSONA_NAMES = frozenset({"cost_skeptic", "sre", "security"})


def _design_all_lenses(points, git_sha, lens_fns, LensDesignError, context=None, model=None):
    """Runs every S4 lens against `points`, warning (not failing) on any
    lens that raises. `lens_fns` must be a {lens_name: design_fn} dict
    covering exactly LENS_TO_POINT_KIND's keys -- the assert below turns a
    missing/extra entry into an immediate, loud crash instead of a silent
    gap. This exists because the equivalent 4-way copy-pasted inline loop
    (one per command) had a lens silently missing from cmd_readiness's own
    copy three separate times this session -- each time caught only by a
    manual grep audit after the fact, never by a test. One shared
    implementation, called identically from every command, makes that
    whole bug class structurally impossible instead of merely
    well-intentioned."""
    assert set(lens_fns) == set(LENS_TO_POINT_KIND), (
        f"lens_fns must cover exactly LENS_TO_POINT_KIND's lenses -- got {sorted(lens_fns)}, "
        f"expected {sorted(LENS_TO_POINT_KIND)}"
    )
    fragments = []
    for lens_name, design_fn in lens_fns.items():
        try:
            fragment = design_fn(points, git_sha, context=context, model=model)
        except LensDesignError as e:
            print(f"warning: {lens_name} lens design failed, continuing without it: {e}", file=sys.stderr)
            continue
        if fragment:
            fragments.append(fragment)
    return fragments


def _run_all_personas(fragments, git_sha, persona_fns, PanelReviewError, context=None, model=None):
    """Same structural fix as _design_all_lenses, for S6's three personas."""
    assert set(persona_fns) == set(_ALL_PERSONA_NAMES), (
        f"persona_fns must cover exactly {sorted(_ALL_PERSONA_NAMES)} -- got {sorted(persona_fns)}"
    )
    verdicts = []
    for persona_name, run_fn in persona_fns.items():
        try:
            verdict = run_fn(fragments, git_sha, context=context, model=model)
        except PanelReviewError as e:
            print(f"warning: S6 {persona_name} panel did not run: {e}", file=sys.stderr)
            continue
        if verdict:
            verdicts.append(verdict)
    return verdicts


def cmd_doctor(args):
    checks = run_doctor(args.target)
    report, all_ok = format_report(checks)
    print(report)
    return 0 if all_ok else 1


def cmd_estimate(args):
    # Found by adversarial review: every sibling command validates the
    # target is a real git repo before doing anything; estimate() didn't,
    # so a typo'd/nonexistent path silently produced a confident-looking
    # dollar estimate (detect_repo()'s rglob() over a nonexistent path
    # just returns zero candidates, and the fixed-overhead pipeline
    # stages still cost something) instead of an error like every other
    # command gives for the same mistake.
    if _git_sha(args.target) is None:
        print(f"error: {args.target} is not a git repository (or git is unavailable)", file=sys.stderr)
        return 1

    if args.workflows is not None and args.workflows < 0:
        print(f"error: --workflows must be >= 0, got {args.workflows}", file=sys.stderr)
        return 1

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
                model = getattr(args, "model", None)
                reason = missing_credentials(model)
                if reason:
                    disambiguation_error = reason
                else:
                    try:
                        disambiguated = disambiguate(still_ambiguous, model=model)
                        db.checkpoint(run_id, "s1", "disambiguate", disambiguated, _now())
                    except DisambiguationError as e:
                        disambiguation_error = str(e)

        if disambiguated is not None:
            surface_map, still_ambiguous = build_surface_map(
                args.target, git_sha=git_sha, disambiguated=disambiguated
            )

        # Found by adversarial review: this used to mark s1 "completed" in
        # both the run manifest and the state DB unconditionally, even when
        # disambiguation never ran (missing credentials, a raised
        # DisambiguationError) or candidates are still unresolved --
        # run_manifest.json is documented as a provenance/audit record, and
        # an audit record that claims a stage finished when it didn't is
        # exactly the "confirmed"-overclaiming pattern already found and
        # fixed elsewhere in readiness_report.py this session.
        s1_fully_resolved = not disambiguation_error and not still_ambiguous
        if s1_fully_resolved:
            rm.mark_stage_completed(manifest, "s1")
            manifest["completed_at"] = _now()
            db.mark_run_status(run_id, "completed", manifest["completed_at"])
        else:
            db.mark_run_status(run_id, "incomplete")

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
        try:
            context = _load_context(args.context)
        except ContextLoadError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1

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
    """S4 (all nine listed lenses now built: generation-capture, pii-governance,
    cost, ops, retrieval, feedback, realtime-multimodal, tracing, tools) + S5's
    deterministic gates + S6 (all
    three personas: cost_skeptic, sre, security). Not `oah design`'s full
    scope per architecture.md -- runs what exists and says so explicitly,
    rather than silently producing an incomplete design as if it were
    complete. A lens that fails to produce a fragment (e.g. missing
    credentials) is a warning, not fatal -- the command proceeds with
    whichever lenses did produce one, matching `oah readiness`'s existing
    graceful-degradation posture. architecture.md: 'Design iterates
    S4->S6 until pass' -- S6 runs on whatever fragments S4 produced
    regardless of S5's own verdict, since both are real signal for that
    iteration, not a strict pipeline where S6 only runs after S5 is
    clean."""
    from oah.discovery.python_adapter import build_surface_map
    from oah.design.lens import (
        design_generation_capture, design_pii_governance, design_cost, design_ops,
        design_retrieval, design_feedback, design_realtime_multimodal, design_tracing,
        design_tools, LensDesignError,
    )
    from oah.design.gates import run_gates, gates_passed
    from oah.design.panel import run_cost_skeptic, run_sre, run_security, PanelReviewError
    from oah.schemas import validate

    git_sha = _git_sha(args.target)
    if git_sha is None:
        print(f"error: {args.target} is not a git repository (or git is unavailable)", file=sys.stderr)
        return 1

    context = None
    if args.context:
        try:
            context = _load_context(args.context)
        except ContextLoadError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1

    surface_map, still_ambiguous = build_surface_map(args.target, git_sha=git_sha)
    if not surface_map["points"]:
        print("No surface points found (or all still ambiguous) — nothing to design for.", file=sys.stderr)
        return 0

    lens_fns = {
        "generation-capture": design_generation_capture,
        "pii-governance": design_pii_governance,
        "cost": design_cost,
        "ops": design_ops,
        "retrieval": design_retrieval,
        "feedback": design_feedback,
        "realtime-multimodal": design_realtime_multimodal,
        "tracing": design_tracing,
        "tools": design_tools,
    }
    model = getattr(args, "model", None)
    fragments = _design_all_lenses(surface_map["points"], git_sha, lens_fns, LensDesignError,
                                    context=context, model=model)

    if not fragments:
        print("No points of a kind any built lens covers to design for.", file=sys.stderr)
        return 0

    findings = []
    for fragment in fragments:
        findings.extend(run_gates(fragment, surface_map_point_ids=_point_ids_for_fragment(fragment, surface_map)))
    s5_passed = gates_passed(findings)

    persona_fns = {"cost_skeptic": run_cost_skeptic, "sre": run_sre, "security": run_security}
    verdicts = _run_all_personas(fragments, git_sha, persona_fns, PanelReviewError, context=context, model=model)

    s6_passed = all(v["overall"] != "fail" for v in verdicts)

    output = {
        "design_fragments": fragments,
        "gate_findings": [f.__dict__ for f in findings],
        "gates_passed": s5_passed,
        "panel_verdicts": verdicts,
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

    for verdict in verdicts:
        for f in verdict["findings"]:
            marker = "ERROR" if f["severity"] == "error" else "WARN"
            print(f"[{marker}] S6 {verdict['persona']} {f['gate']}: {f['summary']}", file=sys.stderr)
        print(f"S6 {verdict['persona']}: {verdict['overall'].upper()}", file=sys.stderr)

    print("\nnote: all nine S4 lenses and all three S6 personas (cost_skeptic, sre, "
          "security) are built and run — this is the full S4/S6 roster, though several "
          "individual lenses (tracing, tools, pii-governance among them) are still "
          "narrower than architecture.md's full per-lens ask; see each skill's own SKILL.md "
          "for its stated scope boundary. S1's own detection is still partial: only 5 of the "
          "surface_map kind vocabulary's kinds are detected (llm_generation, retrieval, "
          "feedback_ingest, realtime_session, tool_call).",
          file=sys.stderr)
    return 0 if (s5_passed and s6_passed) else 1


def cmd_event_schema(args):
    """S7 (partial): event_schema.json only, deterministic merge of
    whatever S4 design fragments exist -- architecture.md's other S7
    outputs (architecture.md prose, rollout_plan.md, runbook.md) need an
    LLM and aren't built yet. Runs all nine S4 lenses. A lens that fails
    to produce a fragment (e.g. missing credentials) is a warning, not
    fatal -- the schema is built from
    whichever lenses did produce one."""
    from oah.discovery.python_adapter import build_surface_map
    from oah.design.lens import (
        design_generation_capture, design_pii_governance, design_cost, design_ops,
        design_retrieval, design_feedback, design_realtime_multimodal, design_tracing,
        design_tools, LensDesignError,
    )
    from oah.design.event_schema import build_event_schema, EventSchemaConflictError
    from oah.schemas import validate

    git_sha = _git_sha(args.target)
    if git_sha is None:
        print(f"error: {args.target} is not a git repository (or git is unavailable)", file=sys.stderr)
        return 1

    context = None
    if args.context:
        try:
            context = _load_context(args.context)
        except ContextLoadError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1

    surface_map, still_ambiguous = build_surface_map(args.target, git_sha=git_sha)
    if not surface_map["points"]:
        print("No surface points found — nothing to build an event schema from.", file=sys.stderr)
        return 0

    lens_fns = {
        "generation-capture": design_generation_capture,
        "pii-governance": design_pii_governance,
        "cost": design_cost,
        "ops": design_ops,
        "retrieval": design_retrieval,
        "feedback": design_feedback,
        "realtime-multimodal": design_realtime_multimodal,
        "tracing": design_tracing,
        "tools": design_tools,
    }
    model = getattr(args, "model", None)
    fragments = _design_all_lenses(surface_map["points"], git_sha, lens_fns, LensDesignError,
                                    context=context, model=model)

    if not fragments:
        print("No points of a kind any built lens covers to build an event schema from.", file=sys.stderr)
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

    print(f"\nnote: all nine S4 lenses' attributes are included, but S7's other outputs "
          f"(architecture.md prose, rollout_plan.md, runbook.md) aren't built -- this is "
          f"event_schema.json only, not the full S7 output.", file=sys.stderr)
    return 0


def cmd_dtos(args):
    """S8 (partial): implementation_dto.json generation from whatever
    event_schema.json + gap_model.json exist so far. Requires a real model
    call (anchor/precondition/change-type judgment) but rollout_step is
    assigned deterministically, by architecture.md S7's real ordering rule
    (workflow criticality from --context, then dimension tiering, then gap
    priority) when --context is given, falling back to gap-priority-only
    ordering otherwise -- never by the model."""
    from oah.discovery.python_adapter import build_surface_map
    from oah.discovery.telemetry_scanner import build_telemetry_inventory
    from oah.discovery.gap_model import build_gap_model
    from oah.design.lens import (
        design_generation_capture, design_pii_governance, design_cost, design_ops,
        design_retrieval, design_feedback, design_realtime_multimodal, design_tracing,
        design_tools, LensDesignError,
    )
    from oah.design.event_schema import build_event_schema, EventSchemaConflictError
    from oah.design.dto_generator import generate_dtos, DtoGenerationError
    from oah.schemas import validate

    git_sha = _git_sha(args.target)
    if git_sha is None:
        print(f"error: {args.target} is not a git repository (or git is unavailable)", file=sys.stderr)
        return 1

    context = None
    if args.context:
        try:
            context = _load_context(args.context)
        except ContextLoadError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1

    surface_map, still_ambiguous = build_surface_map(args.target, git_sha=git_sha)
    if not surface_map["points"]:
        print("No surface points found — nothing to generate DTOs for.", file=sys.stderr)
        return 0

    lens_fns = {
        "generation-capture": design_generation_capture,
        "pii-governance": design_pii_governance,
        "cost": design_cost,
        "ops": design_ops,
        "retrieval": design_retrieval,
        "feedback": design_feedback,
        "realtime-multimodal": design_realtime_multimodal,
        "tracing": design_tracing,
        "tools": design_tools,
    }
    model = getattr(args, "model", None)
    fragments = _design_all_lenses(surface_map["points"], git_sha, lens_fns, LensDesignError,
                                    context=context, model=model)

    if not fragments:
        print("No points of a kind any built lens covers to generate DTOs for.", file=sys.stderr)
        return 0

    try:
        event_schema = build_event_schema(fragments, git_sha)
    except EventSchemaConflictError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    inventory = build_telemetry_inventory(args.target, git_sha=git_sha)
    gap_model = build_gap_model(surface_map, inventory, context=context)

    covered_point_ids = {pid for a in event_schema["attributes"] for pid in a["surface_point_ids"]}
    points = [p for p in surface_map["points"] if p["id"] in covered_point_ids]
    relevant_gap_ids = {g["id"] for g in gap_model["gaps"]
                         if any(pid in covered_point_ids for pid in g["surface_point_ids"])}
    gaps = [g for g in gap_model["gaps"] if g["id"] in relevant_gap_ids]

    try:
        dtos = generate_dtos(event_schema, points, gaps, git_sha, context=context, model=model)
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

    rollout_note = (
        "rollout_step is ordered by workflow criticality (from --context), then dimension "
        "tiering, then gap priority (architecture.md S7's real rule)"
        if context else
        "rollout_step is ordered by gap priority only (p0 first) — pass --context for real "
        "workflow-criticality ordering (architecture.md S7)"
    )
    print(f"\nnote: {rollout_note}. All nine S4 lenses' attributes are covered.",
          file=sys.stderr)
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
    from oah.design.lens import (
        design_generation_capture, design_pii_governance, design_cost, design_ops,
        design_retrieval, design_feedback, design_realtime_multimodal, design_tracing,
        design_tools, LensDesignError,
    )
    from oah.design.gates import run_gates
    from oah.design.panel import run_cost_skeptic, run_sre, run_security, PanelReviewError
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
        try:
            context = _load_context(args.context)
        except ContextLoadError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1

    surface_map, still_ambiguous = build_surface_map(args.target, git_sha=git_sha)
    inventory = build_telemetry_inventory(args.target, git_sha=git_sha)
    gap_model = build_gap_model(surface_map, inventory, context=context)

    gate_findings = []
    panel_verdicts = []
    event_schema = {"schema_version": "0.1.0", "repo_git_sha": git_sha, "attributes": [],
                     "summary": {"attribute_count": 0, "otel_genai_count": 0, "oah_extension_count": 0, "lenses_included": []}}
    dtos = {"schema_version": "0.1.0", "dtos": []}

    model = getattr(args, "model", None)
    if surface_map["points"]:
        lens_fns = {
            "generation-capture": design_generation_capture,
            "pii-governance": design_pii_governance,
            "cost": design_cost,
            "ops": design_ops,
            "retrieval": design_retrieval,
            "feedback": design_feedback,
            "realtime-multimodal": design_realtime_multimodal,
            "tracing": design_tracing,
            "tools": design_tools,
        }
        fragments = _design_all_lenses(surface_map["points"], git_sha, lens_fns, LensDesignError,
                                        context=context, model=model)

        if fragments:
            gate_findings = [
                f.__dict__ for fragment in fragments
                for f in run_gates(fragment, surface_map_point_ids=_point_ids_for_fragment(fragment, surface_map))
            ]

            persona_fns = {"cost_skeptic": run_cost_skeptic, "sre": run_sre, "security": run_security}
            panel_verdicts = _run_all_personas(fragments, git_sha, persona_fns, PanelReviewError,
                                                context=context, model=model)

            try:
                event_schema = build_event_schema(fragments, git_sha)
            except EventSchemaConflictError as e:
                print(f"warning: event schema build failed: {e}", file=sys.stderr)

            covered_point_ids = {pid for a in event_schema["attributes"] for pid in a["surface_point_ids"]}
            points = [p for p in surface_map["points"] if p["id"] in covered_point_ids]
            relevant_gap_ids = {g["id"] for g in gap_model["gaps"]
                                 if any(pid in covered_point_ids for pid in g["surface_point_ids"])}
            gaps_for_dtos = [g for g in gap_model["gaps"] if g["id"] in relevant_gap_ids]
            if points:
                try:
                    generated = generate_dtos(event_schema, points, gaps_for_dtos, git_sha,
                                               context=context, model=model)
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


def cmd_instrument(args):
    """S10, report-only mode only -- see oah/instrument/executor.py's
    module docstring for exactly what's covered (4 of
    implementation_dto.schema.json's 13 change.type values) and what
    isn't (fix mode: real edits, git commit-per-DTO, rollback). Never
    writes to the target repo in this mode. Checkpoints per applied DTO
    via the same state_db.py S1's disambiguation resume path already
    uses -- stage_id="s10", unit_id=dto["id"], per that module's own
    docstring naming this exact usage."""
    from oah.instrument.executor import apply_dto_report_only
    from oah.schemas import validate, SchemaValidationError

    git_sha = _git_sha(args.target)
    if git_sha is None:
        print(f"error: {args.target} is not a git repository (or git is unavailable)", file=sys.stderr)
        return 1

    try:
        dtos_data = json.loads(Path(args.dtos).read_text())
    except OSError as e:
        print(f"error: could not read --dtos file {args.dtos!r}: {e}", file=sys.stderr)
        return 1
    except json.JSONDecodeError as e:
        print(f"error: --dtos file {args.dtos!r} is not valid JSON: {e}", file=sys.stderr)
        return 1
    try:
        validate("implementation_dto", dtos_data)
    except SchemaValidationError as e:
        print(f"error: --dtos file {args.dtos!r} does not match implementation_dto.schema.json: {e}", file=sys.stderr)
        return 1

    dtos = dtos_data["dtos"]
    if not dtos:
        print("No DTOs in --dtos file -- nothing to instrument.", file=sys.stderr)
        return 0

    model = getattr(args, "model", None)
    run_id = getattr(args, "run_id", None) or f"run-{uuid.uuid4().hex[:12]}"

    # Same resume pattern as cmd_map: reload an existing run_id's own
    # manifest rather than overwriting started_at/stages_completed --
    # otherwise --run-id resume would silently discard prior progress
    # recorded by a crashed or budget-limited earlier attempt.
    if rm.manifest_path(run_id).is_file():
        manifest = rm.load(run_id)
    else:
        manifest = rm.new_manifest(run_id, args.target, git_sha, _now(), primary_language="python")
        rm.save(manifest)

    with open_state_db(args.target) as db:
        db.create_run(run_id, args.target, git_sha, manifest["started_at"])
        results = []
        for dto in dtos:
            if db.is_checkpointed(run_id, "s10", dto["id"]):
                results.append(db.get_checkpoint_result(run_id, "s10", dto["id"]))
                continue
            result = apply_dto_report_only(dto, args.target, model=model)
            db.checkpoint(run_id, "s10", dto["id"], result, _now())
            results.append(result)
        db.mark_run_status(run_id, "completed", _now())

    summary = {"total": len(results), "applied": 0, "refused": 0, "unsupported": 0, "failed": 0}
    for r in results:
        summary[r["status"]] += 1
    report = {
        "schema_version": "0.1.0", "repo_git_sha": git_sha, "mode": "report-only",
        "results": results, "summary": summary,
    }
    validate("instrument_report", report)

    rm.mark_stage_completed(manifest, "s10")
    manifest["completed_at"] = _now()
    rm.save(manifest)

    if args.output:
        Path(args.output).write_text(json.dumps(report, indent=2) + "\n")
        print(f"Wrote {args.output}")
    else:
        print(json.dumps(report, indent=2))

    print(f"\nrun_id: {run_id}  (manifest: {rm.manifest_path(run_id)})", file=sys.stderr)
    print(f"S10 report-only: {summary['applied']} applied, {summary['refused']} refused, "
          f"{summary['unsupported']} unsupported, {summary['failed']} failed", file=sys.stderr)
    print("\nnote: report-only mode only -- no fix mode yet, nothing was written to the target "
          "repo. Only 4 of 13 change.type values are supported; see oah/instrument/executor.py.",
          file=sys.stderr)
    return 1 if summary["failed"] else 0


def cmd_interview(args):
    """S3's owner interview — real stdin prompts, not stub data. See
    oah/interview.py's module docstring for why this is genuinely
    interactive rather than something an LLM or scanner answers."""
    from oah.interview import run_interview, InterviewAborted

    git_sha = _git_sha(args.target)
    if git_sha is None:
        print(f"error: {args.target} is not a git repository (or git is unavailable)", file=sys.stderr)
        return 1

    try:
        context = run_interview(git_sha)
    except InterviewAborted:
        print("\ninterview cancelled — no context.yaml written.", file=sys.stderr)
        return 1
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
    p_map.add_argument("--model", default=None, help=_MODEL_HELP)
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

    p_design = sub.add_parser("design", help="S4 (all nine lenses) + S5 gates + S6 panel (all three personas)")
    p_design.add_argument("target", help="Path to the target repository")
    p_design.add_argument("-o", "--output", default=None, help="Write the design fragment + gate findings here instead of stdout")
    p_design.add_argument("--context", default=None, help="Path to a context.yaml from `oah interview`")
    p_design.add_argument("--model", default=None, help=_MODEL_HELP)
    p_design.set_defaults(func=cmd_design)

    p_event_schema = sub.add_parser("event-schema", help="S7 (partial): deterministic event_schema.json merge")
    p_event_schema.add_argument("target", help="Path to the target repository")
    p_event_schema.add_argument("--context", default=None, help="Path to a context.yaml from `oah interview`")
    p_event_schema.add_argument("-o", "--output", default=None, help="Write event_schema.json here instead of stdout")
    p_event_schema.add_argument("--model", default=None, help=_MODEL_HELP)
    p_event_schema.set_defaults(func=cmd_event_schema)

    p_dtos = sub.add_parser("dtos", help="S8 (partial): implementation_dto.json generation")
    p_dtos.add_argument("target", help="Path to the target repository")
    p_dtos.add_argument("--context", default=None,
                         help="Path to a context.yaml from `oah interview` -- enables real "
                              "workflow-criticality rollout_step ordering (architecture.md S7)")
    p_dtos.add_argument("-o", "--output", default=None, help="Write implementation_dto.json here instead of stdout")
    p_dtos.add_argument("--model", default=None, help=_MODEL_HELP)
    p_dtos.set_defaults(func=cmd_dtos)

    p_readiness = sub.add_parser("readiness", help="S9: production readiness report (deterministic assembly)")
    p_readiness.add_argument("target", help="Path to the target repository")
    p_readiness.add_argument("--context", default=None, help="Path to a context.yaml from `oah interview`")
    p_readiness.add_argument("-o", "--output", default=None, help="Write readiness_report.json here instead of stdout")
    p_readiness.add_argument("--model", default=None, help=_MODEL_HELP)
    p_readiness.set_defaults(func=cmd_readiness)

    p_instrument = sub.add_parser(
        "instrument",
        help="S10, report-only mode only: verify + propose diffs for 4 of 13 DTO change types, never writes to the target repo",
    )
    p_instrument.add_argument("target", help="Path to the target repository")
    p_instrument.add_argument("--dtos", required=True, help="Path to an implementation_dto.json from `oah dtos`")
    p_instrument.add_argument("-o", "--output", default=None, help="Write instrument_report.json here instead of stdout")
    p_instrument.add_argument("--run-id", default=None, help="Resume this run_id if already checkpointed, else start it")
    p_instrument.add_argument("--mode", choices=["report-only"], default="report-only",
                               help="Only report-only is built so far -- fix mode (real edits/commits) is not yet implemented")
    p_instrument.add_argument("--model", default=None, help=_AGENT_MODEL_HELP)
    p_instrument.set_defaults(func=cmd_instrument)

    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
