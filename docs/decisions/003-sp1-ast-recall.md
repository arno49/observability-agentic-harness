# SP1 — AST + signature registry recall on Python LLM call-site detection

Status: resolved, with a documented sample-size caveat (see Consequences). Blocks E2.
Timebox: 1 wk (used: same-day). Prototype: [`spikes/sp1-surface-mapping/`](../../spikes/sp1-surface-mapping/).

## Context

E2's S1 needs to know whether AST + signature registry alone can reach ≥90%
recall on Python LLM call-site detection (raw Anthropic SDK, E2's first
target), including the hard cases named in ROADMAP.md — dynamic dispatch and
wrapper functions — and exactly where the LLM disambiguation pass becomes
necessary rather than optional.

## Approach

Built a real, working prototype (not a mockup): `registry.py` (signature
definitions) + `detect.py` (an AST walker doing import-alias resolution,
lightweight same-file assignment/annotation tracking, and suffix-match method
registration — full design rationale is in the module docstrings, not
repeated here) — then tested it against **three small real open-source repos**
using the raw Anthropic SDK, picked to span different architectures:

| Repo | Files | Category |
|---|---|---|
| `naive-memory` | 1 | simple sync chat loop |
| `beacon` | 25 | multi-agent conversational assistant, multi-provider (Anthropic+OpenAI) abstraction |
| `claude-engineer` | 21 | agentic CLI/dev-tool, self-extending tools, several near-duplicate implementations in one repo |

Pinned by commit SHA in `ground_truth/corpus_manifest.json`. **Source is not
vendored into this repo** — `claude-engineer` has no LICENSE file at the
pinned commit, so its code is analyzed read-only here (recall scoring, never
distributed) rather than copied in; the other two are MIT but treated the
same way for one consistent policy. Ground truth was hand-labeled by reading
every real (non-test) `anthropic.*` reference in all 47 files, then
cross-checked against the detector's own output — which caught one real site
I'd missed by hand (`beacon/agents/intake.py:133`, a second call site in a
function I'd only partially read). Worth noting plainly: manual
ground-truthing isn't perfectly reliable either.

## Findings

1. **100% recall at high confidence on this corpus: 17/17 real call sites
   found, 0 false positives at high confidence.** Reproducible via
   `python3 eval.py --corpus-dir <dir-with-the-3-cloned-repos>` — the numbers
   in this record are the tool's actual output, not hand counts. Comfortably
   clears the ≥90% target on this sample (see Consequences for the honest
   caveat on sample size).
2. **The indirection patterns that actually occur in real code — all
   resolved correctly, no LLM pass needed:** a client stored as `self._client`
   and read in a different method of the same class; a function parameter
   annotated `client: anthropic.Anthropic`; a module-level client constructed
   via `import anthropic` or via `from anthropic import Anthropic` (both
   import forms). None of these needed anything beyond a same-file,
   single-pass assignment/annotation tracker — no real type inference, no
   cross-file resolution.
3. **The beta-namespace variant** (`client.beta.prompt_caching.messages.create`,
   3 real occurrences in `claude-engineer`) was resolved correctly *because*
   the registry matches on the **last two path segments**
   (`("messages", "create")`), not the full dotted path — a specific,
   deliberate registry design choice (see `registry.py`'s comment) that
   E2's real registry should carry forward: enumerating every current and
   future beta-namespace prefix by hand would be a maintenance trap.
4. **A real false-positive trap, found in the wild, not constructed:**
   `claude-engineer/Claude-Eng-v2/ollama-eng.py:322` calls
   `client.messages.create(..., extra_headers={"anthropic-beta": ...})` —
   syntactically almost indistinguishable from a real Anthropic call, right
   down to the header name — but `client` is provably `ollama.AsyncClient()`
   (constructed at line 33 of the same file), not an Anthropic client. Reads
   like dead code left over from a prior Anthropic-only version of this
   file. The detector correctly does **not** report this at high confidence
   (a narrow, single-provider registry has no positive evidence it's
   Anthropic) and correctly does **not** silently drop it either — it's
   flagged low-confidence, routed to the LLM pass. This is exactly the
   disambiguation task the LLM pass earns its keep on: not "what is this
   call," but "this looks right and still might not be — check the actual
   receiver."
5. **True dynamic dispatch (`getattr(client.messages, method_name)` where
   `method_name` is a runtime string) occurred zero times across all 47 real
   files in the corpus.** Constructed by hand as a synthetic fixture (see
   `synthetic_hard_cases.py`) specifically because the real corpus never
   exercised it — and confirmed as a **complete, unrecoverable miss** for
   AST-only detection: no `.create`/`.stream` token exists anywhere in the
   source for a suffix match to find. This is the genuine hard boundary the
   spike question asked about, and it's real, but empirically rare in
   practice (0/47 real files) — not the common case the recall number needs
   to defend against.
6. **A related, more common indirection pattern — subscript-indexed
   receivers** (`clients["primary"].messages.create(...)`) — was found to be
   **silently dropped** by the first version of the detector (root resolves
   to `None` for a `Subscript` node, and the original suffix-match check
   required a resolvable root). Fixed during this spike, not just noted: the
   suffix-match check now fires regardless of whether the root resolves,
   reporting low-confidence instead of nothing. Verified against the
   synthetic fixture post-fix.
7. **A documented, un-fixed limitation:** the registry is single-provider.
   When one variable name is conditionally assigned from two *different*
   registered SDK constructors across branches (`if use_anthropic: api_client
   = anthropic.Anthropic() else: api_client = openai.OpenAI()`), today's
   Anthropic-only registry simply never sees the `openai.OpenAI()` branch at
   all (it isn't a registered constructor), so the Anthropic assignment wins
   unconditionally and the call site reports high confidence regardless of
   which branch runs at runtime — a real over-confidence risk once E2 adds
   more provider signatures. Not observed in the real corpus: real
   multi-provider code here (`beacon`'s own `AnthropicProvider`/
   `OpenAIProvider` split) uses one method per provider rather than
   conditionally reassigning one name, which is presumably *why* it isn't
   the common pattern — but it's a known gap for E2 to close, not silently
   carried forward. See Decision.

## Decision

- **AST + signature registry is sufficient for the large majority of real
  Python raw-Anthropic-SDK call sites** — 100% on this sample — using three
  concrete techniques, all worth carrying into E2's real registry: (a) resolve
  both `import X` and `from X import Y [as Z]` alias forms, (b) track
  same-file assignments/self-attrs/annotations in one lightweight pass (not
  full type inference — a lightweight scope model was enough), (c) match
  method registrations on path *suffix*, not full dotted path.
- **The LLM disambiguation pass is required for exactly two situations**,
  which are different tasks and should probably get different prompt framing
  in S1's disambiguation skill rather than one generic "resolve this" prompt:
  (a) **genuinely unresolvable receivers** (subscript/container indirection,
  cross-file receivers a per-file scan can't trace, or a name whose type this
  prototype's tracker never observed) — "what does the target product call
  this?"; (b) **suspicious-looking calls that resolve to nothing yet still
  carry provider-specific markers** (the ollama trap's `anthropic-beta`
  header) — "this looks like it should be Anthropic but the receiver says
  otherwise; which one is real?" Both route to the same low-confidence
  bucket today; E2 should keep them distinguishable in the disambiguation
  batch sent to the LLM, since they need opposite defaults (case (a) defaults
  toward "probably relevant, confirm"; case (b) defaults toward "probably a
  false lead, confirm before including").
- **True dynamic dispatch is out of scope for S1's AST pass entirely, by
  design, not as an acknowledged gap** — no static tool resolves a genuinely
  runtime-only method-name string, LLM-read or not, without executing the
  code. Recommend S2/S3 (not S1) treat any `getattr(<already-known-client>,
  <non-literal-argument>)` pattern as an automatic dark/unknown-surface flag
  routed to the owner interview, rather than something S1 is expected to
  resolve.
- **E2 scope item, closing finding 7:** when a name is assigned from more
  than one *registered* SDK constructor anywhere in the same scope, downgrade
  every call site through that name to low-confidence rather than trusting
  the last-seen assignment. Cheap or free relative to real flow-sensitive
  analysis, and directly closes the over-confidence gap the synthetic case
  demonstrated.

## Consequences

- E2 is unblocked per the spike table.
- **Honest sample-size caveat:** 3 repos, 47 Python files, 17 ground-truth
  positive sites is a real, reproducible, code-grounded result — not a toy —
  but it is not yet E7's real corpus. E7 explicitly wants architectural
  diversity (simple RAG chat / multi-agent / queue-based); this SP1 sample
  covers the first two but has **no queue-based/async-heavy target**, which
  matters more for SP2 (trace-ID propagation through async/queue boundaries)
  than for SP1 directly, but is worth flagging for E7's corpus-selection
  criteria rather than treating this 17-site sample as the final word on
  recall at real E7 scale.
- Prototype code, registry, ground truth, and `eval.py` live in
  `spikes/sp1-surface-mapping/` — explicitly not meant to be imported by real
  E2 code. E2's actual registry is built against SP10's per-language adapter
  interface, once that spike resolves; this prototype's job was answering
  the recall question, not pre-building E2.
- Fully reproducible: clone the three pinned commits from
  `ground_truth/corpus_manifest.json`, run `python3 eval.py --corpus-dir
  <dir>` — recomputes 17/17 from the actual source, not from this record's
  prose.
