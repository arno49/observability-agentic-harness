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
 * SP12 (docs/decisions/013-sp12-ts-detector-shapes.md) added two more
 * detection passes over the same AST, alongside the original receiver/
 * method-suffix pass: declarative route registration (JSX <Route> elements
 * and createBrowserRouter/createHashRouter route-object arrays) and a
 * global unimported callee (bare `fetch(...)`, which the import-anchored
 * resolution model below cannot see at all on its own). Every candidate now
 * carries a `shape` field naming which pass produced it, so eval.py can
 * report recall/FP per shape instead of one pooled number.
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

  // Pass 3: call sites (receiver + method-suffix shape).
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
            shape: "receiver_method_suffix",
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
            shape: "receiver_method_suffix",
            reason: `receiver '${root || "<unresolved receiver expression>"}' type unresolved in this file -> needs LLM disambiguation`,
          });
        }
      }
    }
    ts.forEachChild(node, visitCalls);
  });

  // Pass 4 (SP12): declarative route registration -- JSX <Route path="..."/>
  // elements, and route-object arrays passed to createBrowserRouter/
  // createHashRouter. Neither is a call on a tracked receiver nor a
  // decorator, so this is a structurally different shape from Pass 3 --
  // docs/decisions/011's own finding that a consumer's business journeys
  // ARE its routes is what makes this the shape that matters most.
  function stringLiteralValue(node) {
    if (!node) return null;
    if (ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node)) return node.text;
    return null;
  }

  // A real finding from this pass's own first smoke test, not from the
  // sourced corpus fixture: React Router (and most JS routers) encode a
  // path PARAMETER inside the string literal itself (":id" in
  // "/property/:id"), not as a separate JS expression -- so "is this
  // syntactically a string literal" does NOT distinguish a fully static
  // route from a parameterized one the way this pass's confidence field
  // alone would suggest. Checked separately, surfaced as its own field
  // (has_path_parameter) rather than silently folded into "high
  // confidence" -- this is exactly the low-cardinality-route information
  // a future route_is_templated/cardinality_guard gate needs.
  const PATH_PARAMETER_PATTERN = /:[A-Za-z_$][A-Za-z0-9_$]*|\*/;
  function hasPathParameter(literal) {
    return literal !== null && PATH_PARAMETER_PATTERN.test(literal);
  }

  ts.forEachChild(sourceFile, function visitDeclarativeRoutes(node) {
    // JSX form: <Route path="..." .../> or <Route path="...">...</Route>.
    const isJsxRoute =
      (ts.isJsxSelfClosingElement(node) || ts.isJsxOpeningElement(node)) &&
      ts.isIdentifier(node.tagName) &&
      node.tagName.text === "Route";
    if (isJsxRoute) {
      const pathAttr = node.attributes.properties.find(
        (p) => ts.isJsxAttribute(p) && ts.isIdentifier(p.name) && p.name.text === "path"
      );
      const { line } = sourceFile.getLineAndCharacterOfPosition(node.getStart());
      if (pathAttr) {
        const initializer = pathAttr.initializer;
        const literal =
          initializer && ts.isStringLiteral(initializer)
            ? initializer.text
            : initializer && ts.isJsxExpression(initializer)
            ? stringLiteralValue(initializer.expression)
            : null;
        candidates.push({
          file: filePath,
          line: line + 1,
          confidence: literal !== null ? "high" : "low",
          resolved_sdk: null,
          chain: literal !== null ? `<Route path="${literal}">` : "<Route path={<dynamic expression>}>",
          language: "typescript",
          shape: "declarative_registration",
          has_path_parameter: hasPathParameter(literal),
          reason:
            literal !== null
              ? `JSX <Route> element with a static path literal${hasPathParameter(literal) ? " containing a path parameter" : ""}`
              : `JSX <Route> element with a non-literal (dynamic) path expression -- template not statically recoverable`,
        });
      }
    }
    ts.forEachChild(node, visitDeclarativeRoutes);
  });

  // Route-object array form: createBrowserRouter([{path: "...", ...}, ...])
  // (or createHashRouter, createMemoryRouter -- same array-of-objects shape).
  const ROUTER_FACTORY_NAMES = new Set(["createBrowserRouter", "createHashRouter", "createMemoryRouter"]);
  ts.forEachChild(sourceFile, function visitRouterFactoryCalls(node) {
    if (
      ts.isCallExpression(node) &&
      ts.isIdentifier(node.expression) &&
      ROUTER_FACTORY_NAMES.has(node.expression.text) &&
      node.arguments.length > 0 &&
      ts.isArrayLiteralExpression(node.arguments[0])
    ) {
      for (const element of node.arguments[0].elements) {
        if (!ts.isObjectLiteralExpression(element)) continue;
        const pathProp = element.properties.find(
          (p) =>
            ts.isPropertyAssignment(p) &&
            ((ts.isIdentifier(p.name) && p.name.text === "path") ||
              (ts.isStringLiteral(p.name) && p.name.text === "path"))
        );
        if (!pathProp) continue;
        const literal = stringLiteralValue(pathProp.initializer);
        const { line } = sourceFile.getLineAndCharacterOfPosition(pathProp.getStart());
        candidates.push({
          file: filePath,
          line: line + 1,
          confidence: literal !== null ? "high" : "low",
          resolved_sdk: null,
          chain: literal !== null ? `${node.expression.text}([{path: "${literal}"}])` : `${node.expression.text}([{path: <dynamic>}])`,
          language: "typescript",
          shape: "declarative_registration",
          has_path_parameter: hasPathParameter(literal),
          reason:
            literal !== null
              ? `${node.expression.text} route-object array entry with a static path literal${hasPathParameter(literal) ? " containing a path parameter" : ""}`
              : `${node.expression.text} route-object array entry with a non-literal (dynamic) path -- template not statically recoverable`,
        });
      }
    }
    ts.forEachChild(node, visitRouterFactoryCalls);
  });

  // Pass 5 (SP12): global unimported callee -- bare `fetch(...)`, which has
  // no import to anchor on at all, unlike every Pass-3 receiver. A file
  // that locally binds its own name `fetch` (import, variable, or
  // parameter, anywhere in the file -- same file-wide-not-function-scoped
  // tracking this adapter already uses, per Pass 2's own docstring) is
  // conservatively excluded: a shadowed/wrapped fetch is a real, different
  // case this pass doesn't try to resolve, not the true global.
  // Module-level shadow (`import { fetch } from "some-polyfill"`) is
  // genuinely file-wide -- every call site in the file resolves against
  // that import, not the true global. A function PARAMETER or local
  // variable named `fetch`, though, only shadows calls inside its own
  // enclosing scope -- treating that as file-wide too (an earlier version
  // of this pass did) is a real recall bug: a file with one unrelated
  // `function wrap(fetch) {...}` utility would silently suppress every
  // genuine global fetch() call elsewhere in the same file. So only the
  // import case is checked file-wide; parameter/variable shadowing is
  // checked per call site by walking up the real parent chain
  // (setParentNodes: true above makes `.parent` available).
  let fetchImportedLocally = false;
  ts.forEachChild(sourceFile, function scanForFetchImport(node) {
    if (ts.isImportSpecifier(node) && (node.propertyName || node.name).text === "fetch") {
      fetchImportedLocally = true;
    }
    ts.forEachChild(node, scanForFetchImport);
  });

  const FUNCTION_LIKE_KINDS = new Set([
    ts.SyntaxKind.FunctionDeclaration,
    ts.SyntaxKind.FunctionExpression,
    ts.SyntaxKind.ArrowFunction,
    ts.SyntaxKind.MethodDeclaration,
  ]);

  function isShadowedInEnclosingScope(callNode) {
    let current = callNode.parent;
    while (current) {
      if (FUNCTION_LIKE_KINDS.has(current.kind) && current.parameters) {
        const shadowsHere = current.parameters.some(
          (p) => ts.isIdentifier(p.name) && p.name.text === "fetch"
        );
        if (shadowsHere) return true;
      }
      // Local `const fetch = ...`/`let fetch = ...` anywhere in an
      // enclosing block also shadows -- checked one level (the direct
      // statement list of each enclosing block), not full nested-scope
      // resolution; a real, named limitation (see decision record), not a
      // silent gap.
      if (ts.isBlock(current) || ts.isSourceFile(current)) {
        const shadowsHere = current.statements.some(
          (s) =>
            ts.isVariableStatement(s) &&
            s.declarationList.declarations.some(
              (d) => ts.isIdentifier(d.name) && d.name.text === "fetch"
            )
        );
        if (shadowsHere) return true;
      }
      current = current.parent;
    }
    return false;
  }

  if (!fetchImportedLocally) {
    ts.forEachChild(sourceFile, function visitGlobalFetchCalls(node) {
      if (ts.isCallExpression(node) && ts.isIdentifier(node.expression) && node.expression.text === "fetch") {
        if (!isShadowedInEnclosingScope(node)) {
          const { line } = sourceFile.getLineAndCharacterOfPosition(node.getStart());
          candidates.push({
            file: filePath,
            line: line + 1,
            confidence: "high",
            resolved_sdk: null,
            chain: "fetch(...)",
            language: "typescript",
            shape: "global_unimported_callee",
            reason: "bare global fetch() call, unshadowed in its enclosing scope -- no receiver to resolve, unambiguous by construction",
          });
        }
      }
      ts.forEachChild(node, visitGlobalFetchCalls);
    });
  }

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
