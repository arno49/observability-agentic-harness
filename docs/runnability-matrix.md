# Dynamic validation runnability matrix

SP3's output (`ROADMAP.md`) — what fraction of real corpus repos are
actually runnable at each rung of the validation ladder
([`validation.md`](validation.md)). Every verdict below is from an actual
attempt against the six real repos already in hand from SP1/SP10 (cloned
fresh, not vendored — see those spikes' `corpus_manifest.json` files for
commit SHAs), not inferred from what a `package.json`/`pyproject.toml` file
merely claims.

## The matrix

| Repo | R1 (full dynamic) | R2 (unit-level) | R3 (generated smoke) | R4 (static only) |
|---|---|---|---|---|
| `naive-memory` (Python) | No compose/e2e | No tests exist | **Plausible, not built** — single call site, deterministic CLI loop | Baseline |
| `beacon` (Python) | No compose/e2e | **Confirmed live: 180/180 tests pass** | — (R2 achieved) | — |
| `claude-engineer` (Python) | No compose/e2e | **`test.py` is a decoy** (generic `calculate_sum` example, zero real coverage) | Plausible in principle, harder — 21 files, heavy external tool integrations | Baseline |
| `transcribee` (TypeScript) | No compose/e2e | `"test": "echo ... exit 1"` — npm's default placeholder, zero real tests | Harder — needs real YouTube+ElevenLabs+Anthropic inputs, not just an LLM mock | Baseline |
| `llm-document-ocr` (TypeScript) | Dockerfile exists but is build-only (native `canvas` deps), not a runnable service | Same npm placeholder, zero real tests | Plausible — function-shaped entry point, image input can be synthesized | Baseline |
| `wechatbot` (TypeScript) | No compose/e2e | No test script at all | Harder — the product's real interface is a WeChat session, not a callable function | Baseline |

**1/6 (17%) confirmed at R2. 0/6 at R1. 5/6 (83%) are R4 baseline today**,
with R3 achievability varying by how simple the product's *own* interface
is to synthesize input for — not by language or repo size.

## What "confirmed" required, beyond "tests exist" (the beacon case)

`beacon` has a real `pytest` suite (`testpaths = ["tests"]`,
`pytest-mock`/`pytest-httpx`/`freezegun` as dev dependencies) — but
`pip install -e ".[dev]"`, the obvious first thing to try, **failed twice**,
for two different reasons neither of which was actually about the target
repo being broken:

1. **The repo's own `.python-version` file (`3.11`) pointed at a local
   Python 3.11.3 install with a broken SSL linkage** (missing
   `openssl@1.1`, a homebrew formula since replaced by `openssl@3` on this
   machine) — a harness-environment problem, not a repo problem. Retrying
   with a different available 3.11+ interpreter fixed it.
2. **`pip install -e .` failed independently** with `Multiple top-level
   packages discovered in a flat-layout: ['data', 'design', 'agents']` —
   setuptools' automatic package discovery refusing to guess among several
   top-level directories that look like packages, because `pyproject.toml`
   never declared an explicit `packages`/`find` config (beacon's own dev
   workflow presumably uses `uv sync`, which doesn't hit this path the same
   way). Skipping the editable install entirely — `pip install -r
   requirements.txt` plus the dev-test dependencies, then running `pytest`
   from the repo root — worked cleanly and is what actually produced the
   180-passing result.

**Neither obstacle would have been visible from reading `pyproject.toml`
alone.** Both needed a real install attempt to surface.

## What "decoy" required catching (the claude-engineer case)

`claude-engineer` has a file literally named `test.py`. Reading it revealed
a generic, unrelated `calculate_sum` example with no connection to the
actual application — a file that would pass a naive "does a file named
`test*.py` exist" presence check while providing zero real coverage. This
is a distinct failure mode from "no tests at all": the repo *looks* R2-ready
from directory listing alone and isn't.
