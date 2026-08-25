# Roadmap

Working agreement: epics are outcome-scoped units of work with a definition of done;
spikes are timeboxed research questions that de-risk epics and must produce a written
decision record in `docs/decisions/`. Sequencing below assumes one small team;
milestones are scope gates, not dates.

## Milestones

| Milestone | Outcome | Gate criterion |
|---|---|---|
| **M0 — De-risked** | All blocking spikes answered | Decision records for SP1–SP4 merged |
| **M1 — Auditor** | `oah map` produces a surface map + gap report on real repos | TCR-relevant call-site recall ≥ 90% on reference corpus (Python) |
| **M2 — Architect** | `oah design` emits architecture, event schema, rollout plan, DTOs | Two pilot products accept an S9 gate report with ≤ minor edits |
| **M3 — Implementer** | `oah instrument --mode fix` lands reviewable instrumentation | Instrumented reference repo passes its own test suite; events validate against schema |
| **M4 — Validator** | `oah validate` computes real TCR & overhead; adversarial panel runs | End-to-end run on a pilot product reaches `validated` verdict |

## Epics

### E1 — Pipeline core & operational shell
State DB (SQLite) with checkpoint/resume, per-run `run_manifest.json` (tool version,
model roles, config hash, target git SHA, timing), per-stage cost budgets, structured
artifact passing with schema validation at every stage boundary, `doctor` and
`estimate` commands. *DoD:* a crashed run resumes idempotently; every artifact in a
run validates against `schemas/`; `estimate` predicts cost within ±40% on corpus repos.
*Depends on:* SP5.

### E2 — Discovery (S1–S3)
Deterministic surface mapper for Python (AST + signature registry), LLM
disambiguation pass, telemetry inventory scanner, gap-model skill, owner-interview
stage producing `context.yaml`. **First target stack (pilot-driven): Python + raw
Anthropic SDK** — the Messages API call shapes incl. streaming and tool-use loops
get the first, deepest signature registry and `references/raw-sdk.md`; **LiteLLM**
follows immediately after (both as a call-site signature — `litellm.completion` /
proxy usage in target products — and as an S2 inventory item, since its built-in
callbacks/logging count as existing telemetry); LangChain / LlamaIndex / raw-HTTP /
vector-DB signatures follow as registry extensions.
*DoD:* M1 gate; false-positive rate < 10% on corpus; interview questions cover
PII/criticality/data-egress constraints. *Depends on:* SP1.

### E3 — Design lenses & verification (S4–S6)
Skills: tracing (incl. async/queue propagation), generation capture, retrieval, tools,
feedback loop, PII & governance, cost. Deterministic invariant gates (every surface
point covered; OTel GenAI semconv compliance; no plaintext PII fields; overhead budget
declared). Adversarial design panel (SRE / security / cost-skeptic personas).
*DoD:* design for a corpus repo passes gates; panel findings are reproducibly
categorized, not free-text. *Depends on:* E2, SP2, SP6.

### E4 — Synthesis (S7–S9)
Architecture doc generator, versioned event schema emitter, rollout planner (ordered
by workflow criticality from `context.yaml`), implementation-DTO generator, human
gate-review report (Markdown + machine-readable JSON). *DoD:* M2 gate; every DTO is
traceable to a gap-model entry and a surface-map point.

### E5 — Instrumentation (S10)
Claude Agent SDK executor applying DTOs: SDK/decorator insertion, collector config,
optional docker-compose for self-hosted backend; one commit per DTO;
`report-only`/`fix` modes; loud mutation warnings mirroring VVAH. *DoD:* M3 gate;
a failed DTO application rolls back cleanly and is recorded, not silently skipped.
*Depends on:* E4, SP4.

### E6 — Dynamic validation (S11)
Deterministic layer: run target tests; exercise the product (existing e2e / compose /
generated smoke scenario); intercept emitted events via local OTLP collector; validate
against event schema; compute actual TCR and latency overhead. Agentic layer:
adversarial panel (telemetry auditor: "reconstruct incident X from this trace";
privacy auditor: "find PII in real emitted events"). Verdicts `validated` /
`validation_failed` / `needs_review` with the degradation ladder from
`docs/validation.md`. *DoD:* M4 gate; verdict always states which ladder rung was
achieved. *Depends on:* E5, SP3.

### E7 — Reference corpus & skill evals
Curate open-source LLM apps across architectures (simple RAG chat, multi-agent
system, queue-based pipeline, TS/Node app for later), hand-label ground truth
(call sites, expected spans), eval runner scoring skill recall/precision, regression
suite in CI. *DoD:* every skill PR runs evals; published accuracy table in README.
*Starts alongside E2 — the corpus is the test bed for everything.*

### E8 — Security hardening of the harness
Secret-redaction in harness's own logs, directory allowlist, prompt-injection
resistance when reading target repos (treat repo content as data), private-gateway
mode (base URL + mTLS), threat model doc. *DoD:* red-team exercise on a corpus repo
seeded with injection payloads and fake secrets produces zero leaks/execution.
*Depends on:* SP7. *Runs continuously from M1.*

### E9 — Backend targets
OTel-only emitter (floor), self-hosted Langfuse target (compose + config generation),
constraint-driven backend selection in S7. *DoD:* same repo instrumentable to both
targets from the same DTOs. *Depends on:* SP6.

### E10 — Dogfooding & harness self-telemetry
OAH emits traces of its own stages in the schema it installs; a run is debuggable
from its own telemetry. *DoD:* an OAH incident is reconstructed from OAH traces alone.

### E11 — Second language: TypeScript/Node
Port S1 signature registry + AST layer; extend corpus. *Post-M4.*

## Spikes

| ID | Question | Timebox | Blocks | Output |
|---|---|---|---|---|
| **SP1** | Can AST + signature registry reach ≥90% recall on LLM call-site detection in Python, incl. dynamic dispatch and wrapper functions? Where exactly is the LLM pass required? | 1 wk | E2 | Decision record + prototype on 3 corpus repos |
| **SP2** | Catalog of trace-ID propagation patterns through async/celery/queues per framework; which are auto-instrumentable vs. require code-shape changes? | 1 wk | E3 | Pattern catalog in docs/ |
| **SP3** | Feasibility of the dynamic validation harness: reliably run an unfamiliar product (tests/compose/smoke), intercept OTLP locally, diff against schema. What % of corpus repos are runnable at each ladder rung? | 2 wk | E6 | Decision record + runnability matrix |
| **SP4** | Claude Agent SDK for code mutation: per-DTO commit discipline, rollback on failure, diff quality vs. plain prompting. | 1 wk | E5 | Decision record + demo branch |
| **SP5** | Cost model: predict run cost from repo size/complexity before spending. Accuracy target ±40%. | 3 d | E1 | estimate formula + calibration data |
| **SP6** | Maturity check: OTel GenAI semantic conventions — what's stable vs. experimental right now; gaps we must fill with `oah.*` extension attributes. | 3 d | E3, E9 | Convention mapping doc |
| **SP7** | Prompt-injection attack surface of a harness that reads hostile repo content; mitigation patterns (content/instruction separation, tool sandboxing). | 1 wk | E8 | Threat model section + test payload set |
| **SP8** | LiteLLM as the harness's model abstraction: per-role config (any provider incl. local Ollama/vLLM), streaming & tool-use parity for skill stages, cost-tracking hooks feeding `estimate`. Where does a light tier (Haiku-class / local) hold quality — measure S1-disambiguation and S2-inventory recall light-vs-frontier on corpus. S10/S11 stay Anthropic-pinned (Claude Agent SDK). | 1 wk | E1, E2 | Decision record + role/model matrix |

## Sequencing sketch

```
M0:  SP1 SP5 SP6 → SP2 SP4 SP7 → SP3
M1:  E1 ─┬─ E2 ── E7(start)
M2:      └─ E3 ── E4          E8(start, continuous)
M3:  E5
M4:  E6 ── E9 ── E10
post-M4: E11, managed-backend targets, non-Python frameworks
```

## Explicit non-goals (for now)

- Being an observability *backend* (storage/dashboards) — we install and configure
  existing ones.
- Runtime guardrails/content filtering — adjacent product; we only make their
  signals visible.
- Supporting closed/no-code LLM platforms where we cannot touch source.
