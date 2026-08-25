# Sonnet-tier output, verbatim

Same batch (`batch.json`), same S1 `SKILL.md` instructions, `model: sonnet`.
See [`../../docs/decisions/009-sp8-litellm-model-abstraction.md`](../../docs/decisions/009-sp8-litellm-model-abstraction.md)
for scoring against ground truth.

## c1-ollama-trap (Claude-Eng-v2/ollama-eng.py:322, `generate_edit_instructions`)
- **kind**: `llm_generation`
- **framework**: **inconsistent** — the call shape (`client.messages.create(model=..., max_tokens=8000, system=..., extra_headers={"anthropic-beta": ...})`) is unmistakably the anthropic-sdk shape, but the only visible constructor for `client` is `ollama.AsyncClient()` (33 lines above, 280 lines removed from the call site), and `anthropic` never appears in the import list at all. This is exactly the receiver/call-shape mismatch the instructions ask me to flag rather than resolve by guessing.
- **sync_nature**: uncertain — `client` was constructed as `AsyncClient`, implying async, but the excerpt shows an unawaited `response = client.messages.create(...)`, which doesn't fit an async client call.
- **confidence**: 0.35
- **notes**: Receiver/call-shape mismatch. Either `client` is reassigned somewhere in the 280 elided lines (to `anthropic.Anthropic()`/`AsyncAnthropic()`), this is stale/copy-pasted code, or `ollama` is a red herring here.
- **needs_context**: lines 33-322 of the file (to check for reassignment of `client`); whether the call site is inside an `async def` and actually awaited; confirmation of whether `anthropic` is imported anywhere in the module despite being absent from the listed imports.

## c2-subscript-dict (app.py:34, `case_subscript_receiver`)
- **kind**: `llm_generation`
- **framework**: `anthropic-sdk` (consistent — `clients["primary"]` resolves to `anthropic.Anthropic()`, and `.messages.create(...)` matches exactly)
- **sync_nature**: sync (`Anthropic()` is the sync client; no `await`)
- **confidence**: 0.9
- **notes**: Symbol naming (`case_subscript_receiver`) plus the sibling candidates' naming pattern (`case_getattr_dynamic_method`, `case_branch_assigns_two_sdks`) strongly suggests `app.py` is a scanner test-fixture file rather than production code. Classification reflects the literal code shape regardless.

## c3-getattr-dynamic (app.py:26, `case_getattr_dynamic_method`)
- **kind**: `llm_generation` (default-path assumption)
- **framework**: `anthropic-sdk` (client constructed via `anthropic.Anthropic()`; `getattr` targets `client.messages`)
- **sync_nature**: sync
- **confidence**: 0.5
- **notes**: The method actually invoked is decided at runtime by `LLM_METHOD` env var (default `"create"` -> `messages.create`, i.e. `llm_generation`). If deployments ever set `LLM_METHOD` to something else (e.g. a streaming or token-counting method), true kind/sync_nature would differ -- classification assumes the documented default.
- **needs_context**: actual/possible values of `LLM_METHOD` across deployments/config; any call sites that set it to something other than `"create"`.

## c4-branch-two-sdks (app.py:57, `case_branch_assigns_two_sdks`)
- **kind**: `llm_generation` (agrees with scanner's tentative kind)
- **framework**: **inconsistent** — the call shape `.messages.create(model=..., max_tokens=1, messages=[])` matches anthropic-sdk precisely, but OpenAI's Python SDK has no matching `.messages.create` method with these params (its chat endpoint is `client.chat.completions.create`). When `use_anthropic` is `False`, `api_client = openai.OpenAI()` and this call would raise `AttributeError` at runtime. This looks like a latent bug in the else-branch rather than a genuine dual-provider abstraction -- flagging explicitly rather than picking one SDK.
- **sync_nature**: sync
- **confidence**: 0.55 (below 0.6 -- kind itself is fairly confident, but I'm withholding higher confidence because of the SDK/receiver mismatch on the untaken branch)
- **notes**: Scanner's tentative `llm_generation`/0.5 is directionally right, but the true framework depends on which branch executes; the `openai.OpenAI()` branch appears broken as written.
- **needs_context**: whether `use_anthropic` is ever `False` in practice / whether that branch has test coverage; whether `api_client` is normalized/wrapped elsewhere to unify the two SDKs' interfaces before this call.
