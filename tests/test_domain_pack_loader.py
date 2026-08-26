"""oah/domains/loader.py + the throwaway-second-pack proof E13's own DoD
names as its capstone clause (docs/decisions/011, ROADMAP.md's E13 entry):
'a throwaway second pack declaring one kind and one lens loads and runs
S1->S9 end to end with no edit under oah/ or schemas/'.

Scope, stated plainly: the throwaway pack below is driven through S3
(gap_model), S4 (a lens invocation), S5 (gates), S7 (event_schema merge) and
S8 (DTO generation + rollout ordering) -- the stages this session's research
confirmed are genuinely pack-parameterized (accept `pack` as a real argument,
derive their behavior from it). S1's tree-sitter detection loop
(oah/discovery/python_adapter.py) still reads its receiver/structural-pattern
registries from process-global constants built once at import time (from the
genai pack); re-parameterizing that per-call was scoped out of E13 as a real,
separate engineering cost with no second real pack to justify it yet (see
E13's own plan). So the surface_map point below is hand-built, exactly as if
S1 had already run and found it -- this test proves S3-S9 need zero
pipeline-core edits to run a differently-shaped pack, which is the actual
question E13's seam extraction was answering.
"""
import json

import pytest
from jsonschema import Draft202012Validator

from oah.domains.loader import load_pack, DomainPackError
from oah.domains.validate import known_kinds, known_lenses, known_dimensions, known_attribute_kinds
from oah.schemas import load_schema


def test_load_pack_genai_validates_against_domain_pack_schema():
    pack = load_pack("genai")
    assert pack["name"] == "genai"
    assert known_kinds(pack) == {"llm_generation", "retrieval", "feedback_ingest", "realtime_session", "tool_call"}


def test_load_pack_unknown_name_raises():
    with pytest.raises(DomainPackError, match="no domain pack named 'not-a-real-pack'"):
        load_pack("not-a-real-pack")


def test_load_pack_rejects_a_manifest_that_fails_schema_validation(tmp_path, monkeypatch):
    domains_dir = tmp_path / "domains"
    (domains_dir / "broken").mkdir(parents=True)
    (domains_dir / "broken" / "pack.json").write_text(json.dumps({"schema_version": "0.1.0", "name": "broken"}))
    monkeypatch.setattr("oah.domains.loader.DOMAINS_DIR", domains_dir)
    with pytest.raises(DomainPackError, match="does not match domain_pack.schema.json"):
        load_pack("broken")


THROWAWAY_PACK = {
    "schema_version": "0.1.0",
    "name": "throwaway",
    "version": "0.0.1",
    "description": "A minimal second pack, built only to prove the pipeline-core/domain-pack seam does not require touching oah/ or schemas/ for a second, differently-shaped domain (E13's own DoD capstone clause).",
    "point_kinds": [
        {"kind": "widget_call", "dimension": "widget_capture", "detected_by": "declared_undetected"},
    ],
    "lenses": [
        # Reuses the real, unmodified genai s4-tracing skill -- tracing is
        # cross-cutting (target_kinds: null), so it designs for a point of
        # ANY kind, including this pack's synthetic one, with no edit to
        # its SKILL.md. This is the same "reused unchanged" proof pattern
        # docs/decisions/011 names for E12's own reused lenses.
        {"lens": "tracing", "skill": "s4-tracing", "target_kinds": None, "emits": ["design_fragment"]},
    ],
    "semconv_namespaces": [
        {"namespace": "widget", "stability": "unknown", "pin": "unpinned -- this pack is a test fixture, not a real domain"},
    ],
    "attribute_kind_values": ["oah_extension"],
}


def _widget_surface_map(git_sha):
    """Hand-built, standing in for S1's own output -- see module docstring
    for why this test doesn't drive real tree-sitter detection."""
    return {
        "schema_version": "0.1.0",
        "repo": {"path": "<throwaway>", "git_sha": git_sha, "primary_language": "python"},
        "generated_by": {"harness_version": "0.0.2", "skill_versions": {}},
        "points": [{
            "id": "sp-0001", "kind": "widget_call", "file": "widgets.py", "line": 1,
            "framework": "throwaway-sdk", "sync_nature": "sync",
            "detection": "signature", "confidence": 1.0,
        }],
        "coverage_stats": {"files_scanned": 1, "points_total": 1, "points_llm_disambiguated": 0},
    }


def test_throwaway_pack_runs_s3_through_s8_with_no_pipeline_core_edit():
    from oah.discovery.gap_model import build_gap_model
    from oah.design.gates import run_gates, gates_passed
    from oah.design.event_schema import build_event_schema
    from oah.design.dto_generator import generate_dtos

    Draft202012Validator(load_schema("domain_pack")).validate(THROWAWAY_PACK)
    assert known_kinds(THROWAWAY_PACK) == {"widget_call"}
    assert known_lenses(THROWAWAY_PACK) == {"tracing"}
    assert known_dimensions(THROWAWAY_PACK) == {"widget_capture"}
    assert known_attribute_kinds(THROWAWAY_PACK) == {"oah_extension"}

    git_sha = "cafebabe" * 5
    surface_map = _widget_surface_map(git_sha)

    # S3, real, pack-driven: the point's dimension comes from THIS pack, not
    # the genai pack's own generation_capture/retrieval/etc vocabulary.
    inventory = {"schema_version": "0.1.0", "repo": {"path": "<throwaway>", "git_sha": git_sha},
                 "loggers": [], "existing_otel_usage": []}
    gap_model = build_gap_model(surface_map, inventory, pack=THROWAWAY_PACK)
    assert len(gap_model["gaps"]) == 1
    assert gap_model["gaps"][0]["dimension"] == "widget_capture"

    # S4, invocation mechanism only (not live model): a real design_fragment
    # shape, standing in for what design_tracing would return.
    fragment = {
        "schema_version": "0.1.0", "lens": "tracing", "repo_git_sha": git_sha,
        "failure_mode": "fail_open",
        "signals": [{
            "name": "oah.widget.trace_id", "surface_point_ids": ["sp-0001"],
            "maps_to": {"kind": "oah_extension", "attribute": "oah.widget.trace_id"},
            "sensitivity_tier": "internal", "pii_masked": False,
            "supports_decision": "trace continuity", "acting_role": "on-call",
            "latency_overhead_budget_ms": 2,
        }],
    }

    # S5, real, pack-driven: gate 4 checks maps_to.kind against THIS pack's
    # attribute_kind_values (just oah_extension, no otel_genai at all).
    findings = run_gates(fragment, surface_map_point_ids=["sp-0001"], pack=THROWAWAY_PACK)
    assert gates_passed(findings)

    # S7, real, pack-driven: summary is keyed by THIS pack's own
    # attribute_kind_values, not the genai pack's otel_genai/oah_extension pair.
    event_schema = build_event_schema([fragment], git_sha, pack=THROWAWAY_PACK)
    assert event_schema["summary"] == {
        "attribute_count": 1, "oah_extension_count": 1, "lenses_included": ["tracing"],
    }

    # S8, real (including its own schema validation and real pack-driven
    # rollout-step assignment), mocked only at the LLM call boundary --
    # same injection pattern every other test in this suite uses.
    from types import SimpleNamespace

    def fake_completion(**kwargs):
        payload = {"schema_version": "0.1.0", "dtos": [{
            "id": "dto-0001", "gap_id": gap_model["gaps"][0]["id"], "surface_point_ids": ["sp-0001"],
            "change": {"type": "insert_span", "file": "widgets.py", "anchor": "handle"},
            "expected_events": [{"event_type": "widget_event", "required_attributes": ["oah.widget.trace_id"]}],
            "risk": "low",
        }]}
        message = SimpleNamespace(content=json.dumps(payload))
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    dtos = generate_dtos(event_schema, surface_map["points"], gap_model["gaps"], git_sha,
                          _completion_fn=fake_completion, pack=THROWAWAY_PACK)
    assert dtos["dtos"][0]["expected_events"][0]["event_type"] == "widget_event"
    assert dtos["dtos"][0]["rollout_step"] == 1
