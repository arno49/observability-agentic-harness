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


def load_ground_truth(gt_dir, repo_id):
    data = json.loads((gt_dir / f"{repo_id}.json").read_text())
    return {(s["file"], s["line"]) for s in data["sites"]}


def score_repo(gt_dir, repo_id, repo_path, language):
    truth = load_ground_truth(gt_dir, repo_id)
    found_high, found_low = set(), set()
    for candidate in detect(repo_path, language=language):
        rel = str(Path(candidate["file"]).relative_to(repo_path))
        key = (rel, candidate["line"])
        (found_high if candidate["confidence"] == "high" else found_low).add(key)

    return {
        "repo_id": repo_id,
        "language": language,
        "truth_count": len(truth),
        "found_high_confidence": len(truth & found_high),
        "found_low_confidence": len(truth & found_low),
        "missed_entirely": sorted(truth - found_high - found_low),
        "false_positives_at_high_confidence": sorted(found_high - truth),
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
