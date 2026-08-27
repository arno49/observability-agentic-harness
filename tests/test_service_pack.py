"""E12 phase 1 (docs/decisions/016): the service domain pack's three
reused-unchanged lenses (tracing, ops, pii-governance), the concrete test
of the pipeline-core/domain-pack split (docs/decisions/011's DoD (b) for
E12: "the three reused lenses run with no edit to their SKILL.md files").

Also the regression test for a real bug this effort found: every design_*
wrapper in oah/design/lens.py but design_tracing used to hardcode its own
point-kind filter literal (e.g. design_ops filtered to kind ==
"llm_generation") instead of reading it from the loaded pack's own
lenses[].target_kinds. genai's own behavior happened to keep working
because the pack was extracted from those exact literals in E13 -- but the
service pack's ops/pii-governance entries declare different target_kinds,
and the old code would have silently produced zero points and a None
fragment no matter what the manifest said. Fixed by moving all point-kind
filtering into oah/cli.py's _design_all_lenses, driven by pack data --
verified here against the REAL service pack, not a synthetic throwaway one
(unlike tests/test_domain_pack_loader.py's own second-pack proof)."""
import json
from types import SimpleNamespace

import pytest

from oah.cli import _design_all_lenses, _lens_fns_for_pack, _target_kinds_for_pack
from oah.design import lens as lens_module
from oah.design.lens import design_tracing, design_ops, design_pii_governance, LensDesignError
from oah.design.gates import run_gates, gates_passed
from oah.domains.loader import load_pack
from oah.schemas import validate


def _fake_response(payload):
    message = SimpleNamespace(content=json.dumps(payload))
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


SERVICE_POINTS = [
    {"id": "sp-0001", "kind": "declarative_route", "file": "routes.tsx", "line": 10, "sync_nature": "async"},
    {"id": "sp-0002", "kind": "http_server_route", "file": "server.py", "line": 5, "sync_nature": "sync"},
    {"id": "sp-0003", "kind": "db_query", "file": "db.py", "line": 20, "sync_nature": "async"},
    {"id": "sp-0004", "kind": "queue_producer", "file": "queue.py", "line": 8, "sync_nature": "async"},
]


def _fragment_for(lens_name, point_ids):
    safe_name = lens_name.replace("-", "_")
    return {
        "schema_version": "0.1.0", "lens": lens_name, "repo_git_sha": "deadbeef",
        "failure_mode": "fail_open",
        "signals": [{
            "name": f"oah.{safe_name}.signal", "surface_point_ids": point_ids,
            "maps_to": {"kind": "oah_extension", "attribute": f"oah.{safe_name}.signal"},
            "sensitivity_tier": "internal", "pii_masked": False,
            "supports_decision": "test decision", "acting_role": "test role",
            "latency_overhead_budget_ms": 1,
        }],
    }


def test_service_pack_loads_and_declares_the_three_reused_lenses():
    pack = load_pack("service")
    assert {l["lens"] for l in pack["lenses"]} == {"tracing", "ops", "pii-governance"}
    assert all(l["reused_from"] == "genai" for l in pack["lenses"])
    assert {pk["kind"] for pk in pack["point_kinds"]} == {
        "declarative_route", "http_server_route", "http_client_call",
        "db_query", "queue_producer", "queue_consumer", "scheduled_job",
    }


def test_design_all_lenses_filters_each_lens_by_the_packs_own_target_kinds():
    """The real regression test: before the fix, this would have called
    design_ops/design_pii_governance with the FULL unfiltered point list
    every time (relying on their own now-removed internal hardcoded
    filters, which matched none of these service-domain kinds) -- ops and
    pii-governance would each have silently produced a fragment covering
    every point (wrong for pii-governance) or, with the old pre-fix
    lens.py, returned None for both (since kind == "llm_generation" never
    matched)."""
    pack = load_pack("service")
    target_kinds_by_lens = _target_kinds_for_pack(pack)
    assert target_kinds_by_lens["tracing"] is None
    assert target_kinds_by_lens["ops"] is None
    assert target_kinds_by_lens["pii-governance"] == ["http_server_route", "declarative_route", "db_query"]

    received = {}

    def make_fake(lens_name):
        def fake(points, repo_git_sha, context=None, model=None):
            received[lens_name] = {p["id"] for p in points}
            return _fragment_for(lens_name, [p["id"] for p in points])
        return fake

    lens_fns = {entry["lens"]: make_fake(entry["lens"]) for entry in pack["lenses"]}
    fragments = _design_all_lenses(SERVICE_POINTS, "deadbeef", lens_fns, LensDesignError, pack)

    all_ids = {p["id"] for p in SERVICE_POINTS}
    assert received["tracing"] == all_ids
    assert received["ops"] == all_ids
    assert received["pii-governance"] == {"sp-0001", "sp-0002", "sp-0003"}  # excludes queue_producer
    assert len(fragments) == 3


def test_reused_lens_functions_run_for_real_against_service_points_no_skill_md_edit():
    """The deeper proof: not a fake lens_fn, but the REAL design_tracing/
    design_ops/design_pii_governance -- real SKILL.md files loaded from
    skills/s4-tracing, skills/s4-ops, skills/s4-pii-governance (genai's own,
    zero edits), real output-schema validation, only the LLM call itself
    mocked (no live API key in this environment, same reasoning every
    other lens test in this suite uses)."""
    pack = load_pack("service")
    target_kinds_by_lens = _target_kinds_for_pack(pack)

    for lens_name, design_fn in [("tracing", design_tracing), ("ops", design_ops),
                                  ("pii-governance", design_pii_governance)]:
        target_kinds = target_kinds_by_lens[lens_name]
        points = SERVICE_POINTS if target_kinds is None else [
            p for p in SERVICE_POINTS if p["kind"] in target_kinds
        ]
        point_ids = [p["id"] for p in points]

        def fake(**kwargs):
            return _fake_response(_fragment_for(lens_name, point_ids))

        fragment = design_fn(points, "deadbeef", _completion_fn=fake)
        assert fragment is not None, f"{lens_name} produced no fragment for real service-domain points"
        validate("design_fragment", fragment)

        findings = run_gates(fragment, surface_map_point_ids=point_ids, pack=pack)
        assert gates_passed(findings), f"{lens_name}: {[f for f in findings if not f.passed]}"


def test_declarative_route_and_http_client_call_are_now_gap_model_visible():
    """docs/decisions/014 named this gap explicitly: E11-TS's TypeScript
    adapter already emits declarative_route/http_client_call points via
    fixed passes, but no pack owned that vocabulary, so gap_model.py's
    pack-derived dimension lookup silently excluded them. Declaring both
    kinds in the service pack (detected_by: fixed_pass) closes that gap --
    verified here against the real S3 gap-model code, not just the pack's
    own schema shape."""
    from oah.discovery.gap_model import build_gap_model

    pack = load_pack("service")
    git_sha = "deadbeef" * 5
    surface_map = {
        "schema_version": "0.1.0",
        "repo": {"path": "<test>", "git_sha": git_sha, "primary_language": "typescript"},
        "generated_by": {"harness_version": "0.0.0", "skill_versions": {}},
        "points": [
            {"id": "sp-0001", "kind": "declarative_route", "file": "routes.tsx", "line": 10,
             "detection": "signature", "confidence": 1.0},
            {"id": "sp-0002", "kind": "http_client_call", "file": "api.ts", "line": 5,
             "detection": "signature", "confidence": 1.0},
        ],
        "coverage_stats": {"files_scanned": 2, "points_total": 2, "points_llm_disambiguated": 0},
    }
    inventory = {"schema_version": "0.1.0", "repo": {"path": "<test>", "git_sha": git_sha},
                 "loggers": [], "existing_otel_usage": []}
    gap_model = build_gap_model(surface_map, inventory, pack=pack)
    dimensions = {g["dimension"] for g in gap_model["gaps"]}
    assert dimensions == {"routing", "dependency"}
