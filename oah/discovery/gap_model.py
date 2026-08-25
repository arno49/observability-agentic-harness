"""S3: join S1 x S2, classify every surface point dark/partial/covered,
weight priority by context.yaml's workflow criticality when a point's
workflow_hint matches an interviewed workflow, emit gap_model.json.

context.yaml (oah/interview.py) is optional here on purpose: this module
must produce a useful, honest gap list even before the interview has run
(coverage status alone), and must not fabricate a criticality-weighted
priority for a point whose workflow isn't actually known. A point only
gets weighted by criticality when its own workflow_hint (set by S1's LLM
disambiguation pass, per skills/s1-surface-mapper/SKILL.md — "best-effort
... S3 confirms with the owner") matches an interviewed workflow name; a
point with no hint, or a hint that matches nothing in context.yaml, keeps
the coverage-only baseline priority and correctly omits priority_drivers
rather than guessing.
"""
PROXIMITY_LINES = 15  # a logger call site within this many lines of a
                       # surface point counts as "partial" coverage — a
                       # heuristic, not a claim the log line actually
                       # captures anything about that specific call.

# S1 currently detects four surface_map point kinds (llm_generation,
# retrieval, feedback_ingest, realtime_session) -- the dimension mapping
# below has four entries for that reason, not an oversight; extend as
# S1/S4's kind vocabulary grows.
KIND_TO_DIMENSION = {
    "llm_generation": "generation_capture",
    "retrieval": "retrieval",
    "feedback_ingest": "feedback",
    "realtime_session": "realtime_multimodal",
}

# status -> criticality -> priority. p0 reserved for the most severe case
# (dark coverage on a workflow the owner called critical); a covered point
# never rises above p3 regardless of criticality — it's already covered.
_WEIGHTED_PRIORITY = {
    "dark": {"critical": "p0", "high": "p1", "medium": "p1", "low": "p2"},
    "partial": {"critical": "p1", "high": "p2", "medium": "p2", "low": "p3"},
    "covered": {"critical": "p3", "high": "p3", "medium": "p3", "low": "p3"},
}
_PRIORITY_ORDER = ["p0", "p1", "p2", "p3"]


def _bump_priority(priority, levels=1):
    idx = max(0, _PRIORITY_ORDER.index(priority) - levels)
    return _PRIORITY_ORDER[idx]


def _find_workflow(workflow_hint, context):
    if not workflow_hint or not context:
        return None
    hint = workflow_hint.strip().lower()
    for wf in context.get("workflows", []):
        if wf["name"].strip().lower() == hint:
            return wf
    return None


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


def build_gap_model(surface_map, telemetry_inventory, context=None, harness_version="0.1.0"):
    gaps = []
    dark = partial = covered = 0

    for i, point in enumerate(surface_map["points"], start=1):
        dimension = KIND_TO_DIMENSION.get(point["kind"])
        if dimension is None:
            continue  # a kind with no known dimension mapping yet — not a gap this pass can classify

        status, existing_refs = classify_coverage(point, telemetry_inventory)
        if status == "dark":
            dark += 1
        elif status == "partial":
            partial += 1
        else:
            covered += 1

        # Coverage-only baseline (matches the pre-context.yaml behavior
        # exactly, so a run without an interview still gets a useful,
        # honest priority — not a placeholder).
        priority = {"dark": "p1", "partial": "p2", "covered": "p3"}[status]
        priority_drivers = []

        workflow = _find_workflow(point.get("workflow_hint"), context)
        if workflow is not None:
            priority = _WEIGHTED_PRIORITY[status][workflow["criticality"]]
            priority_drivers.append("workflow_criticality")
            if status != "covered" and workflow.get("pii_presence") == "direct":
                priority = _bump_priority(priority)
                priority_drivers.append("pii_exposure")

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
                + (f" — workflow '{workflow['name']}' is {workflow['criticality']} criticality"
                   if workflow is not None else "")
                + (", direct PII present" if workflow is not None and workflow.get("pii_presence") == "direct" else "")
            ),
        }
        if existing_refs:
            gap["existing_telemetry_refs"] = existing_refs
        if priority_drivers:
            gap["priority_drivers"] = priority_drivers
        if workflow is not None:
            # Structured, not just baked into rationale prose -- S8's real
            # rollout ordering (architecture.md S7: "first workflow = most
            # critical one") needs to group gaps by workflow identity, not
            # re-parse it out of a free-text sentence.
            gap["workflow"] = workflow["name"]
        gaps.append(gap)

    total = dark + partial + covered
    estimated_tcr = round(covered / total, 3) if total else None

    result = {
        "schema_version": "0.1.0",
        "repo_git_sha": surface_map["repo"]["git_sha"],
        "gaps": gaps,
    }
    if context is not None:
        result["context_ref"] = f"context.yaml@{context.get('interviewed_at', 'unknown')}"
    result["summary"] = {
        "dark_points": dark,
        "partial_points": partial,
        "covered_points": covered,
        "estimated_tcr_current": estimated_tcr,
    }
    return result
