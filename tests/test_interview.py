"""Regression tests for oah.interview — driven with canned answers via the
`ask` injection point, not real stdin."""
import pytest

from oah.interview import run_interview, InterviewAborted
from oah.schemas import validate, SchemaValidationError


def _scripted(answers):
    """Returns an `ask` function that yields each canned answer in order,
    ignoring the prompt text — mimics a user typing a fixed script."""
    it = iter(answers)

    def ask(prompt):
        try:
            return next(it)
        except StopIteration:
            raise AssertionError(f"interview asked more questions than the test scripted: {prompt!r}")
    return ask


def test_minimal_interview_one_workflow_no_optional_sections():
    answers = [
        "1",                    # how many workflows
        "support-chat",         # name
        "high",                 # criticality
        "indirect",             # pii_presence
        "",                     # egress constraints (blank)
        "",                     # review workflow (blank)
        "",                     # receives (blank)
        "",                     # retrieves (blank)
        "",                     # returns (blank)
        "",                     # logs (blank)
        "n",                    # add a source? no
        "n",                    # add a trust boundary? no
        "",                     # tool/action boundary (blank)
    ]
    context = run_interview("deadbeef", ask=_scripted(answers), print_fn=lambda *a: None)
    validate("context", context)
    assert context["repo_git_sha"] == "deadbeef"
    assert len(context["workflows"]) == 1
    assert context["workflows"][0] == {
        "name": "support-chat", "criticality": "high", "pii_presence": "indirect",
    }
    assert "source_inventory" not in context
    assert "trust_boundaries" not in context
    assert "tool_action_boundary" not in context


def test_full_interview_all_sections_populated():
    answers = [
        "1", "billing-agent", "critical", "direct",
        "EU-only, no third-party LLM", "security team sign-off required",
        "invoice PDFs", "customer records DB", "payment status", "request metadata only",
        "y",  # add a source
        "internal-crm", "restricted", "eu-west-1", "billing lookups", "via data-access-broker service",
        "n",  # no more sources
        "y",  # add a trust boundary
        "tenant_id", "y", "verified via signed JWT claim",
        "n",  # no more trust boundaries
        "can send refund emails, cannot issue refunds without human approval",
    ]
    context = run_interview("cafebabe", ask=_scripted(answers), print_fn=lambda *a: None)
    validate("context", context)

    wf = context["workflows"][0]
    assert wf["data_egress_constraints"] == "EU-only, no third-party LLM"
    assert wf["data_governance_map"]["receives"] == "invoice PDFs"

    assert context["source_inventory"][0]["approval_status"] == "restricted"
    assert context["source_inventory"][0]["approved_handling_path"] == "via data-access-broker service"

    assert context["trust_boundaries"][0]["context_field"] == "tenant_id"
    assert context["trust_boundaries"][0]["verified_server_side"] is True

    assert "refund" in context["tool_action_boundary"]


def test_invalid_criticality_reprompts_not_crashes():
    answers = [
        "1", "wf-1",
        "urgent",   # invalid -- not in CRITICALITY_LEVELS, interview must re-prompt for this one
        "high",     # corrected
        "none",
        "", "", "", "", "", "",  # egress, review, receives, retrieves, returns, logs
        "n", "n", "",
    ]
    context = run_interview("sha1", ask=_scripted(answers), print_fn=lambda *a: None)
    assert context["workflows"][0]["criticality"] == "high"


def test_invalid_criticality_actually_reprompts_same_question():
    """Distinguishes 're-prompts correctly' from 'silently accepted the
    invalid value' -- the previous test alone wouldn't catch the latter if
    the code coincidentally used the last-seen value regardless."""
    calls = []
    script = ["1", "wf-1", "urgent", "high", "none", "", "", "", "", "", "", "n", "n", ""]

    def ask(prompt):
        calls.append(prompt)
        return script[len(calls) - 1]

    run_interview("sha1", ask=ask, print_fn=lambda *a: None)
    criticality_prompts = [p for p in calls if p.startswith("Business criticality")]
    assert len(criticality_prompts) == 2  # asked once, rejected, asked again


def test_multiple_workflows():
    answers = [
        "2",
        "wf-a", "low", "none", "", "", "", "", "", "",
        "wf-b", "critical", "direct", "", "", "", "", "", "",
        "n", "n", "",
    ]
    context = run_interview("sha2", ask=_scripted(answers), print_fn=lambda *a: None)
    assert [w["name"] for w in context["workflows"]] == ["wf-a", "wf-b"]


# --- Cancellation handling (found by adversarial review) -------------------
# run_interview had no EOFError/KeyboardInterrupt handling at all -- a real
# Ctrl+D or Ctrl+C during `oah interview` crashed with a raw traceback
# instead of the clean error treatment every other failure in this CLI gets.

def test_eof_during_interview_raises_interview_aborted():
    def eof_ask(prompt):
        raise EOFError()

    with pytest.raises(InterviewAborted, match="cancelled"):
        run_interview("deadbeef", ask=eof_ask, print_fn=lambda *a: None)


def test_keyboard_interrupt_during_interview_raises_interview_aborted():
    def interrupt_ask(prompt):
        raise KeyboardInterrupt()

    with pytest.raises(InterviewAborted, match="cancelled"):
        run_interview("deadbeef", ask=interrupt_ask, print_fn=lambda *a: None)


def test_eof_partway_through_interview_also_raises_cleanly():
    """Cancelling isn't only possible on the very first prompt -- must be
    caught no matter which question was in progress."""
    answers = iter(["1", "support-chat", "high"])

    def ask(prompt):
        try:
            return next(answers)
        except StopIteration:
            raise EOFError()

    with pytest.raises(InterviewAborted):
        run_interview("deadbeef", ask=ask, print_fn=lambda *a: None)


# --- Surfacing S1's workflow_hint guesses (docs/decisions/034) -------------
# `_find_workflow` (gap_model.py) requires an exact (stripped/lowered)
# string match between a point's workflow_hint and a workflow name typed
# here -- without seeing the actual hints S1 found, the owner has no real
# way to type a name that connects to anything.

def _surface_map_with_hints(hints):
    return {"points": [{"id": f"sp-{i:04d}", "workflow_hint": h} for i, h in enumerate(hints)]}


def test_workflow_hint_counts_sorted_by_frequency():
    from oah.interview import _workflow_hint_counts
    sm = _surface_map_with_hints(["billing", "billing", "support", "billing", None, "support"])
    assert _workflow_hint_counts(sm) == [("billing", 3), ("support", 2)]


def test_workflow_hint_counts_ignores_points_with_no_hint():
    from oah.interview import _workflow_hint_counts
    sm = {"points": [{"id": "sp-0001"}, {"id": "sp-0002", "workflow_hint": "billing"}]}
    assert _workflow_hint_counts(sm) == [("billing", 1)]


def test_surface_map_hints_printed_before_workflow_questions():
    sm = _surface_map_with_hints(["portfolio", "portfolio", "chat"])
    printed = []
    answers = [
        "1", "portfolio", "critical", "none", "", "", "", "", "", "",
        "n", "n", "",
    ]
    run_interview("deadbeef", ask=_scripted(answers), print_fn=lambda *a: printed.append(" ".join(str(x) for x in a)),
                  surface_map=sm)
    joined = "\n".join(printed)
    assert "'portfolio'" in joined and "(2 points)" in joined
    assert "'chat'" in joined and "(1 point)" in joined


def test_no_surface_map_prints_nothing_extra_byte_identical_default():
    """Default (no surface_map) must behave exactly as before
    docs/decisions/034 -- no hint banner, no change to the question flow."""
    printed = []
    answers = ["1", "support-chat", "high", "indirect", "", "", "", "", "", "", "n", "n", ""]
    run_interview("deadbeef", ask=_scripted(answers), print_fn=lambda *a: printed.append(" ".join(str(x) for x in a)))
    assert not any("candidate workflow names" in line for line in printed)
