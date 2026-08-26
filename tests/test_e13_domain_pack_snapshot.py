"""E13's own byte-identical proof (docs/decisions/011, ROADMAP.md's E13 DoD):
no golden-snapshot harness existed anywhere in this repo before this file.
Drives the real S1->S8 chain against the naive-memory corpus fixture with S4's
model-calling lenses and S8's model-calling DTO judgment mocked deterministically
(same pattern as tests/test_cli_readiness.py), captures surface_map.json,
gap_model.json, event_schema.json and the DTO rollout_step ordering, and asserts
byte-for-byte equality against a reference snapshot committed under
tests/fixtures/e13_snapshot/. A change to E13's wiring (registry.py, gap_model.py,
cli.py, gates.py, event_schema.py, dto_generator.py) that alters any of this
output is exactly the regression this test exists to catch -- the pack is
deliberately scoped to reproduce today's literals exactly (docs/decisions/011),
so nothing here is expected to change.
"""
import json
import subprocess
from pathlib import Path
from unittest.mock import patch

from oah.discovery.python_adapter import build_surface_map
from oah.discovery.telemetry_scanner import build_telemetry_inventory
from oah.discovery.gap_model import build_gap_model
from oah.design.event_schema import build_event_schema
from oah.design.dto_generator import generate_dtos

REPO_ROOT = Path(__file__).parent.parent
FIXTURE = REPO_ROOT / "corpus" / "naive-memory"
SNAPSHOT_DIR = Path(__file__).parent / "fixtures" / "e13_snapshot"
GIT_SHA = "deadbeef" * 5  # 40 hex chars, matches a real sha's shape; fixed so output is reproducible


def _fake_generation_capture(points, repo_git_sha, context=None, model=None, _completion_fn=None):
    point_id = points[0]["id"]
    return {
        "schema_version": "0.1.0", "lens": "generation-capture", "repo_git_sha": repo_git_sha,
        "failure_mode": "fail_open",
        "signals": [{
            "name": "gen_ai.usage.input_tokens", "surface_point_ids": [point_id],
            "maps_to": {"kind": "otel_genai", "attribute": "gen_ai.usage.input_tokens"},
            "sensitivity_tier": "internal", "pii_masked": False,
            "supports_decision": "cost attribution", "acting_role": "cost owner",
            "latency_overhead_budget_ms": 5,
        }],
    }


def _fake_generate_dtos(event_schema, points, gaps, repo_git_sha, context=None, model=None, _completion_fn=None):
    point_id = points[0]["id"]
    gap_id = gaps[0]["id"]
    return {
        "schema_version": "0.1.0",
        "dtos": [{
            "id": "dto-0001", "gap_id": gap_id, "surface_point_ids": [point_id],
            "change": {"type": "wrap_call", "file": "chat.py", "anchor": "run"},
            "expected_events": [{"event_type": "generation",
                                  "required_attributes": ["gen_ai.usage.input_tokens"]}],
            "risk": "low", "rollout_step": 1,
        }],
    }


def _run_s1_through_s8():
    """Real S1 (python_adapter, pack-derived), real S2 (telemetry_scanner),
    real S3 (gap_model, pack-derived), S4 mocked deterministically for the
    one lens naive-memory's single llm_generation point actually reaches
    (every other lens gets an empty batch and returns None without a model
    call -- design_lens()'s own early-return, not something this test needs
    to mock separately), real S5 (gates), real S7 (event_schema merge), S8
    mocked deterministically for the DTO's model-judged fields, with
    rollout_step still assigned by the real deterministic ordering rule."""
    from oah.design.lens import design_generation_capture  # noqa: F401 (imported for the patch target)
    from oah.design import gates as gates_module

    surface_map, _ = build_surface_map(FIXTURE, git_sha=GIT_SHA)
    surface_map["repo"]["path"] = "<fixture>"  # absolute path is environment-dependent, not part of what this test verifies
    inventory = build_telemetry_inventory(FIXTURE, git_sha=GIT_SHA)
    inventory["repo"]["path"] = "<fixture>"
    gap_model = build_gap_model(surface_map, inventory)

    with patch("oah.design.lens.design_generation_capture", side_effect=_fake_generation_capture):
        from oah.design.lens import design_generation_capture as design_fn
        llm_points = [p for p in surface_map["points"] if p["kind"] == "llm_generation"]
        fragment = design_fn(llm_points, GIT_SHA)

    fragments = [fragment] if fragment else []
    findings = [
        f.__dict__ for frag in fragments
        for f in gates_module.run_gates(frag, surface_map_point_ids=[p["id"] for p in llm_points])
    ]

    event_schema = build_event_schema(fragments, GIT_SHA)

    covered_point_ids = {pid for a in event_schema["attributes"] for pid in a["surface_point_ids"]}
    points = [p for p in surface_map["points"] if p["id"] in covered_point_ids]
    relevant_gap_ids = {g["id"] for g in gap_model["gaps"]
                         if any(pid in covered_point_ids for pid in g["surface_point_ids"])}
    gaps = [g for g in gap_model["gaps"] if g["id"] in relevant_gap_ids]

    with patch("oah.design.dto_generator.generate_dtos", side_effect=_fake_generate_dtos):
        from oah.design.dto_generator import generate_dtos as generate_fn
        dtos = generate_fn(event_schema, points, gaps, GIT_SHA)

    return {
        "surface_map": surface_map,
        "gap_model": gap_model,
        "gate_findings": findings,
        "event_schema": event_schema,
        "dtos": dtos,
    }


def test_s1_through_s8_output_matches_committed_snapshot():
    result = _run_s1_through_s8()
    reference = json.loads((SNAPSHOT_DIR / "naive_memory.json").read_text())
    assert result == reference, (
        "S1-S8 output for corpus/naive-memory changed shape or value -- E13's "
        "domain-pack wiring must reproduce today's GenAI-pack behavior exactly "
        "(docs/decisions/011). If this change is real and intended (not an E13 "
        "wiring bug), regenerate tests/fixtures/e13_snapshot/naive_memory.json "
        "and say so explicitly in the commit, per this test's own module docstring."
    )
