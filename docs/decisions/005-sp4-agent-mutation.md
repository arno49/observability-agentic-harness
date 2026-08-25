# SP4 — Agentic code mutation: commit discipline, rollback, diff quality

Status: resolved, with an honest tooling-substitution caveat (see Consequences).
Blocks E5. Timebox: 1 wk (used: same-day). Prototype:
[`spikes/sp4-agent-mutation/`](../../spikes/sp4-agent-mutation/).

## Context

E5's S10 applies implementation DTOs to a target repo: one commit per DTO,
`report-only`/`fix` modes, and — per E5's DoD — "a failed DTO application
rolls back cleanly and is recorded, not silently skipped." SP4 needs
evidence, not an assumption, on three things: does per-DTO commit discipline
actually hold when an agent applies it, does rollback-on-failure actually
happen, and how does the result compare to loose/unstructured prompting.

## Approach

Applied four DTOs sequentially against a real repo (`beacon`, reused from
SP1's corpus, cloned fresh — not vendored here) via Claude Code's own
agent/subagent mechanism, each a separate, isolated invocation instructed to
verify-then-commit-or-refuse. Two were valid, straightforward instrumentation
tasks; one deliberately claimed a call site at the wrong line number (tests
pre-edit refusal); one contained a typo in the instruction text itself that
produces code passing `py_compile` while still being broken at runtime
(tests whether verification catches something syntax-checking can't). Then
ran the same conceptual instrumentation task as a loose, unstructured prompt
(no DTO, no explicit scope/verification requirements) against a third file,
for the diff-quality comparison the spike question asks for.

## Findings

1. **Per-DTO commit discipline held cleanly for both valid DTOs.** Each
   produced exactly one file changed, a minimal surgical diff (3–4 lines),
   a passing `py_compile`, and a commit message naming the DTO id. Neither
   touched a file, function, or call site outside what its own DTO named —
   including correctly leaving *other* call sites in the *same* file alone
   when a DTO scoped itself to one specific function
   (`evidence/dto-001-commit.diff`, `dto-002-commit.diff`).
2. **Pre-edit refusal worked exactly as instructed, not just "well
   enough."** `dto-003` claimed a call site 39 lines from where it actually
   exists. The agent found the real location, correctly refused to guess it
   was the intended target, made zero file edits, attempted zero commits,
   and left `git status` clean — a literal, verifiable "recorded failure,
   never a silent skip," matching E5's DoD wording directly
   (`evidence/dto-003-refusal-transcript.md`).
3. **This is a genuinely different failure mode from real rollback, and the
   spike's first three DTOs didn't test the harder one.** Refusing *before*
   ever touching a file isn't "rollback" in the sense E5's DoD actually
   needs — the harder case is catching a mistake *after* an edit has
   already been made, which is what `dto-004` was built to test.
4. **`dto-004` is the more informative result: given only "verify with
   py_compile" as an explicit bar (dto-001/002's instructions), a
   real semantic bug would have passed that bar uncaught** — the DTO's own
   instruction text asked for `model=selfMODEL` (a missing dot, not a
   syntax error, so `py_compile` alone can't catch it; it would raise
   `NameError` at runtime, after the real LLM call had already been made and
   billed). Given *latitude* instead of a fixed checklist ("use your own
   judgment about what verification means here"), the agent went past
   `py_compile` on its own initiative: it cross-referenced the DTO's *own*
   other fields (the `code_shape_precondition` and the sibling `start` emit
   call both correctly said `self.MODEL`), then ran an actual runtime smoke
   test (stubbed imports, instantiated the class, called the instrumented
   method end-to-end) and confirmed the fix worked before committing. It
   corrected the typo rather than applying it literally or refusing outright
   — reasoning that this was an unambiguous, single-plausible-fix, not a
   genuine judgment call (`evidence/dto-004-commit.diff`).
5. **Finding 4 is a real, unresolved policy question, not a closed one.**
   This spike's n=1 result shows the agent *can* distinguish "safe to
   autocorrect" from "genuinely ambiguous, must refuse" in one concrete
   case. It does not show this judgment is reliable in general — a
   differently-shaped typo, or one without three corroborating pieces of
   evidence pointing at the same fix, could go the other way. E5 needs to
   decide, not infer from this spike, whether S10 is ever allowed to
   autocorrect a DTO's own instruction text versus always refusing and
   escalating any detected inconsistency to the human gate (S9) — this
   spike surfaces the question with real evidence attached, it doesn't
   answer it.
6. **Diff-quality comparison: the plain-prompt version was not obviously
   worse at the code itself — the real, measured gap was structural, not
   qualitative.** The unstructured prompt ("add some telemetry logging
   around the LLM call") independently found and correctly instrumented
   *both* real call sites in the target file (matching SP1's own ground
   truth exactly, including the streaming variant), matched the existing
   convention from sibling files without being told to, and proactively
   flagged that two more call sites in a *different* file lacked the same
   treatment — arguably more thorough than either single-scoped DTO.
   **What it did not do:** commit anything. `git status` after the run
   showed an uncommitted, unstaged, untraceable change — no DTO id, no link
   back to a gap-model entry or surface-map point, no declared expected
   events to check in S11, no checkpoint a resumed run could pick up from.
   The measured difference SP4 should actually design against is
   **traceability and resumability, not code cleanliness** — a plain prompt
   can write code that's just as good; it cannot produce a unit E1's
   checkpoint/resume mechanism or S11's event verification can act on.

## Decision

- **Per-DTO commit discipline and pre-edit refusal are validated design
  choices for S10** — both held cleanly across real test cases, not just in
  the easy path.
- **Verification requirements need to be specified as a real bar, not left
  to "run py_compile."** Finding 4 shows a fixed syntax-only check misses
  real bugs; finding 5 shows that giving latitude instead produced a better
  outcome *this time* but isn't provably safe in general. Recommend S8's DTO
  schema gain an explicit `verification_requirements` field beyond
  `expected_emitted_events` (e.g., "run a smoke invocation if the target is
  reachable without external services," not just "compiles") — a concrete,
  falsifiable design gap this spike found, not a vague "be more careful."
- **S10's skill instructions must state an explicit policy on
  DTO-instruction self-correction** — autocorrect-if-unambiguous vs.
  always-refuse-and-escalate-to-S9 — before E5 ships, per finding 5. This
  decision record surfaces the question with concrete evidence; it does not
  resolve it, and E5 shouldn't treat this spike's one clean outcome as
  proof either policy is safe.
- **S8's DTOs should be scoped as this spike's were — one call site (or
  tightly-related group) per DTO** — findings 1 and 6 together show this is
  what makes commits minimal and traceable; a single loose instruction
  covering "the whole file's telemetry" produced good code but a
  worse-shaped unit of work for the pipeline's own bookkeeping.

## Consequences

- E5 is unblocked per the spike table.
- **Tooling substitution, stated plainly:** this used Claude Code's own
  agent/subagent mechanism, not the standalone `claude-agent-sdk` Python
  package named in the spike question. Both are built on the same
  underlying tool-use-loop architecture (read, edit, run commands, decide
  when to stop), so the commit-discipline and verification findings above
  should transfer — but this spike does not test `claude-agent-sdk`'s own
  specific API (session config, permission modes, hook system) at all, and
  E5 should treat the SDK integration itself as unverified, not covered by
  this record.
- **Sample size, same honest caveat as SP1/SP10:** 4 DTOs, 1 repo, 1
  deliberately-broken case, 1 diff-quality comparison. Real evidence, not a
  toy — but not a statistical claim about how often autocorrection judgment
  (finding 5) goes right. E7's eval suite is where that gets tested at
  scale, once E5 exists to generate DTOs for it to run against.
- Evidence (commit diffs, the refusal transcript, the uncommitted
  plain-prompt diff) lives in `spikes/sp4-agent-mutation/evidence/` —
  captured from a scratch clone, not vendored; only the DTOs and this
  repo's own stub files are tracked.
