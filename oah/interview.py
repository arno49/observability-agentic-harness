"""S3's owner interview — real, human-in-the-loop, not stub data.

architecture.md's S3 names this explicitly *(skill: gap-modeler; interactive)*
— the questions genuinely need a person who knows the product, not
something a deterministic scanner or even an LLM reading the code can
answer honestly (a model can guess at PII presence from field names, but
"is this workflow business-critical" and "is this data source actually
approved for this region" are answers that live with the product owner,
not the source code).

`ask`/`print_fn` are injection points so the interview logic is testable
without real stdin (the same pattern as disambiguate.py's `_completion_fn`)
— real invocations use Python's builtin `input`/`print`.
"""
from datetime import datetime, timezone

from oah.schemas import validate

CRITICALITY_LEVELS = ["low", "medium", "high", "critical"]
PII_LEVELS = ["none", "indirect", "direct"]
APPROVAL_STATUSES = ["approved", "restricted", "unapproved"]


class InterviewAborted(Exception):
    """Raised when the interview is cancelled mid-way (Ctrl+D / EOF, or
    Ctrl+C). Found by adversarial review: run_interview had no handling
    for either, so a real Ctrl+D during `oah interview` crashed with a
    raw traceback instead of a clean message -- the same 'error: ...'
    treatment every other input-validation failure in this CLI already
    gets. Callers must treat this as 'no context.yaml produced,' never
    catch it and fabricate a partial one -- an interview stopped halfway
    has no honest answer for the questions it never reached."""


def _ask_str(ask, print_fn, prompt, allow_blank=False):
    while True:
        value = ask(f"{prompt}: ").strip()
        if value or allow_blank:
            return value
        print_fn("  (required — enter a value)")


def _ask_int(ask, print_fn, prompt, minimum=0):
    while True:
        raw = ask(f"{prompt}: ").strip()
        try:
            value = int(raw)
        except ValueError:
            print_fn("  (enter a whole number)")
            continue
        if value < minimum:
            print_fn(f"  (must be >= {minimum})")
            continue
        return value


def _ask_choice(ask, print_fn, prompt, choices):
    choice_str = "/".join(choices)
    while True:
        value = ask(f"{prompt} [{choice_str}]: ").strip().lower()
        if value in choices:
            return value
        print_fn(f"  (choose one of: {choice_str})")


def _ask_bool(ask, print_fn, prompt):
    while True:
        value = ask(f"{prompt} [y/n]: ").strip().lower()
        if value in ("y", "yes"):
            return True
        if value in ("n", "no"):
            return False
        print_fn("  (enter y or n)")


def _ask_yes_no_loop(ask, print_fn, continue_prompt):
    return ask(f"{continue_prompt} [y/n]: ").strip().lower() in ("y", "yes")


def _interview_workflow(ask, print_fn, index):
    print_fn(f"\n--- Workflow {index} ---")
    name = _ask_str(ask, print_fn, "Workflow name")
    criticality = _ask_choice(ask, print_fn, "Business criticality", CRITICALITY_LEVELS)
    pii = _ask_choice(ask, print_fn, "PII presence (none/indirect: inferable/direct: PII fields present)", PII_LEVELS)
    egress = _ask_str(ask, print_fn, "Data-egress constraints (blank if none)", allow_blank=True)
    review = _ask_str(ask, print_fn, "Review workflow for changes to this workflow (blank if none)", allow_blank=True)

    print_fn("Data & governance map — 'internal-only' is not 'low-risk by default':")
    receives = _ask_str(ask, print_fn, "  What does this workflow receive?", allow_blank=True)
    retrieves = _ask_str(ask, print_fn, "  What does it retrieve?", allow_blank=True)
    returns = _ask_str(ask, print_fn, "  What does it return?", allow_blank=True)
    logs = _ask_str(ask, print_fn, "  What does it log?", allow_blank=True)

    entry = {"name": name, "criticality": criticality, "pii_presence": pii}
    if egress:
        entry["data_egress_constraints"] = egress
    if review:
        entry["review_workflow"] = review
    governance = {k: v for k, v in {
        "receives": receives, "retrieves": retrieves, "returns": returns, "logs": logs,
    }.items() if v}
    if governance:
        entry["data_governance_map"] = governance
    return entry


def _interview_source(ask, print_fn):
    source = _ask_str(ask, print_fn, "Source name (e.g. a vector DB, an internal API)")
    approval = _ask_choice(ask, print_fn, "Approval status", APPROVAL_STATUSES)
    region = _ask_str(ask, print_fn, "Region (blank if not applicable)", allow_blank=True)
    use_case = _ask_str(ask, print_fn, "Approved use case (blank if not applicable)", allow_blank=True)
    entry = {"source": source, "approval_status": approval}
    if region:
        entry["region"] = region
    if use_case:
        entry["use_case"] = use_case
    if approval == "restricted":
        entry["approved_handling_path"] = _ask_str(
            ask, print_fn, "  Approved handling path (required for restricted sources)")
    return entry


def _interview_trust_boundary(ask, print_fn):
    field = _ask_str(ask, print_fn, "Caller-asserted context field (e.g. role, region, tenant_id)")
    verified = _ask_bool(ask, print_fn, "Verified server-side (not just trusted from the caller)?")
    notes = _ask_str(ask, print_fn, "Notes (blank if none)", allow_blank=True)
    entry = {"context_field": field, "verified_server_side": verified}
    if notes:
        entry["notes"] = notes
    return entry


def run_interview(repo_git_sha, ask=input, print_fn=print):
    try:
        return _run_interview_body(repo_git_sha, ask, print_fn)
    except (EOFError, KeyboardInterrupt) as e:
        raise InterviewAborted("interview cancelled before completion") from e


def _run_interview_body(repo_git_sha, ask, print_fn):
    print_fn("OAH owner interview (S3) — architecture.md's context.yaml. Answers weight gap "
              "prioritization; there's no wrong answer, only an honest or a guessed one.\n")

    n_workflows = _ask_int(ask, print_fn, "\nHow many workflows does this product have", minimum=1)
    workflows = [_interview_workflow(ask, print_fn, i + 1) for i in range(n_workflows)]

    print_fn("\n--- Source inventory (data sources the product uses) ---")
    sources = []
    if _ask_yes_no_loop(ask, print_fn, "Add a source"):
        while True:
            sources.append(_interview_source(ask, print_fn))
            if not _ask_yes_no_loop(ask, print_fn, "Add another source"):
                break

    print_fn("\n--- Trust boundaries (caller-asserted context) ---")
    trust_boundaries = []
    if _ask_yes_no_loop(ask, print_fn, "Add a trust boundary"):
        while True:
            trust_boundaries.append(_interview_trust_boundary(ask, print_fn))
            if not _ask_yes_no_loop(ask, print_fn, "Add another trust boundary"):
                break

    print_fn("\n--- Tool/action boundary ---")
    tool_boundary = _ask_str(
        ask, print_fn,
        "What is this product allowed to do autonomously in the current release? (blank if none)",
        allow_blank=True,
    )

    context = {
        "schema_version": "0.1.0",
        "repo_git_sha": repo_git_sha,
        "interviewed_at": datetime.now(timezone.utc).isoformat(),
        "workflows": workflows,
    }
    if sources:
        context["source_inventory"] = sources
    if trust_boundaries:
        context["trust_boundaries"] = trust_boundaries
    if tool_boundary:
        context["tool_action_boundary"] = tool_boundary

    validate("context", context)
    return context
