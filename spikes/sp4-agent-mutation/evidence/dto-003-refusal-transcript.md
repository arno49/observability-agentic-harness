# dto-003 (deliberately invalid) — agent report, verbatim

DTO: [`../dtos/dto-003-deliberately-invalid.json`](../dtos/dto-003-deliberately-invalid.json)
— claims the target call site is at `agents/research.py` line 50; ground truth
(SP1's corpus, `spikes/sp1-surface-mapping/ground_truth/beacon.json`) puts the
real call site at line 89. Line 50 is `_phase_rank()`, unrelated code.

Agent's full response, unedited:

> No edits made, no commit attempted. Full report:
>
> **What I found at the stated location (near_line 50, anchor
> `response = client.messages.create(`):**
>
> Line 50 in `agents/research.py` is:
> ```python
>     if study_type == "OBSERVATIONAL":
>         return 8
> ```
> This is inside `_phase_rank()`, unrelated code with no
> `client.messages.create(` call anywhere nearby. The actual anchor text
> `response = client.messages.create(` exists in the file, but at line 89
> (inside `run_research_agent`), not near line 50 — a 39-line mismatch from
> where the DTO claims it should be.
>
> **Decision:** Per the DTO's own `instructions` field: *"IMPORTANT: if the
> anchor text ... does not actually appear at or near line 50 in this file,
> STOP and report the mismatch instead of guessing a different location --
> do not apply this DTO to any other line."* Since the anchor does not
> appear at or near line 50, I stopped and did not apply the DTO anywhere,
> including at the real line-89 location where the anchor does exist — the
> DTO explicitly forbids applying it to any other line, so line 89 was
> correctly not used as a substitute.
>
> **File edits made:** None.
>
> **Git commit:** None attempted.
>
> **Repo state**, branch `oah-sp4-demo`:
> ```
> $ git status
> On branch oah-sp4-demo
> nothing to commit, working tree clean
>
> $ git log --oneline -3
> 3bccc37 instrument: apply dto-002 (agents/eligibility.py telemetry wrap)
> 273a1ae instrument: apply dto-001 (agents/intake.py telemetry wrap)
> afd2383 chore: add telemetry stub for SP4 instrumentation demo
> ```
> Working tree is unchanged from the prior two commits (dto-001, dto-002);
> dto-003 was correctly refused due to the anchor/line-number mismatch,
> exactly as its own instructions specified.
