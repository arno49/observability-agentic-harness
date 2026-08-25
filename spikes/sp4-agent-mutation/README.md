# SP4 prototype — agentic DTO application, per-commit discipline, and rollback

Spike prototype, not E5's production S10 implementation. Produced to answer
SP4 (`ROADMAP.md`): *Claude Agent SDK for code mutation: per-DTO commit
discipline, rollback on failure, diff quality vs. plain prompting.* See
[`../../docs/decisions/005-sp4-agent-mutation.md`](../../docs/decisions/005-sp4-agent-mutation.md)
for the answer and its evidence.

**Honest substitution, stated up front:** this used Claude Code's own
agent/subagent mechanism, not the standalone `claude-agent-sdk` package —
the two share the same underlying tool-use-loop architecture, but this
wasn't literally the package named in the spike question. See the decision
record's Consequences for why that substitution is reasonable and what it
doesn't establish.

## What was run

Four DTOs applied sequentially against a real repo (`beacon`, from SP1's
corpus — cloned fresh into a scratch working copy, not vendored here; only
the DTOs, the evidence, and this repo's own `oah_telemetry.py` stub are
tracked):

- `dtos/dto-001.json`, `dto-002.json` — valid, applied cleanly, one commit
  each. Evidence: `evidence/dto-001-commit.diff`, `dto-002-commit.diff`.
- `dtos/dto-003-deliberately-invalid.json` — claims a call site at a line
  number that doesn't match reality. Evidence:
  `evidence/dto-003-refusal-transcript.md`.
- `dtos/dto-004-semantically-broken.json` — valid call site, but the
  instruction text itself contains a typo that produces code passing
  `py_compile` while still being broken at runtime. Evidence:
  `evidence/dto-004-commit.diff`.
- `evidence/plain-prompt-uncommitted.diff` — the same conceptual task
  (instrument a third file, `agents/research.py`) given as a loose,
  unstructured prompt instead of a DTO, for the diff-quality comparison.

`oah_telemetry.py` is a stub telemetry helper (not real OTel wiring — OAH's
event schema doesn't exist yet, pre-M0) that makes the inserted instrumentation
code syntactically real and checkable rather than prose describing an edit.
