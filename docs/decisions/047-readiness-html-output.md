# 047 — `oah readiness --html`: HTML rendering as a third first-class output

Status: **landed** (2026-08-30). Part of E4 (Synthesis, S7–S9) — follows
directly from `docs/decisions/038`'s own `--save-intermediates` (the same
"detail already computed, previously discarded" motivation) and the
`039`–`046` investigation chain, whose only way to inspect a real
`readiness_report.json` was reading raw JSON or the two `recommendation`/
`rationale` lines `cmd_readiness` prints to stderr.

## Context

Every `oah` command that produces a JSON artifact supports exactly two
output modes, uniformly: `-o path` writes the file, no flag prints to
stdout. `readiness` additionally prints a two-line human summary
(`recommendation: ...` / `rationale: ...`) to stderr regardless of `-o`,
and optionally writes `--save-intermediates` — the real per-gate,
per-lens detail `readiness_report.json` itself only ever aggregates to a
bare gate name and count (`docs/decisions/038`).

Across `039`–`046`, every real inspection of a `readiness_report.json` —
which gate failed on which point, which lens's fragment produced which
signal, why a self-conflict occurred — was done by hand: reading raw JSON
with `python3 -c "..."`, cross-referencing `--save-intermediates` output,
building one-off HTML by hand outside the framework entirely to make a
finding legible. That last part is the direct prompt for this ADR: an
ad hoc report is disposable and repo-external; a renderer that ships with
`oah` itself is a permanent, reusable capability every future
`oah readiness` run gets for free.

## Decision

New module `oah/design/readiness_html.py`, `render_readiness_html(report,
gate_findings=None, design_fragments=None, panel_verdicts=None) -> str`:

- **Pure presentation over an already-validated artifact.** Its only
  input is `readiness_report.json`'s own validated shape (plus the
  optional `--save-intermediates` detail); its only output is a
  self-contained HTML string nothing downstream reads back. This is not
  a new pipeline stage boundary and carries no schema of its own —
  CLAUDE.md's "every boundary is a schema-validated artifact" rule
  governs artifacts stages pass to each other, not a terminal rendering
  a human reads, the same reasoning that already applies to the
  `recommendation`/`rationale` console lines this flag sits alongside.
- **Pack/target-neutral.** Every section is driven by whichever of
  `readiness_report.schema.json`'s mostly-optional fields the report
  actually has — `deployment_context`, `release_evidence` (+
  `eval_coverage` table), `observability_plan` (+ `health_thresholds`
  table), `failure_response`, the optional `data_and_governance`,
  `known_limitations` — never hardcoded to one pack, lens set, or
  target. An absent optional section renders nothing, not an empty
  header.
- **All free text escaped.** Every field ultimately traces back to a
  model's own prose (`rationale`, `supports_decision`-derived reasons,
  etc.) — `html.escape` on every interpolated value, no exception; a
  report containing `<script>` or any other HTML-shaped text renders as
  inert text, never executes.
- **Optional per-gate/per-persona enrichment.** When `gate_findings`/
  `panel_verdicts` are passed (the same `--save-intermediates` detail,
  already sitting in `cmd_readiness`'s own local variables — no need to
  round-trip through disk), the report gets a per-gate pass/fail rollup
  with real failing-point reasons and a per-persona finding list; without
  them, the report still renders completely from `readiness_report.json`
  alone, just without that layer of detail.

`oah/cli.py`'s `p_readiness` gained `--html PATH`; `cmd_readiness` writes
the render alongside whatever `-o`/`--save-intermediates` already do,
passing its own in-memory `fragments`/`gate_findings`/`panel_verdicts`
straight through — no new I/O, no re-parsing. `getattr(args, "html",
None)` guards it exactly like `--save-intermediates` does, so a
`Namespace` built before this flag existed (every existing test) keeps
working unchanged.

## Verification

`tests/test_readiness_html.py`: renders decision/rationale from a minimal
report, escapes untrusted free text (a literal `<script>` payload proven
inert), omits every optional section when absent, renders each when
present (`known_limitations`, `data_and_governance`, `eval_coverage` and
`health_thresholds` tables), and rolls up mixed pass/fail gate findings
and panel verdicts correctly. `tests/test_cli_readiness.py` gained
`test_html_flag_writes_self_contained_report` (mirrors the existing
`--save-intermediates` test exactly) and
`test_no_html_flag_writes_nothing_extra` (byte-identical default,
matching `--save-intermediates`'s own no-flag test).

Also rendered against the real `readiness_report_sonnet_v5.json` /
`intermediates_sonnet_v5.json` from `docs/decisions/046`'s own real
375/75-point `mf-analyzer-web` run (not shipped in this repo — a private
target, per `CLAUDE.md`) — confirmed the real `remediate_before_release`
verdict, all 88 real gate findings across 6 lenses, and all 3 real S6
panel verdicts (`cost_skeptic`/`security`/`sre`) render correctly from
genuinely messy, full-scale, real-world data, not just the small
hand-built fixtures in the test suite.

771 tests passing (up from 762 at the start of this work).

## Consequences

- `oah readiness` now has three output modes on equal footing: JSON
  (`-o`/stdout), the two-line console summary (unconditional, stderr),
  and HTML (`--html PATH`, optional) — none requires another to be set.
- Every future real `oah readiness` run, on any target/pack, gets a
  legible rendering for free — no more one-off, repo-external HTML for
  the next investigation that needs to show real findings to a human.
- Deliberately did not build a general-purpose report *template* system
  or a second output format (e.g. Markdown) speculatively — one concrete,
  real need (an operator or reviewer wants to read this report without
  parsing JSON) is what's being served; a second format is real, separate
  future evidence to act on if it comes up, not built ahead of it.
