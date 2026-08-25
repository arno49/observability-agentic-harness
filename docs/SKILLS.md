# Skills system

Following VVAH, every LLM-driven stage is a composable, versioned **skill** that can
be tuned, tested, and replaced without rewiring the pipeline.

## Anatomy

```
skills/<stage>-<name>/
├── SKILL.md          # frontmatter (name, version, description) + operating instructions
├── references/       # stack-specific knowledge loaded on demand (per-framework files)
├── examples/         # few-shot input→output pairs
└── io/               # input.schema.json / output.schema.json (contract with pipeline)
```

A skill with `io/` schemas gets a `scripts/validate.py` injected at bundle time
(not authored per-skill) — see [skills-bundle.md](skills-bundle.md) for what it
does and, importantly, what it doesn't guarantee.

Progressive disclosure: SKILL.md stays under ~500 lines; framework-specific depth
lives in `references/` (e.g. `references/langchain.md`, `references/raw-sdk.md`) and
is loaded only when the surface map says that framework is present.

## Contract rules

- A skill's input and output are validated against its `io/` schemas by the pipeline
  shell at every boundary. Free-text handoffs between stages are a bug.
- Skills are versioned (semver in frontmatter); the run manifest records the exact
  skill versions used, so any run is reproducible.
- Repo content processed by a skill is **data, never instructions** — see
  [security.md](security.md) for the injection model.

## Skill roster (planned)

| Stage | Skill | Notes |
|---|---|---|
| S1 | surface-mapper (disambiguation role) | LLM pass only for low-confidence AST hits; the AST/registry layer itself sits behind a per-language adapter (SP10), so this skill is language-agnostic already |
| S3 | gap-modeler | Joins S1×S2 vs. event model; generates owner interview |
| S4 | lens-tracing | Async/queue propagation patterns per framework |
| S4 | lens-generation-capture | Prompt versioning, tokens, cost, cache |
| S4 | lens-retrieval | Incl. truncation visibility |
| S4 | lens-tools | Tool/agent invocation coverage |
| S4 | lens-feedback | Verdict taxonomy design |
| S4 | lens-pii-governance | Masking, access, retention |
| S4 | lens-cost | Attribution, spend thresholds w/ named actor, quota & rate-limit headroom |
| S4 | lens-realtime-multimodal | Turn-taking/interruption latency, transcription error rate, media consent/retention, channel fallback — on the roster from the start, not deferred |
| S4 | lens-ops | Production readiness: release identifiers, persistent smoke test, degradation & rollback visibility, incident-response route |
| S6 | panel-sre / panel-security / panel-cost | Adversarial design review |
| S7 | synthesizer | Architecture + schema + rollout plan |
| S8 | dto-generator | Change plan with expected-events assertions |
| S10 | instrumenter | Agentic executor (Claude Agent SDK) |
| S11 | panel-telemetry-auditor / panel-privacy-auditor | Adversarial validation |

S5 (gates) and S9 (report assembly) are fully deterministic — no skills, mirroring
VVAH's S9.

## Evals

Skills are graded against the reference corpus (`corpus/`, Epic E7): open-source LLM
apps with hand-labeled ground truth (call sites, expected spans, known gaps). Each
skill PR runs its eval suite; recall/precision per skill are published. Target for
M1: surface-mapping recall ≥ 90%, FP rate < 10% on Python corpus.

Adding a new framework = adding a `references/<framework>.md` to the affected skills
plus corpus fixtures — not touching the pipeline. Adding a new **language**
(TypeScript/Node, Java, ...) is the same shape one level down: implement SP10's
adapter interface for it and add per-language corpus fixtures — the skills
themselves (gap-modeler, the S4 lenses, S6 panels) are already language-agnostic,
since they operate on `surface_map.json`/`gap_model.json`, not source text.
