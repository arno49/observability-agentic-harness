# SP2 — Trace-ID propagation pattern catalog

Status: resolved. Blocks E3. Timebox: 1 wk (used: same-day). Output:
[`docs/trace-propagation-patterns.md`](../trace-propagation-patterns.md).

## Context

E3's tracing lens (S4, "the hardest lens" per `architecture.md`) needs to
know, per framework, whether trace-ID correlation across an async/queue
boundary is something an existing instrumentor already handles or something
S4 has to design real code changes for — including the long-running
background-job case named explicitly in the spike question (a
Deep-Research-style call completing via polling or webhook, not a queue
hop).

## Approach

Read the actual source of every relevant `open-telemetry/opentelemetry-python-contrib`
instrumentor rather than inferring behavior from package names or READMEs —
specifically grepped each one for where (if anywhere) it calls
`propagate.inject`/`propagate.extract` at the real publish/consume boundary,
since that call is what actually makes cross-process correlation happen, not
just "there's an instrumentor with this framework's name in it." Full
findings and the table are in the catalog; this record covers the decision
and its consequences.

## Findings (summary — full detail in the catalog)

1. Same-process `asyncio` concurrency needs no instrumentation at all —
   Python's own `contextvars.Context` copy-on-task-creation guarantee
   handles it, confirmed by reading OTel Python's context implementation
   (`ContextVarsRuntimeContext`, built directly on stdlib `contextvars`).
2. Thread pools are the opposite of what that might suggest: `contextvars`
   does **not** cross into a new OS thread automatically, and
   `opentelemetry-instrumentation-threading` exists specifically because of
   this gap — confirmed from its own README, which states plainly that it
   produces no telemetry, only propagation.
3. **Every queue/broker instrumentor checked — Celery, pika, aio-pika,
   kafka-python, aiokafka, confluent-kafka, boto3sqs — does real
   inject/extract at the actual hop**, verified independently in each
   package's source, not assumed from the first one found. All are fully
   auto-instrumentable given both sides call `.instrument()`.
4. **The long-running background-job pattern has no existing instrumentor,
   for a structural reason:** there's no shared transport message to carry
   headers across a poll or webhook boundary. This needs real, application-specific
   code: persist the submission-time trace context in the job's own
   storage, extract it at completion, and use OTel's own **Span Links**
   primitive (not a bespoke mechanism) to correlate a new trace back to the
   original rather than forcing one continuous multi-hour trace that most
   backends handle poorly.

## Decision

- **S1/S2's job for every queue/broker framework in the catalog is presence
  detection, not propagation-code generation:** is the matching contrib
  instrumentor imported and instrumented on both the producer and consumer
  side. A gap here routes to a configuration-shaped DTO (S8), not a design
  task for S4.
- **The long-running-job pattern gets weighted as real design work, not a
  checklist item**, whenever S1 detects its shape (a submit/poll or
  submit/webhook pair with no queue library present): S4's tracing lens
  needs to design the storage-field addition and the extract-and-link code
  explicitly, and S8 needs to emit a real DTO for it, not a config check.
- **OTel's Span Links primitive is the recommended mechanism for
  submit-now/complete-later correlation** — adopted because it's the
  existing, correct answer to a problem OTel already designed for, not
  because OAH lacks a better idea. Carries forward into `event-model.md`
  and S4's tracing-lens description once E3 starts.

## Consequences

- E3 is unblocked per the spike table.
- The catalog is Python-ecosystem-specific (matches E2's Python-first
  scope); E11's TypeScript/Java ports will need their own pass over
  `opentelemetry-js-contrib` / `opentelemetry-java-instrumentation` — the
  *shape* of this catalog (same-process/thread-pool/queue/long-running-job)
  should transfer, but the per-framework auto-instrumentable verdicts do
  not, and shouldn't be assumed to without the same source-level check
  repeated per language.
- No corpus repo in SP1's or SP10's samples exercises a queue-based
  architecture — this was already flagged as a gap in SP1's decision
  record. This catalog is grounded in the instrumentation libraries'
  actual behavior (verifiable independent of any specific target repo), but
  E7's corpus still needs a queue-based fixture to test S1/S2's *detection*
  of these patterns in real code, which this spike doesn't cover.
