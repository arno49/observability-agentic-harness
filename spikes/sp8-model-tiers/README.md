# SP8 prototype — light-tier vs. frontier disambiguation comparison

Spike evidence, not E1/E2's production role-config. Produced to answer part
of SP8 (`ROADMAP.md`): where does a light tier (Haiku-class) hold quality
for S1-disambiguation specifically. See
[`../../docs/decisions/009-sp8-litellm-model-abstraction.md`](../../docs/decisions/009-sp8-litellm-model-abstraction.md)
for the scored comparison and the decision.

## What was run

`batch.json` — 4 disambiguation candidates matching S1's real
`io/input.schema.json` shape exactly: one real hard case (`c1-ollama-trap`,
the receiver-type mismatch found in `claude-engineer`'s corpus repo during
SP1), and three synthetic hard cases already built for SP1's
`synthetic_hard_cases.py` (subscript indirection, `getattr` dynamic
dispatch, and a branch conditionally assigning two different SDK
constructors to one name).

The exact same batch and the exact same S1 `SKILL.md` instructions were run
twice — once with `model: haiku`, once with `model: sonnet` — so the only
variable between `haiku-output.md` and `sonnet-output.md` is the model tier.
