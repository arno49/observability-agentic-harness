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

from oah.backend_targets import SUPPORTED_BACKENDS
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

_LANGUAGE_HELP = (
    "Which S1 adapter (and, on any command that also builds S2's telemetry "
    "inventory, which S2 scanner, docs/decisions/033) to run against the target "
    "repo: python (default -- oah.discovery.python_adapter + telemetry_scanner), "
    "typescript (oah.discovery.typescript_adapter, E11-TS, + ts_telemetry_scanner, "
    "docs/decisions/033), or java (oah.discovery.java_adapter, E11-Java, "
    "docs/decisions/029, + java_telemetry_scanner, docs/decisions/037). typescript "
    "and java S1 are both real but neither has an LLM-disambiguation counterpart yet, so "
    "neither ever returns still-ambiguous candidates. Explicit, not auto-sniffed "
    "from file extensions -- a mixed-language repo has no single right guess."
)

_PACK_HELP = (
    "Which domain pack governs point-kind vocabulary, S1 registries, lenses, gates, "
    "and semconv namespaces: genai (default -- LLM-application observability) or "
    "service (docs/decisions/011, E12 -- ordinary request-driven services; only real "
    "with --language typescript today, since the service pack's one S1 registry "
    "(Express, docs/decisions/018) has no Python- or Java-adapter counterpart yet)."
)


def _build_surface_map(target, git_sha, language, pack=None, disambiguated=None):
    """The one place that decides which S1 adapter runs. All three adapters
    return the same (surface_map, still_ambiguous) 2-tuple shape, so every
    call site downstream of this needs no per-language branching.

    `pack` (the loaded pack dict, default None -- genai) selects which
    pack's registries S1 matches against, e.g. load_pack("service") to
    also resolve Express route registrations (docs/decisions/018). Only
    threaded to the TypeScript adapter today -- python_adapter.py's and
    java_adapter.py's own registries remain genai-only (no Python or Java
    service-domain registries exist yet), a real, named scope boundary
    rather than a silent gap: --pack service with --language python or
    --language java runs but finds nothing new."""
    if language == "typescript":
        from oah.discovery.typescript_adapter import build_surface_map
        return build_surface_map(target, git_sha=git_sha, disambiguated=disambiguated, pack=pack)
    elif language == "java":
        from oah.discovery.java_adapter import build_surface_map
        return build_surface_map(target, git_sha=git_sha, disambiguated=disambiguated, pack=pack)
    else:
        from oah.discovery.python_adapter import build_surface_map
        return build_surface_map(target, git_sha=git_sha, disambiguated=disambiguated)


def _build_telemetry_inventory(target, git_sha, language):
    """The one place that decides which S2 scanner runs -- mirrors
    _build_surface_map's own dispatch shape exactly (docs/decisions/033).
    `oah/discovery/telemetry_scanner.py`'s Python scanner stays the
    default for every existing caller (E13's byte-identical guarantee);
    `typescript` dispatches to `oah/discovery/ts_telemetry_scanner.py`
    (docs/decisions/033); `java` dispatches to
    `oah/discovery/java_telemetry_scanner.py` (docs/decisions/037)."""
    if language == "typescript":
        from oah.discovery.ts_telemetry_scanner import build_telemetry_inventory
        return build_telemetry_inventory(target, git_sha=git_sha)
    if language == "java":
        from oah.discovery.java_telemetry_scanner import build_telemetry_inventory
        return build_telemetry_inventory(target, git_sha=git_sha)
    from oah.discovery.telemetry_scanner import build_telemetry_inventory
    return build_telemetry_inventory(target, git_sha=git_sha)


def _load_pack_for_args(args):
    """Which domain pack a command runs against -- default genai, matching
    every command's own pre-existing hardcoded behavior (E13's
    byte-identical guarantee). --pack service (docs/decisions/016-018)
    threads through to S1's registries, S3's dimension mapping, and every
    S4-S8 pack-aware call downstream."""
    from oah.domains.loader import load_pack
    return load_pack(getattr(args, "pack", "genai") or "genai")

# Replaces the old literal LENS_TO_POINT_KIND dict (docs/decisions/011):
# {lens_name: target_kinds}, target_kinds a list of point kinds or None for
# a cross-cutting lens (pack data's own null -- e.g. tracing,
# architecture.md's cross-cutting lens, unscoped to any one surface_map
# kind the way every other lens is). check_every_surface_point_has_decision
# needs, per fragment, the full set of points that fragment is expected to
# cover -- that set differs by lens, so it's looked up per fragment via its
# own "lens" field, not assumed to be a single hardcoded kind across all of
# them (a bug an absent mapping would produce silently: a fragment checked
# against point IDs it was never designed to cover).
def _target_kinds_for_pack(pack):
    return {entry["lens"]: entry["target_kinds"] for entry in pack["lenses"]}


def _emits_for_pack(pack):
    """{lens_name: emits} -- which artifact_type(s) a lens's own design_*
    function returns (docs/decisions/011 Finding 1, docs/decisions/020).
    Every lens before the slo lens emits exactly ["design_fragment"] and
    its design_* function returns that fragment directly; a lens whose
    emits has more than one entry returns a wrapper {artifact_type: value}
    instead -- design_lens() itself doesn't need to know or care, since it
    just validates+returns whatever the skill's own output.schema.json
    declares; _design_all_lenses is what unpacks the difference."""
    return {entry["lens"]: entry["emits"] for entry in pack["lenses"]}


def _lens_fns_for_pack(pack, lens_module):
    """One shared {lens_name: design_fn} builder, replacing four
    hand-duplicated dict literals this file used to write out
    independently in cmd_design/cmd_event_schema/cmd_dtos/cmd_readiness --
    a lens missing from one copy went undetected by anything but a manual
    grep audit, three times in one session (docs/decisions/011). Every
    design_* function's name is its pack lens name with hyphens replaced
    by underscores, a convention oah/design/lens.py's functions already
    follow (design_generation_capture for "generation-capture", etc.); an
    AttributeError here means the pack names a lens this build of oah
    doesn't actually have a design function for, and that should be loud,
    not silently skipped."""
    return {entry["lens"]: getattr(lens_module, f"design_{entry['lens'].replace('-', '_')}")
            for entry in pack["lenses"]}


def _point_ids_for_fragment(fragment, surface_map, target_kinds_by_lens):
    kinds = target_kinds_by_lens[fragment["lens"]]
    if kinds is None:
        return [p["id"] for p in surface_map["points"]]
    return [p["id"] for p in surface_map["points"] if p["kind"] in kinds]


_ALL_PERSONA_NAMES = frozenset({"cost_skeptic", "sre", "security"})


def _design_all_lenses(points, git_sha, lens_fns, LensDesignError, pack, context=None, model=None):
    """Runs every S4 lens against `points`, warning (not failing) on any
    lens that raises. `lens_fns` must be a {lens_name: design_fn} dict
    covering exactly `pack`'s own lens roster -- the assert below turns a
    missing/extra entry into an immediate, loud crash instead of a silent
    gap. This exists because the equivalent 4-way copy-pasted inline loop
    (one per command) had a lens silently missing from cmd_readiness's own
    copy three separate times this session -- each time caught only by a
    manual grep audit after the fact, never by a test. One shared
    implementation, called identically from every command, makes that
    whole bug class structurally impossible instead of merely
    well-intentioned.

    Point-kind filtering happens HERE, once, driven by the pack's own
    lenses[].target_kinds -- not inside each design_* function (E12's own
    "prove the split with a second real pack" effort found every filtering
    lens but tracing hardcoded a literal kind string instead, docs/decisions/016;
    genai's own behavior happened to match because the pack was extracted
    from those exact literals, but a differently-shaped pack silently got
    zero points and a None fragment no matter what its manifest declared).

    Returns (fragments, extra_artifacts). A lens whose lenses[].emits is
    exactly ["design_fragment"] (every lens before slo) has its raw result
    appended to `fragments` directly, unchanged from before this docstring
    was updated. A lens with more than one emits entry (docs/decisions/020)
    returns {artifact_type: value} instead -- its own "design_fragment" key
    still feeds `fragments` (so S5/S7/S8's existing signal-list-shaped
    consumption needs no change), and every OTHER key lands in
    extra_artifacts[lens_name], for callers that know what to do with a
    second artifact type (e.g. cmd_design surfacing an slo_spec)."""
    expected = {entry["lens"] for entry in pack["lenses"]}
    assert set(lens_fns) == expected, (
        f"lens_fns must cover exactly the pack's lens roster -- got {sorted(lens_fns)}, "
        f"expected {sorted(expected)}"
    )
    target_kinds_by_lens = _target_kinds_for_pack(pack)
    emits_by_lens = _emits_for_pack(pack)
    fragments = []
    extra_artifacts = {}
    for lens_name, design_fn in lens_fns.items():
        target_kinds = target_kinds_by_lens[lens_name]
        lens_points = points if target_kinds is None else [p for p in points if p.get("kind") in target_kinds]
        try:
            result = design_fn(lens_points, git_sha, context=context, model=model)
        except LensDesignError as e:
            print(f"warning: {lens_name} lens design failed, continuing without it: {e}", file=sys.stderr)
            continue
        if not result:
            continue
        if len(emits_by_lens[lens_name]) == 1:
            fragments.append(result)
        else:
            fragment = result.get("design_fragment")
            if fragment:
                fragments.append(fragment)
            extra_artifacts[lens_name] = {k: v for k, v in result.items() if k != "design_fragment"}
    return fragments, extra_artifacts


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

    pack = _load_pack_for_args(args)
    result = run_estimate(args.target, workflows=args.workflows,
                           language=getattr(args, "language", "python"), pack=pack)
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
    from oah.discovery.disambiguate import disambiguate, DisambiguationError, missing_credentials

    language = getattr(args, "language", "python")
    pack = _load_pack_for_args(args)
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
        manifest = rm.new_manifest(run_id, args.target, git_sha, _now(), primary_language=language)
        rm.save(manifest)  # persisted immediately, before any work — a crash after this still resumes correctly

    with open_state_db(args.target) as db:
        db.create_run(run_id, args.target, git_sha, manifest["started_at"])

        if db.is_checkpointed(run_id, "s1", "scan"):
            print(f"s1 scan already checkpointed for {run_id} — resuming from stored result.", file=sys.stderr)
            scan_result = db.get_checkpoint_result(run_id, "s1", "scan")
        else:
            surface_map, still_ambiguous = _build_surface_map(args.target, git_sha, language, pack=pack)
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
            surface_map, still_ambiguous = _build_surface_map(
                args.target, git_sha, language, pack=pack, disambiguated=disambiguated
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
    git_sha = _git_sha(args.target)
    if git_sha is None:
        print(f"error: {args.target} is not a git repository (or git is unavailable)", file=sys.stderr)
        return 1

    inventory = _build_telemetry_inventory(args.target, git_sha, getattr(args, "language", "python"))

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
    from oah.discovery.gap_model import build_gap_model

    pack = _load_pack_for_args(args)
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

    language = getattr(args, "language", "python")
    surface_map, still_ambiguous = _build_surface_map(args.target, git_sha, language, pack=pack)
    inventory = _build_telemetry_inventory(args.target, git_sha, language)
    gaps = build_gap_model(surface_map, inventory, context=context, pack=pack)

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
    from oah.design import lens as lens_module
    from oah.design.lens import LensDesignError
    from oah.design.gates import run_gates, gates_passed
    from oah.design.slo_gates import run_slo_gates
    from oah.design.dependency_gates import run_dependency_gates
    from oah.design.panel import run_cost_skeptic, run_sre, run_security, PanelReviewError
    from oah.schemas import validate

    pack = _load_pack_for_args(args)
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

    surface_map, still_ambiguous = _build_surface_map(
        args.target, git_sha, getattr(args, "language", "python"), pack=pack
    )
    if not surface_map["points"]:
        print("No surface points found (or all still ambiguous) — nothing to design for.", file=sys.stderr)
        return 0

    lens_fns = _lens_fns_for_pack(pack, lens_module)
    target_kinds_by_lens = _target_kinds_for_pack(pack)
    model = getattr(args, "model", None)
    fragments, extra_artifacts = _design_all_lenses(surface_map["points"], git_sha, lens_fns, LensDesignError, pack,
                                                      context=context, model=model)

    if not fragments:
        print("No points of a kind any built lens covers to design for.", file=sys.stderr)
        return 0

    findings = []
    for fragment in fragments:
        findings.extend(run_gates(fragment, surface_map_point_ids=_point_ids_for_fragment(fragment, surface_map, target_kinds_by_lens), pack=pack))
    # slo_spec/dependency_model (and any future non-design_fragment
    # artifact) each need their own gate set -- run_gates() only ever
    # understands a design_fragment's own flat signal-list shape
    # (docs/decisions/020, docs/decisions/021).
    for lens_name, artifacts in extra_artifacts.items():
        slo_spec = artifacts.get("slo_spec")
        if slo_spec is not None:
            findings.extend(run_slo_gates(slo_spec))
        dependency_model = artifacts.get("dependency_model")
        if dependency_model is not None:
            findings.extend(run_dependency_gates(dependency_model))
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
    if extra_artifacts:
        # A multi-emit lens's own non-design_fragment artifacts (e.g. slo's
        # slo_spec, docs/decisions/020) -- S5/S6 above only ever see the
        # design_fragment half; this is the one place a human/reviewer sees
        # the rest, since S7-S9 don't consume these yet.
        output["extra_artifacts"] = extra_artifacts
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
    from oah.design import lens as lens_module
    from oah.design.lens import LensDesignError
    from oah.design.event_schema import build_event_schema, EventSchemaConflictError
    from oah.schemas import validate

    pack = _load_pack_for_args(args)
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

    surface_map, still_ambiguous = _build_surface_map(
        args.target, git_sha, getattr(args, "language", "python"), pack=pack
    )
    if not surface_map["points"]:
        print("No surface points found — nothing to build an event schema from.", file=sys.stderr)
        return 0

    lens_fns = _lens_fns_for_pack(pack, lens_module)
    model = getattr(args, "model", None)
    fragments, _extra_artifacts = _design_all_lenses(surface_map["points"], git_sha, lens_fns, LensDesignError, pack,
                                                       context=context, model=model)

    if not fragments:
        print("No points of a kind any built lens covers to build an event schema from.", file=sys.stderr)
        return 0

    try:
        schema = build_event_schema(fragments, git_sha, pack=pack)
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
    from oah.discovery.gap_model import build_gap_model
    from oah.design import lens as lens_module
    from oah.design.lens import LensDesignError
    from oah.design.event_schema import build_event_schema, EventSchemaConflictError
    from oah.design.dto_generator import generate_dtos, DtoGenerationError
    from oah.schemas import validate

    pack = _load_pack_for_args(args)
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

    language = getattr(args, "language", "python")
    surface_map, still_ambiguous = _build_surface_map(args.target, git_sha, language, pack=pack)
    if not surface_map["points"]:
        print("No surface points found — nothing to generate DTOs for.", file=sys.stderr)
        return 0

    lens_fns = _lens_fns_for_pack(pack, lens_module)
    model = getattr(args, "model", None)
    fragments, _extra_artifacts = _design_all_lenses(surface_map["points"], git_sha, lens_fns, LensDesignError, pack,
                                                       context=context, model=model)

    if not fragments:
        print("No points of a kind any built lens covers to generate DTOs for.", file=sys.stderr)
        return 0

    try:
        event_schema = build_event_schema(fragments, git_sha, pack=pack)
    except EventSchemaConflictError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    inventory = _build_telemetry_inventory(args.target, git_sha, language)
    gap_model = build_gap_model(surface_map, inventory, context=context, pack=pack)

    covered_point_ids = {pid for a in event_schema["attributes"] for pid in a["surface_point_ids"]}
    points = [p for p in surface_map["points"] if p["id"] in covered_point_ids]
    relevant_gap_ids = {g["id"] for g in gap_model["gaps"]
                         if any(pid in covered_point_ids for pid in g["surface_point_ids"])}
    gaps = [g for g in gap_model["gaps"] if g["id"] in relevant_gap_ids]

    try:
        dtos = generate_dtos(event_schema, points, gaps, git_sha, context=context, model=model, pack=pack)
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
    from oah.discovery.gap_model import build_gap_model
    from oah.design import lens as lens_module
    from oah.design.lens import LensDesignError
    from oah.design.gates import run_gates
    from oah.design.slo_gates import run_slo_gates
    from oah.design.dependency_gates import run_dependency_gates
    from oah.design.panel import run_cost_skeptic, run_sre, run_security, PanelReviewError
    from oah.design.event_schema import build_event_schema, EventSchemaConflictError
    from oah.design.dto_generator import generate_dtos, DtoGenerationError
    from oah.design.readiness_report import build_readiness_report
    from oah.schemas import validate

    pack = _load_pack_for_args(args)
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

    language = getattr(args, "language", "python")
    surface_map, still_ambiguous = _build_surface_map(args.target, git_sha, language, pack=pack)
    inventory = _build_telemetry_inventory(args.target, git_sha, language)
    gap_model = build_gap_model(surface_map, inventory, context=context, pack=pack)

    fragments = []
    gate_findings = []
    panel_verdicts = []
    empty_kind_counts = {f"{v}_count": 0 for v in pack["attribute_kind_values"]}
    event_schema = {"schema_version": "0.1.0", "repo_git_sha": git_sha, "attributes": [],
                     "summary": {"attribute_count": 0, **empty_kind_counts, "lenses_included": []}}
    dtos = {"schema_version": "0.1.0", "dtos": []}

    model = getattr(args, "model", None)
    if surface_map["points"]:
        lens_fns = _lens_fns_for_pack(pack, lens_module)
        target_kinds_by_lens = _target_kinds_for_pack(pack)
        fragments, extra_artifacts = _design_all_lenses(surface_map["points"], git_sha, lens_fns, LensDesignError, pack,
                                                          context=context, model=model)

        if fragments:
            gate_findings = [
                f.__dict__ for fragment in fragments
                for f in run_gates(fragment, surface_map_point_ids=_point_ids_for_fragment(fragment, surface_map, target_kinds_by_lens), pack=pack)
            ]
            # slo_spec/dependency_model each need their own gate set --
            # run_gates() only understands a design_fragment's flat signal
            # list (docs/decisions/020, docs/decisions/021). Without this,
            # a readiness decision for the service pack would silently
            # ignore every slo/dependency gate finding.
            for lens_name, artifacts in extra_artifacts.items():
                slo_spec = artifacts.get("slo_spec")
                if slo_spec is not None:
                    gate_findings.extend(f.__dict__ for f in run_slo_gates(slo_spec))
                dependency_model = artifacts.get("dependency_model")
                if dependency_model is not None:
                    gate_findings.extend(f.__dict__ for f in run_dependency_gates(dependency_model))

            persona_fns = {"cost_skeptic": run_cost_skeptic, "sre": run_sre, "security": run_security}
            panel_verdicts = _run_all_personas(fragments, git_sha, persona_fns, PanelReviewError,
                                                context=context, model=model)

            try:
                event_schema = build_event_schema(fragments, git_sha, pack=pack)
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
                                               context=context, model=model, pack=pack)
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

    save_intermediates_path = getattr(args, "save_intermediates", None)
    if save_intermediates_path:
        # S9's own readiness_report only ever surfaces an AGGREGATE count
        # per gate name (build_readiness_report's own design) -- every
        # per-point/per-lens detail (which surface point, which fragment,
        # gate_findings[].reason's own point-ID list) was computed right
        # here and then silently discarded before this flag existed. Real
        # cost: after a real 375-point run against mf-analyzer-web
        # (docs/decisions/032-036's own pilot), "remediate_before_release"
        # had no way to be explained beyond gate names and counts -- this
        # is that data, saved instead of thrown away.
        Path(save_intermediates_path).write_text(json.dumps({
            "design_fragments": fragments,
            "gate_findings": gate_findings,
            "panel_verdicts": panel_verdicts,
            "event_schema": event_schema,
            "dtos": dtos,
        }, indent=2) + "\n")
        print(f"Wrote intermediates to {save_intermediates_path}", file=sys.stderr)

    print(f"\nrecommendation: {report['recommendation']['decision']}", file=sys.stderr)
    print(f"rationale: {report['recommendation']['rationale']}", file=sys.stderr)
    return 0


def cmd_instrument(args):
    """S10 -- see oah/instrument/executor.py's module docstring for
    exactly what's covered (4 of implementation_dto.schema.json's 13
    change.type values) and the shared verification path both modes use.
    report-only never writes to the target repo. fix mode writes and
    commits one DTO at a time, gated on two preconditions checked here
    (not in executor.py, which has no opinion on whether a run should
    start at all): a recorded S9 `ready`/`ready_with_conditions`
    decision (architecture.md: "Fix mode does not proceed without a
    recorded decision of ready or ready_with_conditions"), and a clean
    git working tree in the target repo (a fix-mode rollback restores a
    file to HEAD -- unsafe to do unconditionally if the user has their
    own uncommitted changes sitting there). Checkpoints per DTO via the
    same state_db.py S1's disambiguation resume path already uses --
    stage_id="s10-{mode}" (mode-scoped so a report-only run and a fix
    run sharing a --run-id can never reuse each other's differently-
    shaped checkpointed result), unit_id=dto["id"]."""
    from oah.instrument.executor import apply_dto_fix, apply_dto_report_only
    from oah.schemas import validate, SchemaValidationError

    git_sha = _git_sha(args.target)
    if git_sha is None:
        print(f"error: {args.target} is not a git repository (or git is unavailable)", file=sys.stderr)
        return 1

    mode = getattr(args, "mode", "report-only")

    if mode == "fix":
        readiness_path = getattr(args, "readiness", None)
        if not readiness_path:
            print("error: --mode fix requires --readiness <readiness_report.json> -- "
                  "architecture.md: fix mode does not proceed without a recorded "
                  "ready/ready_with_conditions decision", file=sys.stderr)
            return 1
        try:
            readiness_data = json.loads(Path(readiness_path).read_text())
        except OSError as e:
            print(f"error: could not read --readiness file {readiness_path!r}: {e}", file=sys.stderr)
            return 1
        except json.JSONDecodeError as e:
            print(f"error: --readiness file {readiness_path!r} is not valid JSON: {e}", file=sys.stderr)
            return 1
        try:
            validate("readiness_report", readiness_data)
        except SchemaValidationError as e:
            print(f"error: --readiness file {readiness_path!r} does not match "
                  f"readiness_report.schema.json: {e}", file=sys.stderr)
            return 1
        decision = readiness_data["recommendation"]["decision"]
        if decision not in ("ready", "ready_with_conditions"):
            print(f"error: --readiness file's recommendation is {decision!r} -- fix mode requires "
                  f"'ready' or 'ready_with_conditions'", file=sys.stderr)
            return 1

        status = subprocess.run(["git", "-C", args.target, "status", "--porcelain"],
                                 capture_output=True, text=True)
        if status.returncode != 0:
            print(f"error: git status failed in {args.target}: {status.stderr.strip()}", file=sys.stderr)
            return 1
        if status.stdout.strip():
            print(f"error: {args.target} has uncommitted changes -- fix mode's rollback restores a "
                  f"file to HEAD, which would discard your own uncommitted work. Commit or stash "
                  f"first.", file=sys.stderr)
            return 1

        print(f"\n⚠️  fix mode: about to write to and commit into {args.target}. "
              f"One commit per applied DTO; any failure rolls back cleanly.", file=sys.stderr)

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
    stage_id = f"s10-{mode}"
    apply_dto = apply_dto_fix if mode == "fix" else apply_dto_report_only

    # Same resume pattern as cmd_map: reload an existing run_id's own
    # manifest rather than overwriting started_at/stages_completed --
    # otherwise --run-id resume would silently discard prior progress
    # recorded by a crashed or budget-limited earlier attempt.
    if rm.manifest_path(run_id).is_file():
        manifest = rm.load(run_id)
    else:
        manifest = rm.new_manifest(run_id, args.target, git_sha, _now(),
                                    primary_language=getattr(args, "language", "python"))
        rm.save(manifest)

    with open_state_db(args.target) as db:
        db.create_run(run_id, args.target, git_sha, manifest["started_at"])
        results = []
        for dto in dtos:
            if db.is_checkpointed(run_id, stage_id, dto["id"]):
                results.append(db.get_checkpoint_result(run_id, stage_id, dto["id"]))
                continue
            result = apply_dto(dto, args.target, model=model)
            db.checkpoint(run_id, stage_id, dto["id"], result, _now())
            results.append(result)
        db.mark_run_status(run_id, "completed", _now())

    summary = {"total": len(results), "applied": 0, "refused": 0, "unsupported": 0, "failed": 0}
    for r in results:
        summary[r["status"]] += 1
    report = {
        "schema_version": "0.1.0", "repo_git_sha": git_sha, "mode": mode,
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
    print(f"S10 {mode}: {summary['applied']} applied, {summary['refused']} refused, "
          f"{summary['unsupported']} unsupported, {summary['failed']} failed", file=sys.stderr)
    if mode == "report-only":
        print("\nnote: report-only mode -- nothing was written to the target repo. Only 4 of 13 "
              "change.type values are supported; see oah/instrument/executor.py.", file=sys.stderr)
    else:
        print(f"\nnote: fix mode -- {summary['applied']} commit(s) created in {args.target}. Only "
              "4 of 13 change.type values are supported; see oah/instrument/executor.py.",
              file=sys.stderr)
    return 1 if summary["failed"] else 0


def cmd_validate(args):
    """S11, R4 (static-only presence check) plus real R2 (both halves):
    an opt-in --dynamic pass adds a deterministic regression gate and
    per-DTO event-emission assertion over one real sandboxed run
    (oah/validate/dynamic.py), and a static trace-ID-propagation check
    for propagate_context DTOs (oah/validate/propagation_checker.py) runs
    unconditionally, same as the R4 static check.

    An opt-in --live pass additionally starts the target as a real running
    service alongside a real local OTel collector (E6 R1's mechanism,
    oah/validate/live_sandbox.py) and drives --requests against it,
    reporting real captured requests/latency/spans, per-DTO event
    assertions, an unknown-attribute check (oah/validate/live_diff.py),
    and real TCR (oah/validate/tcr.py) under live_execution. --baseline
    (on top of --live) additionally runs the target's real pre-
    instrumentation code and reports real latency overhead vs. each
    applied DTO's declared budget (oah/validate/overhead.py).

    oah/validate/verdict.py's compute_ladder_verdict is the one place that
    decides whether a run has actually earned ladder_rung 'R2' (--dynamic
    evidence alone) or 'R1' (R2's requirements plus --live/--baseline
    evidence: TCR exactly 1.0, overhead within budget) / verdict
    'validated' -- deliberately conservative, see its own module docstring
    for the exact rule.

    No checkpointing -- none of these make an LLM/agent call, and even
    --dynamic/--live's sandbox runs are cheap enough to always re-run in
    full."""
    from oah.validate.checker import check_dto_static
    from oah.validate.dynamic import run_dynamic_validation
    from oah.validate.event_assertion import check_dto_dynamic, summarize_provenance
    from oah.validate.live_diff import check_unknown_attributes
    from oah.validate.tcr import compute_tcr
    from oah.validate.baseline import run_baseline_live_sandbox
    from oah.validate.overhead import compute_overhead_vs_budget, not_attempted as overhead_not_attempted
    from oah.validate.live_sandbox import run_live_sandbox
    from oah.validate.propagation_checker import check_dto_propagation
    from oah.validate.verdict import compute_ladder_verdict
    from oah.schemas import validate, SchemaValidationError

    live = getattr(args, "live", False)
    if live:
        missing = [name for name in ("start_command", "port", "requests")
                   if getattr(args, name, None) is None]
        if missing:
            print(f"error: --live requires --start-command, --port, and --requests together "
                  f"(missing: {', '.join('--' + m.replace('_', '-') for m in missing)})", file=sys.stderr)
            return 1

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

    try:
        instrument_data = json.loads(Path(args.instrument_report).read_text())
    except OSError as e:
        print(f"error: could not read --instrument-report file {args.instrument_report!r}: {e}", file=sys.stderr)
        return 1
    except json.JSONDecodeError as e:
        print(f"error: --instrument-report file {args.instrument_report!r} is not valid JSON: {e}", file=sys.stderr)
        return 1
    try:
        validate("instrument_report", instrument_data)
    except SchemaValidationError as e:
        print(f"error: --instrument-report file {args.instrument_report!r} does not match "
              f"instrument_report.schema.json: {e}", file=sys.stderr)
        return 1

    instrument_by_id = {r["dto_id"]: r for r in instrument_data["results"]}
    results = [
        check_dto_static(dto, instrument_by_id.get(dto["id"]), args.target)
        for dto in dtos_data["dtos"]
    ]

    summary = {"total": len(results), "present": 0, "absent": 0, "skipped": 0}
    for r in results:
        summary[r["status"]] += 1

    propagation_checks = [
        check_dto_propagation(dto, instrument_by_id.get(dto["id"]), args.target)
        for dto in dtos_data["dtos"]
    ]

    dynamic = getattr(args, "dynamic", False)
    dynamic_result = run_dynamic_validation(args.target, dtos_data["dtos"], dynamic=dynamic)
    regression_gate = dynamic_result["regression_gate"]
    event_assertions = dynamic_result["event_assertions"]

    live_execution = None
    if live:
        event_schema = None
        if args.event_schema:
            try:
                event_schema = json.loads(Path(args.event_schema).read_text())
            except (OSError, json.JSONDecodeError) as e:
                print(f"error: could not read --event-schema file {args.event_schema!r}: {e}", file=sys.stderr)
                return 1
        try:
            requests_list = json.loads(Path(args.requests).read_text())
        except (OSError, json.JSONDecodeError) as e:
            print(f"error: could not read --requests file {args.requests!r}: {e}", file=sys.stderr)
            return 1

        live_result = run_live_sandbox(
            args.target, start_command=args.start_command, port=args.port, requests=requests_list,
            setup_script=getattr(args, "setup_script", None),
        )
        live_event_assertions = (
            [check_dto_dynamic(dto, live_result["spans"]) for dto in dtos_data["dtos"]]
            if live_result["status"] == "ok" else []
        )

        overhead_vs_budget = overhead_not_attempted()
        if getattr(args, "baseline", False):
            baseline_result = run_baseline_live_sandbox(
                args.target, instrument_data["repo_git_sha"],
                start_command=args.start_command, port=args.port, requests=requests_list,
                setup_script=getattr(args, "setup_script", None),
            )
            overhead_vs_budget = compute_overhead_vs_budget(
                baseline_result, live_result, dtos_data["dtos"], results,
            )

        live_execution = {
            "status": live_result["status"],
            "requests": live_result["requests"],
            "latency_p50_ms": live_result["latency_p50_ms"],
            "latency_p95_ms": live_result["latency_p95_ms"],
            "fail_open": live_result["fail_open"],
            "event_assertions": live_event_assertions,
            "unknown_attributes": check_unknown_attributes(live_result["spans"], event_schema),
            "tcr": compute_tcr(live_result["spans"]),
            "overhead_vs_budget": overhead_vs_budget,
            "reason": live_result["reason"],
        }

    ladder_rung, verdict = compute_ladder_verdict(
        dtos_data["dtos"], results, event_assertions, propagation_checks, regression_gate,
        live_execution=live_execution,
    )

    # docs/decisions/011's own S11 addition, phase 2 (docs/decisions/025's
    # own named follow-up): a report-level answer to "were OAH's own
    # changes load-bearing," combining --dynamic's and --live's event
    # assertions (whichever ran) rather than leaving provenance as a
    # per-DTO detail nobody rolls up.
    live_event_assertions_for_summary = live_execution["event_assertions"] if live_execution else []
    signal_provenance = summarize_provenance(event_assertions, live_event_assertions_for_summary)

    report = {
        "schema_version": "0.1.0", "repo_git_sha": git_sha,
        "ladder_rung": ladder_rung, "verdict": verdict,
        "regression_gate": regression_gate,
        "event_assertions": event_assertions,
        "propagation_checks": propagation_checks,
        "live_execution": live_execution,
        "signal_provenance": signal_provenance,
        "results": results, "summary": summary,
    }
    validate("validation_report", report)

    if args.output:
        Path(args.output).write_text(json.dumps(report, indent=2) + "\n")
        print(f"Wrote {args.output}")
    else:
        print(json.dumps(report, indent=2))

    print(f"\nladder_rung: {ladder_rung}  verdict: {verdict}", file=sys.stderr)
    print(f"signal_provenance: {signal_provenance['auto_instrumentation']} auto_instrumentation, "
          f"{signal_provenance['harness_instrumented']} harness_instrumented, "
          f"{signal_provenance['unknown']} unknown", file=sys.stderr)
    print(f"S11 R4 (static): {summary['present']} present, {summary['absent']} absent, "
          f"{summary['skipped']} skipped", file=sys.stderr)
    print(f"regression_gate: {regression_gate['status']}"
          + (f" -- {regression_gate['reason']}" if regression_gate["reason"] else ""), file=sys.stderr)
    event_assertion_counts = {"not_attempted": 0, "skipped": 0, "observed": 0, "not_observed": 0}
    for ea in event_assertions:
        event_assertion_counts[ea["status"]] += 1
    print(f"event_assertions: {event_assertion_counts['observed']} observed, "
          f"{event_assertion_counts['not_observed']} not_observed, "
          f"{event_assertion_counts['skipped']} skipped, "
          f"{event_assertion_counts['not_attempted']} not_attempted", file=sys.stderr)
    propagation_counts = {"not_applicable": 0, "skipped": 0, "present": 0, "absent": 0}
    for pc in propagation_checks:
        propagation_counts[pc["status"]] += 1
    print(f"propagation_checks: {propagation_counts['present']} present, "
          f"{propagation_counts['absent']} absent, {propagation_counts['skipped']} skipped, "
          f"{propagation_counts['not_applicable']} not_applicable", file=sys.stderr)
    if live_execution is None:
        print("live_execution: not_attempted", file=sys.stderr)
    else:
        print(f"live_execution: {live_execution['status']}"
              + (f" -- {live_execution['reason']}" if live_execution["reason"] else ""), file=sys.stderr)
        if live_execution["status"] == "ok":
            tcr = live_execution["tcr"]
            tcr_str = (f"{tcr['tcr']:.2f} ({tcr['traces_complete']}/{tcr['traces_total']} traces complete)"
                       if tcr["tcr"] is not None else "n/a (no traces captured)")
            print(f"  latency_p50_ms={live_execution['latency_p50_ms']:.1f} "
                  f"latency_p95_ms={live_execution['latency_p95_ms']:.1f} "
                  f"fail_open={live_execution['fail_open']} "
                  f"unknown_attributes={live_execution['unknown_attributes']['status']} "
                  f"tcr={tcr_str}", file=sys.stderr)
            ovb = live_execution["overhead_vs_budget"]
            if ovb["status"] == "ok":
                budget_str = f"{ovb['budget_ms']:.1f}ms" if ovb["budget_complete"] else "incomplete"
                print(f"  overhead_vs_budget: p50={ovb['overhead_p50_ms']:.1f}ms "
                      f"p95={ovb['overhead_p95_ms']:.1f}ms budget={budget_str} "
                      f"within_budget={ovb['within_budget']}", file=sys.stderr)
            elif ovb["status"] != "not_attempted":
                print(f"  overhead_vs_budget: {ovb['status']}"
                      + (f" -- {ovb['reason']}" if ovb["reason"] else ""), file=sys.stderr)
    return 0


def cmd_backend_config(args):
    """E9 -- deterministic backend target config generation, no LLM or
    agent call at all (see oah/backend_targets.py's module docstring).
    --backend is a manual choice today, not yet constraint-driven from
    context.yaml -- that needs S7's LLM-driven architecture.md synthesis,
    which isn't built yet."""
    from oah.backend_targets import generate_collector_config, generate_compose_note

    git_sha = _git_sha(args.target)
    if git_sha is None:
        print(f"error: {args.target} is not a git repository (or git is unavailable)", file=sys.stderr)
        return 1

    config_yaml = generate_collector_config(args.backend)

    if args.output_dir:
        output_path = Path(args.output_dir) / "otel-collector-config.yaml"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(config_yaml)
        print(f"Wrote {output_path}")
    else:
        print(config_yaml, end="")

    compose_note = generate_compose_note(args.backend)
    if compose_note:
        print(f"\nnote: {compose_note}", file=sys.stderr)
    print(f"\nnote: --backend is a manual choice today, not yet constraint-driven from "
          f"context.yaml -- that needs S7's LLM-driven architecture.md synthesis, not built yet.",
          file=sys.stderr)
    return 0


def cmd_interview(args):
    """S3's owner interview — real stdin prompts, not stub data. See
    oah/interview.py's module docstring for why this is genuinely
    interactive rather than something an LLM or scanner answers."""
    from oah.interview import run_interview, InterviewAborted

    git_sha = _git_sha(args.target)
    if git_sha is None:
        print(f"error: {args.target} is not a git repository (or git is unavailable)", file=sys.stderr)
        return 1

    surface_map = None
    surface_map_path = getattr(args, "surface_map", None)
    if surface_map_path:
        try:
            surface_map = json.loads(Path(surface_map_path).read_text())
        except (OSError, json.JSONDecodeError) as e:
            print(f"error: could not read --surface-map {surface_map_path}: {e}", file=sys.stderr)
            return 1

    try:
        context = run_interview(git_sha, surface_map=surface_map)
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
    p_estimate.add_argument("--language", choices=["python", "typescript", "java"], default="python", help=_LANGUAGE_HELP)
    p_estimate.add_argument("--pack", choices=["genai", "service"], default="genai", help=_PACK_HELP)
    p_estimate.set_defaults(func=cmd_estimate)

    p_map = sub.add_parser("map", help="S1 deterministic surface mapping (no LLM disambiguation yet)")
    p_map.add_argument("target", help="Path to the target repository")
    p_map.add_argument("-o", "--output", default=None, help="Write surface_map.json here instead of stdout")
    p_map.add_argument("--run-id", default=None, help="Resume this run_id if already checkpointed, else start it")
    p_map.add_argument("--no-disambiguate", action="store_true",
                        help="Skip the LLM disambiguation pass; leave ambiguous candidates unresolved")
    p_map.add_argument("--model", default=None, help=_MODEL_HELP)
    p_map.add_argument("--language", choices=["python", "typescript", "java"], default="python", help=_LANGUAGE_HELP)
    p_map.add_argument("--pack", choices=["genai", "service"], default="genai", help=_PACK_HELP)
    p_map.set_defaults(func=cmd_map)

    p_inventory = sub.add_parser("inventory", help="S2 existing telemetry inventory")
    p_inventory.add_argument("target", help="Path to the target repository")
    p_inventory.add_argument("-o", "--output", default=None, help="Write telemetry_inventory.json here instead of stdout")
    p_inventory.add_argument("--language", choices=["python", "typescript", "java"], default="python", help=_LANGUAGE_HELP)
    p_inventory.set_defaults(func=cmd_inventory)

    p_gaps = sub.add_parser("gaps", help="S3: join S1 x S2, classify coverage, weight priority by --context")
    p_gaps.add_argument("target", help="Path to the target repository")
    p_gaps.add_argument("-o", "--output", default=None, help="Write gap_model.json here instead of stdout")
    p_gaps.add_argument("--context", default=None,
                         help="Path to a context.yaml from `oah interview` — weights priority by workflow criticality")
    p_gaps.add_argument("--language", choices=["python", "typescript", "java"], default="python", help=_LANGUAGE_HELP)
    p_gaps.add_argument("--pack", choices=["genai", "service"], default="genai", help=_PACK_HELP)
    p_gaps.set_defaults(func=cmd_gaps)

    p_interview = sub.add_parser("interview", help="S3 owner interview (interactive) -> context.yaml")
    p_interview.add_argument("target", help="Path to the target repository")
    p_interview.add_argument("-o", "--output", default=None,
                              help="Write context.yaml here instead of stdout (never auto-written into the target repo)")
    p_interview.add_argument("--surface-map", default=None,
                              help="Path to an already-built surface_map.json (e.g. from `oah map -o`). When given, "
                                   "S1's own workflow_hint guesses are shown before the workflow questions "
                                   "(docs/decisions/034) -- naming a workflow with the exact same text is what makes "
                                   "`oah gaps --context` actually weight it; without this, a made-up name almost "
                                   "never matches.")
    p_interview.set_defaults(func=cmd_interview)

    p_design = sub.add_parser("design", help="S4 (all nine lenses) + S5 gates + S6 panel (all three personas)")
    p_design.add_argument("target", help="Path to the target repository")
    p_design.add_argument("-o", "--output", default=None, help="Write the design fragment + gate findings here instead of stdout")
    p_design.add_argument("--context", default=None, help="Path to a context.yaml from `oah interview`")
    p_design.add_argument("--model", default=None, help=_MODEL_HELP)
    p_design.add_argument("--language", choices=["python", "typescript", "java"], default="python", help=_LANGUAGE_HELP)
    p_design.add_argument("--pack", choices=["genai", "service"], default="genai", help=_PACK_HELP)
    p_design.set_defaults(func=cmd_design)

    p_event_schema = sub.add_parser("event-schema", help="S7 (partial): deterministic event_schema.json merge")
    p_event_schema.add_argument("target", help="Path to the target repository")
    p_event_schema.add_argument("--context", default=None, help="Path to a context.yaml from `oah interview`")
    p_event_schema.add_argument("-o", "--output", default=None, help="Write event_schema.json here instead of stdout")
    p_event_schema.add_argument("--model", default=None, help=_MODEL_HELP)
    p_event_schema.add_argument("--language", choices=["python", "typescript", "java"], default="python", help=_LANGUAGE_HELP)
    p_event_schema.add_argument("--pack", choices=["genai", "service"], default="genai", help=_PACK_HELP)
    p_event_schema.set_defaults(func=cmd_event_schema)

    p_dtos = sub.add_parser("dtos", help="S8 (partial): implementation_dto.json generation")
    p_dtos.add_argument("target", help="Path to the target repository")
    p_dtos.add_argument("--context", default=None,
                         help="Path to a context.yaml from `oah interview` -- enables real "
                              "workflow-criticality rollout_step ordering (architecture.md S7)")
    p_dtos.add_argument("-o", "--output", default=None, help="Write implementation_dto.json here instead of stdout")
    p_dtos.add_argument("--model", default=None, help=_MODEL_HELP)
    p_dtos.add_argument("--language", choices=["python", "typescript", "java"], default="python", help=_LANGUAGE_HELP)
    p_dtos.add_argument("--pack", choices=["genai", "service"], default="genai", help=_PACK_HELP)
    p_dtos.set_defaults(func=cmd_dtos)

    p_readiness = sub.add_parser("readiness", help="S9: production readiness report (deterministic assembly)")
    p_readiness.add_argument("target", help="Path to the target repository")
    p_readiness.add_argument("--context", default=None, help="Path to a context.yaml from `oah interview`")
    p_readiness.add_argument("-o", "--output", default=None, help="Write readiness_report.json here instead of stdout")
    p_readiness.add_argument("--save-intermediates", default=None,
                              help="Also write the S4-S8 detail behind this run's summary (design_fragments, "
                                   "gate_findings with their real per-point reasons, panel_verdicts, event_schema, "
                                   "dtos) to this path -- readiness_report.json's own recommendation only ever "
                                   "aggregates gate names and counts; this is the detail that's otherwise "
                                   "computed and silently discarded once S9 assembles its summary.")
    p_readiness.add_argument("--model", default=None, help=_MODEL_HELP)
    p_readiness.add_argument("--language", choices=["python", "typescript", "java"], default="python", help=_LANGUAGE_HELP)
    p_readiness.add_argument("--pack", choices=["genai", "service"], default="genai", help=_PACK_HELP)
    p_readiness.set_defaults(func=cmd_readiness)

    p_instrument = sub.add_parser(
        "instrument",
        help="S10: verify + apply 4 of 13 DTO change types (report-only diffs, or fix mode's real "
             "commit-per-DTO gated on an S9 ready/ready_with_conditions decision)",
    )
    p_instrument.add_argument("target", help="Path to the target repository")
    p_instrument.add_argument("--dtos", required=True, help="Path to an implementation_dto.json from `oah dtos`")
    p_instrument.add_argument("-o", "--output", default=None, help="Write instrument_report.json here instead of stdout")
    p_instrument.add_argument("--run-id", default=None, help="Resume this run_id if already checkpointed, else start it")
    p_instrument.add_argument("--mode", choices=["report-only", "fix"], default="report-only",
                               help="report-only (default): propose diffs, never write. fix: write + commit "
                                    "one DTO at a time, requires --readiness and a clean git working tree")
    p_instrument.add_argument("--readiness", default=None,
                               help="Path to a readiness_report.json from `oah readiness` -- required for "
                                    "--mode fix, whose recommendation.decision must be 'ready' or "
                                    "'ready_with_conditions' (architecture.md)")
    p_instrument.add_argument("--model", default=None, help=_AGENT_MODEL_HELP)
    p_instrument.add_argument("--language", choices=["python", "typescript", "java"], default="python",
                               help="Recorded on a freshly-created run manifest only (S10 itself runs no S1 "
                                    "adapter -- it applies an already-generated --dtos file). Matters only when "
                                    "--run-id doesn't resume an existing `oah map` manifest.")
    p_instrument.set_defaults(func=cmd_instrument)

    p_validate = sub.add_parser(
        "validate",
        help="S11, R4 only: static check that each applied DTO's expected attribute names appear in "
             "the code -- no product execution, verdict capped at needs_review",
    )
    p_validate.add_argument("target", help="Path to the target repository")
    p_validate.add_argument("--dtos", required=True, help="Path to an implementation_dto.json from `oah dtos`")
    p_validate.add_argument("--instrument-report", required=True,
                             help="Path to an instrument_report.json from `oah instrument --mode fix`")
    p_validate.add_argument("-o", "--output", default=None, help="Write validation_report.json here instead of stdout")
    p_validate.add_argument("--dynamic", action="store_true",
                             help="Also run the target's own test suite in an isolated Docker sandbox "
                                  "(E6 R2's mechanism) -- requires Docker. Adds a regression gate (a real "
                                  "test failure forces verdict=validation_failed) and per-DTO event_assertions "
                                  "(observed/not_observed against real captured OTel spans). Without this "
                                  "flag, behavior is unchanged (static-only). Does not change ladder_rung.")
    p_validate.add_argument("--live", action="store_true",
                             help="Also start the target as a real running service alongside a real local "
                                  "OTel collector (E6 R1's mechanism) and drive --requests against it -- "
                                  "requires Docker and --start-command/--port/--requests together. Reports "
                                  "real captured requests/latency/spans under live_execution. Does not change "
                                  "ladder_rung or verdict (R1's full promotion rule isn't built yet).")
    p_validate.add_argument("--start-command", default=None,
                             help="The target's own long-running server start command (required with --live)")
    p_validate.add_argument("--port", type=int, default=None,
                             help="Port the target's server listens on (required with --live)")
    p_validate.add_argument("--requests", default=None,
                             help="Path to a JSON file: a list of {\"method\", \"path\"} objects to drive "
                                  "against the running target (required with --live)")
    p_validate.add_argument("--event-schema", default=None,
                             help="Path to an event_schema.json from `oah event-schema` -- when given with "
                                  "--live, captured spans' attribute names are checked against it for unknown "
                                  "attributes; omit to skip that check (reported as not_attempted)")
    p_validate.add_argument("--setup-script", default=None,
                             help="Optional shell script run at image-build time (has network access) before "
                                  "--start-command runs, e.g. to install the target's own dependencies -- same "
                                  "role as sandbox.py's own setup_script. Unlike --dynamic's pytest_runner, "
                                  "--live has no built-in install-fallback ladder, so a target needing "
                                  "opentelemetry-api/-sdk (or its own dependencies) to even start needs this.")
    p_validate.add_argument("--baseline", action="store_true",
                             help="With --live, also run the target's own pre-instrumentation code (a real "
                                  "git worktree at --instrument-report's own repo_git_sha) through the same "
                                  "--start-command/--port/--requests, and report the real latency overhead vs. "
                                  "each applied DTO's declared estimated_overhead_ms budget under "
                                  "live_execution.overhead_vs_budget. Doubles the live-run cost/time -- opt-in "
                                  "on top of --live, not a default. Does not change ladder_rung.")
    p_validate.set_defaults(func=cmd_validate)

    p_backend_config = sub.add_parser(
        "backend-config",
        help="E9: generate an otel-collector-config.yaml for a chosen backend (otel-only or langfuse) -- "
             "deterministic, no LLM/agent call, --backend is a manual choice today",
    )
    p_backend_config.add_argument("target", help="Path to the target repository")
    p_backend_config.add_argument("--backend", required=True, choices=sorted(SUPPORTED_BACKENDS),
                                   help="Which backend target to generate config for")
    p_backend_config.add_argument("-o", "--output-dir", default=None,
                                   help="Write otel-collector-config.yaml into this directory instead of stdout")
    p_backend_config.set_defaults(func=cmd_backend_config)

    return parser


def main(argv=None):
    from oah.telemetry import setup_tracing
    setup_tracing()

    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
