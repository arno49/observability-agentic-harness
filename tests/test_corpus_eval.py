"""E7 corpus regression suite (ROADMAP.md E7's DoD: "eval runner scoring
skill recall/precision, regression suite in CI"). Runs S1's real detector
against the vendored corpus/ fixtures and asserts the M1 gate metric
directly, not a proxy for it — if this test fails, the gate's own claim is
false, not just "a test broke."
"""
import json

from oah.eval_corpus import score_corpus, CORPUS_DIR

M1_GATE_RECALL_TARGET = 0.90  # ROADMAP.md M1: "TCR-relevant call-site recall >= 90%"


def test_corpus_manifest_and_ground_truth_are_valid_json():
    manifest = json.loads((CORPUS_DIR / "manifest.json").read_text())
    assert len(manifest["fixtures"]) >= 3
    for fixture in manifest["fixtures"]:
        gt_path = CORPUS_DIR / fixture["id"] / "ground_truth.json"
        assert gt_path.is_file(), f"missing ground_truth.json for {fixture['id']}"
        data = json.loads(gt_path.read_text())
        assert len(data["points"]) >= 1


def test_deterministic_recall_meets_m1_gate_target():
    result = score_corpus()
    recall = result["summary"]["deterministic_recall"]
    assert recall is not None
    assert recall >= M1_GATE_RECALL_TARGET, (
        f"deterministic recall {recall:.1%} is below M1's {M1_GATE_RECALL_TARGET:.0%} gate target"
    )


def test_nothing_silently_dropped():
    """Distinct from the recall assertion above: a ground-truth site that
    isn't resolved must still show up in the ambiguous/disambiguation
    bucket, never simply absent from both."""
    result = score_corpus()
    assert result["summary"]["missed_entirely"] == 0, (
        f"points missed entirely (neither resolved nor flagged ambiguous): "
        f"{[f['missed'] for f in result['fixtures'] if f['missed']]}"
    )


def test_no_false_positives():
    result = score_corpus()
    assert result["summary"]["false_positives_total"] == 0, (
        f"false positives: {[f['false_positives'] for f in result['fixtures'] if f['false_positives']]}"
    )


def test_per_fixture_no_regressions():
    """Per-fixture, not just aggregate — a regression hiding inside one
    fixture could be masked by the other two staying perfect."""
    result = score_corpus()
    for fixture in result["fixtures"]:
        assert fixture["missed"] == [], f"{fixture['fixture_id']}: missed {fixture['missed']}"
        assert fixture["false_positives"] == [], f"{fixture['fixture_id']}: false positives {fixture['false_positives']}"


def test_examcopilot_factory_function_case_lands_in_ambiguous_not_missed():
    """Names the specific known hard case (corpus/examcopilot/ground_truth.json
    gt-0002) so a future change that accidentally starts silently dropping
    it (rather than correctly routing it to disambiguation) fails loudly,
    distinct from the aggregate coverage check above."""
    fixture = next(f for f in score_corpus()["fixtures"] if f["fixture_id"] == "examcopilot")
    assert fixture["resolved_hits"] == 1  # tasks.py:48, the direct case
    assert fixture["ambiguous_hits"] == 1  # views.py:298, the factory-function case
    assert fixture["missed"] == []
