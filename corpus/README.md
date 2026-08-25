# Reference corpus (Epic E7)

Planned home for eval fixtures: open-source LLM applications across architectures
(simple RAG chat, multi-agent system, queue-based pipeline) with hand-labeled
ground truth — call sites, expected spans, known gaps, injection-seeded files for
security red-teaming (SP7).

Also planned: **incident tabletop fixtures** — synthetic incident scenarios (e.g.
"field-service troubleshooting API: latency rising, retrieval failing
intermittently, usage approaching quota — same release window") with a labeled
*stronger response* (failure modes named, graceful degradation + paused expansion,
evidence list, ownership) and *weak response* ("it still responds sometimes, keep
going"). The S11 panel and the runbook design are evaluated by walking these
scenarios: from the installed signals alone, the auditor must reach the stronger
response — identify the affected release, pull latency trend / retrieval failure
rate / quota headroom / affected user group, and land on the right decision
(degrade + pause expansion first; rollback only if evidence shows the release
caused unacceptable field impact — an immediate full rollback is not automatically
the safest action).

A governance-review variant of the tabletop fixtures is also planned: a case
packet (Northstar-style) with a partially approved source inventory,
caller-trusted role/region context, and unconfirmed logging controls — the S3
interview and S9 report are evaluated on whether they surface each gap as a named
blocker with an owner rather than letting "internal-only" pass as low-risk.

Rules: permissively licensed sources only; no client code; no real user data;
labels live next to each fixture as `ground_truth.json` validated against
`schemas/surface_map.schema.json` point entries.
