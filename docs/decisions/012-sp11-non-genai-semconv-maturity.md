# SP11 — Non-GenAI semantic convention maturity check (DB/messaging/RPC/browser)

Status: resolved. Blocks E12 (see ROADMAP.md). Timebox: 3 days (used: same-day).

## Context

E12 (service domain pack) proposes point kinds `db_query`, `queue_producer`,
`queue_consumer` and a browser/SPA surface, each needing a
`semconv_namespaces[]` entry in `domains/service/pack.json` with a real
`stability` value (per `schemas/domain_pack.schema.json`, extracted in E13).
Until this spike, this project's own stated position was `unknown` for all
four — an honest gap, not a guess, but one E12 cannot design gates around
(`critical_dependency_extra_nine`, the anti-redundancy gate, `stability_declared_per_attribute`)
without a real answer. HTTP is already known Stable and `gen_ai.*` already
known entirely Development (SP6, `001-sp6-otel-genai-semconv-maturity.md`) —
this spike is the same live check, against four more namespaces, using the
same primary-source discipline.

Checked 2026-08-26 directly against `opentelemetry.io/docs/specs/semconv/`
and the `open-telemetry/semantic-conventions` GitHub repo (core repo, same
one HTTP lives in — unlike `gen_ai.*` and browser, see Finding 5), plus the
new split-out `open-telemetry/opentelemetry-browser` repo.

## Findings

1. **Database (`db.*`) — Stable where it matters, mixed elsewhere.**
   `database-spans.md`: **Stable**. `db.query.text` and `db.namespace` are
   Stable/Conditionally Required; `db.collection.name` is **Stable** and is
   the direct low-cardinality route-equivalent for this namespace (the
   table/container/collection name), the same role `http.route` plays for
   HTTP. `database-metrics.md` is **Mixed**: `db.client.operation.duration`
   is Stable, but response-size and connection-pool metrics remain
   Development. Technology-specific pages (Cassandra, DynamoDB, MongoDB,
   Redis) trail the generic page and are less mature.
2. **Messaging (`messaging.*`) — Development, full stop.** Both the
   overview and `messaging-spans.md` carry a `Development` doc-level status.
   Producer/consumer span-kind guidance is real but is keyed off
   `messaging.operation.type` (`create`/`send`/`receive`/`process`/`settle`),
   not a flat producer/consumer split: `send` → `PRODUCER`, `process`
   (push-based consume) → `CONSUMER`, but `receive` (pull-based consume) →
   **`CLIENT`**, not `CONSUMER`. E12's planned `queue_consumer` point kind
   maps cleanly onto `process`; a pull-based consumer needs its own
   handling, not a silent fold into `queue_consumer` — named here as a real
   design wrinkle for E12, not solved by this spike.
3. **RPC (`rpc.*`) — Release Candidate, a stage this project's schema
   doesn't have a name for.** Core attributes (`rpc.system.name`,
   `rpc.method`, `rpc.method_original`, `rpc.status_code`) are **Release
   Candidate** — one rung above Development, one below Stable — with
   well-known-value maturity uneven beneath that (gRPC and Apache Dubbo are
   Release Candidate; Connect RPC and JSON-RPC are still Development).
   `schemas/domain_pack.schema.json`'s `stability` enum (`stable`,
   `development`, `deprecated`, `removed`, `unknown`) has no slot for this —
   a real gap this spike's own research surfaced, fixed alongside this
   record (see Decision).
4. **Browser/client-side — split, like `gen_ai.*`, and mostly moot for
   request telemetry.** No stable `browser.*` namespace exists. Two tracks:
   the core repo's `model/browser/` (rendered at
   `.../specs/semconv/browser/`, status **Development**, defines exactly one
   event — `browser.web_vital`, i.e. RUM/Core-Web-Vitals data, not spans),
   and the new **experimental** `open-telemetry/opentelemetry-browser` repo
   (future home of the Browser SDK, no `schema_url` published — mirrors
   `gen_ai.*`'s own gap). **The finding that actually matters for E12**:
   the real fetch/XHR auto-instrumentation
   (`@opentelemetry/instrumentation-fetch`/`-xml-http-request`) does **not**
   emit under a browser-specific namespace — it emits under the
   already-Stable **`http.client.*`** namespace (stable since semconv
   v1.23.0). So client-side *request* timing rides on infrastructure this
   project already treats as Stable; only Web Vitals/RUM-style signals need
   the separate, Development-stage `browser.*` namespace at all.
5. **Schema URL: db/messaging/rpc inherit HTTP's mechanism; browser doesn't.**
   db/messaging/rpc all live in the **core** `semantic-conventions` repo,
   which publishes one project-wide, spec-version-tied schema at
   `https://opentelemetry.io/schemas/<version>` (per the OTel schemas spec:
   a new schema ships with every spec version). Renames in these three
   namespaces are therefore covered by OTel's automatic version-translation
   mechanism, the same as HTTP — unlike `gen_ai.*` (SP6 finding 2, literal
   `TODO`) and `browser.*` (no schema_url found at all), which both need
   OAH's own internal versioned rename table as the real fallback.
6. **`error.type` is confirmed on the HTTP duration histograms.** Both
   `http.server.request.duration` and `http.client.request.duration` list
   `error.type` as **Stable**, **Conditionally Required** ("if request has
   ended with an error") on `http-metrics.md`. This directly answers the
   question E12's `slo` lens design depends on: a good/valid-event
   availability SLI **is** computable from the metric alone (filter/group
   the histogram by `error.type` presence), no span required — and because
   it's Stable + Conditionally Required rather than Recommended/Opt-In,
   this is a reliable primary-source guarantee, not a fragile convention.

## Options considered

- **A — treat all four as `unknown` indefinitely**, defer any stability
  claim until each individually reaches Stable. Rejected: db and (partly)
  rpc already have real, checkable answers; refusing to record them
  contradicts this project's own "unknown is an honest gap, not a
  permanent one" stance (SP6's own precedent) and would block E12's `slo`
  lens design (finding 6) for no reason.
- **B — collapse everything to a single `development`/`unknown` bucket**
  per namespace, matching `gen_ai.*`'s all-or-nothing treatment. Rejected:
  the real picture is per-attribute, not per-namespace (db.query.text and
  db.client.operation.duration are Stable while db connection-pool metrics
  are not; the same http.client.* stability already covers most browser
  request telemetry even though browser.* itself doesn't) — a blanket
  per-namespace value would either overclaim or underclaim depending on
  which attribute a signal actually maps to.
- **C — record real, attribute-level findings; extend the stability enum
  to name Release Candidate; and let each domain pack cite the specific
  attribute/schema_url pair it depends on, same discipline event_schema.json
  already applies per-attribute.** Chosen.

## Decision

Option C.

- **`schemas/domain_pack.schema.json`'s `semconv_namespaces[].stability`
  enum gains `release_candidate`**, inserted between `development` and
  `stable`, with its description updated: OTel's own maturity model has
  this intermediate stage and `rpc.*` is squarely in it — collapsing it
  into `development` would understate real convergence, and into `stable`
  would overclaim. Purely additive; the `genai` pack (the only pack that
  exists today) only ever uses `development`, so this is a zero-behavior-change
  widening, not a breaking change to E13's byte-identical guarantee.
- **The future `service` pack's namespace table** (to be written when E12
  actually builds it, not speculatively here) should read: `http` —
  stable (already known, SP-independent); `db` — stable for the
  spans/collection-name/operation-duration attributes E12 actually needs,
  named per-attribute rather than blanket; `messaging` — development, with
  the `receive`-is-CLIENT-not-CONSUMER wrinkle (finding 2) written into
  the lens's own design notes, not silently folded away; `rpc` —
  release_candidate; `browser` — development, scoped narrowly to Web
  Vitals/RUM signals only, since ordinary client request timing already
  rides on the stable `http.client.*` namespace and needs no separate
  browser-specific claim at all.
- **schema_url**: db/messaging/rpc namespace entries cite the core repo's
  shared versioned schema (`https://opentelemetry.io/schemas/1.44.0`, the
  same core semconv version SP6 cross-referenced); `browser` cites none,
  same posture as `gen_ai.*`.

## Consequences

- E12 is unblocked per the spikes table for this specific prerequisite
  (SP12 and E11-TS remain separately blocking).
- `schemas/domain_pack.schema.json` gains one enum value
  (`release_candidate`) in this same change — small, additive, verified
  against the existing test suite (no pack today declares it, so no
  existing behavior changes).
- The messaging `receive`-vs-`process` span-kind wrinkle (finding 2) is a
  real, open design question for E12's own point-kind mapping, not
  resolved here — named so it isn't rediscovered mid-epic.
- **Revisit trigger** (not a recurring spike): re-check when `rpc.*`
  reaches Stable, when `browser.*`/`opentelemetry-browser` ships a
  schema_url or a tagged release, or when messaging's span-kind guidance
  itself changes stability — whichever happens first.
