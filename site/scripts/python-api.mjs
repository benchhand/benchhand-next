// SPDX-FileCopyrightText: 2026 Sjors Robroek
//
// SPDX-License-Identifier: MPL-2.0

// Render the Python API of benchhand-contracts to MDX, from griffe's static JSON dump.
//
// griffe (pinned below, run through uvx) reads the source without importing it. This renderer
// covers what benchhand-contracts exposes today, and no more:
// - only the public names (publicNames below), each resolved through its alias to its definition,
//   and shown under its exported name;
// - functions and classes; a class lists its public attributes and methods, and __init__;
// - docstrings are the repository's style: reStructuredText-flavoured text, with ``code`` and
//   :role:`name` turned into code spans. Sections (Args, Returns, Raises) are not parsed;
// - annotations and defaults are printed from griffe's expression tree; an expression kind
//   this file doesn't know fails the render, so a new kind can't print wrongly.
// The generated models under benchhand_contracts.models are not rendered: the contract
// reference documents those shapes.
import { execFileSync } from "node:child_process";
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

import { repoRoot, repoUrl } from "../site-url.mjs";

const GRIFFE = "griffe==2.4.1";
const PACKAGE = { distribution: "benchhand-contracts", module: "benchhand_contracts", src: "packages/benchhand-contracts/src" };

const siteRoot = fileURLToPath(new URL("..", import.meta.url));
const outDir = path.join(siteRoot, "src/content/docs/reference/python-api");

function dump() {
  const dir = mkdtempSync(path.join(tmpdir(), "griffe-"));
  try {
    const out = path.join(dir, "dump.json");
    const args = ["--from", GRIFFE, "griffe", "dump", PACKAGE.module, "-s", path.join(repoRoot, PACKAGE.src), "-r", "-o", out];
    execFileSync("uvx", args, { stdio: ["ignore", "ignore", "inherit"] });
    return JSON.parse(readFileSync(out, "utf8"))[PACKAGE.module];
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
}

// The one definition of "public" for the Python API pages: a module's `__all__` where it has one,
// otherwise each function and class it defines whose name has no leading underscore. Without
// `__all__`, an import, a submodule or a module attribute is not public. A class's public members
// follow the same underscore rule, and also include `__init__`.
export function publicNames(module) {
  if (module.exports) return module.exports;
  return Object.entries(module.members ?? {})
    .filter(([name, member]) => !name.startsWith("_") && (member.kind === "function" || member.kind === "class"))
    .map(([name]) => name);
}

const EXPRESSIONS = {
  ExprName: (e) => e.name,
  ExprAttribute: (e) => e.values.map(expr).join("."),
  ExprSubscript: (e) => `${expr(e.left)}[${expr(e.slice)}]`,
  ExprTuple: (e) => e.elements.map(expr).join(", "),
  ExprList: (e) => `[${e.elements.map(expr).join(", ")}]`,
  ExprBinOp: (e) => `${expr(e.left)} ${e.operator} ${expr(e.right)}`,
  ExprUnaryOp: (e) => `${e.operator}${expr(e.value)}`,
  ExprKeyword: (e) => `${e.name}=${expr(e.value)}`,
  ExprCall: (e) => `${expr(e.function)}(${e.arguments.map(expr).join(", ")})`,
  ExprDict: (e) => `{${e.keys.map((k, i) => `${expr(k)}: ${expr(e.values[i])}`).join(", ")}}`,
};

function expr(e) {
  if (e === null || e === undefined) return "";
  if (typeof e === "string") return e;
  const render = EXPRESSIONS[e.cls];
  if (!render) throw new Error(`python-api: no renderer for griffe expression ${e.cls}`);
  return render(e);
}

// Find an object by its dotted path, following aliases to their target.
function lookup(root, dotted) {
  const [head, ...rest] = dotted.split(".");
  if (head !== root.name) throw new Error(`python-api: ${dotted} is outside ${root.name}`);
  let node = root;
  let module = root;
  for (const name of rest) {
    node = node.members?.[name];
    if (!node) throw new Error(`python-api: ${dotted} not found`);
    if (node.kind === "module") module = node;
    if (node.kind === "alias") return lookup(root, node.target_path);
  }
  return { node, module, target: dotted };
}

// Escape MDX outside code spans, and turn reST ``code`` and :role:`name` into code spans.
function prose(text) {
  const md = text.replace(/:[a-z]+:`([^`]+)`/g, "``$1``").replace(/``([^`]+)``/g, "`$1`");
  return md
    .split(/(`[^`]*`)/)
    .map((part, i) => (i % 2 ? part : part.replace(/[{}<>]/g, (c) => `\\${c}`)))
    .join("");
}

function signature(fn, name) {
  const params = fn.parameters.map((p) => {
    const prefix = p.kind === "variadic positional" ? "*" : p.kind === "variadic keyword" ? "**" : "";
    const annotation = p.annotation ? `: ${expr(p.annotation)}` : "";
    const fallback = p.default !== null ? `${annotation ? " = " : "="}${expr(p.default)}` : "";
    return `${prefix}${p.name}${annotation}${fallback}`;
  });
  const returns = fn.returns ? ` -> ${expr(fn.returns)}` : "";
  return `def ${name}(${params.join(", ")})${returns}`;
}

function sourceLink(module, node) {
  const file = path.relative(repoRoot, module.filepath).split(path.sep).join("/");
  return `[Source](${repoUrl}/blob/main/${file}#L${node.lineno}-L${node.endlineno})`;
}

function docstring(node) {
  return node.docstring ? [prose(node.docstring.value), ""] : [];
}

function renderFunction(name, node, module) {
  return [`## \`${name}\``, "", "```python", signature(node, name), "```", "", ...docstring(node), sourceLink(module, node), ""];
}

function renderMember(name, member) {
  if (member.kind === "function") {
    const params = { ...member, parameters: member.parameters.filter((p) => p.name !== "self") };
    return [`- \`${signature(params, name).replace(/^def /, "")}\``];
  }
  const annotation = member.annotation ? `: ${expr(member.annotation)}` : "";
  const summary = member.docstring ? ` ${prose(member.docstring.value.split("\n\n")[0].replace(/\s*\n\s*/g, " "))}` : "";
  return [`- \`${name}${annotation}\`${summary}`];
}

function renderClass(name, node, module) {
  const bases = node.bases.map(expr).join(", ");
  const members = Object.entries(node.members ?? {}).filter(([n]) => n === "__init__" || !n.startsWith("_"));
  return [
    `## \`${name}\``,
    "",
    "```python",
    `class ${name}${bases ? `(${bases})` : ""}`,
    "```",
    "",
    ...docstring(node),
    ...(members.length ? ["Members:", "", ...members.flatMap(([n, m]) => renderMember(n, m)), ""] : []),
    sourceLink(module, node),
    "",
  ];
}

function renderPackage(root) {
  const lines = [
    "---",
    `title: ${PACKAGE.distribution}`,
    `description: The public API of ${PACKAGE.distribution}, generated from its source.`,
    "editUrl: false",
    "sidebar:",
    "  order: 1",
    "---",
    "",
    `Generated by \`site/scripts/python-api.mjs\` from \`${PACKAGE.src}\` with ${GRIFFE}. Do not edit.`,
    "",
    ...docstring(root),
  ];
  for (const name of publicNames(root)) {
    const { node, module } = lookup(root, `${root.name}.${name}`);
    let section;
    if (node.kind === "function") section = renderFunction(name, node, module);
    else if (node.kind === "class") section = renderClass(name, node, module);
    else throw new Error(`python-api: ${name} is a ${node.kind}; only functions and classes are rendered`);
    lines.push(...section);
  }
  return lines.join("\n");
}

const PROVIDER_PAGE = "benchhand-provider";

const INDEX = `---
title: Python API
description: The public Python API of the benchhand packages, generated from their source.
editUrl: false
sidebar:
  label: Overview
  order: 0
---

Generated by \`site/scripts/python-api.mjs\` with ${GRIFFE}, which reads the source without importing it.

- [${PACKAGE.distribution}](/reference/python-api/${PACKAGE.distribution}/)
- [${PROVIDER_PAGE}](/reference/python-api/${PROVIDER_PAGE}/), the provider runtime

## What is public

These pages document the public API only. A name is public when the module's \`__all__\` lists it.
A module without \`__all__\` has the functions and classes it defines whose names have no leading underscore.
A class shows its public members and \`__init__\`.

## Docstring style

The renderer expects the repository's docstring style: reStructuredText-flavoured text.
It reads paragraphs and bullet lists, turns \`\`code\`\` and :role:\`name\` into code spans, and shows the rest as written.
It doesn't parse Args, Returns or Raises sections, so write the parameters and results into the prose.
Adopting Google or NumPy sections means extending \`site/scripts/python-api.mjs\` first.
`;

function main() {
  const root = dump();
  mkdirSync(outDir, { recursive: true });
  const page = path.join(outDir, `${PACKAGE.distribution}.mdx`);
  rmSync(page, { force: true });
  writeFileSync(page, renderPackage(root));
  writeFileSync(path.join(outDir, "index.md"), INDEX);
  console.log(`rendered ${publicNames(root).length} names of ${PACKAGE.module} to reference/python-api/`);
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) main();
