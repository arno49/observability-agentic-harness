# SP10 prototype — one adapter interface, two real languages

Spike prototype, not E2/E11's production implementation. Produced to answer
SP10 (`ROADMAP.md`): *what's the language-agnostic intermediate call-site
representation that lets S1 add a new language without touching pipeline
core, and does a unified tree-sitter parse layer beat native per-language
parsers behind a common adapter interface?* See
[`../../docs/decisions/004-sp10-multilang-architecture.md`](../../docs/decisions/004-sp10-multilang-architecture.md)
for the answer and its evidence. Builds directly on
[SP1's Python prototype](../sp1-surface-mapping/) — reused, not duplicated.

## Layout

- `orchestrate.py` — the common interface: one `detect(path, language)` call
  that dispatches to either adapter and returns the same candidate shape.
  This is the actual proof artifact — it doesn't know or care which language
  it's looking at.
- `ts-adapter/detect.js` — the TypeScript/Node adapter, using the TypeScript
  compiler API (native per-language parser) as SP10's first option. Requires
  `npm install` inside `ts-adapter/` (pinned to `typescript@5.7` — see the
  decision record's finding on why `^7` breaks this).
- `treesitter_feasibility_probe.py` — evidence for SP10's second option
  (unified tree-sitter layer), not a competing implementation: confirms a
  pure-Python, no-Node-runtime path is feasible and shows concretely what
  does and doesn't unify across grammars.
- `ground_truth/` — hand-labeled ground truth for three real TypeScript/Node
  repos, same not-vendored policy as SP1 (see `corpus_manifest.json`).
- `eval.py` — scores both languages through the same code path.

## Running it

```
python3 orchestrate.py <path-to-a-python-or-ts-repo>   # auto-detects language
python3 eval.py --python-corpus-dir <dir> --ts-corpus-dir <dir>
python3 treesitter_feasibility_probe.py                 # no corpus needed
```

`treesitter_feasibility_probe.py` needs
`pip install tree-sitter tree-sitter-python tree-sitter-typescript`
(not required for `orchestrate.py`/`eval.py`, which use the native adapters).
