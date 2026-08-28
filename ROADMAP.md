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
| **M4 — Validator** | `oah validate` computes real TCR & overhead; adversarial panel runs | End-to-end run on a pilot product reaches `validated` verdict | **In progress**, started 2026-08-26. `oah validate` real at the ladder's static floor only: R4 ("schema conformance of code-level emission points only") — for each DTO `oah instrument --mode fix` actually applied, does `change.file` contain every `expected_events[].required_attributes` name at or after the DTO's own anchor line. No product execution, no OTLP collector (confirmed zero such code exists anywhere in this repo before starting), no agentic panel, no TCR — verdict fixed at `needs_review` (R4's own table ceiling, never `validated`), by design: this rung can only claim "this string appears in the code," never that telemetry actually fires. Deliberately the smallest rung, chosen because R1-R3 all require running target-repo content (the product itself, or its test suite) — real execution of hostile-repo content (`docs/security.md` T1), which SP3's own findings (0/6 spike repos confirmed R1-capable) say is fragile even before considering safety; R4 needs none of that. Verified end to end through the real S1->S8->S10(fix)->S11 chain twice (LLM/agent calls mocked): once with agent-produced code that does contain the expected attribute (`present`), once with code that deliberately doesn't (`absent`, missing attribute correctly named) -- proving the wiring both ways, not just the happy path. A real gap surfaced while building this: `skills/s10-instrumenter/SKILL.md` never told the agent which telemetry API to actually call, so a live S10 run today has no guarantee of producing code an eventual R1-rung OTLP collector could intercept -- flagged, not yet fixed. R1-R3, the collector, the agentic panel, and TCR remain fully unbuilt. **E10 also landed** (2026-08-26): every real LLM/Agent-SDK call OAH's own pipeline makes now emits a real `opentelemetry-sdk` span to `.oah/traces/oah.jsonl` — see E10's own entry below for what's covered and verified. **E9's config-generation slice also landed** (2026-08-26): `oah backend-config` generates a real, verified `otel-collector-config.yaml` for either target (deterministic, no LLM/agent call at all) — E9's own entry below covers what's built and what's deferred (constraint-driven selection, which is blocked on S7's own unbuilt LLM synthesis, not just deprioritized). **E6 R2's sandbox execution mechanism also landed** (2026-08-26): `oah/validate/sandbox.py`/`pytest_runner.py` run a real target's real `pytest` suite inside a network-isolated, resource/timeout-bounded Docker container — the user explicitly chose this sandboxing approach, resolving the open question the previous version of this row named. Proven against real containers (passing suite, failing suite, a real network-escape attempt blocked, a real timeout kill, confirmed cleanup) both in this environment and in CI. **Wired into `oah validate --dynamic`** (2026-08-26): reuses the sandbox as `docs/validation.md`'s own deterministic-layer regression gate ("instrumentation must not break the product"), independent of ladder rung — a real test failure now sets `verdict: validation_failed`, genuinely new vocabulary the schema never emitted before (`verdict` is an `enum` now, not a `const`). `skills/s10-instrumenter/SKILL.md` was then fixed to name a concrete telemetry API (`opentelemetry.trace`), removing that blocker, and **real R2's first half landed** (2026-08-26): `oah/validate/event_assertion.py` + `oah/validate/dynamic.py` capture what S10-instrumented code actually emits at runtime (via OpenTelemetry's own `opentelemetry-instrument` bootstrap tool, empirically verified against a real container — it silently no-ops without `opentelemetry-distro` installed too) and assert each DTO's expected event was observed on a single real captured span, over the same one sandboxed run as the regression gate. `ladder_rung` at that point still stayed `"R4"` — the ladder table defines R2 as event-emission assertion **and** a static trace-ID-propagation check together, and only the first half was built yet. **Real R2 fully landed two commits later** (2026-08-26): `oah/validate/propagation_checker.py` (the static propagation-boundary check, classified heuristically from `change.description`'s free text per the S10 skill's own three taught boundary shapes) and `oah/validate/verdict.py`'s `compute_ladder_verdict` — the first code in this project able to compute `ladder_rung: "R2"` / `verdict: "validated"` at all, deliberately conservative (requires `--dynamic`, a passed regression gate, at least one applied DTO, and every applicable DTO's relevant check passing). Proven with a real Docker end-to-end case: a real target instrumented per the S10 skill's own pattern, actually applied, reaches `ladder_rung: "R2"` / `verdict: "validated"` through the real `oah validate --dynamic` pipeline. **Real R1 landed next** (2026-08-26, across several further phases): a real execution mechanism (`oah/validate/live_sandbox.py` — a real running target service alongside a real local OTel collector on an internet-isolated Docker network), real TCR (`oah/validate/tcr.py`, `docs/architecture.md`'s own primary metric — share of captured traces reconstructable end-to-end with no missing spans), and a real baseline-vs-instrumented latency-overhead-vs-budget comparison (`oah/validate/baseline.py`/`overhead.py`, using a real `git worktree` at the pre-instrumentation SHA) — tied together in `compute_ladder_verdict`, which now promotes all the way to `ladder_rung: "R1"` / `verdict: "validated"` for real. Proven with `oah validate --dynamic --live --baseline` combined in one real invocation (`tests/test_cli_validate_r1_promotion.py`) — every mechanism this M4 effort built (R2's sandbox, R1's live sandbox, the baseline comparison) proving out *together*, not each in isolation. This closes M4's own gate condition text for both the R2 *and* R1 rungs — **still not** M4 fully done: R3 (generated smoke) and the agentic panel need a live LLM call, blocked in this dev environment by the missing `ANTHROPIC_API_KEY`, not by anything buildable; `event_schema.json`'s semantic invariant checks and the "behavioral rates" metric remain deferred; and a genuine reference-corpus repo (not a hand-built fixture) reaching `validated` hasn't been attempted — SP3's own finding (0/6 vetted corpus repos are even R1-capable) means this can't be attempted against a real one in this environment either. |

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

**Telemetry-API gap fixed** (2026-08-26): `skills/s10-instrumenter/SKILL.md`
previously left the emission library entirely up to the agent's own judgment
("wrap the existing call site with a context manager/span"), which meant a
live S10 run had no guarantee of producing runtime-observable code — flagged
in M4's own status note, surfaced again while scoping E6 R2's wiring (real R2
needs to capture what a DTO actually emits, and there was nothing predictable
to capture). Fixed by naming one concrete API for all four `change.type`
values: `opentelemetry.trace` (`tracer.start_as_current_span(...)` +
`span.set_attribute(...)` for every `expected_events[].required_attributes`
entry, with a real runtime value, never a hardcoded placeholder — refuse
instead if no real value is available), plus `opentelemetry.context` for
`propagate_context` boundaries that don't already share a `contextvars`
context (noting `asyncio.create_task` already does, so needs no explicit
code). Prompt-content only, no schema/Python change, no version bump (same
precedent as the earlier systemic S4 `latency_overhead_budget_ms` prompt-gap
fix). **A new, real, named gap this surfaces**: `implementation_dto.schema.json`'s
13 `change.type` values have no `add_dependency` type, so applying a DTO
never ensures the target repo actually has `opentelemetry-api` installed —
if it doesn't, the instrumented import fails at runtime. This is exactly
what `oah validate --dynamic`'s regression gate (E6, below) is designed to
catch (a real, honest `validation_failed`, not a silent gap), but the DTO
pipeline itself doesn't yet add the dependency proactively — not attempted
here, named for a future pass. Real capture/assertion of these now-predictable
spans (R2's own actual defining check) is still not built — this phase only
removes the blocker that made it impossible to build honestly.

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

**R2 sandbox mechanism landed** (2026-08-26): `oah/validate/sandbox.py`
(`run_in_sandbox`) and `oah/validate/pytest_runner.py`
(`detect_pytest_suite`/`run_pytest_suite`) — the execution primitive R2
needs, built and proven standalone. Per the user's explicit choice, isolation is Docker-based: a throwaway image built
once from the target repo (`COPY . /repo` at `docker build` time; the
running container has no bind mount back to the host at all), then run with
`--network none`, bounded `--memory`/`--cpus`/`--pids-limit`, and a wall-clock
timeout, with unconditional `docker rm -f`/`docker image rm -f` cleanup in a
`finally` block regardless of how the run ended. A real finding shaped the
design: dependency installation (`pip install`) genuinely needs network,
which conflicts with running the target's own test code network-isolated —
resolved by splitting `run_in_sandbox` into a `setup_script` (baked into the
image as a `RUN` instruction at `docker build` time, has network) and the
run-time `script` (network-isolated), so installs happen before any target
code executes, never during. `pytest_runner`'s own install path is grounded
in `docs/runnability-matrix.md`'s real `beacon` finding: try
`pip install -e ".[dev]"` first, fall back to `pip install -r requirements.txt`
+ `pip install pytest` (no editable install) on failure. Four honest
outcomes only: `passed`, `failed` (with pytest's own parsed pass/fail counts
when its summary line is parseable, never fabricated), `install_failed`,
`no_tests_found` (never spins up a container for a repo with nothing to
test). Proven against real containers in `tests/test_sandbox_docker.py`, not
assumed from the flags: a real passing suite, a real failing suite, a real
network-escape attempt (`socket.create_connection` to `8.8.8.8`) actually
blocked, a real timeout kill leaving no container behind, and cleanup
confirmed via real `docker image ls`/`docker ps -a` calls before and after —
this file skips cleanly (not a failure) wherever no Docker daemon is
reachable, but runs for real in this environment and, since GitHub-hosted
`ubuntu-latest` runners ship Docker preinstalled, in CI too. Explicitly not
attempted: distinguishing a real test suite from a decoy (`claude-engineer`'s
`test.py` case from the runnability matrix — a hard, likely
unsolvable-in-general problem); non-Python targets (S1 itself doesn't detect
surface points outside Python yet); R1 (live traffic against a running
product) and R3 (generated smoke) — both bigger asks than R2 even with
sandboxing solved.

**Regression gate wired into `oah validate --dynamic`** (2026-08-26):
`oah/validate/regression_gate.py` reuses the sandbox mechanism above for
`docs/validation.md`'s own "Deterministic layer (runs first, always)"
step 1 — "instrumentation must not break the product" — which the ladder
table itself treats as independent of rung, not a re-badging of R4 or a
claim of real R2. `ladder_rung` stays `"R4"` (`const`, unchanged) even
with `--dynamic`: real R2 needs its own defining check (assert each DTO's
expected telemetry event is actually emitted at runtime), which at this
point in the session was still blocked on `skills/s10-instrumenter/SKILL.md`
never naming a concrete telemetry API for the agent to call — the same
gap M4's status note already flagged (fixed two commits later; see below).
What `--dynamic` does add here is real: `verdict` grew a
genuinely new value, `validation_failed` (`schemas/validation_report.schema.json`'s
`verdict` is now an `enum`, not a `const`) — set only when the sandbox
actually ran the target's test suite and it actually failed after
instrumentation; a new `regression_gate` field (`status`:
`not_attempted`/`skipped`/`passed`/`failed`, `reason`) always present,
`not_attempted` when `--dynamic` wasn't passed (byte-for-byte the old
default behavior, confirmed by a test with no `dynamic` attribute on its
`argparse.Namespace` at all), `skipped` — never blocking, never
fabricating a result — for Docker being unavailable, no test suite found,
or a broken install ladder. A real Docker-only bug surfaced while
proving this end to end through `cmd_validate` itself, not just the
mocked unit tests: the pass/fail-count regex used `\s*` between its two
optional groups, which matches `\n` and let the match silently drift onto
an unrelated earlier line in real multi-line pytest output, reporting a
fabricated `0 failed, 0 passed` for an actual single test failure — fixed
by anchoring to pytest's own single summary line first (`^=+ ... in
[\d.]+s.*=+$`, `MULTILINE`) and only then extracting counts from within
that line. 397 tests passing (up from 388), including two new real-Docker
end-to-end cases through `cmd_validate` (`tests/test_cli_validate_dynamic.py`)
that are what actually caught the regex bug.

**Real R2, first half landed** (2026-08-26): per-DTO event-emission
assertion, the other real capability `docs/validation.md`'s ladder table
names for R2 (the first was the regression gate above). Grounded in a
real Docker spike run before planning against it: code using exactly the
pattern `skills/s10-instrumenter/SKILL.md` now teaches
(`tracer = trace.get_tracer(__name__)` +
`start_as_current_span(...)`/`set_attribute(...)`) is reliably captured
by OpenTelemetry's own official zero-code-change bootstrap tool,
`opentelemetry-instrument`, with `OTEL_TRACES_EXPORTER=console` —
**but only once `opentelemetry-distro` is installed alongside
`-api`/`-sdk`/`-instrumentation`**; without `-distro` the CLI silently
no-ops (no Configurator registered) — the same "looks present but
doesn't actually work" trap this session already hit once with the
Agent SDK's own bundled CLI, caught here the same way: by actually
running it, not by reading pip's dependency graph. Also needs pytest's
`-s` flag (disables fd-level capture, which otherwise swallows the
exporter's background-thread writes). `oah/validate/pytest_runner.py`'s
`run_pytest_suite(capture_spans=True)` wires this in and parses the
`ConsoleSpanExporter`'s back-to-back JSON span dumps (not one valid
document) via a `json.JSONDecoder.raw_decode` scan, filtered to objects
that actually look like a real span. `oah/validate/event_assertion.py`'s
`check_dto_dynamic` then asserts, per DTO, whether a **single** captured
span had every one of `expected_events[].required_attributes` together —
deliberately stricter than R4's own static check.py (which accepts the
union of an entire file, since static text has no span boundary to use);
dynamic capture does have one, and using it is what keeps this an honest
claim rather than conflating two unrelated events' attributes into "both
observed." `oah/validate/dynamic.py` orchestrates both checks
(regression gate + event assertion) over exactly **one** real sandboxed
run per `oah validate --dynamic` invocation, not two.

A second real, more foundational bug surfaced by the real-Docker test for
this phase (not the mocked ones): since S10 now unconditionally emits
`from opentelemetry import trace`, *any* `--dynamic` run against a real
S10-instrumented target — even without span capture — needs
`opentelemetry-api` just to import successfully; it was previously only
installed as part of the capture-only dependency set, so a plain
regression-gate run against S10-instrumented code would have failed to
even collect its tests. Fixed by moving `opentelemetry-api` alone into
the base install ladder (always installed, regardless of `capture_spans`
or the target's own `requirements.txt`) while keeping `-sdk`/
`-instrumentation`/`-distro` capture-only, since the bare API package is
enough for every `tracer`/`span` call to work as a real no-op without
crashing, and only the SDK trio turns those no-ops into real, exported,
capturable spans.

`schemas/validation_report.schema.json` gained a required
`event_assertions` array (one entry per DTO, `status`:
`not_attempted`/`skipped`/`observed`/`not_observed`, `reason`) —
informational only this phase, never affecting `verdict` on its own (an
unobserved event may just mean the test suite doesn't happen to exercise
that code path, the same non-punitive posture R4's own `absent` status
already has). `ladder_rung` **still** stays `"R4"` — the ladder table
defines R2 as event-emission assertion **and** a static
trace-ID-propagation check together in one row; only the first half is
built. 423 tests passing (up from 397): mocked unit coverage for
`parse_captured_spans`/`check_dto_dynamic`/the `dynamic.py` orchestrator,
plus three real-Docker test files (span capture in isolation, the
orchestrator's real end-to-end wiring, and one CLI-level end-to-end case
proving the S10 skill's own taught pattern and this capture mechanism
actually connect, not just each half verified separately).

**What's left before `ladder_rung` can honestly become `R2`**: the static
trace-ID-propagation check for `propagate_context` DTOs — the other half
of R2's own defining check, named as the one remaining piece, not
silently implied by this landing.

**Real R2 fully landed** (2026-08-26): the propagation check above,
`oah/validate/propagation_checker.py`, and — since both halves of R2's own
defining check now exist — `oah/validate/verdict.py`'s
`compute_ladder_verdict`, the first code in this entire project able to
compute `ladder_rung: "R2"` / `verdict: "validated"` at all. No corpus
fixture or real DTO example uses `propagate_context` yet (checked — zero
hits across `tests/`/`corpus/`), so the checker leans on
`skills/s10-instrumenter/SKILL.md`'s own concrete guidance for what
correct propagation code looks like per boundary shape, the same way
R4's `checker.py` leans on `expected_events[].required_attributes`:
classifies the boundary by keyword search over `change.description`'s
free text (no structured boundary-type field exists in the DTO schema)
into `asyncio` (no explicit code needed — `contextvars` already
propagate automatically), `thread` (requires
`context.get_current()`/`context.attach()`), or `queue` (requires
`propagate.inject()`/`propagate.extract()`/`TraceContextTextMapPropagator`,
for a boundary crossing a real wire) — an unclassifiable description is
honestly `skipped` ("needs manual review"), never guessed. This is a
genuine heuristic, not real control-flow analysis, named as this check's
real limit in its own module docstring.

The promotion rule (`compute_ladder_verdict`) is deliberately
conservative, since a wrong promotion here is the one overclaim this
whole R2 effort exists to prevent: `R2`/`validated` only when
`--dynamic` ran *and* the regression gate actually passed *and* there is
at least one DTO S10 actually applied (an empty or all-unapplied DTO set
proves nothing — promoting it would claim "everything checked out" about
nothing having been checked) *and* every one of those applied DTOs'
relevant check came back positive (`event_assertions: "observed"` for
ordinary DTOs, `propagation_checks: "present"` for `propagate_context`
DTOs). Any single failure, anywhere, keeps the whole run at `"R4"`/
`"needs_review"` — a real regression-gate failure overrides everything
else straight to `"validation_failed"`. `schemas/validation_report.schema.json`'s
`ladder_rung` (now `enum: ["R4", "R2"]`) and `verdict` (now includes
`"validated"`) both grew for real, not `const`s anymore. Proven end to
end with a real Docker container, not just the promotion rule's own
pure unit tests: a real target instrumented exactly per the S10 skill's
own taught pattern, actually applied per its instrument report, run
through `oah validate --dynamic` — the report reads `ladder_rung: "R2"`,
`verdict: "validated"`
(`tests/test_cli_validate_dynamic.py::test_dynamic_reports_observed_for_a_dto_the_s10_skill_pattern_actually_emits`).
446 tests passing (up from 423).

**This closes M4's own gate condition text** ("End-to-end run on a pilot
product reaches `validated` verdict") **for the R2 rung specifically** —
worth being precise about what that does and doesn't mean: it's the first
time this codebase can produce a real `validated` verdict, on a real
(if synthetic, hand-built) target, through the real pipeline. It is
**not** M4 fully done — R1 (full dynamic against a live running product,
not just its test suite), R3 (generated smoke), the OTLP collector, the
agentic panel, and TCR remain fully unbuilt, and a genuine reference-corpus
repo (not a hand-built fixture) reaching `validated` hasn't been
attempted. The `add_dependency` DTO-type gap (named two phases ago) also
remains open and unrelated to this phase.

**R1's execution mechanism landed** (2026-08-26): `oah/validate/live_sandbox.py`'s
`run_live_sandbox` — the largest remaining piece toward M4's own gate, and
deliberately scoped the same way as E6 R2's own sandbox-mechanism phase:
prove the mechanism against a synthetic fixture, not wire it into
`oah validate` yet. Real, hard constraint stated up front rather than
routed around: this dev environment has no `ANTHROPIC_API_KEY`, so R3
(generated smoke) and the agentic panel — both needing a live LLM call —
can't be attempted here regardless of how much more code gets written;
SP3's own decision record (`docs/decisions/007-sp3-dynamic-validation-feasibility.md`)
already found 0/6 corpus repos are even R1-capable (no compose file or
automatable dev-server path), so a synthetic fixture is the only honest
target for proving this mechanism, same reasoning R2's own phase already
established.

Unlike R2's `sandbox.py` (one container, `--network none`, a script that
runs to completion), R1 needs a materially different isolation shape: two
long-running containers — the target's own service and a real OTel
Collector — that can talk to *each other* but nowhere else. Grounded in a
real Docker spike run before designing against it, which caught two real
findings: `docker network create --internal` gives a network with no
internet route while still allowing container-to-container DNS (confirmed
via `docker network inspect`); and the collector's `debug` exporter (the
first thing reached for, matching R2's console-exporter precedent) prints
a custom, non-JSON Go text format, while the `file` exporter gives clean,
spec-compliant, line-delimited OTLP-JSON instead — but only once its
target path already exists (`open: no such file`, a real failure hit and
fixed with a pre-`touch`'d, bind-mounted output file, a deliberate,
narrow exception to R2's "no bind mount" posture: the collector is OAH's
own trusted config, not target-repo content, and the mount is directional,
host-reads-back only).

Two more real bugs surfaced only by the module's own real-Docker tests,
not by reasoning about the design in the abstract: the readiness probe
`run_live_sandbox` itself issues to detect when the target service is up
is a real HTTP request against the target's real handler, which (for a
naive target app with no separate health endpoint) gets instrumented and
captured exactly like real traffic — one request produced two captured
spans until fixed by tracking the collector output file's byte offset
right after readiness succeeds, excluding anything before it. Fixing that
with a flat 1-second sleep introduced a second, subtler bug: a 300ms poll
interval was shorter than the target's own `OTEL_BSP_SCHEDULE_DELAY`
(500ms) async flush cycle, so two "equal" file-size reads could land in
the legitimate pause *between* two flush batches and falsely declare
stability with a span still pending -- caught only by running the test
three times in a row (a single run could still get lucky), fixed by
polling with an interval safely longer than the flush cycle instead of a
fixed guess.

Proven for real, all in `tests/test_live_sandbox.py` (real Docker,
`skipif` when unavailable, runs for real here and expected to in CI): a
real request against a real running service returns the right status and
a real captured span; multiple requests with a deliberate artificial delay
produce real, distinguishable per-request latencies with `latency_p50_ms`/
`latency_p95_ms` computed directly from that run's own raw samples (never
averaged from elsewhere, per `docs/validation.md`'s own rule); killing the
collector mid-run and confirming later requests still succeed proves the
deterministic layer's own fail-open check (`fail_open: True`) with the
same infrastructure, not a separate code path; Docker-unavailable and a
target that never binds its port both resolve cleanly
(`docker_unavailable`/`startup_failed`, never a hang); cleanup (both
containers, the built image, the network) confirmed via real
`docker ps -a`/`docker network ls`/`docker image ls` calls before and
after every scenario, including the failure paths.

**A third real bug, this one CI-only** (the same "worked locally, fails on
a real Linux Docker daemon" class this session already hit once for git
identity in S10's fix mode): `otel/opentelemetry-collector` runs as a
non-root UID (`10001:10001`) by default. Locally, Docker Desktop on macOS
doesn't enforce real UID/GID permission checks on bind mounts, so the
collector could write to a host-owned output file freely; on GitHub
Actions' real Linux Docker daemon, it couldn't, and the collector crashed
immediately after starting — but `docker run -d` succeeding only confirms
the container *started*, not that its process stayed up, so this surfaced
as a silently empty `spans: []` "ok" result, not a real error, and only
CI's own test run ever exercised the code path that exposed it. Fixed two
ways: the output file is now made world-writable
(`output_path.chmod(0o666)`) before the collector starts, and a new
liveness check (`docker inspect --format {{.State.Running}}`, a `docker
logs` capture on failure) runs right after starting the collector, turning
any future "started then crashed" case into a real, diagnosable
`build_failed` result instead of a silent empty one — proven with a real,
portable crash scenario (a tiny custom image whose `ENTRYPOINT` always
exits, since most "obviously bad" images fail at the `docker run`
invocation itself rather than reaching a genuinely-started-then-crashed
state). 453 tests passing (up from 446), run three times in a row clean
after all the timing and permission fixes, since a single green run
doesn't prove a real-Docker-timing mechanism isn't still flaky — and this
specific bug is exactly why: it never reproduced locally at all, only in
CI, the same lesson this session's git-identity incident already taught
once about trusting local-only test runs.

**Not wired into `oah validate`** — no `event_schema.json` diffing
(including the unknown-field/invariant checks `docs/validation.md`'s
deterministic layer calls for), no TCR taxonomy, no `--live` CLI flag, no
`ladder_rung: "R1"`, named as the explicit next step, not silently implied
by this landing. R3, the agentic panel, and a real corpus-repo target all
remain blocked exactly as stated above.

**`--live` wired into `oah validate`** (2026-08-26): `oah/validate/live_diff.py`'s
`check_unknown_attributes` plus new `--live`/`--start-command`/`--port`/
`--requests`/`--event-schema`/`--setup-script` flags on `oah validate`,
mirroring exactly the same "mechanism first, wiring second" split R2 went
through (`sandbox.py` → `regression_gate.py`/`dynamic.py`). Real per-DTO
event assertion against R1-captured spans reuses `oah/validate/event_assertion.py`'s
existing `check_dto_dynamic` directly, no new per-DTO matching logic
duplicated. A real gap surfaced only while wiring the CLI, not visible from
the mechanism module alone: `run_live_sandbox` has no built-in install
ladder the way `pytest_runner.py` does for `--dynamic` — without a
`--setup-script` flag, `--live` had no way to install even
`opentelemetry-api` before starting a target using the S10 skill's own
taught pattern, making the flag unusable for exactly the target shape this
whole R2/R1 effort is built around; added before it shipped, not left
broken. Reported under a new `live_execution` report field (`status`
mirroring `run_live_sandbox`'s own vocabulary, real captured
`requests`/`latency_p50_ms`/`latency_p95_ms`/`fail_open`, per-DTO
`event_assertions`, `unknown_attributes`). **`ladder_rung`/`verdict` are
still untouched by `--live`** — R1's own promotion rule needs a real TCR
taxonomy and a latency-vs-budget comparison (the DTO schema's own
`estimated_overhead_ms` field is the natural, still-unused hook) plus
`event_schema.json`'s semantic invariant checks, none built yet, named as
the explicit next step. Proven end to end with a real Docker container
through `cmd_validate` itself (`tests/test_cli_validate_live.py`): a real
target instrumented per the S10 skill's own pattern reports real captured
requests, real latency, and `event_assertions: observed`; a deliberately
mismatched `event_schema.json` correctly flags a real
`unknown_attributes_found`. 461 tests passing (up from 453), the new
real-Docker files run twice in a row clean, matching the same
"a single green run doesn't prove a real-Docker mechanism isn't flaky"
discipline the R1 mechanism phase itself established.

**Real TCR landed** (2026-08-26): `oah/validate/tcr.py`'s `compute_tcr`,
R1's own primary metric per `docs/architecture.md` -- checked the
project's actual definition before designing against it, since an
earlier draft of this plan assumed the wrong thing: "TCR -- share of
exercised user requests reconstructable end-to-end with no missing
spans," about trace/span linkage integrity, **not** the "fallback with
reason, clarification, escalation, restricted-attempt" business-outcome
taxonomy `docs/validation.md`'s Metrics section separately calls
"behavioral rates" (a materially different, still domain-specific metric
that stays deferred). Verified for real with two Docker spikes before
building against it: the OTLP-JSON `live_sandbox.py` already parses
carries `traceId`/`spanId`/`parentSpanId` per span, with `parentSpanId`
present only on child spans (confirmed with a real nested-span capture:
a root span has no `parentSpanId` key at all; a child's `parentSpanId`
matches its real parent's `spanId` exactly) -- `_parse_span_file` now
captures all three, additive to the existing `{name, attributes}` shape,
so `event_assertion.check_dto_dynamic`/`live_diff.check_unknown_attributes`
(which only ever read `attributes`) are unaffected. `compute_tcr` groups
captured spans by `trace_id`; a trace is complete when every span's
parent (if any) points at a `span_id` captured within that *same* trace
-- a dangling parent reference is exactly the "missing span" TCR is
meant to catch. Reported under `live_execution.tcr`
(`traces_total`/`traces_complete`/`tcr`/`incomplete_trace_ids`; `tcr` is
`None`, never a fabricated `0.0`/`1.0`, when nothing was captured).
**Still not promoting to `ladder_rung: "R1"`** -- the ladder table
requires TCR *and* a latency-vs-budget comparison together; the budget
half needs a genuine baseline (pre-instrumentation) live run to compute a
real overhead delta, a materially bigger addition (running
`run_live_sandbox` twice, against two different git states) not attempted
here, named as the explicit next step. Proven with a real nested-span
Docker test (`tests/test_live_sandbox.py`): a real parent+child span pair
captured with correctly linked trace/span/parent IDs, not just the pure
grouping logic in isolation. 469 tests passing (up from 461).

**Baseline vs. instrumented latency overhead landed** (2026-08-26): R1's
other defining check alongside TCR, `docs/validation.md`'s "p50/p95
latency overhead vs. declared budget." "Overhead" only means anything
relative to a baseline (the target's latency *before* instrumentation),
which no prior phase measured. The baseline git ref needed no new
plumbing to locate -- `cmd_instrument` (`oah/cli.py`) already captures
`repo_git_sha` before touching any DTO, and `instrument_report.json`'s
own field is exactly that SHA, already a required `oah validate` input.
`oah/validate/baseline.py`'s `run_baseline_live_sandbox` runs
`live_sandbox.run_live_sandbox` against a real `git worktree` at that
SHA (verified for real before building against it: a worktree checkout
at a parent commit genuinely lacks a file only added in a later commit;
`git worktree remove --force` cleans up completely, confirmed via real
`git worktree list`/`git status --porcelain` before and after, on the
*caller's* actual working tree, never touched). `oah/validate/overhead.py`'s
`compute_overhead_vs_budget` sums `estimated_overhead_ms` across DTOs
S10 actually applied as the declared budget -- a `null` estimate on any
applied DTO makes the budget explicitly *incomplete*, never silently
treated as `0` (which would understate the true budget and make "within
budget" artificially easy); the overhead itself is the raw signed delta
between the two runs' real p50/p95 latencies, reported even if negative,
never clamped to zero. New opt-in `--baseline` flag (on top of `--live`,
since it doubles the live-run cost/time) wires this into
`live_execution.overhead_vs_budget`. Proven end to end through
`cmd_validate` itself with a real two-commit git repo (a real 100ms sleep
present only in the "instrumented" commit): a real, measured
`overhead_p95_ms > 50` against a real, declared 5ms budget correctly
reports `within_budget: False` -- not just wired-but-always-zero. **Still not promoting to `ladder_rung: "R1"`** -- that needs this
evidence combined with TCR in `oah/validate/verdict.py`'s
`compute_ladder_verdict`, a separate, focused follow-up, matching every
"build the evidence, promote later" split this project has used (TCR
itself landed the same way one phase earlier). 480 tests passing (up
from 469), the new real-Docker+git test files run twice in a row clean
before committing.

**Real R1 fully landed** (2026-08-26): the follow-up named directly
above, one phase later — `compute_ladder_verdict` now promotes past R2
all the way to `ladder_rung: "R1"` (still `verdict: "validated"`) when
every one of R2's own requirements holds *and* `--live` succeeded with a
real `tcr.tcr` of exactly `1.0` (every captured trace complete -- a
partially-complete run is real evidence of a real gap, not close enough
to round up) *and* `--baseline` ran with `overhead_vs_budget.within_budget`
`true`. R1's evidence comes from a genuinely different sandboxed run than
R2's own (`--live`/`--baseline` vs. `--dynamic`), so `live_execution` is
an optional parameter to `compute_ladder_verdict`, consulted only once
R2's own requirements are already confirmed — R1 can never be reached by
R1 evidence alone. This is the first code in this project's history able
to compute `ladder_rung: "R1"` at all.

Proven for real, not just the pure promotion-rule's own unit tests
(`tests/test_validate_verdict.py`, extended with the R1 branch's own
cases): a new dedicated test
(`tests/test_cli_validate_r1_promotion.py::test_dynamic_and_live_and_baseline_together_reach_ladder_rung_r1`)
runs `oah validate --dynamic --live --baseline` combined in one real
invocation — a real pytest-in-sandbox run (E6 R2's own `sandbox.py`), a
real running service alongside a real OTel collector (`live_sandbox.py`),
and a real pre-instrumentation baseline comparison (`baseline.py`), all
three of this session's own mechanisms proving out *together*, not each
in isolation — and the resulting report genuinely reads `ladder_rung:
"R1"`, `verdict: "validated"`. Run three times in a row clean before
committing, matching the standing "a single green run doesn't prove a
real-Docker mechanism isn't flaky" discipline this whole R1 effort has
kept throughout.

**What this does and doesn't mean for M4's own gate** ("End-to-end run
on a pilot product reaches `validated` verdict"): the *mechanism* side of
M4 is now complete for both R2 and R1 -- every rung `docs/validation.md`'s
ladder table defines short of R3 can be reached for real, through the
real pipeline, with real evidence, no shortcuts. It is **still not** "M4
done": this is proven against a hand-built synthetic fixture repo, not a
real reference-corpus repo (SP3's own finding — 0/6 vetted corpus repos
are even R1-capable — means this can't be attempted against a real one in
this environment either); R3 (generated smoke) and the agentic audit
panel need a live LLM call, blocked here by the missing
`ANTHROPIC_API_KEY`, not by anything buildable; `event_schema.json`'s
semantic invariant checks and the "behavioral rates" metric remain
deferred, unchanged from every prior phase's own naming of them. 490
tests passing (up from 480).

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

**Threat model + S10 tool allowlist landed earlier** (SP7, `docs/decisions/008`,
`docs/security-threat-model.md`): four real red-team fixtures against a real
Claude-based agent, all resisted; S10's agent session has no Edit/Write tool at
all (a structural restriction, not prompt-level).

**Phase 1: secret redaction landed** (2026-08-27, `docs/decisions/030`).
Audited what actually existed before this phase: `docs/security.md`'s T2
mitigation ("secret-pattern redaction on everything the harness writes")
was a design claim with zero code behind it. A real, concrete leak path:
`oah/discovery/python_adapter.py`'s `_excerpt` copies raw source lines
into an S1 ambiguous-candidate's `code_excerpt`, both sent to
`disambiguate()`'s LLM call and checkpointed to the harness's own state DB
-- a hardcoded credential near an ambiguous call site (plausible, not
hypothetical) would leak through both paths unredacted. New
`oah/security/redaction.py`: provider-specific patterns (AWS, Anthropic,
OpenAI, GitHub, Slack, JWT, PEM private keys) plus a generic
secret-assignment catch-all, wired into `_excerpt`. A real bug found and
fixed while building: the generic catch-all was re-matching a value a
provider-specific pattern had ALREADY redacted (the placeholder text
itself is 8+ chars, tripping the generic rule), downgrading a specific
label to the generic one -- fixed by skipping already-redacted values.
Scoped to this one already-identified site, not a sweep across S4-S9/S6/
validate's own source-reading paths -- named as real, separate follow-up
work, not silently assumed covered. TS/Java adapters have no
ambiguous-candidate path yet, so neither needed the same wiring.

**Phase 2: private-gateway mode landed** (2026-08-27, `docs/decisions/031`)
-- a real finding, not new runtime behavior: verified directly against
litellm's own installed source (not docs, not assumed) that
`oah/llm_client.py`'s delegation straight to `litellm.completion(...)`
means a base-URL override (`ANTHROPIC_API_BASE`/`ANTHROPIC_BASE_URL`) and
mTLS (`SSL_CERTIFICATE`/`SSL_VERIFY`, passed straight to httpx's own
`cert`/`verify` params) were **already working today, via plain
environment variables, with zero OAH code involved** -- "unbuilt" was
wrong; it was built-but-invisible. Re-implementing what litellm already
does correctly was rejected; `oah/doctor.py` gained `_check_llm_gateway()`
(informational, never blocking) so the config choice isn't silently
invisible before a run starts. Real, named boundary: only the default
model's provider env vars are checked; a non-default `--model` relies on
that provider's own equivalent, matching `missing_credentials()`'s
existing precedent. S10's Agent SDK calls (Anthropic-pinned, not
LiteLLM-routed) were not investigated -- a real, separate question.

**Still fully unbuilt, named not implied**: sweeping redaction into every
other stage that reads source; a directory allowlist specifically for
S1-S9's *read* scope (S10's write-side allowlist is real); whether S10's
Agent SDK calls have an equivalent private-gateway mechanism; the
red-team-exercise DoD itself at a larger scale than SP7's own four
fixtures.

### E9 — Backend targets
OTel-only emitter (floor), self-hosted Langfuse target (compose + config generation),
constraint-driven backend selection in S7. *DoD:* same repo instrumentable to both
targets from the same DTOs. *Depends on:* SP6.

**Config-generation slice landed** (2026-08-26): `oah backend-config`,
`oah/backend_targets.py`. Fully deterministic -- no LLM, no agent, nothing to
mock in its own tests, the first genuinely unmocked feature area this session.
Generates a real `otel-collector-config.yaml` for `otel-only` (exports to the
collector's own `debug` exporter -- `logging` was deprecated/removed in
collector v0.111.0, checked against current opentelemetry.io docs rather than
assumed) or `langfuse` (self-hosted Langfuse accepts OTLP directly, HTTP only,
at `/api/public/otel` with Basic Auth + an ingestion-version header -- verified
against langfuse.com's own integration docs). DoD checked directly, not
assumed: generated both configs against a real target, parsed both back with
`yaml.safe_load`, confirmed the *only* difference between them is the
`exporters`/`service.pipelines` block, `receivers.otlp` identical. For
`langfuse`, points at Langfuse's own actively-maintained
`docker-compose.yml` (6 required services: web, worker, postgres, clickhouse,
redis, minio) rather than vendoring a copy that would drift the moment they
change it.

**Constraint-driven selection in S7 not attempted** -- found to be a real,
structural blocker before scoping this, not just deprioritized: it needs S7's
own LLM-driven `architecture.md`-prose synthesis to justify a choice against
`context.yaml`, and only S7's deterministic `event_schema.json` merge is
built; the prose generation that selection reasoning would live in doesn't
exist yet. `--backend` is a manual flag for now. Also deferred: wiring
`add_collector_config`/`add_compose_service` into S8's DTO generation and
S10's `apply_dto_fix`/`apply_dto_report_only` -- those two `change.type`
values need a different application shape (creating a new file has no
`change.anchor` to verify against, unlike the 4 edit-in-place types S10
already covers) that deserves its own design pass, not folded in here.

### E10 — Dogfooding & harness self-telemetry
OAH emits traces of its own stages in the schema it installs; a run is debuggable
from its own telemetry. *DoD:* an OAH incident is reconstructed from OAH traces alone.

**Landed** (2026-08-26): `oah/telemetry.py` (`setup_tracing`, `llm_span`), wired
into all 5 of OAH's own real LLM/Agent-SDK call sites (S1 `disambiguate`, S4
`design_lens`, S6 `run_persona`, S8 `generate_dtos`, S10 `_generate_patch`).
`opentelemetry-api`/`-sdk` are base dependencies (not a new optional extra --
unlike `[llm]`/`[agent]`, self-telemetry is meant to be on for every real
invocation per design principle #8, and the real package footprint, checked
against PyPI before adding it, is 5 small packages with no C extensions,
nothing like `litellm`'s tree). Exports to a local JSONL file
(`.oah/traces/oah.jsonl`, already gitignored) via a small custom
`SpanExporter` -- no OTLP collector exists yet (E6 R1-R3's job), so this is
deliberately the "always works, no collector needed" floor, same posture as
S10/S11's own first slices. `setup_tracing()` runs once from `cli.py`'s
`main()`, never from individual `cmd_*` functions, so every existing test
that calls `cmd_design`/`cmd_dtos`/etc. directly keeps working unchanged --
with no tracer provider configured, a span is a documented OTel no-op.

A real OTel API pitfall found and fixed while building this, not assumed:
`opentelemetry.trace.ProxyTracer` resolves and permanently caches whichever
`TracerProvider` is live the *first* time it's used, and never re-checks --
safe for real usage (`setup_tracing()` runs once, before any span), but it
broke this module's own test suite the first time it was written, where
different tests each configure their own fresh provider; fixed by resolving
the tracer fresh on every `llm_span()` call instead of caching it at module
level, caught by a real failing test before it was understood, not by
reading the SDK source first. Similarly, `set_tracer_provider()` is guarded
by a private, one-shot `Once` object *separate* from the provider value
itself -- resetting the value alone between tests still left it permanently
locked; both had to be reset.

Verified end to end through the real `main()` entrypoint (not `cmd_design`
called directly, so `setup_tracing()` actually ran): a deliberately failing
mocked completion function, `oah design` invoked for real, then the failure
-- which stage, which lens, which model, the full exception and stack trace
-- reconstructed from `.oah/traces/oah.jsonl` alone, matching this epic's
own DoD wording exactly rather than assuming the mechanism works.

Deferred, named not dropped: a trace-per-CLI-command span (this slice only
wraps the 5 LLM/agent calls, not e.g. "which files did S1 scan"); real OTLP
export to a collector (E6 R1-R3); fixing `skills/s10-instrumenter/SKILL.md`
to tell its own agent to write real `opentelemetry-sdk` calls into *target*
code (this slice is OAH's own telemetry, not what S10 generates for a
target repo -- it gives a working reference for that fix, doesn't make it).

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

**TS phase 1 landed** (2026-08-26, `docs/decisions/014`). `oah/discovery/typescript_adapter.py`
— a real, tree-sitter-based (not SP10's own Node/compiler-API spike, which SP10's
own decision explicitly named evidence-only, not a component to carry forward)
S1 adapter reaching the DoD's own recall bar for real: 14/14 (100%), 0 false
positives, verified against all four real corpus repos SP10+SP12 already
pinned (`transcribee`, `llm-document-ocr`, `wechatbot`, `cocktail-app`), all
three detector shapes (receiver/method-suffix, SP12's declarative route
registration, SP12's global unimported callee). `schemas/domain_pack.schema.json`'s
`registries[]` gained a `language` field so one pack (`genai`) can declare
per-language SDK registries for the same domain, and `domains/genai/pack.json`
now has a real TypeScript Anthropic-SDK entry. **Not yet done, named explicitly**:
CLI language dispatch (every command still hardcodes the Python adapter — zero
user-visible change from this phase), a vendored TS corpus fixture + multi-language
`oah/eval_corpus.py` scoring (E7's territory), S2's TS vendor/manifest detection,
and Java (untouched, per this epic's own priority order).

**CLI language dispatch landed** (2026-08-26). `oah/cli.py`'s `_build_surface_map`
is now the single dispatch point all six S1 call sites (`map`, `gaps`, `design`,
`event-schema`, `dtos`, `readiness`) route through; a new `--language
{python,typescript}` flag on each (default `python`, byte-identical default
behavior — confirmed by the existing test suite passing unchanged, 477/477
before this phase, 482/482 after with the 5 new dispatch tests added). Found and
fixed a real gap surfaced by writing this, not by the adapters' own already-green
test suites: `typescript_adapter.build_surface_map` returned a bare `surface_map`
dict, while `python_adapter.build_surface_map` returns a `(surface_map,
still_ambiguous)` 2-tuple — the E11-TS decision record's own claim ("same public
API shape... so a future CLI dispatch layer can swap adapters without touching
anything downstream") didn't actually hold at this one boundary. Fixed by making
the TS adapter return the same 2-tuple shape (`still_ambiguous` always `[]`, since
this module has no disambiguation counterpart), which is what let `_build_surface_map`
be a single unbranching helper instead of dispatch code special-casing return
shapes per language. `run_manifest.json`'s pre-existing `primary_language` field
(already in the schema, previously hardcoded to the literal `"python"` at both
`cmd_map` and `cmd_instrument`) now records whichever language actually ran.
Verified end to end with a real subprocess `oah map --language typescript` run
against a small `.ts` fixture (`tests/test_cli.py`), not just the dispatch
helper's own unit tests. **Still not done**: a vendored TS corpus fixture +
multi-language `oah/eval_corpus.py` scoring (E7's territory), S2's TS
vendor/manifest detection, and Java.

**Java phase 1 landed** (2026-08-27, `docs/decisions/029`), closing E11's
own priority order. Two things verified before any adapter code was
written, same discipline as every prior language port: `tree-sitter-java`'s
real grammar (explored directly -- `method_invocation.object`/`.name`
fields represent a call chain as NESTED nodes, not TS's member-expression-
then-call split) and the real Anthropic/OpenAI Java SDKs' own construction
pattern (a background research agent against their READMEs) -- both build
via a **static builder method chain** rooted at a known class name
(`AnthropicOkHttpClient.builder().apiKey(...).build()` or `.fromEnv()`),
**never `new X()`**, meaning TS phase 1's own first shape
(`receiver_method_suffix`) would have had no real registry to attach to.
`oah/discovery/java_adapter.py` (new) is architecturally closer to the
Python adapter than the TS one -- Java's own class/field structure fits a
class-scoped known-name prescan (mirroring Python's `self_attrs`), not
TS's file-wide model (SP10 finding 3 was JS/TS-specific). One real Java-
specific addition: unqualified instance-field access (`client.foo()`
inside the class declaring `private Client client`, no `this.` needed) --
neither Python nor TS/JS has an equivalent. `static_builder_chain`, a
fourth receiver-resolution `detector_shape`, is real general
infrastructure (`terminal_methods` matches a chain's LAST segment
regardless of how many builder-configuration calls precede it), not an
Anthropic-only hack. Async detection has no keyword to key off in Java, so
it checks for a `.async()` hop inserted mid-chain (a real, documented SDK
pattern) -- suffix matching only checks a chain's tail, so the extra hop
never blocks the match. CLI dispatch (`--language java`) landed in the
SAME phase, unlike TS's own (which deferred it). A real gap found by
testing, not designed around: a single unassigned expression chaining
construction AND the eventual call together (terminal buried mid-chain,
not at the end) doesn't resolve -- named, regression-tested, not chased in
phase 1. Remaining named gaps: OpenAI Java SDK (same shape, not added this
phase), LangChain4j, Spring AI (DI-based construction, structurally
harder), a real vendored Java corpus fixture (E7's territory).

### E13 — Domain pack extraction *(pipeline core; prerequisite for E12)*
There is no object called a domain pack today: domain-ness is sixteen literals
scattered across `oah/cli.py`, `oah/design/gates.py`, `oah/discovery/gap_model.py`,
`oah/discovery/registry.py` and five schemas — all of them in files E12's old
definition of done promised not to touch. E12 could therefore never have passed as
written, and its own text anticipated exactly this ("if pipeline-core needs edits
to fit the second domain, that itself is the finding"). E13 promotes that finding
to work: introduce `schemas/domain_pack.schema.json` plus `oah/domains/<name>/`,
and re-express today's GenAI behaviour as a pack with **zero behaviour change**.
Contents of a pack: surface-point vocabulary with each kind's gap dimension and
rollout rank (replacing `KIND_TO_DIMENSION` and the closed `dimension`/`kind`
enums), S1 signature registries with an explicit `detector_shape`, the lens roster
with target kinds and emitted artifact types (replacing `LENS_TO_POINT_KIND` and
its four duplicated `lens_fns` copies), semconv namespaces with per-namespace pin
and stability, DTO event types, and the advisory gate's word pairs. Two
corrections ride along because the second pack exposes them: `otel_genai`
generalises to `otel_semconv` + `namespace`, and stability moves from per-pack to
**per-attribute** — `event_schema.schema.json`'s current claim that upstream
attributes are "currently always development" is true of `gen_ai.*` and false of
the stable HTTP conventions. A third change is structural: `lenses[].emits` lets a
lens return more than one artifact, because an SLO specification is not
expressible as a list of event attributes and the slo lens (E12) must emit
`design_fragment` **and** `slo_spec` (see
[011](docs/decisions/011-service-domain-pack-architecture.md), Finding 1).
*DoD:* GenAI ships as a pack; corpus results byte-identical before and after; full
suite green with only mechanical renames; a throwaway second pack declaring one
kind and one lens loads and runs S1→S9 end to end with **no edit under `oah/` or
`schemas/`** — that last clause is the whole point of the epic and the only one
that proves the seam exists. *Depends on:* nothing. *Blocks:* E12.

**Landed** (2026-08-26). `schemas/domain_pack.schema.json` + `oah/domains/loader.py`
(pure, deterministic, validates against that schema, no LLM call) +
`domains/genai/pack.json` (the real manifest — 5 point kinds, 5 S1 registries, 9
lenses, one semconv namespace). Wired through: `oah/discovery/registry.py` derives
`REGISTRIES`/`MODULE_TO_REGISTRY`/etc. from the loaded pack instead of four literal
dicts; `oah/discovery/python_adapter.py`'s structural-pattern detector (the
`tool_use`-dispatch check) is now driven by pack-declared `content_signal` data
(`attribute_path`/`equals_value`) instead of a hardcoded string, closing a second
coupling this session's research found beyond the original sixteen (it lived
outside `registry.py` entirely); `oah/discovery/gap_model.py`'s `KIND_TO_DIMENSION`
is pack-derived; `oah/cli.py`'s four duplicated `lens_fns` dict literals collapse
into one `_lens_fns_for_pack` helper (dispatch by `getattr` on the lens module,
convention-based); `oah/design/gates.py`'s gate 4 and the advisory word-pair list
read from the pack's new `attribute_kind_values`/`advisory_contradiction_pairs`
fields; `oah/design/event_schema.py`'s summary counts and `oah/design/dto_generator.py`'s
rollout ranks are pack-derived. Verified byte-identical with a real golden-snapshot
test (`tests/test_e13_domain_pack_snapshot.py`, new — no such harness existed
before) driving real S1/S3/S5/S7 against the `naive-memory` corpus fixture with S4/S8's
model calls mocked. The throwaway-pack proof
(`tests/test_domain_pack_loader.py`) drives a synthetic pack's point through real
S3/S5/S7/S8 with zero edits under `oah/` or `schemas/` — scoped explicitly to those
stages, not S1's tree-sitter walk, which still reads pack-derived *process-global*
constants rather than being re-parameterized per call (a real, separate cost with
no second real pack yet to justify it; see the epic's own plan for why).

Two deliberate deviations from this entry's own text above, both to hold "zero
behaviour change" as the harder constraint: `otel_genai` was **not** renamed to
`otel_semconv` (that would change a real field value in every `design_fragment.json`,
failing byte-identical) — the pack instead declares its own
`attribute_kind_values: ["otel_genai", "oah_extension"]`, keeping today's literal
values as pack data rather than renaming them; per-attribute stability already
lived on `event_schema.json`'s `attributes[].stability` field before this epic
(only the schema's prose claimed "always development" too strongly), so nothing
needed to move. `lenses[].emits` ships in the manifest (forward-looking, for E12's
slo lens) but `oah/design/lens.py`'s `design_lens()` still returns a bare
`design_fragment` — extending its return contract to `{artifact_type: parsed}` was
scoped out as unnecessary risk with zero current consumer; E12 does that when the
slo lens actually needs a second artifact type.

The moment of opening `surface_map.schema.json`'s closed `kind` enum (and its
three duplicates, plus `dimension`, `lens`, `maps_to.kind` ×2 more skill-schema
copies research found beyond the ADR's original list, and `event_type` ×2 copies)
to a pattern-constrained string removed real protection against a hallucinated
value from S1's live LLM disambiguation pass — the one place that mattered, since
every other kind/lens/attribute-kind value is enforced structurally by
construction elsewhere. `oah/discovery/disambiguate.py` now checks a
non-null disambiguated `kind` against the loaded pack's real vocabulary at
runtime (`oah/domains/validate.py`) and refuses to merge a hallucinated one,
with a real regression test for exactly that failure mode.

### E12 — Service domain pack *(rewritten; was "second domain pack, stub")*
Proves — or disproves — the pipeline-core/domain-pack split from README's "Why"
against one concrete non-AI domain: ordinary request-driven services. The domain
is now chosen rather than deferred, because E13 gives the abstraction a seam to be
tested against, and because the evidence needed to pick well already exists (a
real first candidate consumer — see below).

**Why this domain inverts the value proposition, and why that is the point.**
HTTP semantic conventions are Stable; eBPF-based auto-instrumentation emits HTTP
RED metrics and correctly named spans with no code change, no library install and
no restart, and propagates W3C trace context into outgoing calls. The GenAI pack
earns its agentic source editing because nothing else will write those spans. A
service pack that wrapped HTTP handlers would re-emit, worse and later, what
`opentelemetry-instrument` already provides. So this pack's value is the
**decision layer over signals that already exist**, plus the narrow set of things
zero-code instrumentation provably cannot do: business attributes and custom
spans, a guaranteed low-cardinality route, the SLI definition itself (conventions
define attributes, never which events are valid or good), and continuity
verification across runtimes whose propagation maturity differs. An explicit
anti-redundancy gate enforces this: a DTO whose only effect is to re-emit an
attribute already covered by the pack's declared `auto_instrumentation_baseline`
is refused, not generated.

**Lenses.** Six. `tracing`, `ops` and `pii-governance` **reused unchanged** — the
concrete test of the split, and any edit they turn out to need is a reportable
finding against it. `telemetry-cost` adapted from `cost` (token accounting becomes
cardinality, sampling and retention accounting). Two new: `slo` (indicator,
objective, paired-window burn-rate tiers, error budget policy) and `dependency`
(edge criticality, the extra-nine rule, budget split between own failures and
dependency failures). Dropped: `generation-capture`, `retrieval`,
`realtime-multimodal`.

**Point kinds.** `http_server_route`, `http_client_call`, `db_query`,
`queue_producer`, `queue_consumer`, `scheduled_job`. The two `queue_*` kinds
already exist in `surface_map.schema.json` and have never been emitted by
anything — the pack turns dead vocabulary live.

**Excluded from v1, with reasons rather than silence.** Resource saturation: S1
finds call sites in source, and CPU, memory and connection pools are not call
sites; covering them needs a second discovery source (deployment manifests,
runtime inventory), which is SP9's territory. Database and messaging conventions:
stability unverified against primary sources — SP11. Both are declared
`declared_undetected` in the manifest and surfaced in `run_manifest.json`, so an
undetected kind can never read as a covered one.

*DoD:* (a) a corpus fixture in this domain passes S1→S9 and clears S5/S6; (b) the
three reused lenses run with no edit to their SKILL.md files; (c) **registry
families with structurally different detector shapes** are proven, not several of
the same shape — an outbound client call fits the existing receiver/method-suffix
machinery, whereas the first candidate's stack needs two shapes the adapter does
not have at all: a declarative route registration (JSX element or route-object
array) and a global unimported callee (`fetch`). A single-shape prototype would
repeat exactly the mistake SP10 avoided for languages; (d) the anti-redundancy
gate refuses at least one real would-be-redundant DTO on that fixture; (e) every
stability claim traces to a verified namespace, `unknown` where it has not been
verified.
*Depends on:* E13, **E11's TypeScript half**, SP11, SP12. M4 remains a
prerequisite for *evidence* (the GenAI pack proven end to end) but no longer for
*design*.

**E11-TS is now a hard blocker, not parallel work — partially resolved.** The
first candidate consumer's stack contains no Python at all: a React/TypeScript
SPA in front of a Java CMS. `oah/discovery/typescript_adapter.py` (E11-TS phase
1, `docs/decisions/014`) is now real and corpus-verified at 100% recall — S1
itself can map this stack's SDK calls, routes, and fetch calls — and is now
reachable through the real CLI via `--language typescript` (CLI language
dispatch, landed above), not just as a module-level import. S2's
manifest-based vendor detection also now runs against this stack's
`package.json` (next paragraph). What's still missing before a service pack
can actually be piloted against that stack: S2's TypeScript **source-level**
scan (next paragraph — logger call sites, error handling), and E12 itself
(still blocked on Java/AEM being explicitly out of v1 regardless, per
`docs/decisions/011`).

**S2 needs its own small epic alongside — manifest half landed.** The
telemetry inventory scanner is Python-specific and recognises only stdlib
logging, OpenTelemetry and prometheus/statsd/datadog via source scanning. It
could not read `package.json` and did not recognise any commercial APM or log
platform. **`oah/discovery/manifest_scanner.py` landed** (2026-08-27,
`docs/decisions/015`): `oah inventory` (and everything downstream of
`build_telemetry_inventory`) now scans the target repo root's `package.json`
against a real, verified vendor table — OpenTelemetry JS, Dynatrace, New
Relic, Splunk (`@splunk/otel`, itself an OTel JS distribution — kept as its
own vendor identifier, not folded into `opentelemetry`), Datadog, Sentry,
winston, pino, prom-client, and StatsD clients — unconditionally, no new CLI
flag, zero output change for a repo with no `package.json`. Two real gaps
named, not silently dropped: nested/monorepo `package.json` files aren't
scanned (root only), and a real TypeScript **source-level** scan (logger call
sites, error-handling classification — the deeper equivalent of
`telemetry_scanner.py`'s own tree-sitter walk, for TS/JS grammar) remains
fully unbuilt, comparable in size to E11-TS's own S1 port. A real, named
limit of manifest-only detection: Dynatrace's actual auto-instrumentation
runs as a host-level OneAgent process, not an npm dependency at all, so its
absence from `package.json` does not mean "no Dynatrace."

**E12 phase 1 landed** (2026-08-27, `docs/decisions/016`): every blocker
above (E13, E11-TS + CLI dispatch, SP11, SP12) is now real, so E12 itself
started. `domains/service/pack.json`: seven point kinds (`declarative_route`,
`http_server_route`, `http_client_call`, `db_query`, `queue_producer`,
`queue_consumer`, `scheduled_job`) and the three lenses the ADR names as
reused **unchanged** (`tracing`, `ops`, `pii-governance`) — verified for
real against the real pack, real `SKILL.md` files (zero edits), and real S5
gates, closing E12's own DoD (b). A real bug surfaced and fixed along the
way, not routed around: every `design_*` wrapper in `oah/design/lens.py`
but `design_tracing` hardcoded its own point-kind filter literal instead of
reading it from the loaded pack's `lenses[].target_kinds` — invisible with
only the genai pack (extracted from those exact literals in E13), but a
second real pack's `ops`/`pii-governance` entries would have silently
received zero points and returned `None` regardless of what their manifest
declared. Filtering now happens once, pack-driven, in `oah/cli.py`'s
`_design_all_lenses`. `schemas/domain_pack.schema.json`'s `detected_by`
enum gains `fixed_pass` for E11-TS's own hardcoded (not registry-driven)
detector passes — declaring `declarative_route`/`http_client_call` under it
closes `docs/decisions/014`'s own named gap (both already detected, owned
by no pack until now).

**E12 phase 2 landed** (2026-08-27, `docs/decisions/017`): the
anti-redundancy gate, DoD (d). `oah/design/dto_generator.py`'s `generate_dtos`
now refuses any model-proposed DTO whose every `expected_events[].required_attributes`
entry is already in the loaded pack's own `auto_instrumentation_baseline` —
its only effect would have been to re-emit, worse and later, what
`opentelemetry-instrument` already provides for free. Refused DTOs are
reported under a new, additive `refused_dtos` field
(`schemas/implementation_dto.schema.json`), never a rollout step; a DTO
that adds even one genuinely new attribute alongside a covered one
survives whole (attribute-level pruning is a named, deliberately
unattempted refinement). Zero behavior change for genai or any pack that
declares no baseline, by construction.

**E12 phase 3 landed** (2026-08-27, `docs/decisions/018`): the Express
registry, DoD (c)'s second structurally-different detector shape. Hit two
real, pre-existing gaps before it could work at all: `module_function_call`
(a receiver created via a bare factory call, `const app = express()`, not
`new X()`) was named in `schemas/domain_pack.schema.json` since E13 but no
adapter ever implemented it; `oah/discovery/typescript_adapter.py`'s
registry data was derived once, at import time, from the genai pack only —
exactly the "process-global constants, no second pack yet to justify
re-parameterizing" cost `docs/decisions/016` already named as deferred.
Both fixed for real: `ImportResolver.resolve_factory_call` plus a new
`_RegistryContext` threaded through `_walk`'s recursion, `detect_file`/
`detect_repo`/`build_surface_map` all gaining a `pack=None` parameter
(default → genai, byte-identical). Two precision guards grounded in
Express's own documented API, not a real corpus (named explicitly as
docs-grounded, not corpus-verified, same honesty precedent as genai's own
livekit registry): `app.get(name)` (1 arg, a settings read) vs.
`app.get(path, ...handlers)` (2+ args, a route) is disambiguated by
argument count; `app.use(...)`/`app.all(...)` are excluded from
`method_suffixes` entirely (`use` is overwhelmingly plain middleware with
no path argument in real code). New `--pack {genai,service}` flag on
`map`/`gaps`/`design`/`event-schema`/`dtos`/`readiness` (default `genai`)
replaces every command's own hardcoded `load_pack("genai")` — verified
end to end through a real `oah map --language typescript --pack service`
subprocess run.

**E12 phase 4 landed** (2026-08-27, `docs/decisions/019`): the
`telemetry-cost` lens, adapted from genai's `cost` (token accounting
becomes cardinality/sampling/retention accounting). `skills/s4-telemetry-cost/`
is a new skill, not a find-and-replace of `s4-cost` — cardinality risk is
directly informed by S1's own `has_path_parameter` field on route points
(a parameterized route is `high` risk unless the point already shows the
receiver templates the segment), sampling steers toward tail-based/
error-biased strategies for high-cardinality error-relevant points rather
than a flat rate, and retention tiering is a real axis `cost` never
needed. Cross-cutting (`target_kinds: null`), unlike `cost`
(`llm_generation`-only) — cardinality/sampling/retention cost applies to
any point kind. `design_telemetry_cost` is a pure pass-through, matching
every lens's contract since phase 1's own fix. No new S5 gates this
phase — `docs/decisions/011`'s new-gate list is entirely `slo`-shaped;
`telemetry-cost` satisfies the ten existing domain-neutral gates
unchanged, proven by a real `run_gates` call in this phase's own tests.

**E12 phase 5 landed** (2026-08-27, `docs/decisions/020`): the `slo` lens
— the deferred multi-artifact work E13's own decision record named
("`lenses[].emits` ships... extending `design_lens()`'s return contract
was scoped out... E12 does that when the slo lens actually needs a second
artifact type") landed here, driven by the first lens that actually needs
it. `design_lens()` itself needed no change (it already returns whatever
the skill's own output schema declares); `oah/cli.py`'s
`_design_all_lenses` now unpacks a multi-emit lens's `{artifact_type:
value}` result, feeding `design_fragment` into the existing S5/S7 pipeline
unchanged and surfacing everything else (a new `extra_artifacts` return
value) for callers that know what to do with it — `cmd_design` is the only
one that does today, under a new `extra_artifacts` output key.
`schemas/slo_spec.schema.json` (indicator/objective/alert-tiers/error-budget-policy)
and `oah/design/slo_gates.py` (7 gates: burn-rate recomputation verified
against `docs/decisions/011`'s own worked table — 2%/1h→14.4, 5%/6h→6,
10%/1d→3, 10%/3d→1 at a 30-day period — paired short-window validity,
policy exit criteria, dangling-tier-reference checks, objective
completeness, target-not-1.0, and percentile-averaging refusal). No
formula supplied for the short-window ratio itself — the ADR's own
finding that no reviewed source derives it; the skill requires stated
rationale instead of a copied constant.

**E12 phase 6 landed** (2026-08-27, `docs/decisions/021`): the
`dependency` lens — **all six of E12's lenses are now real**
(three reused, one adapted, two new). `schemas/dependency_model.schema.json`
+ `oah/design/dependency_gates.py` (3 gates: `critical_dependency_extra_nine`
— a **hard** edge's dependency failure rate must be at most one-tenth of
its dependent's own failure rate, verified against a real digit-count trap
in the tests where `0.999`→`0.9995` looks like "more nines" but is only a
2x tighter bound, not the required 10x; budget-split-sums-to-one;
every-edge-names-fallback). `skills/s4-dependency/` is the second skill
(after `s4-slo`) whose output isn't a bare `design_fragment`
(`{design_fragment, dependency_model}`) — reuses phase 5's own
multi-artifact plumbing unchanged. `route_is_templated`/`cardinality_guard`
deliberately NOT folded in despite sharing an ADR sentence with the
extra-nine rule — named as a real, separate, still-unbuilt gap rather than
scope-stretched onto this phase.

DoD (b) ("the three reused lenses run with no edit to their SKILL.md
files") is proven across the now-complete lens roster.

**E12 DoD (a) mechanism proof landed** (2026-08-27, `docs/decisions/022`):
`tests/test_e12_service_pack_integration.py` drives the real S1→S9 chain
(`cmd_readiness`, `--pack service --language typescript`) against a small,
hand-authored Express+`fetch` fixture — real S1 detection (all three
points, via the real Express registry), all six lenses (including both
wrapper-shaped ones), S5's ordinary gates AND the new slo/dependency gate
sets, S7's merge, S8's DTO generation, and S9's readiness assembly all
composing correctly end to end, verified directly (printed and inspected,
not just asserted green). Found and fixed a real, separate bug first:
`cmd_readiness` discarded `_design_all_lenses`'s `extra_artifacts` return
value entirely, so `slo_spec`/`dependency_model` gate findings never
reached a readiness decision for the service pack — the exact "an
artifact exists but nothing downstream checks it" gap this project's own
discipline exists to catch, fixed the same way `cmd_design` already
handled it. **Named honestly**: the fixture is hand-authored, not a
vendored real-world repository — E7's own real-corpus territory remains
the stronger, still-unattempted version of DoD (a).

**E12 phase 7 landed** (2026-08-27, `docs/decisions/023`): the `pg`
registry (`db_query`) — the second S1 registry, and unlike Express, zero
adapter code changes: `pg`'s `Client`/`Pool` constructors + single
`.query()` method are the exact `receiver_method_suffix` shape
Anthropic/Pinecone/LangSmith already use, already fully implemented, so
this landed as pure pack data. Verified against node-postgres's own docs
before building (both classes real/current, no dual-purpose-method
ambiguity the way Express's `.get()` had). Deliberately narrow, three real
gaps named: CommonJS `require()` (no registry in this pack has ever
supported it), the default-import-then-destructure form (still common for
pg < 8.15), and `new pg.Client()` namespace-member construction (the same
class of gap `express.Router()` left named).

**Still fully unbuilt, named not implied**: three more S1 registries
(`queue_producer`/`queue_consumer`/`scheduled_job`), `route_is_templated`/
`cardinality_guard`, S11 signal provenance, and a real vendored-corpus
fixture (E7's own territory).

**A real finding worth recording before attempting the queue registries**:
`amqplib` (verified against its own README/API docs — connect/channel/
queue-op method names all confirmed real) needs a materially harder
detector shape than Express or `pg`. Both of those are one-hop
(`new X()` or `X()` → a method on the same variable); `amqplib`'s real
shape is three hops -- `amqp.connect(url)` (a namespaced module-function
call, itself a factory) → `.createChannel()` on the awaited result → the
actual queue operation (`assertQueue`/`sendToQueue`/`publish`/`consume`)
on THAT awaited result. `oah/discovery/typescript_adapter.py`'s
known-name tracking only resolves a single hop from import to receiver
today -- extending it to chain through two intermediate awaited
assignments is a real, separate adapter change, not a data-only registry
addition the way `pg` was. Deliberately not attempted rather than shipped
as a low-confidence heuristic (e.g. matching `sendToQueue`/`consume` by
method name alone, with no receiver resolution at all) -- that would be a
real precision regression from every registry built so far, none of which
guess at an unresolved receiver.

**E12 phase 8 landed** (2026-08-27, `docs/decisions/024`): the `node-cron`
registry (`scheduled_job`). Verified via a live npm download-count query
before choosing a library (`cron` ~6.8M/week but inflated by transitive
NestJS installs that never call `new CronJob()` directly; `node-cron`
~5.5M/week, the real #1 direct-call-site choice; `node-schedule`
~4.4M/week). `node-cron`'s own `cron.schedule(...)` is called directly on
the imported module -- neither existing receiver shape fit, so a third
one, `imported_namespace_method_call`, was added: a single fallback in
the call-site resolver, consulting the SAME `(module, local)` binding
`ImportResolver.name_alias` already stores for every constructor-based
registry, when no real `new X()`/`X()` construction resolved the
receiver. Safe by construction for every existing registry (calling a
method directly on an unconstructed SDK class isn't valid real-world
TypeScript). `cron`'s own `new CronJob(...)` needs a genuinely fourth
shape (the constructor call itself IS the registration, no method-suffix
match needed at all) -- named, not attempted.

**S11 signal provenance landed** (2026-08-27, `docs/decisions/025`) --
`docs/decisions/011`'s own named S11 addition, core validation
infrastructure rather than E12-specific. Verified via a real live local
OTel SDK capture (not assumed, and not the first attempt: the
`ConsoleSpanExporter` pretty-print format `--dynamic` scrapes turned out
not to expose `instrumentation_scope` at all, a real, structural
finding): an auto-instrumented span's `instrumentation_scope.name` is the
instrumenting *library's* own name; a manual `tracer =
trace.get_tracer(__name__)` span (S10's own taught pattern) carries the
*target's own* module name instead. `oah/validate/live_sandbox.py`'s
`_parse_span_file` now extracts this from OTLP-JSON's own
`scopeSpans[].scope.name`; `oah/validate/event_assertion.py`'s
`check_dto_dynamic` classifies it (`auto_instrumentation`/
`harness_instrumented`/`unknown`) into a new `provenance` field, present
only when an event is actually `observed`. A real, honest asymmetry
confirmed by running (not just editing) three real-Docker tests: `--live`
gives a genuinely meaningful answer; `--dynamic` always reports
`["unknown"]`, a structural limit of its own capture mechanism, not a bug
routed around.

**`route_is_templated`/`cardinality_guard` landed** (2026-08-27,
`docs/decisions/026`) -- the last of `docs/decisions/011`'s own two named
new gates now real (`critical_dependency_extra_nine` landed in phase 6).
Resolved the open "S5 or S11?" question this gate was deliberately left
unbuilt over: a `design_fragment` signal carries no runtime value to
check, so this is a design-time question made self-contained by adding an
optional `cardinality_guard: {is_templated, unavailable_reason}` field a
lens's own signal can set. `oah/design/gates.py`'s new
`check_route_is_templated` joined the **domain-neutral** `ALL_GATES` list
(the check itself never looks up point kinds, only the field's own
internal consistency) -- `telemetry-cost`'s own `cardinality_risk` signal
is the first, and so far only, real consumer.
`skills/s4-telemetry-cost/SKILL.md` now teaches exactly when to set
`is_templated: false` (the ADR's own AEM example). Adding a new
always-run gate broke E13's own committed golden snapshot for genai (one
new, always-passing finding on every fragment) -- a real, expected
consequence the snapshot test's own docstring already names its remedy
for; regenerated, six-line diff, confirmed nothing else shifted.

**Signal provenance summary landed** (2026-08-27, `docs/decisions/027`)
-- `docs/decisions/025`'s own named follow-up: a report-level
`signal_provenance` field (`oah/validate/event_assertion.py`'s new
`summarize_provenance`) combining `--dynamic`'s and `--live`'s event
assertions into one real answer to "were OAH's own changes load-bearing?"
Deliberately NOT wired into `compute_ladder_verdict`'s own promotion rule
-- `docs/decisions/011` posed provenance as a question the report answers,
not a new gating threshold; whether it should ever gate promotion is a
real, separate, undecided question. Verified end to end on a real
combined `oah validate --dynamic --live --baseline` Docker run: one
`unknown` (from `--dynamic`'s own capture mechanism) plus one
`harness_instrumented` (from `--live`'s real OTLP-JSON capture of the
same span) in one real report.

**E12 phase 9 landed** (2026-08-27, `docs/decisions/028`): the `amqplib`
registry (`queue_producer`/`queue_consumer`) — the fourth S1 registry, and
the one the "still fully unbuilt" note above flagged as needing a genuinely
new mechanism. Built exactly that: `chain_hop`, a new `detector_shape` that
is pure known-name-propagation data (no surface point of its own), letting
a chain of N pack-declared hops (each one's `sdk_module` matching the
previous one's synthetic `produces_module`) teach the prescan that a
variable assigned from `await <known-receiver>.<method>()` is itself a new
kind of known receiver. amqplib's real two-hop chain (`amqp.connect()` →
`.createChannel()`) now resolves through two chain_hop entries, after which
the **existing** `receiver_method_suffix` matching handles
`sendToQueue`/`publish`/`consume` with zero new detection code. One real
wrinkle found only while building, not anticipated when this was scoped:
`queue_producer` and `queue_consumer` are different `surface_kind`s that
legitimately share one `produces_module` (`"amqplib#channel"` — a single
real `Channel` variable calls both) — the pre-existing one-entry-per-module
`module_to_registry` couldn't express that, so call-site resolution now
disambiguates by which registry's own `method_suffixes` actually matches
(byte-identical for every pre-existing, non-colliding module). General by
construction, not amqplib-specific: a future N-hop SDK (e.g. `kafkajs`'s
`kafka.producer()` → `producer.send()`) is now pure pack-data, no adapter
code change. `assertQueue`/`createConfirmChannel()` named as real,
deliberate exclusions, not folded in.

**E12 phase 10 landed** (2026-08-27, `docs/decisions/032`): the `axios`
registry (`http_client_call`) — the fifth S1 registry, and the first one in
this pack found by actually running the adapter against a real target repo
(`mf-analyzer-web`, an EPAM React/Vite app) rather than reading an SDK's own
docs first. A first version of the registry alone (chain_hop from
`axios.create()` to a synthetic instance module, mirroring amqplib's own
precedent) resolved **0 of the repo's ~291 real axios call sites** — root
cause, found live: the axios instance is built and `export default`-ed in
one file, imported and called in ~450 different consumer files, and every
known-name mechanism this adapter has ever had only ever tracked a receiver
within the file that constructs it (the same boundary SP1's
`docs/decisions/003` named for the Python adapter, routed there to an LLM
pass this adapter has never had). Built the fix, not just documented the
gap: `typescript_adapter.py` gained a two-pass repo scan — pass 1 builds a
repo-wide `{file: {export_name: resolved_module}}` index via a new
`_collect_export_map` (reusing each file's own already-populated
known_names, needing no special handling for `export const x = ...` since
`_walk`'s existing recursion already processes it); pass 2 resolves each
file's own imports (relative paths directly, `tsconfig.json`
`compilerOptions.paths` aliases like `"@/*": ["src/*"]` via a new
`_resolve_module_specifier`) against that index and seeds any hit into
`known_names` before the file's real walk — from there every existing
resolution/suffix-match path handles it exactly like a local receiver, zero
further new code. Single-hop only (a re-export chain through a further
file is a named, tested gap), and verified end to end on the real repo:
**0 → 294 real call sites detected.**

**S2 gains a real TypeScript telemetry inventory** (2026-08-27,
`docs/decisions/033`): assessing E12 phase 10 end to end (`oah map` → `oah
inventory` → `oah gaps` against the same real `mf-analyzer-web` repo)
found `oah inventory` reporting **zero findings** on a real ~450-file
app — `telemetry_scanner.py`'s `build_telemetry_inventory` only ever
scanned `*.py` files, with no `--language` flag at all, so every
TypeScript `oah gaps` run was joining real S1 points against an S2
inventory that had structurally never looked at the target's own source.
The repo's own real shape: a hand-rolled `class Logger {
error()/warn()/info()/debug() {...} }` singleton, exported once,
imported into ~140 consumer files with ~790 real call sites — the
identical shared-singleton-module pattern phase 10's axios fix needed,
now needed a second time for logging. Rather than re-solve it: the
cross-file module-graph mechanism (`_collect_export_map`/
`_load_path_aliases`/`_resolve_module_specifier`) was extracted out of
`typescript_adapter.py` into a new shared `oah/discovery/
ts_module_resolution.py` (detector-agnostic by construction, zero S1
behavior change) and reused by a new `oah/discovery/
ts_telemetry_scanner.py` — `console.*` calls, a `winston`/`pino`/
locally-defined-logger-class heuristic (two-or-more logger-shaped method
names required, matching `manifest_scanner.py`'s existing vendor
vocabulary rather than inventing new identifiers), `@opentelemetry/*`
imports, and `try`/`catch` classification (swallowed/logged/reraised, no
`exception_type` — TS catch bindings carry no real static type info,
unlike Python's `except SomeError as e`). `oah/cli.py` gained a
`_build_telemetry_inventory` dispatcher mirroring `_build_surface_map`'s
own shape, wired into all four S2-consuming commands; `oah inventory`
itself gained the `--language` flag it never had. Verified end to end on
the same real repo: 0 → 440 files scanned, 0 → 759 logger call sites (709
cross-file-resolved), 0 → 688 error_handling entries, and `oah gaps` moved
from 100% `dark` to 265 dark / 110 partial. Java still has no S2 scanner —
a real, named gap, not silently claimed.

**`--context`-weighted priority becomes real for TypeScript**
(2026-08-27, `docs/decisions/034`): running `oah gaps --context
context.yaml` against the same motivating repo, with a real completed `oah
interview`, produced ZERO change in priority — `workflow_hint` (the field
S3's `_find_workflow` matches against a `context.yaml` workflow name) is
populated only by Python's LLM disambiguation pass; the TypeScript adapter
has never had one, so the field was never set on a single TS point.
`oah/discovery/typescript_adapter.py` gained `_infer_workflow_hint`,
deterministic and model-free: a route's own static path segments when
present, else the defining file's module name (camelCase-split, a common
suffix like `Service`/`Api`/`Client` stripped) — wired into all four
point-emission sites, 375/375 points on the real repo now carry a hint. A
second, independent problem surfaced while fixing the first: even with
hints populated, `_find_workflow` requires an EXACT string match, and `oah
interview` never showed the interviewee what hints existed at all, for
*either* language — the owner was always typing workflow names blind.
`oah interview` gained `--surface-map surface_map.json`: when given, it
prints S1's own hints (most-frequent first, with point counts) before
asking for workflow names, so naming a workflow to match one verbatim
actually connects it. Verified end to end: three workflows named to match
three printed hints exactly → 118 of 375 real points matched and
re-weighted by interviewed criticality (12 bumped to `p0`: dark coverage
on a high-criticality, direct-PII workflow), versus 0 matched before this
phase.

**`oah estimate` gains `--language`/`--pack`** (2026-08-27,
`docs/decisions/035`): the same class of bug as the two entries above, found
the same way — `oah estimate` always hardcoded the Python adapter, no
`--language` flag existed on it at all (unlike `map`/`gaps`/`inventory`/
`dtos`/`readiness`, which all gained one already), so a TypeScript target
silently reported `candidate_call_sites: 0`, not an error, making every
downstream per-stage dollar figure wrong by construction. Fixed with the
same normalize-then-dispatch shape as every prior language fix: a new
`_detect_counts` calls the right adapter's `detect_repo` and wraps a
plain resolved-list return (TS/Java, no LLM-disambiguation counterpart) as
`(resolved, [])` so the rest of the cost formula is unchanged. Verified on
the motivating repo: 0 → 375 candidate call sites, $0.67 → $16.40 total
estimate (most of the swing is S10's per-DTO agentic-session cost, now
computed against the real point count instead of zero).

**Spring AI `ChatClient` registry for the Java genai pack** (2026-08-27,
`docs/decisions/036`): a second real pilot repo, `legacy-code-transpilers`
(a real ~4400-file Java/Spring backend — the actual service behind
`mf-analyzer-web`'s own chat feature). `oah map --language java` reported
0 points on 4443 files scanned: the Java genai pack's only entry
(`docs/decisions/029`) covers the raw Anthropic Java SDK, and this repo
routes its LLM calls through Spring AI's `ChatClient` instead, a
completely different abstraction. One new registry entry, zero adapter
code changes (the same "second registry entry, no new mechanism"
precedent `pg`'s TS entry set): `static_builder_chain` covers both real
shapes at once — the dominant DI-injected-field case (`private final
ChatClient chatClient;`, often via Lombok's `@RequiredArgsConstructor`,
resolved purely by its declared type, no visible construction needed) and
the rarer local `ChatClient.builder(model).build()` form. Method suffixes
are 2-segment (`call`+terminal: `chatResponse`/`content`/`entity`), not a
bare `["call"]` — a bare `.call()` returns an intermediate spec object,
never itself a real call site, and matching it alone would risk colliding
with unrelated `.call()` methods (a real, tested precision guard).
Verified end to end: 0 → 13 real call sites across 8 files. A real,
confirmed-in-production instance of the Anthropic entry's own already-
named gap (a single unassigned expression chaining construction and the
call together, terminal buried mid-chain) was found on this same repo (4
files) and named, not fixed.

**S2 gains a real Java telemetry inventory** (2026-08-27,
`docs/decisions/037`): closes the gap the phase above named explicitly —
`oah gaps --language java` still reported all 13 Spring AI call sites
dark after the S1 fix, because no Java S2 scanner existed at all (the
same "fell back to the Python scanner's honest-empty result" shape
`docs/decisions/033` already fixed for TypeScript). New
`oah/discovery/java_telemetry_scanner.py`: `@Slf4j`-annotated classes
(Lombok synthesizes the `log` field at compile time, never visible in
source — the same class of implicit construction the S1 adapter already
had to trust for `@RequiredArgsConstructor`) and explicit
`LoggerFactory.getLogger(...)` fields under any name, `System.out/err
.println`, `io.opentelemetry.*` imports, and `try`/`catch` classification
with REAL exception types (Java's own `catch` carries genuine static
types, including real multi-catch, unlike TS's documented "not
applicable"). No cross-file mechanism built — Java loggers are per-class
by real convention (confirmed by reading the corpus), never a shared
singleton the way TS's own logger shape was, so none was needed. Verified
end to end: 0 → 4560 logger call sites, 0 → 1461 error_handling entries
across 3477 files in 3.6s; `oah gaps` on the 13 Spring AI points moved
from 13 dark / 0 partial to 3 dark / 10 partial.

**`oah readiness` gains `--save-intermediates`** (2026-08-27,
`docs/decisions/038`): explaining a real `remediate_before_release`
verdict from the 375-point mf-analyzer-web run in plain language found
that `readiness_report.json`'s own recommendation only ever aggregates
gate names and counts (`5× every_surface_point_has_decision`, `3×
no_phantom_surface_points`, ...) — not which surface point, which lens's
fragment, or the gate's own real per-point reason string
(`check_every_surface_point_has_decision`'s own code already produces
`"N surface point(s) have no design decision in this fragment: [...]"`, a
specific, useful message that never reached the final report). Root
cause: `cmd_readiness` computes the full S4-S8 detail
(`design_fragments`/`gate_findings`/`panel_verdicts`/`event_schema`/
`dtos`) in local variables, feeds it into S9's own aggregate assembly,
and lets it go out of scope — `oah design -o` already saves this same
detail for its own S4-S6 scope, `readiness` never had an equivalent.
New `--save-intermediates PATH` writes exactly that already-computed
data alongside the normal report, zero additional model calls.

**Real Sonnet pilot run + a design gap named: `health_thresholds`**
(2026-08-28, `docs/decisions/039`, **phases A-C landed same day** — see
next entry). The first
real (non-local-model) `oah readiness` run against `mf-analyzer-web`'s
375 real points produced `remediate_before_release`: the `ops` lens
failed schema validation cleanly (`signals: [] should be non-empty`, a
real rejection, not a reliability concern), and S7's event-schema merge
failed on `oah.telemetry_cost.cardinality_risk` — one journey's
`sensitivity_tier` (`confidential`, the real PII-handling `chat` journey)
disagreed with another's (`internal`). Reading the actual per-journey
fragments (`--save-intermediates`, `docs/decisions/038`) showed both
assignments were individually correct — `build_event_schema`'s own
one-tier-per-attribute-name invariant is what turns a legitimate
per-journey split into a hard conflict, not a model reliability problem;
an earlier draft of the published pilot report mischaracterized this as
"the lens contradicted itself" and should be corrected. Investigating
fixes surfaced a separate, standing gap: no field anywhere in
`design_fragment.schema.json`'s signal object says what a *healthy*
value looks like — the concept exists exactly once, confined to
`slo_spec.alert_tiers`, unavailable to any other lens. `docs/decisions/039`
designs `health_thresholds`: an optional per-signal array
(`state: green/amber/red`, `condition`, `basis: confirmed/assumed`
reusing `evidence_position`'s own vocabulary, `rationale`), deliberately
**not** a copy of `alert_tiers`'s burn-rate math — most signals
(categorical cardinality risk, binary compliance flags) aren't
ratio-based indicators, so that shape doesn't fit them. A new S5 gate,
`check_health_thresholds_well_formed`, checks structural validity only
(no duplicate states, a declared threshold set must name a real `red`
state, non-trivial `condition`/`rationale`) — same division of labor
`slo_gates.py` already draws between "the math is internally consistent"
and "the target was the right one," which stays a lens judgment call.
Decomposed into phases: (A) schema field + gate, zero behavior change for
any existing fragment; (B) targeted SKILL.md rollout to
`slo`/`telemetry-cost`/`ops`/`dependency` only, not all lenses; (C) S9
report roll-up, `basis: assumed` flagged with the same honesty treatment
`evidence_position` gets; (D) S7 merge policy when two lenses design the
same attribute with conflicting thresholds — resolved same-day, see
below. Real, named, deliberately deferred: a post-S11 recalibration path that
could promote `basis` to `confirmed`, a gate blocking a lens from
claiming `confirmed` before any run has happened, and Option B
(namespaced attribute names) as a smaller independent fix for the
original `sensitivity_tier` conflict. The separately-discussed
journey-first S4 batching proposal (group points by `workflow_hint`
before calling lenses; derive `sensitivity_tier` deterministically from
`context.yaml`) is structurally related — it would reduce how often this
class of S7 conflict arises at all — but is a distinct, larger,
not-yet-agreed proposal, tracked separately.

**Phases A-C landed** (2026-08-28, same-day autonomous follow-through on
the design above). `health_thresholds` added to `design_fragment.schema.json`'s
signal object; `check_health_thresholds_well_formed` added to
`oah/design/gates.py`'s domain-neutral `ALL_GATES` (same precedent as
`check_route_is_templated`, `docs/decisions/026`) — 8 new gate tests, all
passing. SKILL.md rollout: `telemetry-cost` and `ops` each gained a Hard
Rule requiring `health_thresholds` on their one genuinely metric-shaped
signal (`cardinality_risk`, `degradation_response`); `slo` and
`dependency` were told to normally omit it, since their own richer
mechanisms (`alert_tiers`, `dependency_model`) already cover it. **A real
bug surfaced and fixed during verification, not just claimed working**:
the first real Sonnet call against the updated `telemetry-cost` SKILL.md
(2 real `mf-analyzer-web` points) produced no `health_thresholds` at all,
schema-valid but silently missing the new field — root cause, found by
reading `oah/design/lens.py`'s `design_lens()`: the strict-mode structured
output schema sent to the model is loaded from each skill's own
`io/output.schema.json`, a hand-maintained, self-contained copy of
`design_fragment.schema.json` (matching every other lens's own stated
precedent) — the canonical schema edit never reached the four targeted
lenses' own copies, so the model was structurally unable to emit a field
its own output schema didn't declare, regardless of the SKILL.md prompt.
Fixed by propagating the field into all four targeted lenses'
`io/output.schema.json` files; re-verified end to end with a second real
Sonnet call against the same 2 real points — `health_thresholds` now
present, well-formed (3 states, correct `basis: "assumed"`, real
rationale per state) on both. S9's `readiness_report.py` gained a
`design_fragments` parameter and rolls declared `health_thresholds` up
into `observability_plan.health_thresholds` (per-lens, not merged across
lenses — kept that way even after Phase D landed, see below) and turns each `red` state into an
`observability_plan.alert_triggers` entry; a lens claiming
`basis: "confirmed"` at S4 time (never true by pipeline construction) is
flagged in `evidence_position.unknown` as unverified rather than silently
promoted to `evidence_position.confirmed` — 5 new tests, all passing.
Real, separate, pre-existing bug found and fixed while running the full
test suite for regression-checking (not caused by this phase's own
`design_fragment.schema.json`/`gates.py` changes, but fixed in the same
phase since it blocked verifying them): running the suite with a real
`ANTHROPIC_API_KEY` now present in `~/.env` (fixed for credential-loading
reasons during the earlier Sonnet pilot phase) meant any CLI-level test
that leaves one lens unmocked could silently make a real, live, possibly
slow model call instead of failing fast on a missing-credential check —
found via a `faulthandler.dump_traceback_later` stack dump showing
`test_cli_design.py::test_design_reports_gate_failures_with_nonzero_exit`
blocked on a live HTTPS read from Anthropic's API. Fixed at the source:
`tests/conftest.py` gained an autouse `_block_real_anthropic_credentials`
fixture forcing `ANTHROPIC_API_KEY=""` for every test (empty, not unset —
`python-dotenv`'s own `override=False` default only fills in a variable
that's entirely absent), restored automatically after each test via
`monkeypatch`. One more real, unrelated regression surfaced along the
way and fixed: `tests/test_e13_domain_pack_snapshot.py`'s committed
golden snapshot (`tests/fixtures/e13_snapshot/naive_memory.json`) no
longer matched, since the new `health_thresholds_well_formed` gate now
legitimately adds one more (passing) finding to every fragment's
`gate_findings` — exactly the test's own documented intended-change path,
not a wiring bug; the snapshot was regenerated and the diff checked by
hand first (6 lines, only the new gate's own finding, nothing else
moved). Full suite green after both fixes: **748 passed, 0 failed**,
0:03:56.

**Phase D landed** (2026-08-28, user decision: hard-fail, matching
`sensitivity_tier`'s own precedent, over leaving it deferred).
`oah/design/event_schema.py`'s `build_event_schema` now tracks each
merged attribute's `health_thresholds` the same way it already tracks
`kind`/`sensitivity_tier`: a fragment that declares none where another
does is not a conflict (silence isn't a competing claim); two fragments
that both declare one and disagree raise `EventSchemaConflictError`,
never merged by picking one arbitrarily. Deliberately does **not** surface
the resolved value in `event_schema.json`'s own merged `attributes[]`
output — that stays the S9 readiness-report rollup's job (Phase C),
kept per-lens/per-fragment there rather than duplicated at this layer. 6
new tests (no-conflict-on-silence, no-conflict-on-identical-values,
conflict-on-disagreement); the `naive-memory` E13 snapshot needed no
regeneration this time (that fixture declares no `health_thresholds`
anywhere, so the newly-tracked field stays `None` throughout and never
reaches the merged output). Full suite re-verified green after this
phase too.

**Deterministic PII-tier floor + attribute namespacing landed**
(2026-08-28, `docs/decisions/040`, same-day follow-up). Continuing the
architecture discussion, "journey-first S4 batching" turned out to be two
bundled ideas: a batching mechanism (left as an open, not-yet-agreed
proposal — real cost/quality tradeoffs, no evidence yet it's needed) and
deterministic `sensitivity_tier` derivation from `context.yaml.pii_presence`
(the piece that actually targets the original S7 conflict). A further
correction found mid-design: a **floor** alone (never let tier go below
some minimum) doesn't prevent the original conflict — it only stops
under-classification, not the same attribute name landing at two
different floor-compliant tiers across two journeys. Closing that needs
a second mechanism, Option B (namespaced attribute names), already named
and deferred in `docs/decisions/039`. Built both, per explicit user
decision. `oah/discovery/gap_model.py`'s `_find_workflow` made public
(`find_workflow` — the identical lookup, not a second implementation) so
`oah/design/gates.py` could reuse it for a new
`check_sensitivity_tier_meets_pii_floor` gate: a workflow with
`pii_presence: "direct"` gets a deterministic floor of `confidential` on
every signal covering its points — the same asymmetry (`indirect`/`none`
never get special-cased) `gap_model.py`'s own gap-priority weighting
already uses. A floor, not an assignment — the gate checks `tier >=
floor`, never sets it. `run_gates()` gained `point_workflow_hints`/
`context` keyword args, threaded through both `oah/cli.py` call sites.
`skills/s4-telemetry-cost/SKILL.md` (the lens with the real, confirmed
conflict — not rolled out blanket to every lens) gained explicit
guidance: namespace the attribute by workflow when tier genuinely differs
by journey, rather than emitting one shared name at disagreeing tiers.
Verified end to end with a real Sonnet call, first attempt, no bug this
time: the same 2 real `mf-analyzer-web` points, now with a constructed
`context.yaml` giving one point's workflow `pii_presence: direct` and the
other `none` — the model produced
`oah.telemetry_cost.cardinality_risk.ai_prompt_context` at `confidential`
for the direct-PII point and plain `oah.telemetry_cost.cardinality_risk`
at `internal` for the other, on its own initiative from the new
guidance; the floor gate passed. 8 new gate tests. Real, named, not
addressed here: the batching-mechanism half of the original proposal
remains open.

**`dependency` had the identical bug — found for real, same day.**
Preparing for a full-scale readiness re-verification: analyzing the
pilot's own already-collected `--save-intermediates` output (plain code,
no new model calls) by grouping every fragment's signals by
`maps_to.attribute` and checking for cross-journey `sensitivity_tier`
disagreement found `telemetry-cost` really did have it on all six of its
own attributes (confirming the fix was necessary), and `dependency`'s
`oah.dependency.edge_name` had the identical pattern — never surfaced in
the original run because `build_event_schema` raises on the *first*
conflict it finds, and `telemetry-cost` came first in fragment order,
silently masking this second bug. `tracing`'s `oah.tracing.propagation_risk`
spans both PII levels but never actually disagrees on tier (no real
risk); `pii-governance`/`slo` showed nothing in this run's own data.
`skills/s4-dependency/SKILL.md` gained the identical Option B guidance —
`pii-governance`/`slo` left untouched, no evidence they need it.
A separate, real, negative-evidence finding from a small isolated
`design_ops` probe against 2 real `http_client_call` points (testing
whether the lens's own `llm_generation`-framed SKILL.md text causes it to
refuse designing for a kind mismatch, per the service pack's own
`target_kinds: None` routing every point to it): it did **not** refuse —
produced 8 sensible signals despite the mismatched framing. The original
run's `signals: [] should be non-empty` failure is therefore likely
batch-size/complexity-related at real scale (375 points in one call), not
a simple kind-mismatch language problem — to be confirmed by the full
re-run, next.

**Step 3 landed: full 375-point real re-run, one self-inflicted
regression found and fixed.** `oah readiness` re-run against the same
`mf-analyzer-web` target/pack/context as the original pilot found a real
false-positive bug in this same day's own Phase D: three `telemetry-cost`
signals legitimately shared one unnamespaced attribute (tier genuinely
agreed, so Option B correctly didn't split the name) but disagreed on
`health_thresholds[].rationale` — free prose tied to each signal's own
distinct points — which the Phase D equality check (rationale included)
treated as a hard conflict, blocking S7/S8 for the whole run.
`oah/design/event_schema.py`'s `_health_thresholds_signature` now
compares only `(state, condition, basis)` per tier; verified against the
real fragments that triggered it (`build_event_schema` now succeeds, 21
attributes, where it previously raised). 2 new regression tests.

Other real findings, sorted by cause: `sensitivity_tier_meets_pii_floor`
worked exactly as designed, catching real under-classification in
`tracing`/`ops` on the `chat` journey (neither lens has the SKILL.md floor
reminder yet — `ops` only got the Option B health_thresholds rule
earlier, not the floor reminder — a named follow-up). A new
`pii_masked_above_tier` failure directly caused by the floor mechanism:
`dependency`'s pointer signal correctly reached `confidential` but
omitted `pii_masked: true` — fixed same day, `skills/s4-dependency/SKILL.md`
now reminds to set it. Two `consistency_assertions_referential_integrity`
failures checked against the pre-`docs/decisions/039` original run and
confirmed **pre-existing** (the model names `maps_to.attribute` values
instead of real `signal.name` values in `fields_involved` — already
failed identically before any of tonight's work), not investigated
further. `pii-governance` still fails with `signals: [] should be
non-empty` on a ~75-point batch — the step-1 finding (`ops` does *not*
refuse on a kind mismatch at small scale, and succeeded here at full
375-point scale too) rules out both "kind mismatch" and "batch size
alone" as the root cause; not investigated further this pass. Overall
verdict is still `remediate_before_release` — for different, mostly
pre-existing or narrower reasons than the original run, not the original
S7 conflict, which now holds clean at real scale.

**Two of the step-3 gaps closed same day, cheap ones first (user's own
prioritization call).** The PII-floor SKILL.md reminder `telemetry-cost`
already had was mirrored into `ops` and `tracing`, the two lenses step 3
caught genuinely under-classifying `chat`-journey signals. The
`consistency_assertions_referential_integrity` field-naming bug (`fields_
involved` getting `maps_to.attribute` names instead of real `signal.name`
values) turned out to have a findable root cause on inspection: no lens's
SKILL.md ever explains what `fields_involved` should contain, and the bare
`{"type": "array", "items": {"type": "string"}}` schema doesn't disambiguate
a signal's own name from any other string in the fragment. Fixed at the
schema level — `fields_involved`'s item schema gained a one-line
`description` naming the requirement explicitly, applied to the canonical
schema plus all 12 `skills/s4-*/io/output.schema.json` copies that declare
it (the now-familiar per-lens-schema-duplication mechanic from
`docs/decisions/039`). Verified against the exact real repro (`s4-ops` on
the `chatService.ts` `streamChat` point that originally failed): the new
fragment's `fields_involved` correctly names real signals, and all 13 S5
gates pass, including `sensitivity_tier_meets_pii_floor` (confirming the
new `ops` reminder worked in the same call). Full details:
`docs/decisions/040`'s Third addendum. `pii-governance`'s empty-signals
failure and the journey-first-batching architecture question remain open,
deferred again by explicit choice — real API budget already spent on step
3, further spend is the user's call, not a default.

**`pii-governance`'s empty-signals bug: root cause found, its own real
service-pack skill built (`docs/decisions/041`).** Three isolated real
Sonnet calls (a 2-point probe, the actual failing 75-point batch, and the
original run's own log) surfaced three *different* failure modes from
the same task — honest refusal, hallucinated content ("raw chat
completions" invented for two plain JSX `<Route>` elements, borrowing
`chat`'s direct-PII status from a `workflow_hint` that didn't actually
resolve to it), and the original literal empty array. That signature
means no coherent task, not a random glitch: `skills/s4-pii-governance`'s
entire framing is "govern content captured at an `llm_generation` point",
which has no valid referent for `http_server_route`/`declarative_route`/
`db_query` points. `domains/service/pack.json`'s own phase-1 claim
("zero SKILL.md edits") was verified at the time by a test whose LLM call
was mocked — structurally incapable of catching this. Fixed with a
genuinely new skill, `skills/s4-pii-governance-route` (masks request/
response parameters and query bind values instead, with explicit
anti-hallucination, full-batch-coverage, and workflow-linkage rules
grounded directly in the three failure modes observed), and a real
dispatch bug found along the way: `oah/cli.py`'s `_lens_fns_for_pack`
derived which Python function to call from the **lens name**, never the
pack's own `lenses[].skill` field — invisible until two packs needed
different skills under the same lens name. Verified against the exact
75-point batch that originally failed: 300 signals, 75/75 points covered,
all 13 gates pass (first attempt hit a real 600s `litellm.Timeout` for a
response this size — not a logic bug — resolved by re-running with a
longer timeout). 762 tests passing.

**A fourth full real re-run confirms the fixes, and finds one new
self-inflicted regression (`docs/decisions/042`).** Explicit user choice
to spend real API budget once more, to see whether `oah readiness`
actually behaves differently now. It does: `pii-governance` (12 signals,
full coverage, all gates pass), `consistency_assertions_referential_integrity`,
and `sensitivity_tier_meets_pii_floor` all hold clean at real scale.
`build_event_schema` raised again, though — `tracing` correctly floored
its `chat`-journey signal to `confidential` (the reminder from
`docs/decisions/040`'s Third addendum working) but kept the same
unnamespaced `oah.tracing.propagation_risk` attribute across all three of
its own signals; splitting the signal `name` alone did nothing, since S7
merges by `maps_to.attribute`. Directly attributable to adding the
PII-floor reminder without also adding Option B namespacing guidance to
`tracing` — fixed the same way, mirroring `telemetry-cost`/`dependency`'s
existing paragraph. Verified mechanically (the real triggering fragment,
hand-patched exactly as the new rule instructs, re-run through
`build_event_schema`: conflict resolved, 26 attributes) rather than via a
fifth live model call — a stated tradeoff, not silently skipped.
`every_surface_point_has_decision`/`latency_budget_declared_per_point`
failures for `ops`/`slo`/`dependency` checked directly against the
pre-today intermediates and confirmed **pre-existing**, unrelated to any
of this session's work, not investigated further — `ops` (1/375 points
covered) and `slo` (~9/75) are now this investigation's single largest
remaining named gap, root cause completely unknown.

**`ops`'s and `slo`'s under-coverage: two different root causes found,
fixed, NOT live-verified (`docs/decisions/043`).** Direct inspection (no
model call needed) found `ops`'s own SKILL.md still said, in four places,
"use for `llm_generation` points" — true under genai, false under the
service pack's cross-cutting assignment ever since `docs/decisions/016`
— the same root-cause class `docs/decisions/041` found for
`pii-governance`, just a softer failure (under-coverage, not empty/
hallucinated output, since `ops`'s four signal categories don't actually
depend on LLM-generation content). Corrected throughout to mirror
`tracing`'s own honest cross-cutting framing. `slo` turned out to be a
genuinely different cause: its SKILL.md *deliberately* only designs real
SLOs for `p0`/`critical` journeys — real, documented architecture, not a
bug — but S5's `every_surface_point_has_decision` gate has no per-lens
exception, so any lens that intentionally skips points always fails it.
Fixed by requiring an honest placeholder signal
(`oah.slo.no_objective_designed`) for every skipped point, not silence —
same "explicit non-decision" pattern `docs/decisions/041`'s own
2-point probe already demonstrated. Landed without live verification
first — the Anthropic account's API credit balance ran out mid-session,
stated plainly rather than glossed over — then **verified for real the
same day** once the balance was topped up: a 12-point mixed-kind batch
for `ops` (12/12 covered, all 13 gates pass) and a 6-point
mixed-criticality batch for `slo` (the one point resolving to a real
critical workflow got a full `slo_spec`; every other point got an honest
`oah.slo.no_objective_designed` placeholder naming why,
`every_surface_point_has_decision` satisfied honestly). Not yet re-run at
the original full 375/75-point scale.

**`latency_budget_declared_per_point`'s `slo`/`dependency` failures: root
cause found and fixed, NOT live-verified (`docs/decisions/044`).** Found
while auditing readiness before spending further API budget: the
2026-08-25 commit that added the `latency_overhead_budget_ms` instruction
to all 9 then-existing lenses landed two commits before `slo` and
`dependency` were built, so those two lenses' own SKILL.md files never
received it — a pure, deterministic prompt gap, not a model-compliance
question, confirmed by `grep` alone. Fixed by adding the same instruction
to both. `ops`'s own instance of this gate failure is a separate,
still-unexplained case — its SKILL.md already has the instruction and the
gate failed anyway at full scale — left open, not guessed at. Prose-only
change; 762 tests passing, unchanged. Deliberately not live-verified yet:
running the pending full 375/75-point re-run (`043`'s own next step)
before this fix would have reconfirmed a failure that was already
predictable for free.

**`ops`'s latency-budget "mystery" closed; `telemetry-cost`'s PII-mask gap
diagnosed (`docs/decisions/045`), both by free data analysis, no code
change.** Diffing `every_surface_point_has_decision`'s and
`latency_budget_declared_per_point`'s own missing-point-ID lists for
`ops` in the saved `intermediates_sonnet_v3.json` shows they are the
identical 374-point set — `ops`'s latency-budget failure isn't a second,
separate bug, it's a direct consequence of the coverage bug `043` already
fixed (a point with no `ops` signal at all trivially has no
latency-overhead budget declared either). `telemetry-cost`'s three
`pii_masked_above_tier` failures were all `sensitivity_tier: confidential`
with `pii_masked` entirely absent — the exact shape `042`'s already-landed
reminder fix targets, raising confidence past "plausible" without
constituting live proof. The one item with no free substitute: confirming
`043`'s `ops`/`slo` coverage fix and `044`'s `slo`/`dependency`
latency-budget fix at the real full 375/75-point scale — isolated batches
already proved the mechanism, only a real full-scale live run proves it
holds at the scale that originally failed.

**That full-scale live run made, with explicit user go-ahead: `043`/`044`
confirmed for real; `ops`'s own self-inflicted S7 conflict found and
fixed (`docs/decisions/046`).** A real `oah readiness` run against
`mf-analyzer-web` at the original 375/75-point scale confirms
`every_surface_point_has_decision`, `latency_budget_declared_per_point`,
and `pii_masked_above_tier` all pass on every one of the 6 lens fragments
— `043`'s coverage fix and `044`'s latency-budget fix both hold at real
scale, and `045`'s diagnosis of `ops`'s and `telemetry-cost`'s failures
is confirmed correct. `build_event_schema` failed again, though — the
same class of self-inflicted conflict `042` fixed for `tracing`, now real
for `ops`: with coverage fixed, `ops` covers all four of the target's
workflows and correctly floors the direct-PII `chat` journey to
`confidential` while the rest stay `internal`, but all four of `ops`'s
own attribute categories (`release_id`, `degradation_response`,
`rollback_target`, `incident_owner`) shared one unsuffixed
`maps_to.attribute` across journeys. `042` had explicitly declined to
namespace `ops` speculatively, citing no evidence at the time — fixing
`043`'s coverage bug is exactly what created the conditions for the
collision to become real. Fixed with the same Option B namespacing
paragraph `tracing`/`telemetry-cost`/`dependency` already have, verified
mechanically (the real triggering fragment hand-patched exactly per the
new rule, re-run through `build_event_schema`: conflict resolved, 35
attributes). The verdict is still `remediate_before_release`, but now for
a genuinely different, out-of-scope reason: S9's dark-gap check reports
265 unaddressed p0/p1 `gap_model` entries with zero existing telemetry —
real, expected, not a design defect; it's M3's own still-open DoD (real
`oah instrument` application), not anything `039`-`046`'s design-lens
fixes were ever meant to close. This closes the loop `039` opened: every
S5 gate and S7 conflict found across real `mf-analyzer-web` runs in this
ADR chain is now fixed-and-confirmed-at-scale or fixed-and-mechanically-
verified.

**First candidate consumer (informs, does not gate, the design above).** A
consumer-travel property running a React/TypeScript SPA in front of Adobe
Experience Manager as a Cloud Service, already carrying Dynatrace, New Relic and
Splunk, with an OpenTelemetry JS rollout planned and W3C traceparent named as the
single correlation backbone; four named critical user journeys (home / search /
property detail / booking-checkout) under GDPR + CCPA. Full design rationale,
including three corrections the candidate forced against the pack's original
assumptions (detector shapes, route templating under AEM, a second correlation
backbone), in `docs/decisions/011-service-domain-pack-architecture.md`. Honest
status today: **OAH does not run on this stack at all** — not partially, not
report-only. The cheapest real deliverable that needs zero new code: run `oah
interview` for the four journeys (works today), hand-build one `slo_spec` for
`booking-checkout` against the designed (not yet built) schema with computed
burn-rate multipliers, and add a `splunk-hec` target to `oah backend-config`
(deterministic, no LLM/S1 dependency) with an OTTL masking policy for
query-string PII.

## Spikes

The first ten spikes are resolved as of 2026-08-25 — see `docs/decisions/`. Every
record includes its honest limitations (sample size, untested scope,
stretch items deferred); resolved does not mean zero remaining risk, it
means the question has a real, evidence-grounded answer instead of an
assumption blocking the dependent epic. SP11 and SP12 were added 2026-08-26 as
prerequisites for E12 (service domain pack), and both resolved the same day.
E12's remaining blocker is E11's TypeScript half.

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
| **SP11** | Stability and attribute sets of the DB, messaging, RPC and **browser** semantic conventions (the last added because the first E12 candidate's primary instrumentable surface is a browser SPA), verified against primary sources rather than inferred. The HTTP conventions are Stable and the GenAI ones are entirely Development; DB/messaging/RPC sit between and are currently **unknown to this project** — several proposed service point kinds depend on the answer, and a pack that guessed "stable" would be making exactly the unverified claim S9 refuses. Also: is `error.type` propagated as an attribute on the HTTP duration metric, which decides whether a good/valid-event SLI is computable from metrics alone or needs spans? | 3 d | E12 | Decision record + namespace stability table for the pack manifest | [012](docs/decisions/012-sp11-non-genai-semconv-maturity.md) — db stable (spans/collection-name), messaging development, rpc release_candidate (new enum value), browser development but request timing already rides on stable http.client.*; error.type confirmed stable+conditionally-required on both HTTP duration histograms |
| **SP12** | Two detector shapes the Python adapter does not have, prototyped in **TypeScript** rather than Python, because the first E12 candidate consumer's stack has no Python in it. (a) **Declarative registration**: SPA routes are JSX elements or a route-object array — neither a method call on a tracked receiver nor a decorator. This is the shape that matters most, because a consumer's business journeys *are* its routes. (b) **Global unimported callee**: `fetch(...)` has no import to anchor on, and the adapter's whole resolution model is import-anchored. Measure both against E2's existing recall and false-positive bars. Must also answer where the route template is *not* statically recoverable — a CMS that resolves URLs to content paths by resource type has no route literal in source, and a route the adapter cannot template is a stated gap, never a licence to substitute the raw path. | 1 wk | E12 | Decision record + TS prototype + corpus fixture | [013](docs/decisions/013-sp12-ts-detector-shapes.md) — 14/14 (100%) recall, 0 FP across 4 real TS repos (3 existing + 1 sourced, `cocktail-app`); route-object-array form (`createBrowserRouter`) prototype-verified only, no real fixture found using it — named gap for E11-TS |

## Sequencing sketch

```
M0:  SP1 SP5 SP6 SP10 → SP2 SP4 SP7 SP9 → SP3   [all resolved 2026-08-25]
M1:  E1 ─┬─ E2 ── E7(start)
     E11 (TS/Node) starts right after M1, Java follows on its own timebox
M2:      └─ E3 ── E4          E8(start, continuous)
M3:  E5
M4:  E6 ── E9 ── E10
     E13 (domain pack extraction) starts independently of M4 -- depends on nothing
     SP11, SP12 → E12 (service domain pack), gated on E13 + E11-TS, not on M4
post-M4: managed-backend targets, Go/.NET (if SP10's abstraction earns it)
```

## Explicit non-goals (for now)

- Being an observability *backend* (storage/dashboards) — we install and configure
  existing ones.
- Runtime guardrails/content filtering — adjacent product; we only make their
  signals visible.
- Supporting closed/no-code LLM platforms where we cannot touch source.
- Retargeting the pipeline to non-AI/non-LLM products, as a claim about *today's*
  code. README's "Why" claims S1–S3's mapping mechanics, S5's gates, S7's roll-up,
  S8/S9's DTO and readiness shapes and S11's ladder are domain-agnostic; enumerating
  where GenAI is actually hardwired found the claim true for the expensive half and
  false for the seam itself — see
  [011](docs/decisions/011-service-domain-pack-architecture.md). E13 (extract the
  seam) and E12 (service domain pack, scheduled and no longer a stub — see above)
  are now the real, sequenced answer to this non-goal, gated on E13 + E11-TS + SP11
  + SP12, not on M4.
