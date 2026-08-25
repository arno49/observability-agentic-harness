# SP5 — Cost model: predict run cost before spending

Status: resolved (formula + worked example). Blocks E1. Timebox: 3 days (used: same-day).
Accuracy target: ±40% (per ROADMAP.md) — **not yet verified against a real run; see
Consequences for why, and the recalibration protocol that closes the gap.**

## Context

E1's `estimate` command must predict a run's dollar cost from repo size/complexity
*before* spending anything. No pipeline code exists yet (pre-M0), so there is no
real run to calibrate against — SP5 has to produce a testable formula and a
recalibration protocol, not a validated number.

## Approach

### What actually drives cost isn't repo size directly

Repo LOC/file-count only predicts the *first* variable in the chain — everything
downstream is driven by pipeline-derived counts that don't exist until earlier
stages run. So `estimate` has to be two-phase, not one lookup:

1. **A free, deterministic pre-scan** (no LLM call): the same AST + signature-registry
   pass S1 runs anyway (per `architecture.md` S1 — "Walk the target repo with AST
   parsing and a signature registry... Ambiguous sites... go to an LLM disambiguation
   pass"), run once up front in scan-only mode. This costs nothing and yields the
   real driver variables below instead of guessing them from LOC.
2. **The formula**, applied to those counts.

### Driver variables (from the pre-scan, not from LOC)

| Variable | Meaning | Source |
|---|---|---|
| `C` | candidate call-sites found by AST pass | S1 pre-scan |
| `A` | of those, ambiguous → need LLM disambiguation | S1 pre-scan (`A ≤ C`) |
| `P` | finalized surface points (`≈ C`) | S1 |
| `G` | gap-model entries (`≈ P`, roughly 1:1 before merging) | S3 |
| `W` | workflows in rollout plan (from `context.yaml`, typically 3–8) | S3 |
| `D` | implementation DTOs (`≈ P × 1.2–2`: some surface points need more than one DTO — e.g. SDK call site + collector config) | S8 |
| `N_lens = 8` | S4 lens skills (fixed, per `architecture.md` S4) | fixed |
| `N_persona ≥ 3` | S6 panel personas (SRE, security, cost-skeptic; fixed minimum) | fixed |
| `N_scenario ≈ W` | S11 agentic-panel scenarios, roughly one per critical workflow | S9 rollout |

`LOC`/file-count only estimate `C` before the pre-scan has run (e.g. for a
pre-repo, "should I even try this" estimate); once the pre-scan runs, `C` and `A`
are known exactly and the LOC-based guess is discarded.

### Per-stage cost, and which stages actually cost anything

| Stage | LLM cost? | Scales with |
|---|---|---|
| S1 | AST pass free; disambiguation costs | `A` |
| S2 | inventory scan, similar shape to S1 | files with telemetry-related imports |
| S3 | one gap-modeler call joining S1×S2 against the reference domain model | `P` (input), `G` (output) |
| S4 | 8 independent lens calls over shared context | `N_lens` calls, each sized by `P`/`G` |
| S5 | pure code | $0 |
| S6 | 3+ panel calls over the *same* shared context as S4 | `N_persona` calls |
| S7 | one large synthesis call (architecture.md + event_schema.json + rollout_plan.md + runbook.md) | `G`, `W` (input); large fixed-ish output |
| S8 | DTO generation, batchable | `D` |
| S9 | mostly deterministic assembly from S5–S8 artifacts; at most one narration call | ~$0–small |
| S10 | Claude Agent SDK, one commit per DTO, standard token pricing incl. tool-use overhead (bash/text-editor tool definitions) — **not** the separate Managed-Agents session-runtime SKU, since S10 is the self-hosted SDK, not a Managed Agents session | `D` |
| S11 | deterministic layer free; agentic panel (telemetry auditor, privacy auditor, optional cross-service analyzer) | `N_scenario` |

### A real optimization the formula should exploit: shared-context caching

S4's 8 lens calls and S6's 3+ panel calls all read essentially the same underlying
context (`surface_map.json`, `gap_model.json`, `context.yaml`). That's 11+ calls
against one shared block. Writing it once with a cache breakpoint and reading it
10+ times costs `1 × write_price + 10 × (0.1 × base_input_price)` instead of
`11 × base_input_price` — roughly a **70%+ reduction** on the shared-context
portion of S4+S6's input cost at current 1h-cache-write pricing (2x base, read at
0.1x base: caching pays off after two reads per Anthropic's own pricing page, and
S4+S6 guarantees far more than two). This is
a concrete `estimate`/E1 implementation requirement, not just a cost-saving
footnote: the DTO/skill-invocation layer should structure the S4→S6 context as one
cached block, and `estimate`'s formula should credit the caching discount rather
than pricing every lens/persona call at full input rate.

### Worked example

Small target repo: 50 files, ~8,000 LOC, one workflow family. Pre-scan finds
`C = 40` candidate call-sites, `A = 15` ambiguous, `P = 40`, `G = 38` (a couple
merged), `W = 3` workflows, `D = 55` DTOs (~1.4× `P`), `N_scenario = 3`.

Baseline model-role assignment: **uniform Sonnet 5 ($2/$10 per MTok) across every
role** — a deliberately conservative upper bound, since SP8 (light-tier
Haiku-class role assignment) hasn't run yet; `estimate` should default to this
upper-bound mode until SP8 lands, then offer a cheaper mixed-tier estimate as an
option, not a default.

First-pass per-unit token assumptions (explicitly **uncalibrated** — see
Consequences):

| Item | Input tok | Output tok |
|---|---|---|
| S1 disambiguation, per candidate (batched, 20/batch, ~1,500 tok batch overhead) | ~300 | ~120 |
| S3 gap-modeler, per surface point (one call, ~4,000 tok reference material) | ~150 | ~150 |
| S4, shared cached context (written once) | ~10,000 | — |
| S4, per lens call (cache read + lens-specific) | ~1,000 read + ~1,500 | ~2,500 |
| S6, per persona call (cache read + persona-specific) | ~1,000 read + ~1,000 | ~1,500 |
| S7, one synthesis call | ~12,000 | ~18,000 |
| S8, per DTO (batched, 15/batch, ~1,200 tok batch overhead) | ~250 | ~200 |
| S10, per DTO application session (incl. tool-use overhead) | ~3,000 | ~2,000 |
| S11, per scenario, panel calls (2 auditors) | ~2,000 | ~1,500 |

Totals at these assumptions, Sonnet 5 pricing, S4's shared context written once
(1h cache write) and read at the 0.1x hit rate by the other 7 lens calls and all
3 S6 persona calls:

| Stage | Cost |
|---|---|
| S1 (15 candidates) | $0.03 |
| S2 (assumed comparable to S1) | $0.03 |
| S3 (40 points) | $0.08 |
| S4 (8 lenses: 1 write + 7 cached reads) | $0.28 |
| S6 (3 personas, cached reads) | $0.06 |
| S7 | $0.20 |
| S8 (55 DTOs, batched) | $0.15 |
| S10 (55 DTOs) | $1.43 |
| S11 (3 scenarios) | $0.06 |
| **Total** | **$2.31** |

At ±40% this reads as a **$1.39–$3.24** predicted range for this repo profile.
The absolute numbers are small at this repo size — the point of the worked
example is the *shape*: S10's per-DTO agentic application dominates (62% of
total), S4 is the second-largest line item even with caching (lens-specific
generation across 8 skills adds up faster than the shared-context discount
saves), and S1/S2/S3/S6/S11 are all cheap relative to S10/S4/S7/S8. That
ranking — not the dollar figure — is what `estimate` needs to get right before
the number matters at real repo sizes, since it tells `estimate` (and a user
deciding whether to run `fix` mode) where the actual spend risk concentrates:
S10, not the design/discovery phases.

## Decision

- `estimate` is a **two-phase command**: free deterministic pre-scan (reuses S1's
  AST pass in scan-only mode) → formula over the resulting counts, not a
  LOC-only lookup.
- Default estimate mode is **uniform-frontier** (single model role, currently
  Sonnet 5) as a conservative upper bound; a cheaper mixed-tier mode is deferred
  to SP8, not designed here.
- S4→S6's shared context **must** be structured as one cached block in the real
  implementation (E1/E3) — this is a design requirement the cost model surfaced,
  not just a pricing assumption, and belongs in `architecture.md`'s S4/S6
  description once E3 starts.
- The per-unit constants table above ships as a **versioned config**
  (`estimate_constants.json` or equivalent under E1), not hardcoded, specifically
  so it can be overwritten by real measurements once they exist.

## Consequences

- **This spike's output is a falsifiable formula, not a calibrated one** — every
  per-unit constant above is a first-pass assumption from the stage descriptions
  in `architecture.md`, not measured token usage, because no skill beyond S1's
  draft exists yet and no corpus run has ever happened. The ±40% target from
  ROADMAP.md is therefore **unverified**, not met — this spike cannot honestly
  claim otherwise pre-M0.
- **Recalibration protocol** (closes the gap, doesn't just note it): once E1
  exists, every real run's `run_manifest.json` (already tracking cost per
  E1's description) must log actual per-stage token usage alongside the
  pre-run estimate. `estimate`'s constants file gets refreshed from accumulated
  real-run data — the first several corpus runs (E7) function as SP5's real
  calibration set, retroactively. Track predicted-vs-actual per stage, not just
  total — S10 is predicted to dominate cost and S4 to be the runner-up despite
  caching, and that ranking is exactly the claim the first real runs should
  stress-test first.
- E1 gains one concrete scope item beyond what was already listed: the
  cache-breakpoint structuring of S4→S6 shared context.
