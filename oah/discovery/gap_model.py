"""S3, deterministic half only: join S1 x S2, classify every surface point
dark/partial/covered, emit gap_model.json.

architecture.md's S3 also generates an owner interview and context.yaml —
genuinely interactive/human-in-the-loop pieces, not something a deterministic
join can produce. Building a fake interview flow just to claim "S3 done"
would violate the same principle oah/cli.py's own docstring states for
commands: not registering a half-built stage as if it were finished. This
module is explicitly the join-and-classify half; the interview half is a
separate, tracked piece of work, not silently skipped.

Without context.yaml, workflow criticality is unknown — gap_model.schema.json's
priority field still gets a value (a gap list with no priority isn't useful),
but priority_drivers correctly omits workflow_criticality/pii_exposure/etc.
since none of those are knowable yet, and priority itself is conservative
(coverage status alone, not the full criticality-weighted priority S3's
real design calls for once context.yaml exists).
"""
from pathlib import Path

PROXIMITY_LINES = 15  # a logger call site within this many lines of a
                       # surface point counts as "partial" coverage — a
                       # heuristic, not a claim the log line actually
                       # captures anything about that specific call.

# S1 currently only detects llm_generation kind (raw-Anthropic-SDK
# call sites) — the dimension mapping below is a single entry for that
# reason, not an oversight; extend as S1/S4's kind vocabulary grows.
KIND_TO_DIMENSION = {
    "llm_generation": "generation_capture",
}


def _nearby_logger(point, loggers_by_file):
    same_file = loggers_by_file.get(point["file"], [])
    return any(abs(l["line"] - point["line"]) <= PROXIMITY_LINES for l in same_file)


def _file_has_otel(point, otel_by_file):
    return point["file"] in otel_by_file


def classify_coverage(point, telemetry_inventory):
    """Returns (status, existing_telemetry_ids) for one surface_map point."""
    loggers_by_file = {}
    for l in telemetry_inventory.get("loggers", []):
        loggers_by_file.setdefault(l["file"], []).append(l)
    otel_by_file = set(o["file"] for o in telemetry_inventory.get("existing_otel_usage", []))

    if _file_has_otel(point, otel_by_file):
        return "partial", [o["id"] for o in telemetry_inventory["existing_otel_usage"] if o["file"] == point["file"]]
        # "partial" not "covered": file-level otel import presence doesn't
        # prove *this* call site is actually wrapped in a span — a stronger
        # claim needs call-site-level analysis this pass doesn't attempt.
    if _nearby_logger(point, loggers_by_file):
        nearby = [l for l in loggers_by_file.get(point["file"], [])
                  if abs(l["line"] - point["line"]) <= PROXIMITY_LINES]
        return "partial", [l["id"] for l in nearby]
    return "dark", []


def build_gap_model(surface_map, telemetry_inventory, harness_version="0.1.0"):
    gaps = []
    dark = partial = covered = 0

    for i, point in enumerate(surface_map["points"], start=1):
        dimension = KIND_TO_DIMENSION.get(point["kind"])
        if dimension is None:
            continue  # a kind with no known dimension mapping yet — not a gap this pass can classify

        status, existing_refs = classify_coverage(point, telemetry_inventory)
        if status == "dark":
            dark += 1
            priority = "p1"
        elif status == "partial":
            partial += 1
            priority = "p2"
        else:
            covered += 1
            priority = "p3"

        gap = {
            "id": f"gap-{i:04d}",
            "surface_point_ids": [point["id"]],
            "dimension": dimension,
            "status": status,
            "priority": priority,
            "rationale": (
                f"{point['kind']} call site at {point['file']}:{point['line']} is {status} for {dimension}"
                + (" — no existing OTel usage in file and no logger call within "
                   f"{PROXIMITY_LINES} lines" if status == "dark" else "")
                + (" — file has existing OTel usage; call-site-level coverage not yet verified"
                   if status == "partial" and any(r.startswith("otel-") for r in existing_refs) else "")
                + (" — a logger call exists nearby, but proximity is not proof of coverage"
                   if status == "partial" and existing_refs and not any(r.startswith("otel-") for r in existing_refs) else "")
            ),
        }
        if existing_refs:
            gap["existing_telemetry_refs"] = existing_refs
        gaps.append(gap)

    total = dark + partial + covered
    estimated_tcr = round(covered / total, 3) if total else None

    return {
        "schema_version": "0.1.0",
        "repo_git_sha": surface_map["repo"]["git_sha"],
        "gaps": gaps,
        "summary": {
            "dark_points": dark,
            "partial_points": partial,
            "covered_points": covered,
            "estimated_tcr_current": estimated_tcr,
        },
    }
