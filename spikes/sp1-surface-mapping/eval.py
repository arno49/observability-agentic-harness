#!/usr/bin/env python3
"""Score detect.py against the hand-labeled ground truth.

Usage:
    python3 eval.py --corpus-dir /path/to/dir/containing/naive-memory,beacon,claude-engineer

Each repo under --corpus-dir must be checked out at the commit pinned in
ground_truth/corpus_manifest.json (see that file / README.md for clone
instructions — source is not vendored into this repo).
"""
import argparse
import json
from pathlib import Path

from detect import detect_path

HERE = Path(__file__).parent


def load_ground_truth(repo_id):
    data = json.loads((HERE / "ground_truth" / f"{repo_id}.json").read_text())
    return {(s["file"], s["line"]) for s in data["sites"]}


def score_repo(repo_id, repo_path):
    truth = load_ground_truth(repo_id)
    found_high = set()
    found_low = set()
    for candidate in detect_path(repo_path):
        rel = str(Path(candidate["file"]).relative_to(repo_path))
        key = (rel, candidate["line"])
        if candidate["confidence"] == "high":
            found_high.add(key)
        else:
            found_low.add(key)

    hit_high = truth & found_high
    hit_low = truth & found_low
    missed = truth - found_high - found_low
    false_positives_high = found_high - truth

    return {
        "repo_id": repo_id,
        "truth_count": len(truth),
        "found_high_confidence": len(hit_high),
        "found_low_confidence_needs_llm": len(hit_low),
        "missed_entirely": sorted(missed),
        "false_positives_at_high_confidence": sorted(false_positives_high),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus-dir", required=True, type=Path)
    args = parser.parse_args()

    manifest = json.loads((HERE / "ground_truth" / "corpus_manifest.json").read_text())
    total_truth = 0
    total_high = 0
    total_low = 0
    total_missed = 0
    total_fp = 0

    for repo in manifest["repos"]:
        repo_path = args.corpus_dir / repo["id"]
        if not repo_path.exists():
            print(f"SKIP {repo['id']}: not found at {repo_path}")
            continue
        result = score_repo(repo["id"], repo_path)
        total_truth += result["truth_count"]
        total_high += result["found_high_confidence"]
        total_low += result["found_low_confidence_needs_llm"]
        total_missed += len(result["missed_entirely"])
        total_fp += len(result["false_positives_at_high_confidence"])
        print(json.dumps(result, indent=2))

    recall_high_only = total_high / total_truth if total_truth else 0
    recall_high_or_flagged = (total_high + total_low) / total_truth if total_truth else 0
    print("\n--- TOTALS ---")
    print(f"ground truth sites: {total_truth}")
    print(f"found at high confidence: {total_high}  (recall: {recall_high_only:.1%})")
    print(f"found but only low-confidence (needs LLM pass): {total_low}")
    print(f"recall including low-confidence flags (nothing silently dropped): {recall_high_or_flagged:.1%}")
    print(f"missed entirely (not reported at any confidence): {total_missed}")
    print(f"false positives at high confidence: {total_fp}")


if __name__ == "__main__":
    main()
