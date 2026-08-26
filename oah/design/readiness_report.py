"""S9 — production readiness report, deterministic assembly (architecture.md
S9: *(deterministic assembly)*, unlike every LLM-driven stage before it).

readiness_report.schema.json is deep — many fields (intended_users,
eval_coverage, health_and_smoke_evidence, known-limitations narrative)
genuinely need either an LLM synthesis pass this module doesn't attempt, or
real runtime evidence from S10/S11, neither of which exist yet at this
pipeline stage. Rather than fabricate them, this assembler populates only
what's mechanically derivable from S1-S8's actual outputs and leaves the
rest genuinely absent — surfaced honestly through the schema's own
`evidence_position` (confirmed/assumed/unknown) and `known_limitations`
fields, which exist precisely for this: "confidence, urgency, or a
successful demo alone never move an item into 'confirmed'" is the schema's
own rule, and it applies to this assembler's own output as much as to a
human reviewer's judgment.
"""


def _decide(gate_findings, panel_verdicts, gap_model):
    """Deterministic recommendation rule. No S10/S11 evidence exists yet at
    this pipeline stage (design-only) -- 'ready' outright would overclaim
    real, applied, validated instrumentation that hasn't happened. The
    ceiling here is ready_with_conditions, not ready, regardless of how
    clean S5/S6 come back, unless there's an actual blocking gate/panel
    failure or an unaddressed critical gap, in which case it's worse than
    that ceiling, not better."""
    failed_gates = [f for f in gate_findings if not f["passed"] and f["severity"] == "error"]
    if failed_gates:
        return (
            "remediate_before_release",
            f"S5 deterministic gate(s) failed: {[f['gate'] for f in failed_gates]}",
            failed_gates[0]["gate"],
        )

    failed_personas = [v for v in panel_verdicts if v["overall"] == "fail"]
    if failed_personas:
        error_findings = [f for v in failed_personas for f in v["findings"] if f["severity"] == "error"]
        return (
            "remediate_before_release",
            f"S6 panel persona(s) failed: {[v['persona'] for v in failed_personas]}",
            error_findings[0]["gate"] if error_findings else "panel failure",
        )

    critical_dark_gaps = [g for g in gap_model.get("gaps", []) if g["status"] == "dark" and g["priority"] in ("p0", "p1")]
    if critical_dark_gaps:
        return (
            "remediate_before_release",
            f"{len(critical_dark_gaps)} unaddressed p0/p1 dark gap(s): {[g['id'] for g in critical_dark_gaps]}",
            critical_dark_gaps[0]["id"],
        )

    return (
        "ready_with_conditions",
        "S5 gates and S6 review pass on the design produced so far, but no instrumentation has "
        "been applied (S10) and no runtime evidence exists (S11) -- design-clean is not "
        "release-ready on its own.",
        None,
    )


def build_readiness_report(gap_model, gate_findings, panel_verdicts, event_schema, dtos,
                            context=None, repo_git_sha=None, run_manifest_ref=None):
    decision, rationale, top_blocker = _decide(gate_findings, panel_verdicts, gap_model)

    workflows = (context or {}).get("workflows", [])
    workflow_names = [w["name"] for w in workflows]

    key_signals = [a["name"] for a in event_schema.get("attributes", [])]

    source_inventory = []
    for s in (context or {}).get("source_inventory", []):
        source_inventory.append({
            "source": s["source"],
            "status": s["approval_status"],
            "pilot_handling": s.get("approved_handling_path", "not specified"),
        })

    trust_boundaries = (context or {}).get("trust_boundaries", [])
    trust_boundary_verification = (
        "; ".join(f"{tb['context_field']}: {'verified server-side' if tb['verified_server_side'] else 'trusted only'}"
                  for tb in trust_boundaries)
        if trust_boundaries else None
    )

    all_personas = {"cost_skeptic", "sre", "security"}
    ran_personas = {v["persona"] for v in panel_verdicts}
    missing_personas = sorted(all_personas - ran_personas)

    confirmed = []
    if gate_findings and not any(not f["passed"] and f["severity"] == "error" for f in gate_findings):
        confirmed.append("S5 deterministic invariant gates pass on the current design")
    if panel_verdicts and all(v["overall"] != "fail" for v in panel_verdicts):
        confirmed.append(
            f"S6 reviewed personas ({len(ran_personas)} of 3: {sorted(ran_personas)}) found no error-severity issues"
        )

    unknown = []
    if not gate_findings:
        unknown.append("S5 gates have not run -- no design fragment exists yet to check (S4 did not produce one)")
    if not panel_verdicts:
        unknown.append("S6 panel has not run -- no design fragment exists yet to review (S4 did not produce one)")
    elif missing_personas:
        unknown.append(f"S6 persona(s) did not produce a verdict this run: {missing_personas}")
    unknown += [
        "S10 instrumentation has not been applied to the target repo",
        "S11 dynamic validation has not run -- no real Trace Completeness Rate or overhead measurement exists",
    ]
    if not workflow_names:
        unknown.append("no context.yaml interview has run -- workflow criticality, PII presence, and governance answers are all unknown")

    has_dtos = bool(dtos.get("dtos"))
    if not has_dtos:
        # Found by adversarial review: this claim used to be derived
        # purely from whether context.yaml had workflows, ignoring `dtos`
        # entirely (the parameter was accepted but never read) -- so it
        # asserted a real ordering rule had been followed even when zero
        # DTOs existed for it to apply to. Don't claim either ordering
        # happened when there's nothing to have ordered.
        rollout_limitation = "no DTOs were generated this run -- rollout_step ordering does not apply."
    elif workflow_names:
        rollout_limitation = (
            "rollout_step ordering follows architecture.md S7's real workflow-criticality "
            "rule (this run had --context)."
        )
    else:
        rollout_limitation = (
            "rollout_step ordering is gap-priority-only, not real workflow-criticality-"
            "ordered -- no context.yaml was supplied to this run."
        )

    known_limitations = [
        "All nine S4 lenses are built, but several are still narrower than "
        "architecture.md's full per-lens ask. tracing only distinguishes same-process "
        "asyncio (verified safe) from everything else (unverified: thread-pool/queue "
        "instrumentor presence isn't checked, and the long-running background-job pattern "
        "isn't detected at all yet). tools is detected via a structural pattern match "
        "(`<expr>.type == \"tool_use\"`), not a resolved SDK call -- it locates dispatch "
        "sites, not the specific handler/arguments/result at each one.",
        rollout_limitation,
    ]

    report = {
        "schema_version": "0.1.0",
        "repo_git_sha": repo_git_sha,
        "deployment_context": {
            "workflow": "; ".join(workflow_names) if workflow_names else "unknown -- no context.yaml interview has run",
            "intended_users": "unknown -- not derivable from S1-S8 outputs, needs owner input",
            "environment": "unknown",
            "environment_provenance": "unknown",
        },
        "release_evidence": {
            "release_identifiers": {},
            "owners": {},
            "evidence_missing": [
                "S10 application evidence", "S11 validation evidence", "eval coverage by case class",
            ],
        },
        "observability_plan": {
            "key_signals": key_signals,
        },
        "failure_response": {
            "failure_modes": ["telemetry loss (declared fail_open in every S4 fragment reviewed)"],
            "incident_route": "unknown -- not derivable without context.yaml",
        },
        "recommendation": {
            "decision": decision,
            "rationale": rationale,
            "top_blocker": top_blocker,
            "next_action_owner": "unknown -- not derivable without context.yaml",
            "evidence_position": {
                "confirmed": confirmed,
                "assumed": [],
                "unknown": unknown,
            },
        },
        "known_limitations": known_limitations,
    }
    if run_manifest_ref:
        report["run_manifest_ref"] = run_manifest_ref
    if source_inventory or trust_boundary_verification or (context or {}).get("tool_action_boundary"):
        report["data_and_governance"] = {}
        if source_inventory:
            report["data_and_governance"]["source_inventory"] = source_inventory
        if trust_boundary_verification:
            report["data_and_governance"]["trust_boundary_verification"] = trust_boundary_verification
        if (context or {}).get("tool_action_boundary"):
            report["data_and_governance"]["tool_action_boundary"] = context["tool_action_boundary"]

    return report
