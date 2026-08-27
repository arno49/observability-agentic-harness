# 035 — `oah estimate` gains `--language`/`--pack`

Status: landed. Closes a gap found while assessing E12/S2/`workflow_hint`
(`docs/decisions/032`/`033`/`034`'s own retrospective).

## Context

Before this phase, `oah/estimate.py`'s `estimate()` unconditionally
imported and called `oah.discovery.python_adapter.detect_repo` — no
`--language` flag existed on `oah estimate` at all, unlike `map`/`gaps`/
`inventory`/`dtos`/`readiness`, which all gained one over `docs/decisions/
014`/`018`/`029`/`033`. Running `oah estimate` against a real TypeScript
target repo (the same `mf-analyzer-web` pilot the three preceding decision
records used) reported `candidate_call_sites: 0` — not an error, a
confident-looking zero, because `detect_repo`'s own `rglob("*.py")` simply
found no Python files. Every downstream per-stage dollar figure (S4
through S11) was therefore silently wrong by construction, not honestly
absent — the same shape of bug `docs/decisions/033`/`034` already found
and fixed in S2 and S3's `workflow_hint`, this time in the cost model.

## What was built

`oah/estimate.py`: `estimate(repo_path, workflows=None, constants=None,
language="python", pack=None)` gained the two new parameters (defaults
byte-identical to every pre-existing caller). A new `_detect_counts`
dispatches phase 1's free pre-scan by language, mirroring `oah/cli.py`'s
own `_build_surface_map`: `typescript`/`java` call their own adapter's
`detect_repo(repo_path, pack=pack)`, wrapped as `(resolved, [])` — neither
adapter has an LLM-disambiguation counterpart (E11-TS/E11-Java's own
stated scope boundary), so `ambiguous_candidates` is always `0` for
either, same honest shape `map`'s own CLI help already states. Python's
own `detect_repo(repo_path)` (no `pack` param — no Python service-domain
registries exist yet) is called exactly as before. `oah/cli.py`'s
`cmd_estimate` and `p_estimate`'s argparse definition gained `--language`/
`--pack`, reusing the existing `_LANGUAGE_HELP`/`_PACK_HELP`/
`_load_pack_for_args` machinery every sibling command already has.

## Verified end to end

On the motivating repo (449 TS files, 375 real S1 points per
`docs/decisions/032`): before this phase, `oah estimate --workflows 7`
reported 0 candidate call sites and a cost breakdown reflecting only
fixed per-run overhead (S4/S6/S7/S11, ~$0.67 total — S3/S8/S10 all
$0 since they scale with the point count that was wrongly 0). After,
`--language typescript --pack service` reports the real 375 points, 525
estimated DTOs, and a materially different total (~$16.40, driven mostly
by S10's per-DTO agentic-session cost) — the number a real go/no-go
decision about running the LLM stages against this repo should actually
be based on.

## Decision

**Same normalize-then-dispatch shape as every prior language-dispatch
fix, not a special case.** `_detect_counts`'s tuple-normalization (wrapping
a plain list as `(resolved, [])`) is the only genuinely new code; every
other stage of `estimate()`'s formula was already generic over `C`/`A`/`P`
and needed no change.

## Consequences

- `oah estimate` now gives an honest, language-aware cost figure for all
  three S1-supported languages — the same "silently confident zero" class
  of bug named and fixed for S2 (`docs/decisions/033`) and S3's
  `workflow_hint` (`docs/decisions/034`) is now closed for the cost model
  too.
- `oah estimate`'s own driver-count formula (`D = P * dtos_per_surface_point`,
  etc.) is unchanged and still uncalibrated against real token usage — see
  `docs/decisions/002`'s own recalibration protocol; this phase only fixed
  which repo's source the formula's inputs come from, not the formula
  itself.
