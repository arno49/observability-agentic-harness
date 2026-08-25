#!/usr/bin/env python3
"""SP10 evidence, not a third implementation: confirms tree-sitter can parse
both Python and TypeScript through one pure-Python API (pip install
tree-sitter tree-sitter-python tree-sitter-typescript — no Node.js runtime
required), and shows concretely what does and doesn't unify: the parsing API
is shared, but the AST node type names are not (Python: call/attribute; TS:
call_expression/member_expression). See the decision record's tree-sitter
finding for what this does and doesn't establish — this script is the
evidence, not a competing detector to ts-adapter/detect.py.
"""
import tree_sitter_python as tspython
import tree_sitter_typescript as tstypescript
from tree_sitter import Language, Parser

PY_SRC = b"""
import anthropic
client = anthropic.Anthropic()
response = client.messages.create(model="x")
"""

TS_SRC = b"""
import Anthropic from "@anthropic-ai/sdk";
const client = new Anthropic();
const response = await client.messages.create({model: "x"});
"""

# The parsing API is identical for both languages -- this part IS unified.
GRAMMARS = {
    "python": (Language(tspython.language()), PY_SRC, {"call", "attribute"}),
    "typescript": (Language(tstypescript.language_typescript()), TS_SRC, {"call_expression", "member_expression"}),
}


def walk(node, interesting_types, depth=0):
    if node.type in interesting_types:
        print("  " * depth, node.type, node.text.decode()[:60])
    for child in node.children:
        walk(child, interesting_types, depth + 1)


if __name__ == "__main__":
    for name, (language, src, interesting_types) in GRAMMARS.items():
        parser = Parser(language)
        tree = parser.parse(src)
        print(f"=== {name} (node type names: {sorted(interesting_types)}) ===")
        walk(tree.root_node, interesting_types)
