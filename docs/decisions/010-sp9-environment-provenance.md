# SP9 — Environment provenance: MVP vs. stretch, and the data model

Status: resolved. Blocks E6, E4. Timebox: 1.5 wk (used: same-day).

## Context

E6's S11 verdicts (`validated`/`validation_failed`/`needs_review`) mean
different things depending on which environment produced the evidence — a
`validated` run against a throwaway sandbox is not the same claim as one
from production-shadow. SP9 asks how OAH determines this, not just accepts
it on trust, comparing four options, and needs to decide an MVP versus a
future-epic stretch, plus the data model: where environment lives and how
self-reported-vs-corroborated gets distinguished in the S9 report.

## Approach

Before designing the comparison in the abstract, checked what's actually
available to parse in the real corpus already in hand — six repos across
SP1 and SP10 — since option (b) specifically depends on target repos
carrying real IaC/CI deploy config, and that's an empirical question, not
one to assume an answer to.

## Findings

1. **0/6 real corpus repos have any parseable deploy-target IaC/CI
   config.** No Terraform, Helm, or k8s manifests anywhere; the only
   `.github/workflows` found (`beacon`) is a PR-review bot, not a deploy
   pipeline; the only `Dockerfile` found (`llm-document-ocr`) is a
   build-only native-dependency image, already established as such in SP3's
   runnability matrix — not a deploy target either. This is a real,
   concrete data point against treating option (b) as sufficient on its
   own: for the realistic population of small/demo/hobby repos E7's early
   corpus will likely include, there is often nothing there to parse.
2. **Even where IaC/CI config exists, it describes the *possibility space*,
   not necessarily *this run's active target*.** A repo's Terraform might
   define both staging and production workspaces; parsing it tells you what
   environments the repo *can* deploy to, not which one a given validation
   run is actually pointed at right now, without a second piece of evidence
   (an env var, a target hostname, an explicit flag) to resolve which
   possibility is live.
3. **Options (c) and (d) both address real gaps that (b) alone can't close,
   at real, different costs.** (c) — a separately supplied infra/IaC repo
   path — matches how real production organizations actually split app code
   from deployment config (unlike this session's demo-heavy corpus), but
   requires the user to supply a second path and OAH to correlate two
   repos, nontrivial cross-repo reasoning. (d) — cloud-API introspection at
   run time — is the most directly authoritative option in principle
   (asking the cloud provider what account/project/tags actually apply) but
   requires OAH to hold and use real cloud credentials at validation time, a
   materially larger security surface (adjacent to SP7's threat model — a
   new high-value credential OAH would hold) and multi-cloud-provider
   scope, not just an engineering cost.
4. **This isn't a new report-structure problem — `architecture.md`'s S9
   already has the right shape for it.** S9's Markdown report already
   requires an explicit "evidence position (confirmed vs. assumed vs.
   unknown)" section. Environment provenance is a specific instance of that
   existing framework, not a new concept SP9 needs to invent a report
   section for.

## Decision

- **MVP (M4 gate): option (a), self-reported, always required, always
  explicitly labeled `self_reported` — never silently presented as if
  verified.** Per finding 1, this is the only option guaranteed to produce
  *something* across the realistic corpus population, and per finding 4,
  the existing evidence-position framework already has the vocabulary for
  labeling it honestly rather than needing new report machinery.
- **MVP-adjacent, best-effort, not required: option (b), attempted
  opportunistically.** If IaC/CI config exists and names an explicit
  environment matching the self-reported value, the label upgrades to
  `corroborated`. **If it contradicts the self-reported value, that's a
  stronger and more actionable signal than confirmation would have been** —
  surfaced prominently in S9's report, not just logged, since a user
  claiming "staging" against config that labels the same target
  "production" (or vice versa) is exactly the kind of evidence a
  deployment-safety gate exists to catch.
- **Options (c) and (d) are explicitly future-epic stretch, not M4 scope**,
  per finding 3's real cost asymmetry — cross-repo correlation for (c),
  credential-holding and multi-cloud scope for (d). Worth their own future
  epic (a dedicated IaC-assessment sub-pipeline, as SP9's own question
  anticipated), not folded into E6/E4's M4 timeline.
- **Data model: environment lives on the run manifest, once per run — not
  per-trace or per-verdict.** A single S11 validation run targets one
  environment by construction; splitting this per-trace would model a
  degree of freedom that doesn't exist in how a run actually executes. The
  manifest's `environment` field is a structured object, not a flat string:
  `{claimed, provenance: self_reported|corroborated|contradicted,
  corroboration_source, corroboration_detail}` — so `contradicted` is a
  distinct, first-class state from `self_reported`, not something a report
  author has to infer from free text.

## Consequences

- E6 and E4 are unblocked per the spike table.
- `run_manifest.json` (E1) gains this structured `environment` field —
  a concrete scope addition on top of what E1's description already lists
  (tool version, model roles, config hash, target git SHA, timing).
- S9's existing "evidence position" report section is where this surfaces
  to a human reviewer — no new report structure needed, per finding 4, but
  E4's synthesis skill needs to actually populate it from the run
  manifest's `environment` field once E6 exists to produce one.
- **Honest scope note, not a gap to hide:** finding 1 is drawn from six
  small/demo-shaped repos, which is exactly the population most likely to
  lack IaC entirely — it's real evidence for why (a) has to be the
  floor, but it isn't evidence about how often (b) succeeds against a
  larger, more production-representative corpus. E7's corpus, once it
  includes repos with real deploy config, is where option (b)'s actual
  hit-rate gets measured rather than argued from absence.
