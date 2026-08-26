# Roadmap

Working agreement: epics are outcome-scoped units of work with a definition of done;
spikes are timeboxed research questions that de-risk epics and must produce a written
decision record in `docs/decisions/`. Sequencing below assumes one small team;
milestones are scope gates, not dates.

## Milestones

| Milestone | Outcome | Gate criterion | Status |
|---|---|---|---|
| **M0 — De-risked** | All blocking spikes answered | Decision records for SP1–SP4, SP10 merged | **Met** 2026-08-25 — [SP1](docs/decisions/003-sp1-ast-recall.md), [SP2](docs/decisions/006-sp2-trace-propagation-patterns.md), [SP3](docs/decisions/007-sp3-dynamic-validation-feasibility.md), [SP4](docs/decisions/005-sp4-agent-mutation.md), [SP10](docs/decisions/004-sp10-multilang-architecture.md). All ten spikes SP1–SP10 resolved. |
| **M1 — Auditor** | `oah map` produces a surface map + gap report on real repos | TCR-relevant call-site recall ≥ 90% on reference corpus (Python) | **In progress**, started 2026-08-25. Real `oah` CLI (`doctor`/`estimate`/`map`/`inventory`/`gaps`/`interview`): tree-sitter S1 (LLM disambiguation wired to a real LiteLLM call, SP8's frontier default), S2, S3 (deterministic join + real interactive owner-interview → `context.yaml`, wired into gap priority weighting), state DB + checkpoint/resume, run_manifest.json. **E7's first corpus fixtures now exist** (`corpus/`: 3 vendored, permissively-licensed repos incl. a queue-based Celery fixture filling the gap SP1's decision record flagged) with `oah/eval_corpus.py` scoring the gate's own metric — 91.7% deterministic recall / 100% coverage (nothing silently dropped), asserted in CI (`.github/workflows/test.yml`). Still thin — 3 fixtures, 12 ground-truth points — not yet the broader corpus E7 ultimately wants (retrieval-heavy, TS/Java once E11 starts). 65 tests passing. |
| **M2 — Architect** | `oah design` emits architecture, event schema, rollout plan, DTOs | Two pilot products accept an S9 gate report with ≤ minor edits | **Build complete, DoD not yet evaluated** (2026-08-25). Full S1→S9 vertical slice real, tested, and wired end to end (`oah design`, `event-schema`, `dtos`, `readiness`); every stage states its own scope boundary rather than silently presenting partial output as finished. **S1** detects 5 surface-point kinds via a generalized registry list (`oah/discovery/registry.py`): `llm_generation` (anthropic), `retrieval` (pinecone), `feedback_ingest` (langsmith), `realtime_session` (livekit — needed a new import-tracking shape, `from pkg import submodule`), `tool_call` (a structural pattern match — `<expr>.type == "tool_use"` — not a resolved SDK call, since tool dispatch is application code, not an SDK method); also determines `sync_nature` (async/sync) from tree-sitter's own `async` token. Each detector's real-world-fit tradeoffs (suffix genericity, which import/call shape is/isn't supported) are stated in the module docstrings, not glossed over; corpus recall unregressed at every step. **S4**: all 9 lenses built — generation-capture (SP6-verified `gen_ai.*` attributes) plus 8 lenses that are all `oah.*` extensions only (pii-governance, cost, ops, retrieval, feedback, realtime-multimodal, tracing, tools), each narrower than architecture.md's full per-lens ask and each SKILL.md says exactly where (tracing: one signal, everything but same-process-asyncio is "unverified"; tools: locates dispatch sites, not the handler/arguments/result inside them). Tracing is the first cross-cutting lens (not scoped to one point kind — `LENS_TO_POINT_KIND["tracing"] = None` means "every point"), verified with positive *and* negative gate-check controls. Wiring the first non-`llm_generation` lens caught a real cross-kind gate-checking bug (fixed, confirmed by reverting and watching the regression test fail as predicted). **S5** gates fully built (pure code). **S6**: all 3 personas built (cost_skeptic, sre, security). **S7** event-schema merge fully built (pure code). **S8** DTO rollout_step follows architecture.md's real workflow-criticality ordering from `--context`, falling back to gap-priority ordering without it — fixed two prerequisite gaps to make this actually reachable (`gap_model.py` silently dropping non-generation-capture points; `oah dtos` missing `--context` entirely). **S9** readiness report is deterministic assembly, capped at `ready_with_conditions` (no S10/S11 evidence exists at this stage). A late sweep for stale partial-scope language caught one real bug, not just copy-edits: `readiness_report.py` still unconditionally claimed gap-priority-only ordering after S8 started using the real rule — now conditional on whether `--context` was actually supplied. What M2's DoD still needs: real LLM evaluation against two pilot products (blocked in this dev environment — no `ANTHROPIC_API_KEY` — every LLM-wired path here is tested via mocked `_completion_fn` only, never against a live model). **Adversarial self-review pass** (4 parallel agents over S1/S4/S5-S9/CLI, since no API key means no live-model testing is possible): found and fixed 8 real bugs the mocked-test-fixture pattern had been masking — 3 in S1's tool_use dispatch detector and lambda is_async threading, 3 in S5/S6/S9 (a missing reverse-direction phantom-point gate, a persona `overall` never cross-checked against its own `findings`, an unused `dtos` parameter causing an overclaimed rollout-ordering statement), a systemic prompt gap (no SKILL.md across all 9 lenses ever asked the model to set `latency_overhead_budget_ms`, which S5 blocks on), and a CLI `--context` gap on `event-schema` — plus a structural fix (`_design_all_lenses`/`_run_all_personas` shared helpers with a loud assertion) that closes the specific 4-way-copy-paste bug class for good, not just the latest instance of it. 270 tests passing. |
| **M3 — Implementer** | `oah instrument --mode fix` lands reviewable instrumentation | Instrumented reference repo passes its own test suite; events validate against schema | **In progress**, started 2026-08-26. `oah instrument` real in both modes: first use of the Claude Agent SDK in this repo (SP4's spike used Claude Code's own agent mechanism, not the standalone SDK — this is genuinely new integration), covers 4 of `implementation_dto.schema.json`'s 13 `change.type` values (`wrap_call`, `add_decorator`, `insert_span`, `propagate_context` — pure source edits; the 9 infra-generating types wait on S11's collector design), per-DTO checkpointing/resume via `state_db.py` (`stage_id="s10-{mode}"`, mode-scoped so a report-only and a fix run sharing a `--run-id` can't reuse each other's differently-shaped checkpoint). The agent gets `tools=["Read"]` only in both modes — a hard, SDK-enforced restriction per `docs/security.md` T4, not prompt trust — and returns proposed file content, never a self-formatted diff; `report-only` diffs it via `difflib` and never writes; `fix` writes it and creates one git commit per DTO, gated on a recorded S9 `ready`/`ready_with_conditions` decision and a clean target working tree (both checked before any DTO is touched), with any failure past verification (syntax-invalid content, a rejected `git commit`) rolling back to `HEAD` and recorded as `failed`, never a half-applied file. Verified end to end with a real S1→S8-generated `implementation_dto.json` and a real `build_readiness_report()`-produced readiness report (LLM/agent calls mocked): report-only leaves the target repo byte-for-byte unchanged; fix mode produces exactly one real git commit with the exact proposed content, confirmed via `git log`/`git show`/`git status --porcelain`, including a real rollback under an actual rejected commit (a `pre-commit` hook returning nonzero) restoring the file and leaving no trace. What's still unverified: the real Claude Agent SDK call itself, live, since this dev environment has no `ANTHROPIC_API_KEY` -- and M3's actual DoD (a real reference-corpus repo, actually instrumented, its own test suite actually passing) hasn't been attempted, only the underlying mechanism. |
| **M4 — Validator** | `oah validate` computes real TCR & overhead; adversarial panel runs | End-to-end run on a pilot product reaches `validated` verdict | **In progress**, started 2026-08-26. `oah validate` real at the ladder's static floor only: R4 ("schema conformance of code-level emission points only") — for each DTO `oah instrument --mode fix` actually applied, does `change.file` contain every `expected_events[].required_attributes` name at or after the DTO's own anchor line. No product execution, no OTLP collector (confirmed zero such code exists anywhere in this repo before starting), no agentic panel, no TCR — verdict fixed at `needs_review` (R4's own table ceiling, never `validated`), by design: this rung can only claim "this string appears in the code," never that telemetry actually fires. Deliberately the smallest rung, chosen because R1-R3 all require running target-repo content (the product itself, or its test suite) — real execution of hostile-repo content (`docs/security.md` T1), which SP3's own findings (0/6 spike repos confirmed R1-capable) say is fragile even before considering safety; R4 needs none of that. Verified end to end through the real S1->S8->S10(fix)->S11 chain twice (LLM/agent calls mocked): once with agent-produced code that does contain the expected attribute (`present`), once with code that deliberately doesn't (`absent`, missing attribute correctly named) -- proving the wiring both ways, not just the happy path. A real gap surfaced while building this: `skills/s10-instrumenter/SKILL.md` never told the agent which telemetry API to actually call, so a live S10 run today has no guarantee of producing code an eventual R1-rung OTLP collector could intercept -- flagged, not yet fixed. R1-R3, the collector, the agentic panel, and TCR remain fully unbuilt. |

## Epics

### E1 — Pipeline core & operational shell
State DB (SQLite) with checkpoint/resume, per-run `run_manifest.json` (tool version,
model roles, config hash, target git SHA, timing), per-stage cost budgets, structured
artifact passing with schema validation at every stage boundary, `doctor` and
`estimate` commands. Checkpoint granularity is sub-stage, not just stage-boundary:
S10 checkpoints per applied DTO, S11 per completed scenario/panel-question, and any
long agentic stage that hits a token/session-budget wall (not just a crash) must be
resumable from the last completed unit of work via `oah resume <run_id>` — this was
a specific pain point in VVAH (no way to pick back up mid-stage after hitting a
session limit) that OAH must not repeat. *DoD:* a crashed OR session-limit-terminated
run resumes idempotently from its last completed unit of work; every artifact in a
run validates against `schemas/`; `estimate` predicts cost within ±40% on corpus repos.
*Depends on:* SP5.

### E2 — Discovery (S1–S3)
Deterministic surface mapper built as a **per-language pluggable registry from day
one** (architecture decided by SP10, not re-derived when the second language lands),
LLM disambiguation pass, telemetry inventory scanner, gap-model skill, owner-interview
stage producing `context.yaml`. **First target stack (pilot-driven): Python + raw
Anthropic SDK** — the Messages API call shapes incl. streaming and tool-use loops
get the first, deepest signature registry and `references/raw-sdk.md`; **LiteLLM**
follows immediately after (both as a call-site signature — `litellm.completion` /
proxy usage in target products — and as an S2 inventory item, since its built-in
callbacks/logging count as existing telemetry); LangChain / LlamaIndex / raw-HTTP /
vector-DB signatures follow as registry extensions. Python-only scope at the M1 gate
is deliberate — one concrete, deep registry proves the pipeline — not a statement
that other stacks are secondary; see E11 for the mainstream-language follow-on,
sequenced immediately after M1 rather than deferred to post-M4.
*DoD:* M1 gate; false-positive rate < 10% on corpus; interview questions cover
PII/criticality/data-egress constraints; the registry interface has at least one
non-Python language plugged in against SP10's abstraction before M2, proving it
holds. *Depends on:* SP1, SP10.

### E3 — Design lenses & verification (S4–S6)
Skills: tracing (incl. async/queue propagation), generation capture, retrieval, tools,
feedback loop, PII & governance, cost, **realtime & multimodal** (turn-taking/
interruption latency for live voice, transcription/recognition error rate, media
consent/retention/derived-artifact visibility, fallback across channels — see
`realtime_session` in `surface_map.schema.json` and the `modality` attribute on the
Generation entity in [event-model.md](docs/event-model.md)). This lens is on the
roster from the start, not a deferred bolt-on — the event model is designed
modality-neutral now precisely so a text-only first registry doesn't require a
schema migration when voice/image call sites are added. Deterministic invariant
gates (every surface point covered; OTel GenAI semconv compliance; no plaintext PII
fields; overhead budget declared). Adversarial design panel (SRE / security /
cost-skeptic personas).
*DoD:* design for a corpus repo passes gates; panel findings are reproducibly
categorized, not free-text. *Depends on:* E2, SP2, SP6.

### E4 — Synthesis (S7–S9)
Architecture doc generator, versioned event schema emitter, rollout planner (ordered
by workflow criticality from `context.yaml`), implementation-DTO generator, human
gate-review report (Markdown + machine-readable JSON). `runbook.md` includes a
drill cadence and the post-incident retrospective process (architecture.md S7) —
resolved escalations with a named `preventative_action` feed back into the next
S3 gap model and E7's eval dataset, closing the design loop, not just the
incident. *DoD:* M2 gate; every DTO is traceable to a gap-model entry and a
surface-map point.

### E5 — Instrumentation (S10)
Claude Agent SDK executor applying DTOs: SDK/decorator insertion, collector config,
optional docker-compose for self-hosted backend; one commit per DTO;
`report-only`/`fix` modes; loud mutation warnings mirroring VVAH. *DoD:* M3 gate;
a failed DTO application rolls back cleanly and is recorded, not silently skipped.
*Depends on:* E4, SP4.

**Both modes landed** (2026-08-26): `oah instrument`, `oah/instrument/executor.py`,
`skills/s10-instrumenter/`. 4 of 13 `change.type` values (pure source edits only —
the 9 infra-generating types depend on E6's collector design, not built here).
Per-DTO checkpointing via `state_db.py` (`stage_id="s10-{mode}"`, mode-scoped so
report-only and fix runs sharing a `--run-id` never reuse each other's differently-
shaped checkpoint). The agent session gets `tools=["Read"]` only in *both* modes —
a hard, SDK-enforced restriction, not prompt trust — and always returns proposed
file content, never a self-formatted diff.

`report-only`: `oah` computes the diff itself via `difflib` against the file it
already read; never writes to the target repo.

`fix`: writes the file and creates exactly one git commit per DTO. Gated on two
preconditions checked before any DTO is touched (`cmd_instrument`, not
executor.py, which has no opinion on whether a run should start): a
`--readiness readiness_report.json` whose `recommendation.decision` is `ready` or
`ready_with_conditions` (architecture.md's own rule), and a clean git working tree
in the target repo. SP4's own evidence for post-edit rollback was thinner than for
pre-edit refusal, so it was verified deliberately, not assumed: a real rejected
`git commit` (a `pre-commit` hook returning nonzero) correctly restores the file to
`HEAD` and records `status: "failed"`, confirmed via `git log`/`git status
--porcelain` showing no trace left behind, same for syntax-invalid agent output
(never committed at all). Fix mode's own open policy question from SP4's decision
record -- whether the agent may ever autocorrect an ambiguous DTO instead of
refusing -- resolved as: never, same hard rule as report-only, since writing to
disk doesn't make a guessed edit safer.

### E6 — Dynamic validation (S11)
Deterministic layer: run target tests; exercise the product (existing e2e / compose /
generated smoke scenario); intercept emitted events via local OTLP collector; validate
against event schema; compute actual TCR and latency overhead. Agentic layer:
adversarial panel (telemetry auditor: "reconstruct incident X from this trace";
privacy auditor: "find PII in real emitted events"). Verdicts `validated` /
`validation_failed` / `needs_review` with the degradation ladder from
`docs/validation.md`, **plus the environment the evidence came from** (per SP9's
data model) so a `validated` verdict in a throwaway sandbox is never presented the
same way as one from staging or production-shadow. **`oah check-drift`** — a
standalone, cheap command — runs two non-agentic checks without re-running the
full pipeline: stale evidence (each DTO's `retest_triggers` vs. current repo
state) and **orphaned instrumentation** (each DTO's `surface_point_ids` vs. a
fresh deterministic-only S1 pass — flags a DTO whose call site was refactored
away, per `docs/validation.md`'s Staleness section). The runbook (S7) also names
a **drill cadence** so the corpus tabletop walkthrough and the fail-open
collector-kill check rerun on a schedule, not only once at S11. *DoD:* M4 gate;
verdict always states which ladder rung was achieved and which environment
produced it; `check-drift` correctly flags both staleness and an orphaned DTO on
a corpus repo seeded with a post-validation prompt/schema change and a removed
call site, respectively. *Depends on:* E5, SP3, SP9.

**R4 slice landed** (2026-08-26): `oah validate`, `oah/validate/checker.py`,
`schemas/validation_report.schema.json`. Static-only: given the DTOs
`oah instrument --mode fix` actually applied, checks each one's expected
attribute names appear in its target file at or after its own anchor line.
`ladder_rung`/`verdict` are consts (`"R4"`/`"needs_review"`) for this slice —
R4's own table entry says never `validated`, a hard ceiling, not situational.
No OTLP collector, no product execution, no agentic panel, no TCR, no
`environment` field (meaningless without real runtime evidence to say what
environment it came from) — all explicitly deferred, matching E5's own
"smallest honest slice first" precedent, for the same reason: R1-R3 need
either a real running product or its test suite, i.e. executing hostile-repo
content, a materially bigger security surface (T1) that SP3's own findings
say is fragile even before considering safety.

### E7 — Reference corpus & skill evals
Curate open-source LLM apps across architectures (simple RAG chat, multi-agent
system, queue-based pipeline) and, once SP10 lands, across languages (Python first;
a TypeScript/Node and a Java fixture follow immediately, not deferred — otherwise
E11's registries have no eval signal). Add a realtime/voice or image-input fixture
once `lens-realtime-multimodal` is buildable, so that lens isn't shipped
unevaluated. Hand-label ground truth (call sites, expected spans), eval runner
scoring skill recall/precision, regression suite in CI. *DoD:* every skill PR runs
evals; published accuracy table in README, broken out per language once more than
one is registered. *Starts alongside E2 — the corpus is the test bed for everything.*

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

### E11 — Mainstream language coverage: TypeScript/Node, Java
Python-only would cede most of the enterprise LLM-app market, where a large share
of production API/backends are TS/Node or Java/Spring. Port the S1 signature
registry + call-site detection layer to each per SP10's language-agnostic
abstraction; extend the corpus (E7) per language as it lands. Priority order and
rationale: **1. TypeScript/Node** — dominant for LLM-facing backends and the
Vercel AI SDK / LangChain.js ecosystem, closest in call-shape to the Python raw-SDK
registry already built; **2. Java** — dominant in regulated-enterprise backends
(finance, healthcare, public sector) that are exactly OAH's stated vertical context
in `context.yaml`, but a heavier lift (Spring AI / LangChain4j patterns, different
async model). Go and C#/.NET are stretch candidates, sequenced only after SP10's
abstraction survives two real languages, not designed for speculatively now.
*DoD:* TS/Node registry reaches E2's M1 recall/FP bar on a TS corpus fixture before
M2 closes; Java follows using the same bar, timeboxed independently so a slow Java
port doesn't block M2. *Depends on:* SP10, E2. *Starts immediately after SP10's
decision record lands — not deferred to post-M4.*

### E12 — Second domain pack *(stub, post-M4)*
Proves — or disproves — the pipeline-core/domain-pack split from README's "Why":
port S3's reference domain model and S4's three GenAI-specific lenses
(generation-capture, retrieval, realtime-multimodal) to one concrete non-LLM
domain, without touching S1–S2, S5–S11, or the DTO/schema-as-truth mechanics.
Candidate domain and lens replacements are not chosen yet — picking one now would
be designing the abstraction before a second real instance tests it, the same
mistake SP10 already avoids for languages by requiring two. *DoD:* the second
domain pack reaches the M2-equivalent gate (design passes S5/S6 on a corpus repo
in that domain) while changing zero pipeline-core files outside the
`event-model.md`-equivalent and the swapped S4 lenses — if pipeline-core needs
edits to fit the second domain, that itself is the finding, not a failure.
*Depends on:* M4 (GenAI domain pack proven end-to-end first).

## Spikes

All ten spikes are resolved as of 2026-08-25 — see `docs/decisions/`. Every
record includes its honest limitations (sample size, untested scope,
stretch items deferred); resolved does not mean zero remaining risk, it
means the question has a real, evidence-grounded answer instead of an
assumption blocking the dependent epic.

| ID | Question | Timebox | Blocks | Output | Resolved |
|---|---|---|---|---|---|
| **SP1** | Can AST + signature registry reach ≥90% recall on LLM call-site detection in Python, incl. dynamic dispatch and wrapper functions? Where exactly is the LLM pass required? | 1 wk | E2 | Decision record + prototype on 3 corpus repos | [003](docs/decisions/003-sp1-ast-recall.md) — 17/17 real sites, 100% recall |
| **SP2** | Catalog of trace-ID propagation patterns through async/celery/queues per framework, **plus long-running background jobs** (e.g. Deep Research / batch-style calls that run tens of minutes via polling or webhook completion rather than a queue hop) — how does a trace stay correlated from submission to a completion event that may arrive in a different process/session entirely? Which are auto-instrumentable vs. require code-shape changes? | 1 wk | E3 | Pattern catalog in docs/ | [006](docs/decisions/006-sp2-trace-propagation-patterns.md) — [catalog](docs/trace-propagation-patterns.md) |
| **SP3** | Feasibility of the dynamic validation harness: reliably run an unfamiliar product (tests/compose/smoke), intercept OTLP locally, diff against schema. What % of corpus repos are runnable at each ladder rung? | 2 wk | E6 | Decision record + runnability matrix | [007](docs/decisions/007-sp3-dynamic-validation-feasibility.md) — [matrix](docs/runnability-matrix.md) |
| **SP4** | Claude Agent SDK for code mutation: per-DTO commit discipline, rollback on failure, diff quality vs. plain prompting. | 1 wk | E5 | Decision record + demo branch | [005](docs/decisions/005-sp4-agent-mutation.md) |
| **SP5** | Cost model: predict run cost from repo size/complexity before spending. Accuracy target ±40%. | 3 d | E1 | estimate formula + calibration data | [002](docs/decisions/002-sp5-cost-model.md) — formula unverified pending real runs |
| **SP6** | Maturity check: OTel GenAI semantic conventions — what's stable vs. experimental right now; gaps we must fill with `oah.*` extension attributes. | 3 d | E3, E9 | Convention mapping doc | [001](docs/decisions/001-sp6-otel-genai-semconv-maturity.md) — everything is Development stability |
| **SP7** | Prompt-injection attack surface of a harness that reads hostile repo content; mitigation patterns (content/instruction separation, tool sandboxing). | 1 wk | E8 | Threat model section + test payload set | [008](docs/decisions/008-sp7-prompt-injection.md) — [threat model](docs/security-threat-model.md) |
| **SP8** | LiteLLM as the harness's model abstraction: per-role config (any provider incl. local Ollama/vLLM), streaming & tool-use parity for skill stages, cost-tracking hooks feeding `estimate`. Where does a light tier (Haiku-class / local) hold quality — measure S1-disambiguation and S2-inventory recall light-vs-frontier on corpus. S10/S11 stay Anthropic-pinned (Claude Agent SDK). | 1 wk | E1, E2 | Decision record + role/model matrix | [009](docs/decisions/009-sp8-litellm-model-abstraction.md) — S2 untested |
| **SP9** | Environment provenance: how does OAH determine — not just accept on trust — which environment (sandbox / staging / production-shadow / production) a validation run's evidence actually came from? Compare: (a) a self-reported CLI flag (weak, unverified), (b) parsing IaC/CI config already in the product repo (Terraform/Helm/k8s manifests, deploy workflows) to infer environment from what's being targeted, (c) accepting a second, separately supplied infra/IaC repo path for cross-reference, (d) cloud-API introspection at run time. Recommend an MVP for the M4 gate vs. what's a stretch worth its own future epic (e.g. a dedicated IaC-assessment sub-pipeline). Must also decide the data model: does environment live on the run manifest only, or per-trace/per-verdict, and how is self-reported-and-unverified visually distinguished from corroborated in the S9 report? | 1.5 wk | E6, E4 | Decision record + environment-provenance data model | [010](docs/decisions/010-sp9-environment-provenance.md) |
| **SP10** | Multi-language surface-mapping architecture: what's the language-agnostic intermediate call-site representation that lets S1 add a new language (TypeScript/Node, Java, then Go/.NET as stretch) without touching pipeline core or the S3+ skills downstream of it? Compare a unified tree-sitter-based parse layer across all languages vs. native per-language parsers (Python `ast`/`libcst`; TypeScript `ts-morph`/compiler API; Java `javaparser`/tree-sitter) behind a common adapter interface. Prototype must prove the abstraction on **two** real languages (Python + TypeScript), not one — a single-language prototype doesn't test whether the abstraction actually generalizes. | 1.5 wk | E2, E11 | Decision record + two-language prototype | [004](docs/decisions/004-sp10-multilang-architecture.md) — 21/21 across both languages |

## Sequencing sketch

```
M0:  SP1 SP5 SP6 SP10 → SP2 SP4 SP7 SP9 → SP3   [all resolved 2026-08-25]
M1:  E1 ─┬─ E2 ── E7(start)
     E11 (TS/Node) starts right after M1, Java follows on its own timebox
M2:      └─ E3 ── E4          E8(start, continuous)
M3:  E5
M4:  E6 ── E9 ── E10
post-M4: managed-backend targets, Go/.NET (if SP10's abstraction earns it),
         E12 (second domain pack, if pursued)
```

## Explicit non-goals (for now)

- Being an observability *backend* (storage/dashboards) — we install and configure
  existing ones.
- Runtime guardrails/content filtering — adjacent product; we only make their
  signals visible.
- Supporting closed/no-code LLM platforms where we cannot touch source.
- Retargeting the pipeline to non-AI/non-LLM products. The S1–S11 orchestration
  and DTO/schema-as-truth mechanics are domain-agnostic by construction (see
  README's "Why") — what's LLM-specific is concentrated in `event-model.md` and
  three of S4's eight lenses — but that portability isn't being exercised or
  promised until one domain (GenAI) is dogfooded end-to-end through M4. Stubbed
  as E12, not scheduled.
