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
  each containing that skill's folder as-is (`SKILL.md` plus any `references/`,
  `examples/`, `io/` it has).
- **`oah-skills-bundle`** — `oah-skills-bundle.zip`, all skills together under a
  single `skills/` folder.

A validation step runs first and fails the build if a `SKILL.md`'s frontmatter
`name:` doesn't match its directory name, or `description:`/`version:` is missing
— the same shape check a skill needs to pass before anything downstream (a real
pipeline, or a Claude skill loader) can use it.

## Downloading

From the Actions run page, or via the CLI:

```
gh run download <run-id> -n oah-skills-bundle
gh run download <run-id> -n oah-skills-individual
```

Artifacts expire after 30 days — re-run the workflow if you need a fresh copy.

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
schema-validated I/O enforced around it. `io/input.schema.json` and
`io/output.schema.json` (see [SKILLS.md](SKILLS.md)) are what the real harness
will validate against once S1–S11 exist; a hand-run session in Claude Code or
claude.ai enforces none of that, so treat its output as a way to sanity-check the
skill's instructions, not as a substitute for the real eval suite (Epic E7).

## Adding a skill so it gets picked up

Nothing to register. Add `skills/<stage>-<name>/SKILL.md` with `name`, `version`,
and `description` in its frontmatter — `name` must equal the directory name — and
the next push (or manual run) bundles it automatically.
