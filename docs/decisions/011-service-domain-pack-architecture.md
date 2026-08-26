# 011 — Service domain pack: architecture of the pipeline-core/domain-pack split

Status: decided, not yet built. Rewrites E12; introduces E13 as its
prerequisite. Depends on M4 for evidence, not for code.

## Context

README's "Why" claims a split: the S1–S3 mapping mechanics, the S4 ops
lens, S5's gates, S7's roll-up, S8/S9's DTO and readiness shapes and
S11's ladder are domain-agnostic SRE engineering, while what is
LLM-specific is confined to `docs/event-model.md` and three S4 lenses —
"the GenAI domain pack the harness ships with."

E12 was written to prove or disprove that claim by porting the pack to a
second domain "without touching S1–S2, S5–S11, or the DTO/schema-as-truth
mechanics," and its definition of done requires **zero pipeline-core edits
outside the event-model equivalent and the swapped lenses**.

Before designing the second pack, we enumerated where the GenAI domain is
actually hardwired. The claim does not survive contact with the code.

## Findings

**Finding 0 — the split is real in the places that matter most, and
absent in the places that would let a second pack load.**

Eight of S5's ten gates, all of S7's merge, all of S9's readiness
assembly, all of S10's instrumenter and all of S11's validation contain
no domain vocabulary whatsoever. That half of the claim holds, and it is
the expensive half. But the *seam* does not exist: there is no object
called a domain pack. Domain-ness is scattered across sixteen literals in
files E12 promises not to touch:

| Coupling | Location |
|---|---|
| `otel_genai` in the signal-mapping enum | `schemas/design_fragment.schema.json:40`, `schemas/event_schema.schema.json:24` |
| `otel_genai` in the S5 gate | `oah/design/gates.py:95` |
| `otel_genai` in the S7 merge and its CLI stub | `oah/design/event_schema.py:82`, `oah/cli.py:693` |
| Stability asserted per pack, not per attribute | `schemas/event_schema.schema.json:27` |
| semconv pin bound to the GenAI repository | `schemas/event_schema.schema.json:14` |
| `KIND_TO_DIMENSION` | `oah/discovery/gap_model.py:25` |
| Closed `dimension` enum | `schemas/gap_model.schema.json:25` |
| Closed `kind` enum, ×4 copies | `schemas/surface_map.schema.json:33`, `skills/s1-surface-mapper/io/{input,output}.schema.json`, `skills/s4-tracing/io/input.schema.json` |
| `LENS_TO_POINT_KIND` + four duplicated `lens_fns` dicts | `oah/cli.py:98, 416, 515, 590, 698` |
| Closed `lens` enum | `schemas/design_fragment.schema.json:11` |
| GenAI-shaped `event_type` enum | `schemas/implementation_dto.schema.json:44` |
| Advisory-gate word pairs | `oah/design/gates.py:37` |
| Registries | `oah/discovery/registry.py:80–114` |

So E12 as written cannot pass, and its own text anticipates this: "if
pipeline-core needs edits to fit the second domain, that itself is the
finding, not a failure." This record is that finding, promoted from a
post-hoc note to a prerequisite epic.

**Finding 1 — one lens needs two output artifacts, and core assumes one.**

Every S4 lens today returns a bare `design_fragment`, and
`oah/design/lens.py` hard-codes that assumption. An SLO specification is
not expressible as a list of event attributes: an indicator, a target, a
window, alert tiers and a budget policy are a different shape. The slo
lens must emit `design_fragment` **and** `slo_spec`. This is a genuine
core change, declared in the pack manifest as `lenses[].emits`.

**Finding 2 — for a non-AI service, most of what the GenAI pack designs
is already emitted for free, on firmer ground than the GenAI pack stands
on.**

HTTP semantic conventions are Stable, with server and client duration
metrics, a normative low-cardinality route requirement and a defined
status mapping. eBPF-based instrumentation emits HTTP RED metrics and
correctly named spans with no code changes, no library installs and no
restarts, and propagates W3C trace context into outgoing requests. By
contrast the GenAI conventions are entirely Development, have no tagged
releases at all, and publish no schema URL — so no automatic version
translation exists for them.

This inverts the value proposition. The GenAI pack earns its agentic
source-editing because nothing else will write those spans. A service
pack that generated wrappers around HTTP handlers would be re-emitting,
worse and later, what `opentelemetry-instrument` already provides. The
service pack's value is therefore **not** instrumentation volume. It is
the decision layer above signals that already exist, plus the four narrow
things auto-instrumentation provably cannot do.

**Finding 3 — the burn-rate multipliers everyone copies are derivable;
what is undrived is something else entirely.**

The corpus review of SLO alerting turned up a widely repeated claim that
the 14.4 / 6 / 3 / 1 multipliers and the one-twelfth short-window ratio
lack a published derivation. Half of that is wrong, and the half that is
right matters more. From the corpus's own relation
`budget_consumed = burn_rate × window ÷ period`:

```
burn_rate = budget_fraction × period ÷ detection_window

30d period:  2% in 1h  → 0.02 × 720 ÷ 1  = 14.4
             5% in 6h  → 0.05 × 720 ÷ 6  =  6
            10% in 1d  → 0.10 × 720 ÷ 24 =  3
            10% in 3d  → 0.10 × 720 ÷ 72 =  1
```

All four fall out exactly. The multipliers are not arbitrary constants —
they are the consequence of choosing three budget fractions (2%, 5%, 10%)
and three detection windows, **at a thirty-day period**. Copying them onto
a 28-day or 14-day period, which two of the sources and one popular
generator do, silently changes what fraction of budget each tier
represents. Running the same arithmetic backwards over the one tool that
parameterises windows from the SLO period shows it lands on ≈2%, 6%, 7%,
14% instead of 2/5/10 — close, but not the same policy, and nowhere
stated.

What genuinely has no derivation anywhere in the reviewed corpus is the
**one-twelfth short-window ratio**, and the choice of the budget
fractions themselves.

The consequence for the schema is direct: `budget_fraction` and
`detection_window` are declared inputs, `burn_rate_multiplier` is
computed and gate-verified, and `short_window_rationale` is required
prose — because the pack can compute the first and cannot compute the
second, and pretending otherwise would be the exact overclaim the S9 gate
refuses elsewhere.

## Options

**A. Build the service pack against the current hardwiring.** Fastest to
a demo, and produces a second pack that cannot coexist with the first:
every enum edit is a fork of the GenAI behaviour, not an addition.
Rejected — it proves nothing about the split, which is E12's entire
purpose.

**B. Design the pack abstraction from first principles, then build both
packs against it.** Rejected for the reason SP10 already rejected it for
languages: an abstraction validated by one instance is not validated. It
also inverts the evidence — we would be guessing at extension points
instead of extracting the sixteen real ones.

**C. Extract the seam from the evidence, then build the second pack
through it.** Chosen. E13 extracts a `domain_pack.json` manifest and an
`oah/domains/<name>/` package whose contents are exactly the sixteen
coupling points above, and re-expresses the existing GenAI behaviour as
a pack, with zero behaviour change and the full suite green. E12 then
builds the service pack through that seam, and its zero-core-edits
definition of done becomes meaningful because there is finally a seam it
can be measured against.

## Decision

Split E12 into two epics.

**E13 — Domain pack extraction (pipeline core).** Introduce
`schemas/domain_pack.schema.json` and `oah/domains/genai/`. Core reads
vocabulary, registries, lens roster, semconv namespaces, DTO event types
and the advisory lexicon from loaded packs instead of literals.
Generalise `otel_genai` → `otel_semconv` with `namespace` and
per-attribute `stability`, which also corrects the false claim that
upstream attributes are always Development. Collapse the four duplicated
`lens_fns` dicts. Add `lenses[].emits` so a lens may return more than one
artifact.
*DoD:* the GenAI pack ships as a pack; behaviour is byte-identical on the
corpus; the full suite passes with only mechanical renames; a second pack
declaring one kind and one lens loads and runs end to end with **no edit
under `oah/` or `schemas/`**. *Blocks:* E12.

**E12 (rewritten) — Service domain pack.** Six lenses: `tracing`, `ops`
and `pii-governance` **reused unchanged** from the GenAI pack — the
concrete test of the split — `telemetry-cost` adapted from `cost` (token
accounting becomes cardinality and retention accounting), and two new:
`slo` and `dependency`. Point kinds `http_server_route`,
`http_client_call`, `db_query`, `queue_producer`, `queue_consumer`,
`scheduled_job`. The first two `queue_*` kinds already exist in
`surface_map.schema.json` and have never been emitted by anything; the
pack turns dead vocabulary live.

*DoD:* (a) a corpus fixture in this domain passes S1→S9 and clears S5/S6;
(b) the three reused lenses run with **no edit to their SKILL.md files**,
and any edit they do need is reported as a finding against the split;
(c) two registry families with **structurally different detector shapes**
are proven, not one — see Consequences; (d) every generated DTO is
checked against `auto_instrumentation_baseline` and one that only
re-emits an already-covered attribute is refused; (e) every claim of
convention stability traces to a verified namespace, with `unknown` used
where verification has not happened.

**Scope explicitly excluded from v1, with reasons rather than silence.**
Resource saturation: S1 finds call sites in source, and CPU, memory and
connection pools are not call sites — covering them needs a second
discovery source (deployment manifests, runtime inventory), which is
SP9's territory, not S1's. Database and messaging conventions: their
stability is unverified against primary sources; SP11 must resolve it
before any signal claims them. Both gaps are declared in the manifest as
`declared_undetected` and surfaced in `run_manifest.json`, so a reader
can never mistake an undetected kind for a covered one.

## Consequences

**The stack-agnostic risk is now closed by a real candidate, and the
candidate corrected the design rather than confirming it.** This pack was
first specified without committing to a target stack — the mistake SP10
avoided for languages by requiring two real instances. A first candidate
consumer has since appeared: a consumer-travel property running a
React/TypeScript SPA in front of Adobe Experience Manager as a Cloud
Service, already carrying Dynatrace, New Relic and Splunk, with an
OpenTelemetry JS rollout planned and W3C traceparent named as the single
correlation backbone.

Three corrections follow, and they are why guessing was the wrong method:

1. **The language is wrong.** There is no Python anywhere in that stack.
   S1 cannot map it at all today: the TypeScript adapter exists only as a
   211-line prototype under `spikes/sp10-multilang/`, never promoted into
   `oah/`, and Java does not exist even as a prototype. E11's TypeScript
   half therefore moves from "parallel work after M1" to a **hard blocker
   for E12**.
2. **There are three missing detector shapes, not one, and the important
   one is not a decorator.** SPA routes are declared as JSX elements or a
   route-object array — a declarative registration, matching neither the
   receiver/suffix machinery nor a decorator. Global `fetch` is an
   unimported callee, which the adapter's import-anchored resolution
   cannot see at all. Both matter more than the decorator shape here,
   because the four business journeys *are* the routes. SP12 is rewritten
   accordingly.
3. **Route templating is not always statically recoverable.** The
   `route_is_templated` gate assumed a framework whose route template can
   be read from source. AEM resolves a URL to a content path by resource
   type; for a travel catalogue the raw path's cardinality is the number
   of properties. The gate stands, but `cardinality_guard`'s
   `unavailable_reason` branch becomes the primary path for that layer
   rather than a theoretical fallback — with the consequence that a
   server-side SLI there is built on Dispatcher and CDN logs at the
   cheapest rung of the measurement ladder, not on spans.

**The pilot also adds one gate the GenAI pack never needed.** Dynatrace
RUM carries its own correlation identity and does not emit W3C traceparent
by default, while the consumer names traceparent as the *single*
correlation backbone and already imports the Dynatrace RUM API types. Two
agents owning trace context on one page produce two unjoinable views of
one user request. `single_correlation_backbone` therefore requires that,
where S2's inventory finds more than one correlation mechanism, the design
names the owning one and how the others are stitched to it — never
assuming traceparent silently wins.

**And it makes an existing hole a compliance matter.** The conventions
normatively redact only `user:pass@` credentials from `url.full` and say
nothing about the query string. A travel search carries dates,
destinations, party composition and sometimes names there. Under GDPR and
CCPA a default OTel JS configuration would ship personal data to the log
platform. The remedy is an OTTL policy in the collector, which means it
belongs in `oah backend-config`'s generated output, not in prose.

Until the two new detector shapes are proven on that stack, the
abstraction remains unvalidated and must be described that way.

**Nine of the ten S5 gates carry over; the pack adds its own.** Gate 4
becomes namespace-aware in E13. Gate 7's word pairs move into the
manifest. The new gates are deterministic and check structure, not taste:
recomputed burn rate matches the declared inputs; every alert tier has a
paired short window; every policy step has an exit criterion; every
policy entry criterion names a tier that exists in the same spec; an
availability objective declares up-predicate, granularity and brownout
classification; no target equals 1.0; no signal averages a precomputed
percentile; a route attribute is templated, never a raw path; a critical
dependency's target is at least one nine better than its dependent's.
Note that the existing gate requiring every signal to name a decision and
an acting role already encodes, by construction, the alerting literature's
actionability and ownership requirements — an alert nobody owns cannot be
expressed in this schema. That convergence is evidence for the split,
arrived at independently.

**S11 needs one addition, not a redesign.** The propagation checker built
for R2 generalises directly: propagation maturity for zero-code
instrumentation varies sharply by runtime, and verifying continuity
per runtime is exactly what that checker does. What must be added is
**signal provenance** on the verdict — whether the evidence came from
auto-instrumentation or from code this harness edited. Ladder rung
answers how much was run; environment answers against what; provenance
answers by whose instrumentation, and collapsing it into the others hides
whether OAH's own changes were load-bearing.

**Two spikes are prerequisites.** SP11: verify DB, messaging, RPC and browser
convention stability against primary sources — currently unknown, and several
proposed point kinds depend on the answer. SP12: prototype, in TypeScript rather
than Python, the two detector shapes the candidate's stack actually needs —
declarative route registration (JSX element or route-object array) and a global
unimported callee (`fetch`) — against the recall and false-positive bars E2
already sets. Not `decorator_registration`: the candidate corrected that
assumption too (see Consequences above).

**One test-suite landmine is already visible.** Corpus scoring counts a
false positive as any resolved point absent from ground truth, across all
fixtures. Two existing GenAI fixtures contain live outbound HTTP calls
that ground truth does not mark. The moment an `http_client_call`
registry lands, those tests fail — correctly. Ground truth for every
existing fixture must be extended in the same commit as the first
service registry, not after.
