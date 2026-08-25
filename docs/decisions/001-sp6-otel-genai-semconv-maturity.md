# SP6 — OTel GenAI semantic conventions: maturity check

Status: resolved. Blocks E3, E9 (see ROADMAP.md). Timebox: 3 days (used: same-day).

## Context

E3's design gates (S4–S6) and E9's backend-constraint-driven selection both need
to know, concretely, which `gen_ai.*` attributes and metrics are safe to hard-require
in a generated architecture/DTO and which should be treated as likely to churn.
`architecture.md`'s S7 schema-versioning policy (Development/Stable/Deprecated/Removed
stages, dual-emission window on rename, consumers pin to a version) was written from
OTel's general stability-stage discipline, not from a live check of where `gen_ai.*`
itself currently sits. This spike is that check.

Checked 2026-08-25 against `open-telemetry/semantic-conventions-genai` — GenAI
conventions now live in their own repo, split out of the core
`open-telemetry/semantic-conventions` repo. Sources: `README.md`, `docs/gen-ai/gen-ai-spans.md`,
`docs/gen-ai/gen-ai-metrics.md`, `docs/gen-ai/gen-ai-events.md`, `docs/registry/attributes/gen-ai.md`,
`CHANGELOG.md`, cross-referencing `opentelemetry-specification` v1.56.0 and core
`semantic-conventions` v1.44.0 as linked from those docs.

## Findings

1. **Every `gen_ai.*` attribute and metric observed is at Development stability.**
   Checked all attributes on the inference span (`gen_ai.inference.client`, ~40
   attributes) and all 10 currently defined `gen_ai.*` metrics
   (`client.token.usage`, `client.operation.duration`,
   `client.operation.time_to_first_chunk`, `client.operation.time_per_output_chunk`,
   `server.request.duration`, `server.time_per_output_token`,
   `server.time_to_first_token`, `invoke_workflow.duration`, `invoke_agent.duration`,
   `invoke_agent.inference_calls`, `invoke_agent.tool_calls`, `execute_tool.duration`)
   — zero are Stable. The only Stable attributes present on GenAI spans are
   attributes borrowed from core semconv (`error.type`, `server.address`,
   `server.port`), not GenAI-specific ones. The doc-level status line on every
   `gen-ai-*.md` file itself reads `Development`.
2. **`gen_ai.*` still publishes no schema-version marker.** The repo's own
   `README.md` has a literal `## Schema URL` section with a body of `TODO`. This
   confirms, rather than changes, what `architecture.md`'s S7 section already
   anticipated and designed `oah.*`'s own versioning discipline around — the gap
   is real and current, not closed.
3. **Content-capture attributes are `Opt-In` requirement level**, independent of
   the stability axis: `gen_ai.input.messages`, `gen_ai.output.messages`,
   `gen_ai.system_instructions`, `gen_ai.tool.definitions`,
   `gen_ai.prompt.variable` are all Opt-In *and* Development. This matches, not
   conflicts with, OAH's own PII/governance stance in S4 (capture is
   opt-in-and-governed by design already) — no change needed there.
4. **Churn is observed, not hypothetical.** `gen_ai.system` — the attribute OAH's
   earlier drafts referred to informally — no longer exists in the current
   registry; it has been superseded by `gen_ai.provider.name`. (OAH's own tracked
   docs never hard-referenced `gen_ai.system` by name, so no correction was
   needed there — but this is direct evidence the dual-emission-window policy in
   `architecture.md` S7 is load-bearing, not a hedge against a theoretical risk.)
5. **New attributes since OAH's docs were last drafted, relevant to the cost and
   latency lenses (S4):**
   - Per-tier token accounting: `gen_ai.usage.cache_read.input_tokens`,
     `gen_ai.usage.cache_write.input_tokens`, `gen_ai.usage.reasoning.output_tokens`,
     plus per-modality (`audio.*`, `image.*`, `text.*`) input/output token splits.
   - TTFT is a matched client/server pair, not one attribute: span attribute +
     client histogram (`gen_ai.response.time_to_first_chunk`,
     `gen_ai.client.operation.time_to_first_chunk`) versus a server-observed
     histogram (`gen_ai.server.time_to_first_token`, populated only when the
     provider surfaces it) — with a matching per-chunk/per-token pair for
     steady-state decode rate after the first token.
   - Conversation/session continuity: `gen_ai.conversation.id`,
     `gen_ai.conversation.compacted`, `gen_ai.request.previous_response.id`.
   - `gen_ai.request.reasoning.level` (extended-thinking effort setting) and
     `gen_ai.prompt.name`/`gen_ai.prompt.version` for prompt-template tracking.

## Options considered

- **A — treat `gen_ai.*` as if stable**, assume names/shapes hold for a project's
  lifetime once designed. Rejected: contradicted directly by finding 4
  (`gen_ai.system` → `gen_ai.provider.name` already happened).
- **B — pin every pipeline run to a specific semconv reference** (repo commit or
  future tag) and treat the *entire* `gen_ai.*` namespace as Development-stage for
  OAH's own versioning-policy purposes — not a hedge for a few edge-case fields,
  since the live check found no Stable fields at all — until upstream ships a
  first tagged release or its first Stable attribute, whichever comes first.
- **C — wait for `gen_ai.*` to reach Stable** before designing S4–S6 or E9 around
  it. Rejected: no announced timeline exists upstream; blocks OAH indefinitely
  against a moving target it doesn't control, defeating the point of being
  useful pre-M4 rather than after upstream stabilizes.

## Decision

Option B.

- **E1 scope note:** `run_manifest.json` (already tracking tool version, model
  roles, config hash, target git SHA, timing per E1's description) gains a field
  recording the pinned `open-telemetry/semantic-conventions-genai` reference
  (commit SHA, or tag once one exists) a run was designed/validated against —
  the same idea as pinning any other unstable dependency, applied consistently.
- **S7's schema-versioning policy is confirmed correct as designed** — no
  rewrite needed — but its practical scope changes from "some `oah.*` extension
  attributes may need this" to "the entire `gen_ai.*` transport-floor namespace
  is Development-stage right now, full stop." Dual-emission-window guidance
  applies to any DTO-generated code that names a `gen_ai.*` attribute directly.
- **Fold the concretely observed attributes into the design lenses** where they
  sharpen an existing generic mention rather than adding new scope: cost
  accounting in S4's generation-capture lens now names cache/reasoning token
  line items explicitly (`architecture.md`); the TTFT discussion in
  `event-model.md` now names the actual client/server attribute and metric
  pair instead of referring to "a TTFT attribute" generically.
- **No change to OAH's PII/opt-in stance** — finding 3 confirms alignment, not a
  gap.

## Consequences

- E3 and E9 are unblocked per the spikes table.
- Small, real cost added to E1's scope: recording a pinned semconv reference per
  run. Not a new epic; folded into `run_manifest.json`'s existing field set.
- Risk is contained, not eliminated: Development-stage attributes can still be
  renamed or removed between two OAH releases designed months apart. The
  dual-emission window is the mitigation; it was already designed, this spike
  just confirmed it's necessary rather than precautionary.
- **Revisit trigger** (not a recurring spike): re-check this record when
  `open-telemetry/semantic-conventions-genai` ships its first tagged release, or
  when any `gen_ai.*` attribute first reaches Stable — whichever happens first.
  Note this is **not** part of the M0 gate criterion (`ROADMAP.md` gates M0 on
  decision records for SP1–SP4 and SP10 specifically); this record satisfies
  SP6's own listed blockers (E3, E9) and the sequencing sketch's `M0: SP1 SP5
  SP6 SP10` ordering, but doesn't by itself close the M0 milestone.
