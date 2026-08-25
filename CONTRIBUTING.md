# Contributing

This repository follows the same governance model as the project that inspired it
(Visa Vulnerability Agentic Harness): **open source, closed development**. The code
is Apache-2.0 licensed — you are free to use it, fork it, and build commercial
products on top of it — but **external code contributions are not being accepted at
this stage**. This keeps copyright ownership unified and development velocity high
while the design settles.

What is welcome right now:

- **Issues**: bug reports, design critique, gaps in the pipeline model, spike input
  (reference ROADMAP.md epic/spike IDs `E1`–`E11` / `SP1`–`SP7`).
- **Discussions** of the event model, validation ladder, and skill contracts.
- **Corpus pointers**: suggestions of permissively licensed open-source LLM apps
  suitable as eval fixtures (Epic E7).

If this policy changes, a DCO/CLA process will be introduced first and announced in
CHANGELOG.md.

## Internal working agreements

- Every stage-boundary artifact must have a JSON Schema in `schemas/` before code
  consumes it; breaking changes bump `schema_version`.
- Every LLM-driven behavior lives in a skill (`skills/`), never inline in pipeline
  code; skill changes ship with eval fixtures once the corpus exists.
- Spike outcomes land as decision records in `docs/decisions/` before the dependent
  epic starts.
- Security-relevant changes are reviewed against `docs/security.md` threats T1–T5.
