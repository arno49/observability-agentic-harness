"""`oah estimate` — two-phase cost prediction per docs/decisions/002-sp5-cost-model.md.

Phase 1: a free, deterministic pre-scan (S1's own detector, in scan-only
mode) yields the real driver counts (C, A) instead of guessing them from
LOC. Phase 2: a per-stage formula over those counts, using constants from
estimate_constants.json — versioned, not hardcoded, so real run data can
overwrite them later (the recalibration protocol that decision record
specifies).

Explicitly NOT calibrated: every constant is a first-pass assumption from
architecture.md's stage descriptions, not measured token usage. Say so in
the output, not just in a docstring nobody reading `oah estimate`'s output
will see.
"""
import json
import math
from pathlib import Path

CONSTANTS_PATH = Path(__file__).parent / "estimate_constants.json"


def load_constants():
    return json.loads(CONSTANTS_PATH.read_text())


def _cost(input_tokens, output_tokens, pricing):
    return input_tokens * pricing["base_input_per_token"] + output_tokens * pricing["output_per_token"]


def _detect_counts(repo_path, language, pack):
    """Phase 1's own S1 dispatch, mirroring oah/cli.py's _build_surface_map
    (docs/decisions/035): found by a real target-repo assessment that
    `estimate()` had ALWAYS hardcoded the Python adapter, with no
    --language at all -- a TypeScript/Java target silently got
    `candidate_call_sites: 0` (an empty rglob over the wrong file
    extension), not an error, making every stage's cost estimate wrong by
    construction rather than honestly absent. python_adapter.detect_repo
    returns (resolved, ambiguous) -- the only adapter with an LLM
    disambiguation counterpart; typescript_adapter/java_adapter.detect_repo
    return a plain resolved list (E11-TS/E11-Java's own stated scope
    boundary: neither has ever produced an ambiguous candidate), normalized
    here to the same 2-tuple shape so every caller below is unchanged."""
    if language == "typescript":
        from oah.discovery.typescript_adapter import detect_repo
        return detect_repo(repo_path, pack=pack), []
    if language == "java":
        from oah.discovery.java_adapter import detect_repo
        return detect_repo(repo_path, pack=pack), []
    from oah.discovery.python_adapter import detect_repo
    return detect_repo(repo_path)


def estimate(repo_path, workflows=None, constants=None, language="python", pack=None):
    """Returns a dict: per-stage cost breakdown, total, +-40% range, and the
    driver counts the formula actually ran on (so the caller can see what
    was measured vs. assumed). `language`/`pack` (defaults byte-identical
    to every caller before docs/decisions/035) select which S1 adapter the
    free phase-1 pre-scan runs -- python by default, matching every
    pre-existing caller exactly."""
    constants = constants or load_constants()
    pricing = constants["pricing"]
    units = constants["per_unit_tokens"]
    batching = constants["batching"]
    fixed = constants["fixed_counts"]
    ratios = constants["derived_ratios"]

    # Phase 1: free pre-scan (S1's own detector, scan-only).
    resolved, ambiguous = _detect_counts(repo_path, language, pack)
    C = len(resolved) + len(ambiguous)
    A = len(ambiguous)
    P = C
    W = workflows if workflows is not None else fixed["default_workflows_if_unknown"]
    D = max(1, round(P * ratios["dtos_per_surface_point"])) if P else 0
    N_scenario = max(1, W)

    per_stage = {}

    # S1: AST pass is free; only disambiguation costs.
    if A > 0:
        n_batches = math.ceil(A / batching["s1_batch_size"])
        s1_in = n_batches * units["s1_batch_overhead_in"] + A * units["s1_per_candidate_in"]
        s1_out = A * units["s1_per_candidate_out"]
        per_stage["s1"] = _cost(s1_in, s1_out, pricing)
    else:
        per_stage["s1"] = 0.0

    # S2: assumed comparable to S1 per the decision record (no S2 skill yet
    # to measure independently -- see docs/decisions/009-sp8's own gap note).
    per_stage["s2"] = per_stage["s1"]

    # S3: one call, input scales with P (reference material + per-point),
    # output scales with G ~= P.
    if P > 0:
        s3_in = units["s3_reference_material_in"] + P * units["s3_per_point_in"]
        s3_out = P * units["s3_per_point_out"]
        per_stage["s3"] = _cost(s3_in, s3_out, pricing)
    else:
        per_stage["s3"] = 0.0

    # S4: 8 lens calls, shared context written once (1h cache), read by the
    # other 7 lenses + all S6 personas at the 0.1x hit rate.
    n_lens = fixed["n_lens"]
    shared = units["s4_shared_context_tokens"]
    lens_in, lens_out = units["s4_lens_specific_in"], units["s4_lens_specific_out"]
    s4_write = shared * pricing["cache_write_1h_per_token"] + _cost(lens_in, lens_out, pricing)
    s4_reads = (n_lens - 1) * (shared * pricing["cache_read_per_token"] + _cost(lens_in, lens_out, pricing))
    per_stage["s4"] = s4_write + s4_reads

    # S5: pure code, no LLM cost.
    per_stage["s5"] = 0.0

    # S6: personas read the S4-cached shared context.
    n_persona = fixed["n_persona"]
    persona_in, persona_out = units["s6_persona_specific_in"], units["s6_persona_specific_out"]
    per_stage["s6"] = n_persona * (shared * pricing["cache_read_per_token"] + _cost(persona_in, persona_out, pricing))

    # S7: one synthesis call.
    per_stage["s7"] = _cost(units["s7_in"], units["s7_out"], pricing)

    # S8: DTO generation, batched.
    if D > 0:
        n_batches = math.ceil(D / batching["s8_batch_size"])
        s8_in = n_batches * units["s8_batch_overhead_in"] + D * units["s8_per_dto_in"]
        s8_out = D * units["s8_per_dto_out"]
        per_stage["s8"] = _cost(s8_in, s8_out, pricing)
    else:
        per_stage["s8"] = 0.0

    # S9: deterministic assembly, ~$0.
    per_stage["s9"] = 0.0

    # S10: one agentic session per DTO.
    per_stage["s10"] = D * _cost(units["s10_per_dto_in"], units["s10_per_dto_out"], pricing)

    # S11: deterministic layer free; agentic panel per scenario.
    per_stage["s11"] = N_scenario * _cost(units["s11_per_scenario_in"], units["s11_per_scenario_out"], pricing)

    total = sum(per_stage.values())

    return {
        "constants_version": constants["constants_version"],
        "model_role_assumption": "uniform-frontier (Sonnet 5) -- SP8's default until light/frontier routing is designed",
        "driver_counts": {
            "candidate_call_sites": C,
            "ambiguous_candidates": A,
            "surface_points": P,
            "estimated_dtos": D,
            "workflows": W,
            "workflows_assumed": workflows is None,
            "scenarios": N_scenario,
        },
        "per_stage_usd": {k: round(v, 4) for k, v in per_stage.items()},
        "total_usd": round(total, 2),
        "range_usd_at_40pct": [round(total * 0.6, 2), round(total * 1.4, 2)],
        "calibrated": False,
        "calibration_note": (
            "Every per-unit constant is a first-pass assumption, not measured "
            "token usage -- see docs/decisions/002-sp5-cost-model.md's "
            "Consequences for the recalibration protocol via run_manifest.json."
        ),
    }
