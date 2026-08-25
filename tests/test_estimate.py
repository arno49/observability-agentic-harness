"""Regression test for oah.estimate — pins the formula to the exact numbers
worked out by hand in docs/decisions/002-sp5-cost-model.md, so a future
change to the formula or constants has to be a deliberate, reviewed change,
not a silent drift."""
from oah.estimate import estimate, load_constants, _cost


def test_s4_matches_decision_record_worked_example():
    """SP5's decision record hand-calculates S4 (8 lenses, 1 cached write +
    7 cached reads) at $0.278 for its worked example's constants. Same
    constants, same formula here should reproduce that exactly."""
    constants = load_constants()
    pricing = constants["pricing"]
    units = constants["per_unit_tokens"]
    shared = units["s4_shared_context_tokens"]
    lens_in, lens_out = units["s4_lens_specific_in"], units["s4_lens_specific_out"]
    write = shared * pricing["cache_write_1h_per_token"] + _cost(lens_in, lens_out, pricing)
    reads = 7 * (shared * pricing["cache_read_per_token"] + _cost(lens_in, lens_out, pricing))
    assert round(write + reads, 3) == 0.278


def test_estimate_zero_candidates_is_free_except_synthesis(tmp_path):
    (tmp_path / "empty.py").write_text("x = 1\n")
    result = estimate(tmp_path)
    assert result["driver_counts"]["candidate_call_sites"] == 0
    assert result["per_stage_usd"]["s1"] == 0.0
    assert result["per_stage_usd"]["s8"] == 0.0
    assert result["per_stage_usd"]["s10"] == 0.0
    # S7 (one synthesis call) and S11 (min 1 scenario) still run regardless of surface-point count.
    assert result["per_stage_usd"]["s7"] > 0
    assert result["calibrated"] is False


def test_estimate_workflows_assumed_flag(tmp_path):
    (tmp_path / "app.py").write_text("import anthropic\nc = anthropic.Anthropic()\n")
    default = estimate(tmp_path)
    assert default["driver_counts"]["workflows_assumed"] is True

    explicit = estimate(tmp_path, workflows=5)
    assert explicit["driver_counts"]["workflows_assumed"] is False
    assert explicit["driver_counts"]["workflows"] == 5
