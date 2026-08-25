# Haiku-tier output, verbatim

Same batch (`batch.json`), same S1 `SKILL.md` instructions, `model: haiku`.
See [`../../docs/decisions/009-sp8-litellm-model-abstraction.md`](../../docs/decisions/009-sp8-litellm-model-abstraction.md)
for scoring against ground truth.

**Candidate c1-ollama-trap:**
- **candidate_id**: c1-ollama-trap
- **kind**: llm_generation
- **framework**: ollama (client is ollama.AsyncClient)
- **sync_nature**: async
- **confidence**: 0.5
- **notes**: Code initializes ollama.AsyncClient but includes Anthropic-specific header ("anthropic-beta": "max-tokens-3-5-sonnet-2024-07-15"), suggesting SDK confusion or incompatibility. The call shape matches Anthropic SDK more closely than Ollama's standard API.
- **needs_context**: Verify whether ollama.AsyncClient actually supports .messages.create() with Anthropic headers, or if this is a misconfiguration mixing two SDKs.

**Candidate c2-subscript-dict:**
- **candidate_id**: c2-subscript-dict
- **kind**: llm_generation
- **framework**: anthropic-sdk
- **sync_nature**: sync
- **confidence**: 0.95
- **notes**: Straightforward Anthropic SDK usage with minor indirection through dict subscript (no functional impact).

**Candidate c3-getattr-dynamic:**
- **candidate_id**: c3-getattr-dynamic
- **kind**: llm_generation
- **framework**: anthropic-sdk
- **sync_nature**: sync
- **confidence**: 0.75
- **notes**: Clear Anthropic SDK call with dynamic method resolution via getattr. Default method_name is "create" (valid), but runtime override via LLM_METHOD env var introduces uncertainty about which method will actually execute.
- **needs_context**: What values can LLM_METHOD legitimately take? Are all possibilities valid anthropic.Anthropic.messages methods?

**Candidate c4-branch-two-sdks:**
- **candidate_id**: c4-branch-two-sdks
- **kind**: llm_generation
- **framework**: inconsistent (anthropic-sdk or openai-sdk depending on use_anthropic condition)
- **sync_nature**: sync
- **confidence**: 0.65
- **notes**: Intent is clearly LLM generation, but framework is inherently ambiguous at static analysis time. Both branches assign clients with compatible .messages.create() APIs. The scanner's 0.5 confidence reflects this legitimate ambiguity.
- **needs_context**: Runtime value of use_anthropic flag to determine actual SDK in effect.
