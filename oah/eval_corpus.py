"""E7 corpus eval runner: scores S1's deterministic pass against corpus/
fixtures' hand-labeled ground truth (ROADMAP.md E7's DoD: "eval runner
scoring skill recall/precision, regression suite in CI").

Two-tier recall, not one number, for the same reason SP1's spike
(spikes/sp1-surface-mapping/eval.py) reported it that way: a ground-truth
site that lands in the LLM-disambiguation bucket rather than being resolved
directly isn't a miss (nothing was silently dropped) — but it also isn't
resolved without a live model call, which this eval, run without network
access, can't make. `deterministic_recall` is what M1's gate metric
actually measures; `coverage_rate` is the honest ceiling once
disambiguation runs.
"""
import json
from pathlib import Path

from oah.discovery.python_adapter import detect_repo

CORPUS_DIR = Path(__file__).parent.parent / "corpus"


def load_ground_truth(fixture_id):
    data = json.loads((CORPUS_DIR / fixture_id / "ground_truth.json").read_text())
    return data["points"]


def score_fixture(fixture_id):
    truth = load_ground_truth(fixture_id)
    truth_keys = {(p["file"], p["line"]) for p in truth}

    fixture_path = CORPUS_DIR / fixture_id
    resolved, ambiguous = detect_repo(fixture_path)
    resolved_keys = {(p["file"], p["line"]) for p in resolved}
    ambiguous_keys = {(c["file"], c["line"]) for c in ambiguous}

    return {
        "fixture_id": fixture_id,
        "truth_count": len(truth_keys),
        "resolved_hits": len(truth_keys & resolved_keys),
        "ambiguous_hits": len(truth_keys & ambiguous_keys),
        "missed": sorted(truth_keys - resolved_keys - ambiguous_keys),
        "false_positives": sorted(resolved_keys - truth_keys),
    }


def score_corpus(fixture_ids=None):
    manifest = json.loads((CORPUS_DIR / "manifest.json").read_text())
    ids = fixture_ids or [f["id"] for f in manifest["fixtures"]]
    results = [score_fixture(fid) for fid in ids]

    total_truth = sum(r["truth_count"] for r in results)
    total_resolved = sum(r["resolved_hits"] for r in results)
    total_ambiguous = sum(r["ambiguous_hits"] for r in results)
    total_missed = sum(len(r["missed"]) for r in results)
    total_fp = sum(len(r["false_positives"]) for r in results)

    return {
        "fixtures": results,
        "summary": {
            "truth_count": total_truth,
            "deterministic_recall": round(total_resolved / total_truth, 4) if total_truth else None,
            "coverage_rate": round((total_resolved + total_ambiguous) / total_truth, 4) if total_truth else None,
            "missed_entirely": total_missed,
            "false_positives_total": total_fp,
        },
    }


if __name__ == "__main__":
    import sys
    result = score_corpus()
    print(json.dumps(result, indent=2))
    if result["summary"]["missed_entirely"] or result["summary"]["false_positives_total"]:
        sys.exit(1)
