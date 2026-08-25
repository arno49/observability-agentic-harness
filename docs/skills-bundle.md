# Skills bundle (debug tooling, not part of the pipeline)

The pipeline doesn't run yet (see [ROADMAP.md](../ROADMAP.md)) — `skills/*/SKILL.md`
are drafts, exercised so far only by reading them. The **Bundle skills** GitHub
Action (`.github/workflows/bundle-skills.yml`) packages those drafts into
downloadable artifacts so a skill can be loaded into a real Claude session and
tried against the corpus by hand, without copy-pasting file contents. It has no
effect on `oah`'s own code; it only repackages `skills/`.

## What it produces

Runs on every push that touches `skills/**`, or on demand
(Actions tab → Bundle skills → Run workflow, or `gh workflow run bundle-skills.yml`).
Two artifact sets land on the run's summary page:

- **`oah-skills-individual`** — one zip per skill (`s1-surface-mapper.zip`, ...),
  each containing that skill's folder as-is (`SKILL.md`, any `references/` or
  `examples/` it has, its `io/` schemas if present, and a `scripts/validate.py`
  injected at bundle time — see "What a skill can validate about itself" below).
- **`oah-skills-bundle`** — `oah-skills-bundle.zip`, all skills together under a
  single `skills/` folder, each with the same `scripts/validate.py` injected.

Two validation steps run first and fail the build if a `SKILL.md`'s frontmatter
`name:` doesn't match its directory name, `description:`/`version:` is missing,
or any `io/*.schema.json` isn't a well-formed JSON Schema document — the same
shape check a skill needs to pass before anything downstream (a real pipeline,
or a Claude skill loader) can use it.

## Downloading

From the Actions run page, or via the CLI:

```
gh run download <run-id> -n oah-skills-bundle
gh run download <run-id> -n oah-skills-individual
```

Artifacts expire after 30 days — re-run the workflow if you need a fresh copy.
For a link that doesn't expire, use a release instead (below).

## Durable, versioned publish (releases)

`bundle-skills.yml`'s artifacts are workflow-run-scoped and expire in 30 days —
fine for iterating, not for pointing someone at a stable link. **Release skills
bundle** (`.github/workflows/release-skills.yml`) builds the same bundle and
attaches it to a [GitHub Release](https://github.com/arno49/observability-agentic-harness/releases)
instead, which doesn't expire.

Two ways to cut one:

1. Push a tag matching `skills-*` yourself: `git tag skills-my-label && git push
   origin skills-my-label`.
2. Actions tab → **Release skills bundle** → Run workflow. Auto-generates a
   `skills-<UTC YYYYMMDDHHMM>` tag off the current commit and releases under it
   — no local tagging needed.

The bundle itself has no single meaningful semver — it's a snapshot of however
many independently-versioned skills exist (right now, one). Each skill's own
`version:` in its `SKILL.md` frontmatter stays the real, authoritative version
(what a real pipeline run would pin to, per [SKILLS.md](SKILLS.md)); the release
tag is only a monotonic pointer to a snapshot in time. Every release's notes and
its `MANIFEST.txt` asset list every bundled skill's name and version explicitly,
so the two never get conflated.

This intentionally does **not** use GitHub Packages: Packages is built for
package-manager artifacts (npm, container images, Maven, NuGet) and a
markdown+JSON bundle doesn't natively fit any of those short of wrapping it as
an OCI artifact pushed to ghcr.io — heavier tooling for less discoverability
than a release asset a human can just click.

## Loading a skill into Claude

**Claude Code** (project- or personal-scoped skills, `.claude/skills/<name>/`):
unzip `oah-skills-bundle.zip` and copy the `skills/` folder's contents into
`.claude/skills/` in whatever repository you want to try the skill against (a
corpus fixture, a real target repo) — or into `~/.claude/skills/` to make it
available everywhere. Claude Code discovers skills from that directory
automatically; no restart or registration step.

**claude.ai / API Skills capability**: use the individual per-skill zips —
current tooling expects one skill per upload. Upload `s1-surface-mapper.zip`
(etc.) through the Skills section of your account/workspace settings, or via the
Skills endpoint if you're driving this from the API. Check Anthropic's current
Skills documentation if the upload flow has moved since this was written — the
zip's shape (a folder with `SKILL.md` at its root) is what has to stay stable,
not the exact menu path.

Either way, remember what you're loading: a **draft**, not a pipeline stage with
schema-validated I/O enforced by code outside its control.

## What a skill can validate about itself

A skill with `io/` schemas (so far: `s1-surface-mapper`) carries its own
`scripts/validate.py` — a small `jsonschema`-based CLI injected at bundle time
from `skills/_shared/validate.py` — and its own `SKILL.md` instructs it to run
`python3 scripts/validate.py io/output.schema.json output.json` on its own
output before returning anything. In an environment with shell access (Claude
Code) that's a real, working check: run it once by hand
(`pip install jsonschema` if it's not already available) and the skill will keep
enforcing it on itself for the rest of the session.

What this is *not*: a pipeline shell that validates at every stage boundary
whether or not the LLM cooperates. The self-check lives in the skill's own
instructions — nothing stops a session from skipping it, the way nothing stops
a person from skipping a step in a checklist they wrote for themselves. That
guarantee only exists once the real pipeline shell (Epic E1) validates a
skill's outputs from outside, in code the skill can't opt out of. Until then,
treat a hand-run session's output as a way to sanity-check the skill's
instructions and its schemas — including whether the schemas themselves are
even the right shape — not as a substitute for the real eval suite (Epic E7).

## Adding a skill so it gets picked up

Nothing to register. Add `skills/<stage>-<name>/SKILL.md` with `name`, `version`,
and `description` in its frontmatter — `name` must equal the directory name — and
the next push (or manual run) bundles it automatically.
