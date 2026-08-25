# SP8 — LiteLLM model abstraction, light-tier vs. frontier quality

Status: resolved, with an explicit scope gap (S2 untested — see Consequences).
Blocks E1, E2. Timebox: 1 wk (used: same-day). Output:
[`spikes/sp8-model-tiers/`](../../spikes/sp8-model-tiers/) (test batch + raw outputs).

## Context

E1/E2 need per-role model configuration (any provider, including local
Ollama/vLLM) and cost-tracking hooks feeding `estimate` (SP5). SP8 asks two
separable things: is LiteLLM the right abstraction library, and — the part
that actually needs evidence, not a library choice — where does a light
tier (Haiku-class) hold up against frontier for S1-disambiguation quality
specifically, since that determines real cost savings SP5's formula could
exploit.

## Approach

Verified LiteLLM's current real capabilities from its own repo rather than
its README's marketing framing (a lesson carried over from SP6's live
semconv check — read the source, not the pitch). Then ran a real, controlled
comparison: the exact same 4 disambiguation candidates, following S1's
actual `SKILL.md` instructions verbatim, through both a Haiku-tier and a
Sonnet-tier agent — one real hard case (the `ollama-eng.py` receiver-type
trap from SP1's corpus) and three synthetic hard cases already built for
SP1 (`synthetic_hard_cases.py`'s subscript, getattr-dynamic, and
branch-assigns-two-SDKs candidates), scored against known ground truth.

## Findings

1. **LiteLLM verified, not assumed:** core SDK is MIT-licensed (only an
   `enterprise/` subdirectory carries a different license, irrelevant to
   OAH's use); confirmed multi-provider support including self-hosted
   Ollama/vLLM; a real `completion_cost()` function exists in
   `litellm/cost_calculator.py`, directly usable as the calibration hook
   SP5's decision record already specified `estimate` needs. **One thing
   worth naming, not assuming away:** the project now describes itself as
   "Rust core with Python SDK" — an AI Gateway, not a thin Python wrapper —
   and offers two integration depths: an in-process Python SDK call
   (`litellm.completion(...)`) versus running the full self-hosted Proxy
   Server as a separate gateway process. E1 needs to pick one, not assume
   the lighter-weight option by default.
2. **On straightforward candidates, light and frontier tiers performed
   equivalently.** The subscript-indirection case (clear
   `anthropic.Anthropic()` construction, minor syntactic indirection) and
   the core SDK-identity question in the getattr-dynamic-dispatch case: both
   tiers correctly identified `anthropic-sdk` and appropriately flagged the
   residual uncertainty.
3. **On the two candidates requiring cross-referencing knowledge beyond the
   immediate excerpt, frontier caught real issues light tier missed or got
   wrong — not just "less confident," actually incorrect:**
   - The `ollama-eng.py` trap: Sonnet additionally noticed `anthropic` never
     appears in the file's import list at all, and that the client was
     constructed as `AsyncClient` yet the call site has no `await` — two
     concrete inconsistencies neither of which Haiku's answer surfaced.
     Haiku's `framework` field named `"ollama"` outright despite its own
     `notes` flagging the header mismatch — an internally inconsistent
     answer, not just a lower-confidence one.
   - The branch-assigns-two-SDKs case: **Sonnet correctly identified that
     OpenAI's Python SDK has no `.messages.create` method at all** — its
     real chat endpoint is `client.chat.completions.create` — meaning the
     untaken `else` branch would raise `AttributeError` if ever executed, a
     real latent bug in the fixture, not a benign dual-provider
     abstraction. **Haiku's answer confidently stated the opposite**: that
     both branches have "compatible `.messages.create()` APIs" — a
     factually wrong claim about a real, well-known SDK's actual method
     names, not a hedge that turned out imprecise.
4. **The failure mode in finding 3 is the one that matters most for exactly
   this role.** S1's disambiguation skill exists specifically to resolve
   cases the deterministic scanner couldn't — by construction, every
   candidate it sees needs the kind of judgment finding 3 shows light tier
   getting wrong. A tier that performs fine on the easy half of a
   disambiguation batch isn't good evidence for the role, because the easy
   half is exactly what the deterministic scanner would have resolved
   without needing disambiguation at all.

## Decision

- **Adopt LiteLLM as OAH's model-abstraction layer** for every role except
  S10/S11 (which stay Anthropic-pinned to the Claude Agent SDK, per SP8's
  own stated scope, not re-litigated here) — its verified capabilities
  (finding 1) match what E1/E2 need, and the MIT core license clears it for
  a hard dependency.
- **S1's disambiguation role stays on frontier tier by default, not light
  tier** — this reverses what would otherwise be the obvious cost-saving
  assumption (Haiku-class for a "simple classification" task), and the
  reversal is the actual finding this spike exists to produce. Finding 3's
  failure mode — confidently wrong about external SDK API shape, not just
  underconfident — is disqualifying for a role whose whole job is resolving
  genuine ambiguity.
- **A per-candidate light/frontier routing decision is plausible in
  principle** (per finding 2's easy-candidate parity) but is explicitly
  **not designed by this spike** — it would need its own selection signal
  (what makes a candidate "easy enough" for light tier, decided *before*
  running it, not after seeing which tier got it right) that doesn't exist
  yet. Default the whole role to frontier until that signal is designed and
  evaluated on its own, rather than defaulting to light tier on an
  unevaluated hope.
- **Finding 3's specific catch (`OpenAI` has no `.messages.create`) is
  itself worth encoding as a static registry fact for E2/E11**, not just
  something to hope a frontier model recalls correctly every time — a
  cross-provider method-name incompatibility table is cheap to build once
  and removes the need to re-derive this exact fact per disambiguation call.

## Consequences

- E1 and E2 are unblocked per the spike table.
- **Explicit scope gap, not silently carried forward:** this spike tested
  S1-disambiguation only. SP8's own question also named S2-inventory recall
  light-vs-frontier — untested here, because S2 has no skill draft or `io/`
  schema yet (only S1 does, per the skills-bundle work). A follow-up pass is
  needed once S2 exists; this record's frontier-default recommendation
  should not be assumed to transfer to S2 without its own check.
- **Sample size, same caveat shape as every other spike this session:** n=4
  candidates, one model pairing (Haiku vs. Sonnet), one skill. Real,
  concrete, decision-grounding evidence — not a statistical claim about
  Haiku's disambiguation accuracy in general. E7's eval suite is where a
  larger-scale version of this exact comparison belongs once real skills
  and corpus runs exist to generate a bigger sample from.
- E1's scope gains a concrete decision point (finding 1's last sentence):
  in-process LiteLLM SDK calls versus a self-hosted Proxy Server, which
  wasn't a choice this spike was asked to make and shouldn't be assumed
  either way when E1 design starts.
