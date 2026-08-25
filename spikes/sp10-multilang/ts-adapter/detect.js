#!/usr/bin/env node
/**
 * TypeScript/Node adapter for the SP10 multi-language prototype.
 *
 * Mirrors spikes/sp1-surface-mapping/detect.py's design one-to-one (see that
 * file's docstring for the reasoning) but using the TypeScript compiler API
 * as the native per-language parser, per SP10's "native parser behind a
 * common adapter interface" option. Emits the SAME candidate JSON shape as
 * the Python adapter (see registry.py in this directory for the shared
 * suffix list) so the orchestrator in eval.py can consume both without
 * caring which language produced a given line.
 *
 * Usage: node detect.js <file_or_directory> [...]
 */
const fs = require("fs");
const path = require("path");
const ts = require("typescript");

const SDK_MODULE = "@anthropic-ai/sdk";
const METHOD_SUFFIXES = new Set([
  JSON.stringify(["messages", "create"]),
  JSON.stringify(["messages", "stream"]),
]);

function suffixMatches(chain) {
  if (chain.length < 2) return false;
  return METHOD_SUFFIXES.has(JSON.stringify(chain.slice(-2)));
}

/** Flatten a PropertyAccessExpression chain: a.b.c -> {root, chain: ["b","c"]} */
function flattenChain(node) {
  const parts = [];
  while (ts.isPropertyAccessExpression(node)) {
    parts.unshift(node.name.text);
    node = node.expression;
  }
  if (ts.isIdentifier(node)) {
    return { root: node.text, chain: parts };
  }
  if (node.kind === ts.SyntaxKind.ThisKeyword) {
    return { root: "this", chain: parts };
  }
  return { root: null, chain: parts };
}

/** Resolve a type annotation node to true if it names the SDK's default
 * export type (handles `Anthropic`, `Anthropic | null`, `Anthropic | undefined`). */
function annotationMatchesSdk(typeNode, importedLocalNames) {
  if (!typeNode) return false;
  if (ts.isUnionTypeNode(typeNode)) {
    return typeNode.types.some((t) => annotationMatchesSdk(t, importedLocalNames));
  }
  if (ts.isTypeReferenceNode(typeNode) && ts.isIdentifier(typeNode.typeName)) {
    return importedLocalNames.has(typeNode.typeName.text);
  }
  return false;
}

function detectFile(filePath) {
  const source = fs.readFileSync(filePath, "utf8");
  const sourceFile = ts.createSourceFile(
    filePath,
    source,
    ts.ScriptTarget.Latest,
    true,
    filePath.endsWith(".tsx") ? ts.ScriptKind.TSX : ts.ScriptKind.TS
  );

  // Local names bound to the SDK's default export (import Anthropic from "@anthropic-ai/sdk").
  // File-scoped, not function-scoped: TS/JS closures and hoisting make a
  // per-function scope model less reliable than in Python, and the real
  // corpus needs this — see the decision record's wechatbot finding (a
  // module `let` assigned inside one function, read inside another).
  const importedLocalNames = new Set();
  // Names (module-level OR narrower) known to construct an SDK client,
  // found anywhere in the file via `X = new Anthropic(...)` — assignment
  // OR declaration-with-initializer, deliberately not scope-restricted for
  // the same reason as above.
  const knownClientNames = new Set();
  const candidates = [];

  function isSdkConstructorCall(expr) {
    // `new Anthropic(...)` where `Anthropic` is bound to the SDK's default import.
    if (!ts.isNewExpression(expr)) return false;
    return ts.isIdentifier(expr.expression) && importedLocalNames.has(expr.expression.text);
  }

  // Pass 1: imports.
  ts.forEachChild(sourceFile, function visitImports(node) {
    if (ts.isImportDeclaration(node) && ts.isStringLiteral(node.moduleSpecifier)) {
      if (node.moduleSpecifier.text === SDK_MODULE && node.importClause) {
        if (node.importClause.name) {
          importedLocalNames.add(node.importClause.name.text); // default import
        }
        const bindings = node.importClause.namedBindings;
        if (bindings && ts.isNamedImports(bindings)) {
          for (const el of bindings.elements) {
            const original = (el.propertyName || el.name).text;
            if (original === "default" || original === "Anthropic") {
              importedLocalNames.add(el.name.text);
            }
          }
        }
      }
    }
    ts.forEachChild(node, visitImports);
  });

  // Pass 2: known-client-name prescan (declarations + reassignments,
  // anywhere in the file) and type-annotation-based bindings.
  ts.forEachChild(sourceFile, function prescan(node) {
    if (ts.isVariableDeclaration(node)) {
      if (node.initializer && isSdkConstructorCall(node.initializer) && ts.isIdentifier(node.name)) {
        knownClientNames.add(node.name.text);
      }
      if (annotationMatchesSdk(node.type, importedLocalNames) && ts.isIdentifier(node.name)) {
        knownClientNames.add(node.name.text);
      }
    }
    if (
      ts.isBinaryExpression(node) &&
      node.operatorToken.kind === ts.SyntaxKind.EqualsToken &&
      ts.isIdentifier(node.left) &&
      isSdkConstructorCall(node.right)
    ) {
      knownClientNames.add(node.left.text);
    }
    // Class property: `client: Anthropic | null = null;` or `this.client = new Anthropic(...)`.
    if (ts.isPropertyDeclaration(node) && node.name && ts.isIdentifier(node.name)) {
      if (annotationMatchesSdk(node.type, importedLocalNames)) {
        knownClientNames.add(node.name.text);
      }
    }
    ts.forEachChild(node, prescan);
  });

  // Pass 3: call sites.
  ts.forEachChild(sourceFile, function visitCalls(node) {
    if (ts.isCallExpression(node) && ts.isPropertyAccessExpression(node.expression)) {
      const { root, chain } = flattenChain(node.expression);
      if (suffixMatches(chain)) {
        const receiverName = root === "this" ? chain[0] : root;
        const resolved = receiverName && knownClientNames.has(receiverName);
        const { line } = sourceFile.getLineAndCharacterOfPosition(node.getStart());
        const dotted = [root === "this" ? "this" : root || "<expr>", ...chain].join(".");
        if (resolved) {
          candidates.push({
            file: filePath,
            line: line + 1,
            confidence: "high",
            resolved_sdk: "anthropic",
            chain: dotted,
            language: "typescript",
            reason: `receiver '${receiverName}' resolved to anthropic via assignment/annotation tracking`,
          });
        } else {
          candidates.push({
            file: filePath,
            line: line + 1,
            confidence: "low",
            resolved_sdk: null,
            chain: dotted,
            language: "typescript",
            reason: `receiver '${root || "<unresolved receiver expression>"}' type unresolved in this file -> needs LLM disambiguation`,
          });
        }
      }
    }
    ts.forEachChild(node, visitCalls);
  });

  return candidates;
}

function walkDir(dir, out) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    if (entry.name === "node_modules" || entry.name === ".git" || entry.name === "dist") continue;
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      walkDir(full, out);
    } else if (/\.(ts|tsx)$/.test(entry.name) && !/\.test\.|\.spec\./.test(entry.name)) {
      out.push(full);
    }
  }
}

function detectPath(target) {
  const stat = fs.statSync(target);
  const files = [];
  if (stat.isDirectory()) {
    walkDir(target, files);
  } else {
    files.push(target);
  }
  const out = [];
  for (const f of files) {
    out.push(...detectFile(f));
  }
  return out;
}

if (require.main === module) {
  const targets = process.argv.slice(2);
  for (const t of targets) {
    for (const c of detectPath(t)) {
      console.log(JSON.stringify(c));
    }
  }
}

module.exports = { detectPath, detectFile };
