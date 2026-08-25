# Observability Agentic Harness (OAH) — Agentic Observability Pipeline

> **Status: pre-alpha / design stage.** This repository currently contains the product
> design, artifact schemas, skill drafts, and roadmap. No runnable pipeline yet.
> Follow [ROADMAP.md](ROADMAP.md) for progress.

OAH is an agentic harness that **builds LLM observability into an existing product**
(or produces observability requirements for a product being designed). Given access to
a repository, it runs a multi-stage pipeline: it maps every LLM call site, retrieval
step, and tool invocation; inventories existing telemetry; designs a target
observability architecture; produces an implementation plan; then — in fix mode —
generates and applies the instrumentation code and **validates that telemetry actually
flows** by exercising the product and checking emitted events against a versioned
schema.

OAH ships two co-equal deliverables:

1. **Working instrumentation** — code, event schema, collector config, and a
   validated Trace Completeness Rate for the target product.
2. **A production readiness decision** — a structured five-question readiness
   report ([schema](schemas/readiness_report.schema.json)) ending in one of six
   evidence-led recommendations: *ready / ready with conditions / remediate before
   release / pause and redesign / escalate for review / rollback or pause
   expansion* — with the epistemic position stated (confirmed vs. assumed vs.
   unknown), scope exclusions, named owners, and the evidence that would change
   the decision. The gate never advances on confidence, urgency, or a successful
   demo alone.

The two reinforce each other: the readiness decision is only as good as the
signals behind it, and the installed signals are designed backwards from the
decisions they must support — every signal names the decision it serves and the
owner who acts, or it is not built (the anti-metric-hoarding gate).

## Inspiration & credit

The architecture of this project is directly inspired by
[**Visa Vulnerability Agentic Harness (VVAH)**](https://github.com/visa/visa-vulnerability-agentic-harness) —
Visa's open-source agentic SAST pipeline built on learnings from Anthropic's Project
Glasswing. We adopt its core design pattern and adapt it from vulnerability management
to observability engineering:

| VVAH pattern | OAH adaptation |
|---|---|
| Threat modeling before analysis | Observability surface mapping & gap modeling before design |
| Multi-phase pipeline of composable, versioned skills | Same — each LLM-driven stage is an independently testable skill |
| Deterministic controls + frontier-model reasoning | Deterministic AST/code scanning + LLM reasoning at each phase |
| Structured artifacts (DTOs, SARIF) between stages | Structured artifacts (surface map, gap model, implementation DTOs) |
| Remediation applies code changes, then adversarial validation panel | Instrumentation applies code changes, then dynamic validation: run the product, intercept telemetry, verify against schema |
| Primary metric: Mean Time to Adapt (MTTA) | Primary metric: **Trace Completeness Rate (TCR)** — share of user requests reconstructable end-to-end from telemetry with no gaps |

We are not affiliated with Visa. VVAH is licensed under Apache-2.0; this project is an
independent implementation of the pattern in a different domain and is also released
under Apache-2.0.

## Why

For LLM products, the dominant failure class is not "the call failed" but "the call
succeeded and the output was bad": hallucination, irrelevant retrieval, silent context
truncation, instruction bypass. Classic APM sees green dashboards while the product
degrades. Observability for LLM systems therefore needs a domain model of its own —
traces, generations, retrieval spans, tool spans, feedback events, eval datasets —
plus governance over the telemetry itself (prompts and outputs are sensitive data).

The pipeline itself doesn't know it's about LLMs, though: S1–S3's mapping/gap-model
mechanics, the S4 ops lens (release identifiers, alert plan, decision menu), S5's
invariant gates, S7's runbook/roll-up structure, S8–S9's DTO and readiness-report
shapes, and S11's TCR/validation-ladder concept are domain-agnostic SRE engineering.
What's LLM-specific is concentrated in [docs/event-model.md](docs/event-model.md)
(the Generation/Retrieval entities S3 diffs against) and three of S4's eight lenses
(generation-capture, retrieval, realtime-multimodal) — call it the **GenAI domain
pack** the harness ships with. That's a scope choice, not an architectural limit:
LLM observability is where OTel semantic conventions and APM tooling are least
mature, so it's where a gap-modeling harness adds the most value first.

Retrofitting this by hand into an existing codebase is slow, inconsistent, and usually
stalls after the first dashboard. OAH turns it into a repeatable, reviewable,
agent-executed pipeline with human gates.

## Pipeline (4 phases, 11 stages)

| Phase | Stages | Purpose |
|---|---|---|
| **1 — Discovery & Modeling** | S1–S3 | Map the observability surface (LLM/retrieval/tool call sites), inventory existing telemetry, build a prioritized gap model with owner context |
| **2 — Design & Verification** | S4–S6 | Design instrumentation per lens (tracing, generation capture, retrieval, tools, feedback, PII/governance, cost); deterministic invariant gates; adversarial design review panel |
| **3 — Synthesis & Planning** | S7–S9 | Emit architecture doc, versioned event schema, rollout plan + runbook (ownership matrix, alert plan, decision menu), per-change implementation DTOs, and the production readiness report — the human gate with a six-way recommendation |
| **4 — Implementation & Validation** | S10–S11 | Apply instrumentation to source (agentic, per-change commits); dynamically validate — run the product, intercept emitted events, compute actual TCR and latency overhead; adversarial audit panel |

Detailed stage-by-stage description: [docs/architecture.md](docs/architecture.md).
Target telemetry domain model: [docs/event-model.md](docs/event-model.md).

## Planned CLI

```
oah doctor                          # check credentials, backends, repo access
oah estimate --repo ./product       # scope & cost estimate — spends nothing
oah map --repo ./product            # S1–S3 only: surface map + gap report (standalone audit)
oah design --repo ./product         # through S9: architecture + plan, no code changes
oah instrument --repo ./product     # S10, --mode report-only|fix
oah validate --repo ./product       # S11
oah scan --repo ./product           # full run; --stop-after s9 for analysis-only
oah resume <run_id>                 # continue a crashed or session-limit-terminated run
                                     # from its last completed unit of work
oah check-drift --repo ./product    # cheap staleness check against DTOs' retest_triggers,
                                     # no full pipeline re-run
```

> ⚠️ Following VVAH's convention and warning: a full run in fix mode **edits source
> files in the target repo**. `--mode report-only` and `--stop-after s9` are the
> non-mutating paths. Every applied change lands as an individual commit/PR for review.

`oah map` is intentionally a standalone deliverable: a one-shot observability audit of
a codebase has value even if you never proceed to instrumentation.

## Design principles

1. **Model before you design.** The gap model (S3) focuses all downstream work, the
   same way VVAH's threat model focuses vulnerability hunting.
2. **Skills, not a monolith.** Every LLM stage is a versioned skill with a declared
   input/output schema, testable in isolation against a reference corpus
   ([docs/SKILLS.md](docs/SKILLS.md)).
3. **Deterministic where possible, LLM where necessary.** AST scanning finds call
   sites; the LLM resolves ambiguity and designs. Invariant gates (S5) are pure code.
4. **OpenTelemetry as the transport floor.** Generated instrumentation targets OTel
   GenAI semantic conventions regardless of chosen backend, insuring the client
   against vendor lock-in. Opinionated backend targets (self-hosted Langfuse,
   OTel-only, managed) are selected by constraints, not fashion.
5. **Never claim more validation than performed.** S11 has an explicit degradation
   ladder (full dynamic → unit-level → generated smoke → `needs_review`);
   see [docs/validation.md](docs/validation.md).
6. **Telemetry is sensitive data.** PII masking, role-scoped access to trace content,
   and retention policy are first-class requirements, not add-ons
   ([docs/event-model.md](docs/event-model.md), [docs/security.md](docs/security.md)).
7. **Signals exist for decisions.** A health check says the service is reachable —
   not that users receive correct, approved, region- and role-appropriate, safely
   escalated answers. Every designed signal names the decision it supports and the
   role that acts; alerts no one owns are not created; evidence is judged by
   coverage class, not test count.
8. **Dogfooding.** Every OAH run emits a trace of its own stages in the very schema it
   installs for clients.
9. **Language and modality are plugins, not the core.** S1's registry and the S4
   design lenses are architected so a new source language (TypeScript, Java, ...)
   or a new call-site modality (voice, image) is an additive extension, not a
   pipeline rewrite — Python and text-first are the first concrete targets because
   a pilot needs one deep example, not because the architecture assumes them.

## Repository layout

```
docs/          architecture, event model, skills system, validation ladder, security
schemas/       JSON Schemas for inter-stage artifacts (the contract backbone)
skills/        skill drafts (SKILL.md per stage lens)
corpus/        reference repositories & eval fixtures for skill testing (planned)
ROADMAP.md     milestones, epics, spikes
```

## Requirements (planned)

- Python ≥ 3.11
- Models are configured per stage role through a [LiteLLM](https://www.litellm.ai/)
  abstraction layer — any provider or a local model (Ollama/vLLM) for skill stages;
  light-tier defaults for high-volume stages. The agentic stages S10–S11 require an
  Anthropic credential (Claude Code login or `ANTHROPIC_API_KEY`) — mirroring
  VVAH's Anthropic-only remediation/validation constraint. Enterprise deployments
  behind a private gateway supported via base-URL override + mTLS.
- The `claude` CLI for agentic stages (S10–S11)

## Limitations (read before you trust output)

- **LLM-generated, non-deterministic.** Designs and code changes are candidates
  requiring human review at the S9 gate and at every S10 commit.
- **Dynamic validation depends on the target's runnability.** If the product cannot be
  exercised (no tests, no compose, no smoke path), the best achievable verdict is
  `needs_review` — never `validated`.
- **Elevated privilege.** The harness reads source code that may contain prompts,
  keys, and data samples, and in fix mode edits it. Run only against repositories you
  own or are authorized to modify. See [docs/security.md](docs/security.md).
- **No accuracy numbers yet.** Skill precision/recall against the reference corpus
  will be published as the corpus lands (Epic E7).

## License

Apache License 2.0 — see [LICENSE](LICENSE) and [NOTICE](NOTICE).
