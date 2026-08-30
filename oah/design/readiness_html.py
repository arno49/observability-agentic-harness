"""S9 -- HTML rendering of a readiness_report.json (docs/decisions/047).

A pure presentation layer over an already schema-validated
readiness_report (schemas/readiness_report.schema.json) -- not a new
pipeline artifact boundary and never free text passed between stages
(CLAUDE.md's own rule): this module's only inputs are data other stages
already produced and validated, and its only output is a self-contained
HTML string a human reads. Nothing downstream parses it back.

`gate_findings`/`panel_verdicts` (the same --save-intermediates detail,
docs/decisions/038) are optional enrichment -- the report renders
completely without them, a plain readiness_report.json's own eight
sections are shown either way; passing them in adds a per-gate pass/fail
breakdown readiness_report.json itself only ever aggregates to a bare
name and count.

Deliberately pack/target-neutral: every section is driven by whatever
keys the report actually has (all but the schema's required fields are
optional), never assumes a specific pack, lens set, or target shape.
"""
import html as _html


def _e(value):
    """Escape untrusted text -- report prose ultimately traces back to a
    model's own free-text fields (rationale, supports_decision, etc.);
    never interpolate it into HTML unescaped."""
    return _html.escape(str(value)) if value is not None else ""


def _badge(text, kind):
    return f'<span class="badge {kind}">{_e(text)}</span>'


DECISION_BADGE_KIND = {
    "ready": "ready",
    "ready_with_conditions": "conditions",
    "remediate_before_release": "remediate",
    "pause_and_redesign": "remediate",
    "escalate_for_review": "escalate",
    "rollback_or_pause_expansion": "remediate",
}


def _list_block(title, items, empty_text=None):
    if not items:
        if empty_text is None:
            return ""
        return f"<h3>{_e(title)}</h3><p class='dim'>{_e(empty_text)}</p>"
    rows = "".join(f"<li>{_e(item)}</li>" for item in items)
    return f"<h3>{_e(title)}</h3><ul>{rows}</ul>"


def _field_row(label, value):
    if value in (None, "", [], {}):
        return ""
    return f"<div class='row'><div class='k'>{_e(label)}</div><div class='v'>{_e(value)}</div></div>"


def _section(title, body_html):
    if not body_html.strip():
        return ""
    return f"<section><h2>{_e(title)}</h2>{body_html}</section>"


def _render_recommendation(rec):
    decision = rec.get("decision", "unknown")
    kind = DECISION_BADGE_KIND.get(decision, "unknown")
    parts = [f"<div class='verdict'>{_badge(decision, kind)}</div>"]
    parts.append(f"<p class='rationale'>{_e(rec.get('rationale', ''))}</p>")
    parts.append(_field_row("top_blocker", rec.get("top_blocker")))
    parts.append(_field_row("next_action_owner", rec.get("next_action_owner")))
    parts.append(_list_block("Conditions", rec.get("conditions") or []))

    ev = rec.get("evidence_position") or {}
    if ev.get("confirmed") or ev.get("assumed") or ev.get("unknown"):
        rows = ""
        for tag, key in (("confirmed", "confirmed"), ("assumed", "assumed"), ("unknown", "unknown")):
            for item in ev.get(key) or []:
                rows += f"<div class='ev-row'><span class='tag {tag}'>{tag}</span><div>{_e(item)}</div></div>"
        parts.append(f"<h3>evidence_position</h3><div class='ev-table'>{rows}</div>")

    change = rec.get("evidence_that_would_change_decision") or {}
    if change.get("to_upgrade") or change.get("to_escalate_or_downgrade"):
        parts.append("<h3>evidence_that_would_change_decision</h3>")
        parts.append(_field_row("to_upgrade", change.get("to_upgrade")))
        parts.append(_field_row("to_escalate_or_downgrade", change.get("to_escalate_or_downgrade")))

    scope = rec.get("scope") or {}
    if scope.get("in_scope") or scope.get("out_of_scope_unless_approved"):
        parts.append(_list_block("in_scope", scope.get("in_scope") or []))
        parts.append(_list_block("out_of_scope_unless_approved", scope.get("out_of_scope_unless_approved") or []))

    if rec.get("s11_verdict_ref"):
        parts.append(_field_row("s11_verdict_ref", rec.get("s11_verdict_ref")))

    return "".join(p for p in parts if p)


def _render_deployment_context(ctx):
    parts = [
        _field_row("workflow", ctx.get("workflow")),
        _field_row("intended_users", ctx.get("intended_users")),
        _field_row("environment", ctx.get("environment")),
        _field_row("environment_provenance", ctx.get("environment_provenance")),
        _field_row("runtime_and_secrets_approach", ctx.get("runtime_and_secrets_approach")),
        _field_row("open_blocker", ctx.get("open_blocker")),
        _list_block("assumptions", ctx.get("assumptions") or []),
    ]
    return "".join(parts)


def _render_release_evidence(ev):
    parts = []
    ids = ev.get("release_identifiers") or {}
    if ids:
        parts.append("<h3>release_identifiers</h3>")
        for k, v in ids.items():
            parts.append(_field_row(k, v))
    owners = ev.get("owners") or {}
    if owners:
        parts.append("<h3>owners</h3>")
        for k, v in owners.items():
            parts.append(_field_row(k, v))
    parts.append(_field_row("health_and_smoke_evidence", ev.get("health_and_smoke_evidence")))
    parts.append(_field_row("open_blocker", ev.get("open_blocker")))
    parts.append(_list_block("evidence_missing", ev.get("evidence_missing") or []))

    coverage = ev.get("eval_coverage") or []
    if coverage:
        rows = "".join(
            f"<tr><td>{_e(c.get('case_class'))}</td><td>{_e(c.get('status'))}</td>"
            f"<td>{_e(c.get('expected_behavior'))}</td><td>{_e(c.get('notes'))}</td></tr>"
            for c in coverage
        )
        parts.append(
            "<h3>eval_coverage</h3><table class='data'><thead><tr>"
            "<th>case_class</th><th>status</th><th>expected_behavior</th><th>notes</th>"
            f"</tr></thead><tbody>{rows}</tbody></table>"
        )
    return "".join(parts)


def _render_observability_plan(plan):
    parts = [
        _list_block("key_signals", plan.get("key_signals") or []),
        _list_block("alert_triggers", plan.get("alert_triggers") or []),
        _list_block("sensitive_data_excluded", plan.get("sensitive_data_excluded") or []),
        _field_row("correlation_ids", plan.get("correlation_ids")),
        _field_row("open_blocker", plan.get("open_blocker")),
    ]
    thresholds = plan.get("health_thresholds") or []
    if thresholds:
        rows = ""
        for t in thresholds:
            states = ", ".join(
                f"{_e(th.get('state'))}: {_e(th.get('condition'))} ({_e(th.get('basis'))})"
                for th in (t.get("thresholds") or [])
            )
            points = ", ".join(t.get("surface_point_ids") or [])
            rows += (
                f"<tr><td>{_e(t.get('attribute'))}</td><td>{_e(t.get('lens'))}</td>"
                f"<td>{_e(points)}</td><td>{_e(states)}</td></tr>"
            )
        parts.append(
            "<h3>health_thresholds</h3><table class='data'><thead><tr>"
            "<th>attribute</th><th>lens</th><th>surface_point_ids</th><th>thresholds</th>"
            f"</tr></thead><tbody>{rows}</tbody></table>"
        )
    return "".join(parts)


def _render_failure_response(fr):
    parts = [
        _list_block("failure_modes", fr.get("failure_modes") or []),
        _field_row("retry_degradation_fallback", fr.get("retry_degradation_fallback")),
        _field_row("incident_route", fr.get("incident_route")),
        _field_row("rollback_or_pause_criteria", fr.get("rollback_or_pause_criteria")),
        _field_row("open_blocker", fr.get("open_blocker")),
    ]
    return "".join(parts)


def _render_data_and_governance(dg):
    if not dg:
        return ""
    parts = []
    data_map = dg.get("data_map") or {}
    if data_map:
        parts.append("<h3>data_map</h3>")
        for k in ("input", "retrieved", "output", "logged"):
            parts.append(_field_row(k, data_map.get(k)))
    sources = dg.get("source_inventory") or []
    if sources:
        rows = "".join(
            f"<tr><td>{_e(s.get('source'))}</td><td>{_e(s.get('status'))}</td>"
            f"<td>{_e(s.get('pilot_handling'))}</td><td>{_e(s.get('owner'))}</td></tr>"
            for s in sources
        )
        parts.append(
            "<h3>source_inventory</h3><table class='data'><thead><tr>"
            "<th>source</th><th>status</th><th>pilot_handling</th><th>owner</th>"
            f"</tr></thead><tbody>{rows}</tbody></table>"
        )
    parts.append(_field_row("restricted_source_handling", dg.get("restricted_source_handling")))
    parts.append(_field_row("trust_boundary_verification", dg.get("trust_boundary_verification")))
    parts.append(_field_row("tool_action_boundary", dg.get("tool_action_boundary")))
    parts.append(_list_block("governance_owners_unnamed", dg.get("governance_owners_unnamed") or []))
    parts.append(_field_row("open_blocker", dg.get("open_blocker")))
    return "".join(parts)


def _render_gate_summary(gate_findings):
    """Per-gate pass/fail rollup across every lens fragment this run
    produced -- the detail readiness_report.json's own recommendation
    only ever compresses to a gate name and a count."""
    if not gate_findings:
        return ""
    by_gate = {}
    for f in gate_findings:
        name = f.get("gate", "?")
        entry = by_gate.setdefault(name, {"pass": 0, "fail": 0, "fail_reasons": []})
        if f.get("passed"):
            entry["pass"] += 1
        else:
            entry["fail"] += 1
            reason = f.get("reason")
            if reason:
                entry["fail_reasons"].append(reason)

    cells = []
    for name in sorted(by_gate):
        entry = by_gate[name]
        dot = "fail" if entry["fail"] else "pass"
        count = entry["pass"] + entry["fail"]
        cells.append(
            f"<div class='gate'><span class='dot {dot}'></span>{_e(name)}"
            f"<span class='n'>{entry['pass']}/{count}</span></div>"
        )
    body = f"<div class='gate-grid'>{''.join(cells)}</div>"

    failing = {name: e for name, e in by_gate.items() if e["fail"]}
    if failing:
        rows = ""
        for name, entry in sorted(failing.items()):
            reasons = "".join(f"<li>{_e(r)}</li>" for r in entry["fail_reasons"][:5])
            more = len(entry["fail_reasons"]) - 5
            more_note = f"<li class='dim'>... and {more} more</li>" if more > 0 else ""
            rows += f"<div class='fail-block'><div class='fail-gate'>{_e(name)}</div><ul>{reasons}{more_note}</ul></div>"
        body += f"<h3>Failing gate detail</h3>{rows}"

    return body


def _render_panel_summary(panel_verdicts):
    if not panel_verdicts:
        return ""
    rows = ""
    for v in panel_verdicts:
        overall = v.get("overall", "?")
        dot = "pass" if overall == "pass" else "fail"
        findings = v.get("findings") or []
        finding_list = "".join(
            f"<li><strong>{_e(f.get('severity'))}</strong> [{_e(f.get('gate'))}] {_e(f.get('summary'))}</li>"
            for f in findings
        )
        rows += (
            f"<div class='gate'><span class='dot {dot}'></span>{_e(v.get('persona'))}"
            f"<span class='n'>{_e(overall)}</span></div>"
        )
        if finding_list:
            rows += f"<ul>{finding_list}</ul>"
    return f"<div class='gate-grid'>{rows}</div>"


_CSS = """
:root {
  --bg:#0f1115; --panel:#171a21; --panel-2:#1d2129; --border:#2a2f3a;
  --text:#e6e9ef; --text-dim:#9aa3b2; --accent:#5b9dff;
  --green:#3ecf8e; --amber:#f0b429; --red:#f2555a; --violet:#b18cf0;
}
* { box-sizing: border-box; }
body { margin:0; background:var(--bg); color:var(--text);
  font-family:-apple-system,"Segoe UI",Roboto,sans-serif; line-height:1.55; }
.wrap { max-width: 880px; margin:0 auto; padding: 36px 22px 80px; }
header { margin-bottom: 26px; }
h1 { font-size: 1.35rem; margin: 0 0 6px; }
.sub { color: var(--text-dim); font-size: 0.88rem; font-family: monospace; }
section { background: var(--panel); border:1px solid var(--border); border-radius:10px;
  padding: 18px 22px; margin-bottom: 18px; }
section h2 { font-size:0.78rem; text-transform:uppercase; letter-spacing:.07em;
  color: var(--text-dim); margin: 0 0 12px; border-bottom:1px solid var(--border); padding-bottom:8px; }
section h3 { font-size:0.72rem; text-transform:uppercase; letter-spacing:.06em;
  color: var(--text-dim); margin: 16px 0 6px; }
section h3:first-of-type { margin-top: 0; }
p { margin: 0 0 8px; font-size: 0.92rem; }
p.rationale { font-size: 1rem; }
p.dim { color: var(--text-dim); }
ul { margin: 4px 0 8px; padding-left: 20px; font-size: 0.9rem; }
li { margin-bottom: 4px; }
.row { display:grid; grid-template-columns: 220px 1fr; gap: 10px; padding: 6px 0;
  border-bottom: 1px solid var(--border); font-size: 0.88rem; }
.row:last-child { border-bottom: none; }
.row .k { color: var(--text-dim); }
.badge { display:inline-block; padding: 4px 12px; border-radius:999px; font-size:0.82rem;
  font-weight:700; letter-spacing:.02em; }
.badge.ready { background: rgba(62,207,142,.15); color: var(--green); border:1px solid rgba(62,207,142,.4); }
.badge.conditions { background: rgba(91,157,255,.15); color: var(--accent); border:1px solid rgba(91,157,255,.4); }
.badge.remediate { background: rgba(242,85,90,.15); color: var(--red); border:1px solid rgba(242,85,90,.4); }
.badge.escalate { background: rgba(177,140,240,.15); color: var(--violet); border:1px solid rgba(177,140,240,.4); }
.badge.unknown { background: rgba(154,163,178,.15); color: var(--text-dim); border:1px solid rgba(154,163,178,.35); }
.verdict { margin-bottom: 10px; }
.ev-table .ev-row { display:grid; grid-template-columns: 90px 1fr; gap:12px; padding:6px 0;
  border-bottom:1px solid var(--border); font-size:0.88rem; }
.ev-table .ev-row:last-child { border-bottom: none; }
.tag { font-size:0.68rem; font-weight:700; text-transform:uppercase; letter-spacing:.04em; }
.tag.confirmed { color: var(--green); } .tag.assumed { color: var(--amber); } .tag.unknown { color: var(--text-dim); }
table.data { width: 100%; border-collapse: collapse; font-size: 0.85rem; margin: 6px 0 10px; }
table.data th, table.data td { text-align:left; padding: 6px 8px; border-bottom: 1px solid var(--border); }
table.data th { color: var(--text-dim); font-weight:600; font-size:0.75rem; text-transform:uppercase; }
.gate-grid { display:grid; grid-template-columns: repeat(auto-fill, minmax(220px,1fr)); gap: 8px; }
.gate { background: var(--panel-2); border:1px solid var(--border); border-radius:8px;
  padding: 8px 10px; font-size: 0.82rem; display:flex; align-items:center; gap:8px; }
.gate .n { color: var(--text-dim); margin-left:auto; font-size:0.72rem; }
.dot { width:8px; height:8px; border-radius:50%; flex-shrink:0; }
.dot.pass { background: var(--green); } .dot.fail { background: var(--red); }
.fail-block { margin-top: 8px; }
.fail-gate { font-weight:600; font-size:0.85rem; color: var(--red); }
@media (prefers-color-scheme: light) {
  :root { --bg:#f7f8fa; --panel:#fff; --panel-2:#f0f2f5; --border:#e2e5eb; --text:#1a1d24; --text-dim:#5c6472; }
}
"""


def render_readiness_html(report, gate_findings=None, design_fragments=None, panel_verdicts=None):
    """Render a self-contained HTML document for a validated
    readiness_report.json. `gate_findings`/`design_fragments`/
    `panel_verdicts` are the same optional --save-intermediates detail
    (docs/decisions/038) -- pass them when available (cmd_readiness
    already holds them in memory; a caller re-reading from disk can pass
    the loaded --save-intermediates JSON's own top-level keys) for a
    per-gate/per-persona breakdown; omit them for a report driven purely
    by readiness_report.json's own eight sections."""
    sha = report.get("repo_git_sha", "unknown")
    rec = report.get("recommendation", {})

    body = [
        _section("Recommendation", _render_recommendation(rec)),
        _section("Deployment context", _render_deployment_context(report.get("deployment_context", {}))),
        _section("Release evidence", _render_release_evidence(report.get("release_evidence", {}))),
        _section("Observability plan", _render_observability_plan(report.get("observability_plan", {}))),
        _section("Failure response", _render_failure_response(report.get("failure_response", {}))),
        _section("Data & governance", _render_data_and_governance(report.get("data_and_governance"))),
        _section("Known limitations", _list_block("", report.get("known_limitations") or [])),
        _section("S5 gate findings", _render_gate_summary(gate_findings)),
        _section("S6 panel verdicts", _render_panel_summary(panel_verdicts)),
    ]

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>oah readiness report -- {_e(sha)[:12]}</title>
<style>{_CSS}</style>
</head>
<body>
<div class="wrap">
<header>
<h1>oah readiness report</h1>
<div class="sub">repo_git_sha: {_e(sha)} &middot; schema_version: {_e(report.get('schema_version'))}</div>
</header>
{''.join(body)}
</div>
</body>
</html>
"""
