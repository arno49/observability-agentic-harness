"""Hand-authored fixture for the SP1 hard cases that never occurred naturally
across the three real repos in the corpus (see ground_truth/ and the decision
record). Author-constructed, not derived from real code — kept separate from
the real-repo recall numbers, never blended into the headline figure.

Each case is annotated with the expected detector outcome and why.
"""
import anthropic
import os

client = anthropic.Anthropic()


def case_direct():
    """Baseline control: plain direct call. Expected: HIGH confidence."""
    return client.messages.create(model="x", max_tokens=1, messages=[])


def case_getattr_dynamic_method():
    """The method name is a runtime string, not a literal attribute access
    anywhere in the source. Expected: MISSED — no `.create`/`.stream` token
    exists in this function's AST at all for the suffix match to find. This
    is the genuine boundary: no amount of import/assignment tracking helps
    when the attribute name itself isn't static."""
    method_name = os.environ.get("LLM_METHOD", "create")
    return getattr(client.messages, method_name)(model="x", max_tokens=1, messages=[])


def case_subscript_receiver():
    """Receiver is a dict lookup, not a plain name. Expected: LOW confidence
    (flagged for disambiguation) — the suffix matches but the receiver
    expression isn't a Name/self-attr this prototype resolves."""
    clients = {"primary": anthropic.Anthropic()}
    return clients["primary"].messages.create(model="x", max_tokens=1, messages=[])


def case_branch_assigns_two_sdks(use_anthropic):
    """The same name is assigned from two *different* SDK constructors in
    two branches of one `if`. Confirmed result: this reports HIGH confidence
    regardless of `use_anthropic`'s runtime value — not because of flow-
    insensitive last-write-wins tracking (the actual mechanism is narrower
    and worth naming precisely): this prototype's registry only recognizes
    Anthropic's own constructors, so the `openai.OpenAI()` branch is
    invisible to it entirely and never overwrites the tracked binding.  A
    registry scoped to one provider will silently over-report confidence
    exactly where a variable can be genuinely different SDK clients
    depending on runtime branching — real multi-provider code in the wild
    (see beacon's `AnthropicProvider`/`OpenAIProvider` split in the SP1
    corpus) tends to avoid this by using one method per provider rather
    than conditionally reassigning one name, which is why this pattern
    wasn't observed naturally and had to be constructed by hand."""
    import openai
    if use_anthropic:
        api_client = anthropic.Anthropic()
    else:
        api_client = openai.OpenAI()
    return api_client.messages.create(model="x", max_tokens=1, messages=[])
