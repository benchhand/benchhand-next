// SPDX-FileCopyrightText: 2026 Sjors Robroek
//
// SPDX-License-Identifier: MPL-2.0

// The ADR index and the contracts index, written by sync-docs.mjs in place of the synced READMEs.
// Both are tables built from their sources, so they can't drift from them:
// - the ADR index reads each docs/adr/NNNN-*.md H1 and its "Status:" line;
// - the contracts index reads each published schema's title and x-version, and links the
//   contract's reference page, its domain-model page and the served schema.
import { existsSync, readdirSync, readFileSync } from "node:fs";
import path from "node:path";

import { repoRoot, repoUrl } from "../site-url.mjs";

const ADR_DIR = "docs/adr";
const CONTRACT_PAGES = "docs/contract/generated";

// Markdown table cells can't hold a pipe or a line break.
const cell = (text) => text.replace(/\|/g, "\\|").replace(/\s+/g, " ").trim();

// "[text](url)" → "text".
const unlink = (markdown) => markdown.replace(/\[([^\]]*)\]\([^)]*\)/g, "$1");

/**
 * The short status of an ADR from its "Status:" line: the status word and any qualifier before the
 * first sentence or clause break, such as "accepted, narrowed by ADR-0018". undefined without a line.
 * @param {string} markdown
 */
export function adrStatus(markdown) {
  const line = markdown.match(/^Status:\s*(.+)$/m)?.[1];
  if (line === undefined) return undefined;
  const text = unlink(line);
  const end = text.search(/[.:]\s|[.:]$|\s\(/);
  return (end < 0 ? text : text.slice(0, end)).trim();
}

function adrRoute(file) {
  return `/adr/${file.replace(/\.md$/, "")}/`;
}

/** The ADR index page: number, title and status of every ADR, in number order. */
export function adrIndexPage() {
  const files = readdirSync(path.join(repoRoot, ADR_DIR))
    .filter((file) => /^\d{4}-.*\.md$/.test(file))
    .sort();
  const routeByNumber = new Map(files.map((file) => [file.slice(0, 4), adrRoute(file)]));
  const linkAdrs = (text) =>
    text.replace(/ADR-(\d{4})/g, (match, number) => (routeByNumber.has(number) ? `[${match}](${routeByNumber.get(number)})` : match));

  const rows = files.map((file) => {
    const markdown = readFileSync(path.join(repoRoot, ADR_DIR, file), "utf8");
    const heading = markdown.match(/^# ADR-(\d{4}):\s*(.+)$/m);
    if (!heading) throw new Error(`${ADR_DIR}/${file} has no "# ADR-NNNN: title" heading`);
    const [, number, title] = heading;
    if (number !== file.slice(0, 4)) throw new Error(`${ADR_DIR}/${file} is titled ADR-${number}`);
    const status = adrStatus(markdown);
    if (status === undefined) console.warn(`warning: ${ADR_DIR}/${file} has no "Status:" line; the ADR index shows "—"`);
    return `| ${number} | [${cell(title)}](${adrRoute(file)}) | ${status === undefined ? "—" : linkAdrs(cell(status))} |`;
  });

  return [
    "---",
    'title: "Architecture decision records"',
    "description: Every architecture decision record, with its number, title and status.",
    "editUrl: false",
    "sidebar:",
    "  label: Index",
    "  order: 0",
    "---",
    "",
    `Each record states one decision, its context and its consequences. The table is built from the records in [\`${ADR_DIR}\`](${repoUrl}/tree/main/${ADR_DIR}), and the status is the start of each record's "Status:" line.`,
    "",
    "| No. | Decision | Status |",
    "|---|---|---|",
    ...rows,
    "",
  ].join("\n");
}

// The areas of the contracts, in reading order. A schema directory missing here fails the sync.
const AREAS = [
  { dir: "record", title: "Record documents", intro: "The files of a project's `hw/` record, and the definitions they share." },
  { dir: "provider", title: "Provider", intro: "The provider manifest and the JSON-RPC protocol between benchhand and a provider." },
  { dir: "jobs", title: "Jobs", intro: "A unit of work that benchhand runs on a provider." },
  { dir: "common", title: "Common", intro: "Shapes that every area uses." },
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
