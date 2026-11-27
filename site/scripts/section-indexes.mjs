// SPDX-FileCopyrightText: 2026 Sjors Robroek
//
// SPDX-License-Identifier: MPL-2.0

// The contracts index, written by sync-docs.mjs in place of the synced README. It is a table built
// from its sources, so it can't drift from them: it reads each published schema's title and
// x-version, and links the contract's reference page, its domain-model page and the served schema.
import { existsSync, readdirSync, readFileSync } from "node:fs";
import path from "node:path";

import { repoRoot, repoUrl } from "../site-url.mjs";

const CONTRACT_PAGES = "docs/contract/generated";

// Markdown table cells can't hold a pipe or a line break. A schema title's `<` is escaped, so a placeholder
// such as the `<PN>` of `hw/parts/<PN>/part.yaml` is not read as an HTML tag (tools/gen markdown_prose).
const cell = (text) =>
  text
    .replace(/\|/g, "\\|")
    .replace(/<(?=[A-Za-z/!?])/g, "\\<")
    .replace(/\s+/g, " ")
    .trim();

// The areas of the contracts, in reading order. A schema directory missing here fails the sync.
const AREAS = [
  { dir: "record", title: "Record documents", intro: "The files of a project's `hw/` record, and the definitions they share." },
  { dir: "envelope", title: "Tool result envelope", intro: "The result that every benchhand MCP tool call returns." },
  { dir: "flow", title: "Flow", intro: "The flow definition, `flow.yaml`, and the rule-list files it references. Every condition in them is a CEL expression." },
  { dir: "policy", title: "Policy", intro: "What a policy provider contributes to the flow: rule lists and gate requirements." },
  { dir: "provider", title: "Provider", intro: "The provider manifest and the JSON-RPC protocol between benchhand and a provider." },
  { dir: "jobs", title: "Jobs", intro: "A unit of work that benchhand runs on a provider." },
  { dir: "common", title: "Common", intro: "Shapes that every area uses, including the CEL expression types." },
];

/**
 * The contracts index page, grouped by area. Each row links the contract's reference page, its
 * domain-model page and its served schema, with the schema's x-version.
 * @param {string} schemasSource repo-relative directory of the published schemas
 */
export function contractsIndexPage(schemasSource) {
  const schemaFiles = readdirSync(path.join(repoRoot, schemasSource), { recursive: true })
    .map((file) => file.split(path.sep).join("/"))
    .filter((file) => file.endsWith(".schema.json"))
    .sort();
  const known = new Set(AREAS.map((area) => area.dir));
  for (const file of schemaFiles) {
    if (!known.has(path.posix.dirname(file))) throw new Error(`${schemasSource}/${file}: its area has no entry in AREAS (section-indexes.mjs)`);
  }

  const sections = AREAS.flatMap(({ dir, title, intro }) => {
    const files = schemaFiles.filter((file) => path.posix.dirname(file) === dir);
    if (files.length === 0) return [];
    const rows = files.map((file) => contractRow(schemasSource, file));
    return [`## ${title}`, "", intro, "", "| Contract | Version | Domain model | Schema |", "|---|---|---|---|", ...rows, ""];
  });

  return [
    "---",
    'title: "Contracts"',
    "description: Every benchhand contract, grouped by area, with its version, domain-model page and JSON Schema.",
    "editUrl: false",
    "sidebar:",
    "  label: Overview",
    "  order: 0",
    "---",
    "",
    `The contracts define every record, job, finding and provider-protocol shape once, in TypeSpec under [\`contracts/\`](${repoUrl}/tree/main/contracts) (ADR-0017). \`just contracts\` generates the JSON Schemas, the Python models, the TypeScript types and these pages from them.`,
    "",
    "Each row links the contract's field reference, its page in the [domain model](/reference/contracts/domain-model/), and the JSON Schema that this site serves. [JSON Schemas](/reference/contracts/schemas/) lists every schema with its `$id`, and [versioning](/reference/contracts/versioning/) says when a version changes.",
    "",
    ...sections,
  ].join("\n");
}

function contractRow(schemasSource, file) {
  const schema = JSON.parse(readFileSync(path.join(repoRoot, schemasSource, file), "utf8"));
  const name = file.replace(/\.schema\.json$/, "");
  const page = `${CONTRACT_PAGES}/${name}.md`;
  if (!existsSync(path.join(repoRoot, page))) throw new Error(`${schemasSource}/${file} has no reference page ${page}`);
  const modelPage = `${CONTRACT_PAGES}/domain-model/${name}.md`;
  const model = existsSync(path.join(repoRoot, modelPage)) ? `[diagram and fields](/reference/contracts/domain-model/${name}/)` : "—";
  const version = schema["x-version"] ? `\`${schema["x-version"]}\`` : "—";
  return `| [${cell(schema.title ?? name)}](/reference/contracts/${name}/) | ${version} | ${model} | [\`${path.posix.basename(file)}\`](/contracts/${file}) |`;
}
