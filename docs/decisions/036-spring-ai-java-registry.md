# 036 — Spring AI `ChatClient` registry for the Java genai pack

Status: landed. Advances E11-Java/genai pack coverage, found while assessing
a second real EPAM pilot repo alongside `mf-analyzer-web`.

## Context

The user offered a second real pilot candidate:
`legacy-code-transpilers`, a real ~4400-file Java/Spring Maven multi-module
repo — the actual backend behind `mf-analyzer-web`'s own chat/AI features
(`/api/portfolios/*/chat*` etc., found in `docs/decisions/032`'s own
per-journey report). `pom.xml` declares `spring-ai`/Anthropic dependencies.
Running `oah map --language java` reported **0 points on 4443 files
scanned** — not an error, the same class of silently-confident-zero this
whole session has repeatedly found and fixed (S2, `workflow_hint`,
`oah estimate`), this time because the genai pack's only Java entry
(`docs/decisions/029`) covers the raw Anthropic Java SDK's own
`static_builder_chain` shape, and this repo doesn't call that SDK
directly — it uses **Spring AI**, a completely different abstraction Spring
applications route LLM calls through.

Read the actual source, not assumed: Spring AI's real API is
`org.springframework.ai.chat.client.ChatClient`, almost always a
Spring-managed bean injected as a field or constructor parameter (often via
Lombok's `@RequiredArgsConstructor`, which generates the constructor at
compile time — never visible in source at all), called via a fluent chain:
`chatClient.prompt().system(...).user(...).call().content()` (or
`.chatResponse()`/`.entity(...)`). A second, rarer real shape also exists:
`ChatClient.builder(chatModel).build()`, a static factory — Spring AI's own
documented alternative to DI for cases needing a differently-configured
client per call site.

## What was built

One new `genai` pack registry entry, `domains/genai/pack.json`:

```json
{
  "framework": "spring-ai", "surface_kind": "llm_generation", "language": "java",
  "sdk_module": "org.springframework.ai.chat.client",
  "constructor_names": ["ChatClient"],
  "method_suffixes": [["call","chatResponse"], ["call","content"], ["call","entity"]],
  "detector_shape": "static_builder_chain", "terminal_methods": ["build"]
}
```

**Zero adapter code changes** — the same "second registry entry, no new
mechanism" precedent `pg` (`docs/decisions/023`) already set for
TypeScript. `static_builder_chain` (not `receiver_method_suffix`) chosen
so one entry covers BOTH real shapes at once, mirroring the Anthropic Java
entry's own reasoning exactly:
- `constructor_names: ["ChatClient"]` alone is what makes the dominant
  DI-injected-field case resolve — verified that `annotation_sdk`/typed-
  field resolution consults the pack's whole `constructor_names` union,
  not gated by which detector_shape declared a name, the same trust every
  adapter already extends to a typed parameter/field (`docs/decisions/029`'s
  own `test_field_declared_type_alone_resolves_constructor_injected_client`).
- `terminal_methods: ["build"]` additionally resolves the rarer local
  `ChatClient.builder(model).build()` construction, feeding the SAME
  `sdk_module` into the identical `method_suffixes` matching.

Method suffixes are deliberately **2-segment** (`call`+terminal), not a
bare `["call"]`: `.call()` alone returns an intermediate spec object, not
a result — never itself the end of a real call site in this SDK, and
matching it bare would risk colliding with any other unrelated `.call()`
method (e.g. `java.util.concurrent.Callable.call()`, a real, checked
precision guard in this phase's own test suite, not a hypothetical one).

**Deliberately NOT included**, named rather than silently dropped:
- `.stream()`-based terminals (Spring AI's real streaming alternative) —
  0 real occurrences found in the motivating repo; docs-grounded but not
  corpus-verified, a narrow first cut.
- A single unassigned expression chaining construction AND the call
  together (`ChatClient.builder(model).build().prompt()...content()`, no
  intermediate variable) — the exact same named gap `docs/decisions/029`'s
  own Java adapter already documents for the Anthropic entry (terminal
  buried mid-chain, `_resolve_static_builder` only checks `chain[-1]`).
  Found actually occurring in this real repo (4 files use this exact
  inline-lambda shape) — a real, confirmed instance of a previously
  theoretical boundary, not fixed here.

## Verified end to end

`oah map --language java` against the real repo: **0 → 13 real LLM call
sites across 8 files** (`ChatController`, `SqlAiAnalysisService`,
`PortfolioChatService`, `ProgramChatService`, `AiSkillGenerationService`,
`NetworkArchitectureSummaryService`, `ProgramClassificationAiService`,
`SpringAiChatClientLlmClient`), confirmed correct by reading each real
call site, not just counting. Both the confirmed named gap above and the
`AiConfig.java` `@Bean` factory method that actually DEFINES the injected
`ChatClient` (correctly NOT itself flagged as a call site — it's
infrastructure, not a call) were checked by hand.

## Decision

**Registry-only, no new detector shape.** The existing `static_builder_chain`
mechanism already expressed everything this SDK's real shape needed;
inventing a new mechanism would have duplicated `docs/decisions/029`'s own
reasoning for no real gain.

**Did not attempt the inline-construct-and-call gap.** Closing it needs a
new mechanism (propagating a `static_builder_chain` resolution into an
IMMEDIATELY-CHAINED suffix match within the same unassigned expression,
not just a variable) — real, separately-scoped work, not a registry-data
change. Named here with a regression test documenting it, not silently
dropped.

## Consequences

- The Java genai pack now covers two real GenAI SDK shapes (raw Anthropic
  SDK, Spring AI) instead of one — both corpus-verified against real repos
  now, not docs-grounded-only.
- `oah gaps`/`oah estimate`/`oah interview --surface-map` all become real
  and useful for this second pilot repo for free, downstream of this one
  registry addition — no further wiring needed, matching every prior
  language-dispatch fix's own "fix once, benefit everywhere" shape.
- Real, named follow-ups: the inline-chain gap (above); Spring AI's
  `.stream()` API; `legacy-code-transpilers` has no `--pack service`
  coverage either (Java has no service-domain registries at all yet, a
  pre-existing, separately-scoped gap, not new here).
