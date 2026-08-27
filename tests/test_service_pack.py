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
from oah.design.lens import (design_tracing, design_ops, design_pii_governance,
                              design_telemetry_cost, LensDesignError)
from oah.design.gates import run_gates, gates_passed
from oah.design.dto_generator import generate_dtos
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


def _minimal_slo_spec(point_ids):
    return {
        "schema_version": "0.1.0", "repo_git_sha": "deadbeef",
        "surface_point_ids": point_ids,
        "indicator": {"name": "test-journey availability",
                      "good_event_definition": "error.type absent", "aggregation_method": "ratio_of_counts"},
        "objective": {"target": 0.999, "period_days": 30, "up_predicate": "error.type absent",
                      "granularity": "1m", "brownout_classification": "not modeled in this test fixture"},
        "alert_tiers": [{"tier": "fast_burn", "budget_fraction": 0.02, "detection_window_hours": 1,
                         "short_window_hours": 0.0833, "short_window_rationale": "test",
                         "burn_rate_multiplier": 14.4}],
        "error_budget_policy": {"steps": [{"step": "page", "entry_criterion_tier": "fast_burn",
                                            "exit_criterion": "test"}]},
    }


def _minimal_dependency_model(point_ids):
    return {
        "schema_version": "0.1.0", "repo_git_sha": "deadbeef",
        "surface_point_ids": point_ids,
        "edges": [{
            "name": "test-dependency", "dependency_kind": "queue_producer", "criticality": "hard",
            "own_target": 0.999, "required_dependency_target": 0.9999,
            "budget_split": {"own_failures_fraction": 0.5, "dependency_failures_fraction": 0.5},
            "fallback_behavior": "test",
        }],
    }


def test_service_pack_loads_and_declares_its_lenses():
    pack = load_pack("service")
    assert {l["lens"] for l in pack["lenses"]} == {
        "tracing", "ops", "pii-governance", "telemetry-cost", "slo", "dependency",
    }
    reused = {l["lens"] for l in pack["lenses"] if l.get("reused_from") == "genai"}
    assert reused == {"tracing", "ops", "pii-governance"}
    assert "reused_from" not in next(l for l in pack["lenses"] if l["lens"] == "telemetry-cost")
    assert "reused_from" not in next(l for l in pack["lenses"] if l["lens"] == "slo")
    assert "reused_from" not in next(l for l in pack["lenses"] if l["lens"] == "dependency")
    slo_entry = next(l for l in pack["lenses"] if l["lens"] == "slo")
    assert slo_entry["emits"] == ["design_fragment", "slo_spec"]
    dependency_entry = next(l for l in pack["lenses"] if l["lens"] == "dependency")
    assert dependency_entry["emits"] == ["design_fragment", "dependency_model"]
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
    assert target_kinds_by_lens["telemetry-cost"] is None
    assert target_kinds_by_lens["pii-governance"] == ["http_server_route", "declarative_route", "db_query"]
    assert target_kinds_by_lens["slo"] == ["http_server_route", "declarative_route"]
    assert target_kinds_by_lens["dependency"] == ["http_client_call", "queue_producer"]

    received = {}
    emits_by_lens = {entry["lens"]: entry["emits"] for entry in pack["lenses"]}

    def make_fake(lens_name):
        def fake(points, repo_git_sha, context=None, model=None):
            received[lens_name] = {p["id"] for p in points}
            point_ids = [p["id"] for p in points]
            fragment = _fragment_for(lens_name, point_ids)
            emits = emits_by_lens[lens_name]
            if len(emits) == 1:
                return fragment
            if "slo_spec" in emits:
                return {"design_fragment": fragment, "slo_spec": _minimal_slo_spec(point_ids)}
            return {"design_fragment": fragment, "dependency_model": _minimal_dependency_model(point_ids)}
        return fake

    lens_fns = {entry["lens"]: make_fake(entry["lens"]) for entry in pack["lenses"]}
    fragments, extra_artifacts = _design_all_lenses(SERVICE_POINTS, "deadbeef", lens_fns, LensDesignError, pack)
    assert set(extra_artifacts) == {"slo", "dependency"}  # the two current multi-emit lenses
    assert set(extra_artifacts["slo"]) == {"slo_spec"}
    assert set(extra_artifacts["dependency"]) == {"dependency_model"}

    all_ids = {p["id"] for p in SERVICE_POINTS}
    assert received["tracing"] == all_ids
    assert received["ops"] == all_ids
    assert received["telemetry-cost"] == all_ids
    assert received["pii-governance"] == {"sp-0001", "sp-0002", "sp-0003"}  # excludes queue_producer
    assert received["slo"] == {"sp-0001", "sp-0002"}  # http_server_route + declarative_route only
    assert received["dependency"] == {"sp-0004"}  # queue_producer only (no http_client_call point here)
    assert len(fragments) == 6


def test_reused_lens_functions_run_for_real_against_service_points_no_skill_md_edit():
    """The deeper proof: not a fake lens_fn, but the REAL design_tracing/
    design_ops/design_pii_governance/design_telemetry_cost -- real SKILL.md
    files loaded from skills/s4-tracing, skills/s4-ops,
    skills/s4-pii-governance (genai's own, zero edits) and
    skills/s4-telemetry-cost (the service pack's own adapted skill), real
    output-schema validation, only the LLM call itself mocked (no live API
    key in this environment, same reasoning every other lens test in this
    suite uses). design_slo's own real-function proof lives in
    tests/test_slo_lens.py -- its two-part {design_fragment, slo_spec}
    return shape doesn't fit this loop's single-fragment assumption."""
    pack = load_pack("service")
    target_kinds_by_lens = _target_kinds_for_pack(pack)

    for lens_name, design_fn in [("tracing", design_tracing), ("ops", design_ops),
                                  ("pii-governance", design_pii_governance),
                                  ("telemetry-cost", design_telemetry_cost)]:
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


# --- E12 DoD (d): the anti-redundancy gate -------------------------------

def _fake_completion(payload):
    message = SimpleNamespace(content=json.dumps(payload))
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


_SERVICE_EVENT_SCHEMA = {
    "schema_version": "0.1.0", "repo_git_sha": "deadbeef",
    "attributes": [
        {"name": "http.route", "kind": "otel_semconv", "stability": "stable",
         "deprecated_by": None, "sensitivity_tier": "internal",
         "source_lenses": ["ops"], "surface_point_ids": ["sp-0001"]},
        {"name": "oah.service.slo_indicator", "kind": "oah_extension", "stability": "development",
         "deprecated_by": None, "sensitivity_tier": "internal",
         "source_lenses": ["ops"], "surface_point_ids": ["sp-0001"]},
    ],
    "summary": {"attribute_count": 2, "otel_semconv_count": 1, "oah_extension_count": 1,
                "lenses_included": ["ops"]},
}
_SERVICE_POINTS_FOR_DTO = [{"id": "sp-0001", "kind": "http_server_route", "file": "app.py", "line": 5}]
_SERVICE_GAPS_FOR_DTO = [{"id": "gap-0001", "surface_point_ids": ["sp-0001"], "dimension": "routing",
                          "status": "dark", "priority": "p1", "rationale": "x"}]


def test_dto_that_only_reemits_a_baseline_covered_attribute_is_refused():
    """E12 DoD (d): a DTO whose every expected_events[].required_attributes
    entry is already in auto_instrumentation_baseline.covered_signals would
    only re-emit, worse and later, what opentelemetry-instrument already
    provides for free (docs/decisions/011 Finding 2) -- refused, not
    generated."""
    pack = load_pack("service")
    payload = {
        "schema_version": "0.1.0",
        "dtos": [{
            "id": "dto-0001", "gap_id": "gap-0001", "surface_point_ids": ["sp-0001"],
            "change": {"type": "insert_span", "file": "app.py", "anchor": "handler"},
            "expected_events": [{"event_type": "http_span", "required_attributes": ["http.route"]}],
            "risk": "low",
        }],
    }
    result = generate_dtos(
        _SERVICE_EVENT_SCHEMA, _SERVICE_POINTS_FOR_DTO, _SERVICE_GAPS_FOR_DTO, "deadbeef",
        _completion_fn=lambda **kw: _fake_completion(payload), pack=pack,
    )
    validate("implementation_dto", result)
    assert result["dtos"] == []
    assert result["refused_dtos"] == [
        {"id": "dto-0001", "gap_id": "gap-0001", "reason": "redundant_with_auto_instrumentation"}
    ]


def test_dto_with_a_genuinely_new_attribute_is_kept_even_if_partly_baseline_covered():
    """A DTO that emits http.route AND a real new oah.* attribute is not
    redundant -- it does more than the baseline already provides, so it
    must survive the gate."""
    pack = load_pack("service")
    payload = {
        "schema_version": "0.1.0",
        "dtos": [{
            "id": "dto-0002", "gap_id": "gap-0001", "surface_point_ids": ["sp-0001"],
            "change": {"type": "insert_span", "file": "app.py", "anchor": "handler"},
            "expected_events": [{
                "event_type": "http_span",
                "required_attributes": ["http.route", "oah.service.slo_indicator"],
            }],
            "risk": "low",
        }],
    }
    result = generate_dtos(
        _SERVICE_EVENT_SCHEMA, _SERVICE_POINTS_FOR_DTO, _SERVICE_GAPS_FOR_DTO, "deadbeef",
        _completion_fn=lambda **kw: _fake_completion(payload), pack=pack,
    )
    validate("implementation_dto", result)
    assert len(result["dtos"]) == 1
    assert result["dtos"][0]["id"] == "dto-0002"
    assert "refused_dtos" not in result


def test_genai_pack_never_refuses_it_declares_no_baseline():
    """Zero behavior change for the pack that existed before this gate:
    genai declares no auto_instrumentation_baseline at all, so
    _baseline_covered_attributes returns an empty set and the redundancy
    check never fires, by construction."""
    from oah.design.dto_generator import _baseline_covered_attributes
    genai_pack = load_pack("genai")
    assert _baseline_covered_attributes(genai_pack) == set()
    assert _baseline_covered_attributes(None) == set()


# --- E12 phase 3: the express registry (docs/decisions/018) --------------

def _write_ts(tmp_path, name, content):
    path = tmp_path / name
    path.write_text(content)
    return path


def test_express_route_registration_detected_with_service_pack(tmp_path):
    from oah.discovery.typescript_adapter import detect_repo
    pack = load_pack("service")
    _write_ts(tmp_path, "app.ts", (
        'import express from "express";\n'
        'const app = express();\n'
        'app.get("/users/:id", (req, res) => { res.send("ok"); });\n'
        'app.post("/users", (req, res) => { res.send("created"); });\n'
    ))
    points = detect_repo(tmp_path, pack=pack)
    assert len(points) == 2
    assert all(p["kind"] == "http_server_route" for p in points)
    assert all(p["framework"] == "express" for p in points)
    get_point = next(p for p in points if p["line"] == 3)
    post_point = next(p for p in points if p["line"] == 4)
    assert get_point["has_path_parameter"] is True
    assert post_point["has_path_parameter"] is False


def test_express_settings_getter_not_treated_as_a_route(tmp_path):
    """Express's own documented dual-purpose method: app.get(name) (1 arg)
    reads a setting; only app.get(path, ...handlers) (2+ args) registers a
    route."""
    from oah.discovery.typescript_adapter import detect_repo
    pack = load_pack("service")
    _write_ts(tmp_path, "app.ts", (
        'import express from "express";\n'
        'const app = express();\n'
        'app.get("view engine");\n'
    ))
    assert detect_repo(tmp_path, pack=pack) == []


def test_express_use_call_not_treated_as_a_route(tmp_path):
    """app.use(middleware) is overwhelmingly plain middleware in real
    Express code, not a route -- deliberately excluded from
    method_suffixes (domains/service/pack.json's own confidence_note)."""
    from oah.discovery.typescript_adapter import detect_repo
    pack = load_pack("service")
    _write_ts(tmp_path, "app.ts", (
        'import express from "express";\n'
        'const app = express();\n'
        'app.use(express.json());\n'
    ))
    assert detect_repo(tmp_path, pack=pack) == []


def test_default_pack_never_detects_express_routes():
    """Zero behavior change for every existing caller that doesn't pass
    pack= explicitly -- Express is service-domain vocabulary, not genai's."""
    from oah.discovery.typescript_adapter import detect_repo
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        from pathlib import Path
        _write_ts(Path(d), "app.ts", (
            'import express from "express";\n'
            'const app = express();\n'
            'app.get("/users", (req, res) => { res.send("ok"); });\n'
        ))
        assert detect_repo(Path(d)) == []


def test_express_route_visible_to_gap_model_via_service_pack():
    """End to end: a real Express route, detected via the real adapter
    against the real service pack, resolves to the routing dimension
    through the real S3 gap-model code -- not just asserted at the S1
    output shape."""
    from oah.discovery.typescript_adapter import build_surface_map
    from oah.discovery.gap_model import build_gap_model
    import tempfile
    from pathlib import Path

    pack = load_pack("service")
    with tempfile.TemporaryDirectory() as d:
        _write_ts(Path(d), "app.ts", (
            'import express from "express";\n'
            'const app = express();\n'
            'app.get("/bookings/:id", (req, res) => { res.send("ok"); });\n'
        ))
        surface_map, _ = build_surface_map(Path(d), git_sha="deadbeef", pack=pack)
        assert surface_map["points"][0]["kind"] == "http_server_route"

        inventory = {"schema_version": "0.1.0", "repo": {"path": "<test>", "git_sha": "deadbeef"},
                     "loggers": [], "existing_otel_usage": []}
        gap_model = build_gap_model(surface_map, inventory, pack=pack)
        assert gap_model["gaps"][0]["dimension"] == "routing"


# --- E12 phase 7: the pg registry (docs/decisions/023) --------------------

def test_pg_query_detected_with_service_pack_named_import(tmp_path):
    from oah.discovery.typescript_adapter import detect_repo
    pack = load_pack("service")
    _write_ts(tmp_path, "db.ts", (
        'import { Client } from "pg";\n'
        "const client = new Client();\n"
        'async function run() {\n'
        '  await client.query("SELECT * FROM users WHERE id = $1", [1]);\n'
        "}\n"
    ))
    points = detect_repo(tmp_path, pack=pack)
    assert len(points) == 1
    assert points[0]["kind"] == "db_query"
    assert points[0]["framework"] == "pg"
    assert points[0]["sync_nature"] == "async"


def test_pg_pool_query_also_detected(tmp_path):
    from oah.discovery.typescript_adapter import detect_repo
    pack = load_pack("service")
    _write_ts(tmp_path, "db.ts", (
        'import { Pool } from "pg";\n'
        "const pool = new Pool();\n"
        'pool.query("SELECT 1");\n'
    ))
    points = detect_repo(tmp_path, pack=pack)
    assert len(points) == 1
    assert points[0]["kind"] == "db_query"


def test_pg_require_form_not_detected_named_gap(tmp_path):
    """CommonJS require() is a real, named gap -- no registry in this pack
    has ever supported it, confirmed here rather than silently assumed."""
    from oah.discovery.typescript_adapter import detect_repo
    pack = load_pack("service")
    _write_ts(tmp_path, "db.ts", (
        'const { Client } = require("pg");\n'
        "const client = new Client();\n"
        'client.query("SELECT 1");\n'
    ))
    assert detect_repo(tmp_path, pack=pack) == []


def test_default_pack_never_detects_pg_queries(tmp_path):
    """Zero behavior change for every existing caller -- pg is service-domain
    vocabulary, not genai's."""
    from oah.discovery.typescript_adapter import detect_repo
    _write_ts(tmp_path, "db.ts", (
        'import { Client } from "pg";\n'
        "const client = new Client();\n"
        'client.query("SELECT 1");\n'
    ))
    assert detect_repo(tmp_path) == []


def test_pg_query_visible_to_gap_model_as_db_dimension():
    from oah.discovery.typescript_adapter import build_surface_map
    from oah.discovery.gap_model import build_gap_model
    import tempfile
    from pathlib import Path

    pack = load_pack("service")
    with tempfile.TemporaryDirectory() as d:
        _write_ts(Path(d), "db.ts", (
            'import { Client } from "pg";\n'
            "const client = new Client();\n"
            'client.query("SELECT 1");\n'
        ))
        surface_map, _ = build_surface_map(Path(d), git_sha="deadbeef", pack=pack)
        assert surface_map["points"][0]["kind"] == "db_query"

        inventory = {"schema_version": "0.1.0", "repo": {"path": "<test>", "git_sha": "deadbeef"},
                     "loggers": [], "existing_otel_usage": []}
        gap_model = build_gap_model(surface_map, inventory, pack=pack)
        assert gap_model["gaps"][0]["dimension"] == "db"


# --- E12 phase 8: the node-cron registry (docs/decisions/024) -------------

def test_node_cron_schedule_detected_with_service_pack(tmp_path):
    """imported_namespace_method_call: cron is the receiver directly from
    the import binding, no constructor/factory step at all."""
    from oah.discovery.typescript_adapter import detect_repo
    pack = load_pack("service")
    _write_ts(tmp_path, "jobs.ts", (
        'import cron from "node-cron";\n'
        'cron.schedule("*/5 * * * *", () => {\n'
        '  console.log("job running");\n'
        "});\n"
    ))
    points = detect_repo(tmp_path, pack=pack)
    assert len(points) == 1
    assert points[0]["kind"] == "scheduled_job"
    assert points[0]["framework"] == "node-cron"


def test_default_pack_never_detects_node_cron(tmp_path):
    """Zero behavior change for every existing caller -- node-cron is
    service-domain vocabulary, not genai's."""
    from oah.discovery.typescript_adapter import detect_repo
    _write_ts(tmp_path, "jobs.ts", (
        'import cron from "node-cron";\n'
        'cron.schedule("*/5 * * * *", () => {});\n'
    ))
    assert detect_repo(tmp_path) == []


def test_node_cron_unrelated_local_import_not_matched(tmp_path):
    """Real precision guard, not just a name match: name_alias stores the
    ACTUAL module string from the import, so a local module confusingly
    also named `cron` doesn't false-positive."""
    from oah.discovery.typescript_adapter import detect_repo
    pack = load_pack("service")
    _write_ts(tmp_path, "jobs.ts", (
        'import cron from "./myLocalCronThing";\n'
        'cron.schedule("* * * * *", () => {});\n'
    ))
    assert detect_repo(tmp_path, pack=pack) == []


def test_node_cron_visible_to_gap_model_as_scheduling_dimension():
    from oah.discovery.typescript_adapter import build_surface_map
    from oah.discovery.gap_model import build_gap_model
    import tempfile
    from pathlib import Path

    pack = load_pack("service")
    with tempfile.TemporaryDirectory() as d:
        _write_ts(Path(d), "jobs.ts", (
            'import cron from "node-cron";\n'
            'cron.schedule("0 0 * * *", () => {});\n'
        ))
        surface_map, _ = build_surface_map(Path(d), git_sha="deadbeef", pack=pack)
        assert surface_map["points"][0]["kind"] == "scheduled_job"

        inventory = {"schema_version": "0.1.0", "repo": {"path": "<test>", "git_sha": "deadbeef"},
                     "loggers": [], "existing_otel_usage": []}
        gap_model = build_gap_model(surface_map, inventory, pack=pack)
        assert gap_model["gaps"][0]["dimension"] == "scheduling"
