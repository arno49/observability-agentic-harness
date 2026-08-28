# 037 — S2 gains a real Java telemetry inventory

Status: landed. Closes the gap `docs/decisions/036` named explicitly.

## Context

`docs/decisions/036` fixed S1 for `legacy-code-transpilers` (a real
~4400-file Java/Spring backend) — 0 → 13 real Spring AI call sites — but
`oah gaps --language java` still reported all 13 dark, TCR 0%. Not because
the repo lacks logging: 668 of its files use real SLF4J call sites. No
Java S2 scanner had ever been written — `_build_telemetry_inventory`
(`oah/cli.py`) fell back to the Python scanner for `java`, which finds
`*.py` files (none) and reports an honest-but-useless empty inventory,
the exact same shape `docs/decisions/033` already fixed for TypeScript.

Reading the real source: two logger-construction shapes matter.
**Explicit SLF4J** (`private static final Logger log =
LoggerFactory.getLogger(X.class);`) and, far more common in this
Lombok-heavy codebase, **`@Slf4j`** — a class-level annotation that
generates a `log` field at *compile time*, never written in source at
all. This is the same class of implicit construction `java_adapter.py`'s
own S1 pass already had to handle for `@RequiredArgsConstructor`
(`docs/decisions/036`) — Lombok annotation processing keeps producing
real, invisible-in-source constructs this adapter family has to trust
structurally rather than see literally.

## What was built

`oah/discovery/java_telemetry_scanner.py` (new), matching
`telemetry_scanner.py`/`ts_telemetry_scanner.py`'s four categories and
`schemas/telemetry_inventory.schema.json`'s exact shape:

- **Loggers**: `@Slf4j`-annotated classes get their (always-named) `log`
  field trusted structurally; explicit `LoggerFactory.getLogger(...)`
  field initializers are recognized under whatever name they're declared
  (`log`, `LOGGER`, anything). Both resolve into a class-scoped
  `self_attrs` dict — Java loggers are per-class by convention, never a
  cross-file shared singleton the way TS's own logger/client shapes were
  (`docs/decisions/033`), so **no cross-file propagation is needed here at
  all**, a real simplification relative to the TS scanner.
  `System.out`/`System.err` `.println`/`.print`/`.printf` are Java's own
  weakest logging tier (kind `print`).
- **`existing_otel_usage`**: `io.opentelemetry.*` imports.
- **`metrics_libraries`**: `io.prometheus.client`/`com.timgroup.statsd`
  import prefixes, normalized to the schema's existing enum values
  (docs-grounded, 0 real occurrences in the motivating repo).
- **`error_handling`**: `catch_clause` classified reraised (a `throw`
  anywhere in the body) > logged (a call whose method name is a
  recognized log-level name, receiver-agnostic — the same coarse
  heuristic Python/TS both already use) > swallowed. Unlike TS,
  **`exception_type` is real and populated here** — Java `catch` bindings
  carry genuine static types, including real multi-catch (`catch
  (IOException | SQLException e)`, captured verbatim) — the same
  information Python's own `except SomeError as e` handling already
  extracts, a real difference from TS's documented "not applicable."

`oah/cli.py`'s `_build_telemetry_inventory` dispatcher gained the `java`
branch (was previously falling through to the Python scanner's
honest-empty result); `_LANGUAGE_HELP` updated to match.

**Deliberately not covered**, named rather than silently dropped: Log4j2
(one real occurrence in the motivating repo, not worth a second
logger-construction shape); an inline `LoggerFactory.getLogger("x")
.debug(...)` chain with no intermediate variable (one real occurrence —
the same "terminal buried mid-chain" boundary `docs/decisions/029`
already names for S1); and a Maven `pom.xml` manifest scanner (the Java
analogue of `manifest_scanner.py`'s `package.json` reader) — real,
separate, larger work, `vendor_dependencies` stays `[]` for every Java
repo until it exists.

## Verified end to end

On the motivating repo: **0 → 4560 logger call sites** (4484
`stdlib_logging`, 76 `print`) across 3477 non-test files, **0 → 1461
`error_handling` entries** (950 logged, 261 swallowed, 250 reraised), in
3.6 seconds. `oah gaps --language java` on the same 13 Spring AI call
sites from `docs/decisions/036`: **13 dark / 0 partial → 3 dark / 10
partial** — real nearby SLF4J evidence now counts.

## Decision

**No cross-file mechanism, and that's a real, evidence-based design
choice, not an oversight.** TypeScript's own S2 scanner needed
`ts_module_resolution.py` because a shared logger singleton is a real TS
idiom (`docs/decisions/033`'s own motivating case). Java's per-class
logger convention (`@Slf4j`/`LoggerFactory.getLogger(ThisClass.class)`,
always scoped to the declaring class) has no equivalent shared-instance
shape — confirmed by reading the actual repo, not assumed from the
language's reputation. Building unused cross-file machinery here would
have been speculative complexity with zero corpus evidence behind it.

## Consequences

- S2 is now real for all three S1-supported languages (Python,
  TypeScript, Java).
- `oah gaps`'s dark/partial/covered classification for Java targets is
  now grounded in the target's own real logging, closing the loop
  `docs/decisions/036` opened.
- Real, un-closed gaps, named rather than silently dropped: Log4j2, the
  inline-chain logger-construction shape, and Maven manifest scanning
  (`vendor_dependencies` for Java).
