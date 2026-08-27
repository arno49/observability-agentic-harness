#!/usr/bin/env python3
"""Score both language adapters against their ground truth through the SAME
scoring code — the point being that this file does not need to know or care
which language it's scoring; only orchestrate.py's per-adapter detect() call
differs.

Usage:
    python3 eval.py --python-corpus-dir <dir-with-3-python-repos> \
                     --ts-corpus-dir <dir-with-3-ts-repos>

Repos must be checked out at the commits pinned in the two
ground_truth/corpus_manifest.json files (SP1's for Python, SP10's for TS).
"""
import argparse
import json
from pathlib import Path

from orchestrate import detect

HERE = Path(__file__).parent
SP1_GT = HERE.parent / "sp1-surface-mapping" / "ground_truth"
SP10_GT = HERE / "ground_truth"


_DEFAULT_SHAPE = "receiver_method_suffix"  # every ground-truth site before SP12 tested only this shape


def load_ground_truth(gt_dir, repo_id):
    data = json.loads((gt_dir / f"{repo_id}.json").read_text())
    return {(s["file"], s["line"]): s.get("shape", _DEFAULT_SHAPE) for s in data["sites"]}


def score_repo(gt_dir, repo_id, repo_path, language):
    truth_by_key = load_ground_truth(gt_dir, repo_id)
    truth = set(truth_by_key)
    found_high, found_low = set(), set()
    found_shape_by_key = {}
    for candidate in detect(repo_path, language=language):
        rel = str(Path(candidate["file"]).relative_to(repo_path))
        key = (rel, candidate["line"])
        (found_high if candidate["confidence"] == "high" else found_low).add(key)
        found_shape_by_key[key] = candidate.get("shape", _DEFAULT_SHAPE)

    missed = truth - found_high - found_low
    false_positives = found_high - truth

    # Shape-aware breakdown (SP12, docs/decisions/013): a pooled number can
    # hide one weak shape inside two strong ones -- report each shape's own
    # recall/FP separately, not just the combined total below.
    shapes = sorted({*truth_by_key.values(), *found_shape_by_key.values()})
    by_shape = {}
    for shape in shapes:
        shape_truth = {k for k, s in truth_by_key.items() if s == shape}
        shape_found_high = {k for k in found_high if found_shape_by_key.get(k) == shape}
        by_shape[shape] = {
            "truth_count": len(shape_truth),
            "found_high_confidence": len(shape_truth & shape_found_high),
            "missed_entirely": sorted(shape_truth - found_high - found_low),
            "false_positives_at_high_confidence": sorted(
                k for k in false_positives if found_shape_by_key.get(k) == shape
            ),
        }

    return {
        "repo_id": repo_id,
        "language": language,
        "truth_count": len(truth),
        "found_high_confidence": len(truth & found_high),
        "found_low_confidence": len(truth & found_low),
        "missed_entirely": sorted(missed),
        "false_positives_at_high_confidence": sorted(false_positives),
        "by_shape": by_shape,
    }


def run_corpus(gt_dir, corpus_dir, language):
    manifest = json.loads((gt_dir / "corpus_manifest.json").read_text())
    results = []
    for repo in manifest["repos"]:
        repo_path = corpus_dir / repo["id"]
        if not repo_path.exists():
            print(f"SKIP {repo['id']}: not found at {repo_path}")
            continue
        result = score_repo(gt_dir, repo["id"], repo_path, language)
        results.append(result)
        print(json.dumps(result, indent=2))
    return results


def summarize(label, results):
    truth = sum(r["truth_count"] for r in results)
    high = sum(r["found_high_confidence"] for r in results)
    low = sum(r["found_low_confidence"] for r in results)
    missed = sum(len(r["missed_entirely"]) for r in results)
    fp = sum(len(r["false_positives_at_high_confidence"]) for r in results)
    recall = high / truth if truth else 0
    print(f"\n--- {label} ---")
    print(f"ground truth: {truth}, high-confidence recall: {high}/{truth} ({recall:.1%}), "
          f"low-confidence: {low}, missed: {missed}, false positives: {fp}")

    # Per-shape breakdown (SP12): a pooled number can hide one weak shape
    # inside two strong ones.
    shapes = sorted({shape for r in results for shape in r.get("by_shape", {})})
    for shape in shapes:
        s_truth = sum(r["by_shape"][shape]["truth_count"] for r in results if shape in r.get("by_shape", {}))
        s_high = sum(r["by_shape"][shape]["found_high_confidence"] for r in results if shape in r.get("by_shape", {}))
        s_missed = sum(len(r["by_shape"][shape]["missed_entirely"]) for r in results if shape in r.get("by_shape", {}))
        s_fp = sum(len(r["by_shape"][shape]["false_positives_at_high_confidence"]) for r in results if shape in r.get("by_shape", {}))
        s_recall = s_high / s_truth if s_truth else 0
        print(f"  [{shape}] ground truth: {s_truth}, high-confidence recall: {s_high}/{s_truth} "
              f"({s_recall:.1%}), missed: {s_missed}, false positives: {s_fp}")

    return {"truth": truth, "high": high, "low": low, "missed": missed, "fp": fp}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--python-corpus-dir", type=Path)
    parser.add_argument("--ts-corpus-dir", type=Path)
    args = parser.parse_args()

    py_results, ts_results = [], []
    if args.python_corpus_dir:
        py_results = run_corpus(SP1_GT, args.python_corpus_dir, "python")
        summarize("PYTHON", py_results)
    if args.ts_corpus_dir:
        ts_results = run_corpus(SP10_GT, args.ts_corpus_dir, "typescript")
        summarize("TYPESCRIPT", ts_results)

    if py_results and ts_results:
        summarize("COMBINED (both languages, one scoring path)", py_results + ts_results)


if __name__ == "__main__":
    main()
