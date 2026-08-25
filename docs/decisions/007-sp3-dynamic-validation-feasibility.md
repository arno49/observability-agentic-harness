# SP3 — Feasibility of the dynamic validation harness

Status: resolved, with an honest sample-size caveat. Blocks E6. Timebox: 2 wk
(used: same-day). Output: [`docs/runnability-matrix.md`](../runnability-matrix.md).

## Context

E6's S11 needs to reliably run an unfamiliar product, intercept OTLP
locally, and diff against schema — but "reliably run an unfamiliar product"
is exactly the part that's unverified pre-M0. SP3 asks what fraction of real
repos are actually runnable at each `validation.md` ladder rung, and — more
usefully than a percentage alone — what specifically breaks when you try.

## Approach

Attempted, not assumed: ran real install-and-test cycles against all six
repos already in hand from SP1 and SP10 (three Python, three TypeScript;
cloned fresh, not vendored — same policy as those spikes). No repo in this
sample was chosen for SP3 specifically; reusing SP1/SP10's corpus is
deliberate — it tests runnability against the same repos already used to
validate detection, rather than a hand-picked "easy" sample.

## Findings

1. **1/6 repos (`beacon`) confirmed at R2 — live, not inferred: 180/180
   tests pass.** 0/6 reach R1 (none have a compose file or an obviously
   automatable e2e/dev-server path already built — `llm-document-ocr`'s
   Dockerfile is a build environment for native `canvas` dependencies, not
   a runnable service). 5/6 are R4 baseline today.
2. **Getting `beacon` to R2 required working around two real obstacles,
   neither of which was visible from reading `pyproject.toml` and neither
   of which was actually a defect in the target repo:** its own
   `.python-version` file pointed the harness's toolchain selection at a
   locally broken Python 3.11.3 build (missing an SSL library dependency
   this specific machine no longer has); and `pip install -e .` failed on
   setuptools' automatic package-discovery refusing to guess among several
   ambiguous top-level directories. Both were real install-attempt findings,
   not predictable from static inspection, and both had a working fallback
   (a different 3.11+ interpreter; skip the editable install, install
   `requirements.txt` directly and run pytest from the repo root instead).
3. **"A test file exists" is not evidence of coverage — confirmed as a real
   failure mode, not a hypothetical one.** `claude-engineer` has a
   `test.py`; its contents are an unrelated generic example
   (`calculate_sum`), zero real assertions about the actual application. A
   presence check alone would have misclassified this repo as R2-eligible.
4. **R3 (generated smoke) achievability tracks the product's own interface
   shape, not language or repo size.** `naive-memory` (1 file, Python) and
   `llm-document-ocr` (a function-shaped library entry point, TypeScript)
   both look genuinely synthesizable — small, few external dependencies
   beyond the LLM call itself. `wechatbot`'s real interface is a live
   WeChat session; `transcribee` needs real YouTube+ElevenLabs+Anthropic
   inputs. Smoke-generation difficulty is a property of what the product
   *does*, and needs to be assessed per-repo by S1/S3, not assumed uniform
   across "no tests exist" cases.
5. **Two categories of runnability failure need to be tracked separately in
   S11's actual implementation, per finding 2 vs. 3:** harness-environment
   brittleness (toolchain/dependency resolution failing for reasons outside
   the target repo's control) versus target-repo reality (no real tests,
   despite appearances). Conflating them into one "not runnable" verdict
   would hide that the first category has retriable fallbacks and the
   second doesn't.

## Decision

- **S11's dependency-install step needs a fallback ladder, not one install
  strategy:** attempt the repo's own declared install method first (e.g.
  `pip install -e .`), but on failure, fall back to installing declared
  dependencies directly (`requirements.txt` / `pyproject.toml`'s dependency
  list) without an editable package install, and re-attempt test discovery
  from the repo root. Finding 2's beacon result is real evidence this
  recovers a genuine R2 case a single-strategy installer would have missed
  entirely.
- **Runtime-version pinning files (`.python-version`, `.nvmrc`, engines
  fields) should be read and preferred, but never allowed to hard-fail the
  attempt** if the harness's own environment can't satisfy them exactly —
  fall back to the nearest compatible available runtime rather than
  reporting the repo as unrunnable over an environment gap that has nothing
  to do with the target product.
- **"Tests exist" (S1/S2 presence detection) and "tests actually cover the
  application" (an R2 verdict) must be distinct signals**, not one
  presence-implies-coverage assumption — per finding 3, a repo can carry a
  decoy test file that would pass a naive check.
- **R3 smoke-generation effort should be estimated per-repo from the
  product's interface shape** (callable function vs. long-running
  session/bot vs. requires multiple real external services), not treated as
  a uniform fallback whenever R1/R2 aren't available — per finding 4, some
  R4-today repos are a short step from R3 and others are a much longer one.

## Consequences

- E6 is unblocked per the spike table.
- **Honest sample-size caveat, same shape as every other spike this
  session:** 6 repos, 1 confirmed R2, 0 confirmed R1 or R3 (R3 is assessed
  as plausible per-repo, not built and verified the way beacon's R2 result
  is) — real, but thin, and skewed toward small hobby/demo projects rather
  than the kind of production system E7's corpus should eventually include.
  Zero R1 evidence in particular is a real gap: no repo in this sample ships
  a compose file or e2e harness, so SP3's R1 feasibility claim rests on
  nothing yet — E7's corpus needs at least one repo with a working
  docker-compose or equivalent before R1 feasibility can be claimed with
  the same confidence as R2's.
- The fallback-ladder install strategy (Decision, point 1) is a concrete
  scope addition to E6/S11 beyond what `architecture.md` already describes
  — worth folding into that document once E6 design starts.
