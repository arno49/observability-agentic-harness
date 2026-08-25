# Trace-ID propagation pattern catalog

SP2's output (`ROADMAP.md`) — which async/queue/background-job patterns
already propagate trace context automatically once instrumented, and which
need real code changes. Grounded in the actual behavior of
`open-telemetry/opentelemetry-python-contrib`'s instrumentors (source read
directly, not assumed from package names — see each row's verification
note), not from documentation summaries alone.

## Why "auto-instrumentable" is a specific, narrow claim

Every "auto" row below means: calling `SomeInstrumentor().instrument()` on
**both sides of the hop** (the process that creates the correlation and the
process that resumes it) is sufficient — no application code changes. That's
a real, verifiable claim about what the instrumentor's source does
(`propagate.inject`/`propagate.extract` calls at the actual hop, confirmed
by reading each package's source below), not a description of what the
package's name suggests it might do.

## Same-process concurrency

| Pattern | Auto-instrumentable? | Mechanism | Code-shape changes |
|---|---|---|---|
| `async`/`await`, `asyncio.create_task`, `asyncio.gather` | **Yes, with zero instrumentation at all** | OTel Python's default context storage is `ContextVarsRuntimeContext` (built on stdlib `contextvars`); `asyncio.Task` creation copies the current `contextvars.Context` into the new task automatically — this is CPython's own guarantee, not an OTel behavior | None |
| `ThreadPoolExecutor` / `threading.Thread` | **No, by default** — `contextvars.Context` is per-thread and is *not* inherited by a newly spawned OS thread automatically | `opentelemetry-instrumentation-threading` exists specifically for this: its own README states its only job is ensuring context propagates across threads, producing no telemetry itself | None once the instrumentor is added — but it's easy to silently miss, since nothing fails loudly without it (spans just land in a disconnected trace) |

## Queue / message-broker hops

Verified by reading each instrumentor's source for `propagate.inject`/
`propagate.extract` calls at the actual publish/consume boundary — every one
below stores the trace context in the message's own header/attribute
mechanism, not a side channel:

| Framework | Auto-instrumentable? | Where context is carried | Verification |
|---|---|---|---|
| Celery | **Yes** | Task message `headers`, injected on the `before_task_publish` signal, extracted on `task_prerun` | `opentelemetry-instrumentation-celery/.../__init__.py`: `signals.before_task_publish.connect` → `inject(headers)`; `signals.task_prerun.connect` → `extract(request, getter=celery_getter)` |
| RabbitMQ (`pika`) | **Yes** | AMQP message `properties.headers` | `pika_instrumentor.py`/`utils.py`: `propagate.inject(properties.headers)` on publish, `propagate.extract(properties.headers, ...)` on consume |
| RabbitMQ (`aio-pika`) | **Yes** | Same, via `message.properties.headers` | `publish_decorator.py`: `propagate.inject(message.properties.headers)`; `callback_decorator.py`: `propagate.extract(headers)` |
| Kafka (`kafka-python`, `aiokafka`, `confluent-kafka`) | **Yes, all three** | Kafka record `headers` (native support since broker 0.11+) | Each package's `utils.py`: `propagate.inject(...)` at produce time, `propagate.extract(record.headers, ...)` at consume time — confirmed independently in all three, not just one |
| AWS SQS (`boto3sqs`) | **Yes** | `MessageAttributes` on the SQS message | `opentelemetry-instrumentation-boto3sqs/.../__init__.py`: `propagate.extract(message_attributes, ...)` on receive, `propagate.inject(attributes, ...)` on send |

**Practical implication for S1/S2/S4's tracing lens:** for every framework in
this table, S1/S2's job is presence detection — is the matching contrib
instrumentor imported and `.instrument()`-called on *both* the producer and
the consumer side — not writing new propagation code. A gap here is "the
instrumentor exists but isn't wired up on one side," which is a
configuration DTO, not a novel code-shape one.

## Long-running background jobs (submit-now, complete-later)

The pattern named explicitly in SP2's question — a Deep-Research-style call
that runs for minutes to hours via polling or a webhook callback, not a
queue hop. **No existing OTel instrumentor covers this, for a structural
reason, not an oversight:** there is no shared transport message carrying
headers between submission and completion — the job might be polled from an
entirely different process, or complete via a webhook POST from the
provider's infrastructure, arriving with no OTel-aware caller on the other
end at all.

**This is the one pattern in this catalog that needs real code-shape
changes, not just an instrumentor:**

1. At submission time, capture the current trace context as a portable
   string (`propagate.inject()` into a plain dict — the same mechanism every
   row above uses, just with nowhere transport-native to put it) and persist
   it *in the job's own storage* — a column/field alongside whatever record
   already tracks the job (a DB row, a state file), not a side channel OAH
   invents.
2. At completion time (poll result or webhook handler), read that stored
   string back and `propagate.extract()` it into a carrier to resume
   correlation.
3. **Whether that resumption continues the original trace or starts a new
   one with a link back is a real design choice, not a detail:** most
   tracing backends and UIs handle a trace spanning hours or days poorly —
   "trace" semantically implies a bounded unit of work. OTel's own answer to
   this exact problem is **Span Links** (`opentelemetry.trace.Link`): start
   a new trace at completion time, and attach a link to the original
   submission span's context. This is an existing OTel primitive, not
   something to invent — the recommendation is to use it, not to design
   around its absence.

**Practical implication:** this pattern needs an actual `implementation_dto`
(S8) — a schema change to whatever tracks the job, plus explicit
extract-and-link code at the completion path — not a presence check. It's
materially heavier design work than every queue/broker row above, and
should be weighted that way in S4's tracing-lens effort estimate whenever S1
detects this shape (a submit/poll or submit/webhook pair with no queue
library in between).
