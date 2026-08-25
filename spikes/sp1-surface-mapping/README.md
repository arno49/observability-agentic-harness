# SP1 prototype — AST + signature registry for raw Anthropic SDK call sites

Spike prototype, not E2's production S1 implementation. Produced to answer
SP1 (`ROADMAP.md`): *can AST + signature registry reach ≥90% recall on
Python LLM call-site detection, including the hard cases (dynamic dispatch,
wrapper functions), and where exactly does the LLM disambiguation pass
become necessary?* See [`../../docs/decisions/003-sp1-ast-recall.md`](../../docs/decisions/003-sp1-ast-recall.md)
for the answer and its evidence.

This is real, working code — not a mockup — but it is deliberately scoped to
one signature family (raw `anthropic` Python SDK, `messages.create`/`.stream`,
sync + async + beta-namespace variants) on three small real repos. E2's actual
registry, once built against SP10's per-language adapter interface, will
supersede this; nothing here is meant to be imported by the real pipeline.

## Layout

- `registry.py` — the signature definitions this prototype matches against.
- `detect.py` — the AST walker: `python3 detect.py <path-to-repo>` prints one
  JSON object per detected candidate (file, line, confidence, resolution
  reasoning) to stdout.
- `ground_truth/corpus_manifest.json` — the three real repos this was tested
  against, pinned by commit SHA, with license. **Source is not vendored into
  this repo** (see the decision record's Decision section for why) — clone
  the pinned SHA yourself to reproduce:
  ```
  git clone <repo_url> && git -C <dir> checkout <commit>
  ```
- `ground_truth/*.json` — hand-labeled ground truth per repo: every real
  Anthropic inference call site (file, line, confidence category, why),
  written by reading the actual code, not generated.
- `eval.py` — runs `detect.py` against a cloned corpus repo and scores it
  against the matching `ground_truth/*.json`, printing recall/precision.
- `synthetic_hard_cases.py` — hand-authored fixture exercising the dynamic
  -dispatch/multi-hop-wrapper cases that did not occur naturally in any of
  the three real repos (see decision record) — kept separate from the real-repo
  numbers, never blended into the headline recall figure.

## Running it

```
python3 eval.py --corpus-dir /path/to/cloned/corpus
python3 detect.py synthetic_hard_cases.py   # hard-case fixture, standalone
```
