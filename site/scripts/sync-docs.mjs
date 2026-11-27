// Copy the repository's narrative and generated docs, and the published JSON Schemas, into the
// site before `astro build`. The copies are gitignored: docs/ and the schemas stay the source.
//
// For each Markdown file it
// - moves the first H1 into the front matter title, and points editUrl at the source file;
// - rewrites each repo-relative link: to the site route when the target is a synced page, and to
//   the file on GitHub otherwise. A link to a file that doesn't exist fails the sync.
// Every rewrite is listed in .cache/link-rewrites.tsv.
import { cpSync, existsSync, mkdirSync, readdirSync, readFileSync, rmSync, statSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { fromMarkdown } from "mdast-util-from-markdown";
import { gfmFromMarkdown } from "mdast-util-gfm";
import { gfm } from "micromark-extension-gfm";
import { visit } from "unist-util-visit";

import { repoRoot, repoUrl, schemaIdPrefix } from "../site-url.mjs";

const siteRoot = fileURLToPath(new URL("..", import.meta.url));
const docsOut = path.join(siteRoot, "src/content/docs");
const schemasSource = "packages/benchhand-contracts/src/benchhand_contracts/schemas";

// Source directory (repo-relative) → destination directory (under src/content/docs).
// Each source's README.md becomes the destination's index page.
const MARKDOWN_SOURCES = [
  { from: "docs/architecture", to: "architecture", recursive: false },
  { from: "docs/adr", to: "adr", recursive: false },
  { from: "docs/contract", to: "reference/contracts", recursive: false },
  { from: "docs/contract/generated", to: "reference/contracts", recursive: true },
];

// Images copied next to the synced pages, so relative image links keep working.
const ASSET_EXTENSIONS = new Set([".svg", ".png"]);

// The gitignored outputs (site/.gitignore), cleared before each sync.
const OUTPUTS = ["src/content/docs/architecture", "src/content/docs/adr", "src/content/docs/reference/contracts", "public/contracts"];

// Rewritten to GitHub when the target is not a synced page. A link to a file that doesn't exist
// fails the sync: fix the source doc.

const toPosix = (p) => p.split(path.sep).join("/");

function listFiles(dir, recursive) {
  const out = [];
  for (const entry of readdirSync(path.join(repoRoot, dir), { withFileTypes: true })) {
    const rel = `${dir}/${entry.name}`;
    if (entry.isDirectory()) {
      if (recursive) out.push(...listFiles(rel, true));
    } else {
      out.push(rel);
    }
  }
  return out;
}

// Map every synced source file (repo-relative) to its destination (relative to src/content/docs).
function planCopies() {
  const pages = new Map();
  const assets = new Map();
  for (const { from, to, recursive } of MARKDOWN_SOURCES) {
    for (const file of listFiles(from, recursive)) {
      const rel = path.posix.relative(from, file);
      const ext = path.posix.extname(file);
      if (ext === ".md") {
        const dest = rel.replace(/(^|\/)README\.md$/, "$1index.md");
        addUnique(pages, file, `${to}/${dest}`);
      } else if (ASSET_EXTENSIONS.has(ext)) {
        addUnique(assets, file, `${to}/${rel}`);
      }
    }
  }
  return { pages, assets };
}

const destinations = new Set();
function addUnique(map, source, dest) {
  if (destinations.has(dest)) throw new Error(`two sources sync to ${dest}; the second is ${source}`);
  destinations.add(dest);
  map.set(source, dest);
}

// The site route of a destination page: "reference/contracts/record/part.md" → "/reference/contracts/record/part/".
function routeOf(dest) {
  return `/${dest.replace(/\.md$/, "").replace(/(^|\/)index$/, "")}/`.replace(/\/+/g, "/");
}

const isExternal = (url) => /^[a-z][a-z0-9+.-]*:/i.test(url) || url.startsWith("//");

// Decide where a link from `source` (repo-relative) to `url` should go. Returns the new URL, or
// undefined to keep it.
function rewriteUrl(url, source, kind, plan) {
  if (!url || isExternal(url) || url.startsWith("#") || url.startsWith("/")) return undefined;
  const match = url.match(/^([^?#]*)([?#].*)?$/);
  const [, target, suffix = ""] = match;
  const resolved = path.posix.normalize(path.posix.join(path.posix.dirname(source), decodeURI(target)));
  if (resolved.startsWith("../")) throw new Error(`${source}: link ${url} leaves the repository`);

  if (plan.pages.has(resolved)) return { rule: "synced page → site route", url: routeOf(plan.pages.get(resolved)) + suffix };
  if (kind === "image" && plan.assets.has(resolved)) return undefined;
  return githubTarget(resolved, suffix, kind, `${source}: link ${url}`);
}

// The GitHub URL of a repository file that the site doesn't serve.
function githubTarget(resolved, suffix, kind, context) {
  const absolute = path.join(repoRoot, resolved);
  const exists = existsSync(absolute);
  if (!exists) throw new Error(`${context} points to ${resolved}, which doesn't exist`);
  if (kind === "image") return { rule: "image outside the synced directories \u2192 GitHub raw", url: `${repoUrl}/raw/main/${resolved}${suffix}` };
  const isDir = statSync(absolute).isDirectory();
  const rule = "repo file \u2192 GitHub";
  return { rule, url: `${repoUrl}/${isDir ? "tree" : "blob"}/main/${resolved.replace(/\/$/, "")}${suffix}` };
}

// The [start, end) source offsets of a link node's destination.
function destinationRange(markdown, node) {
  const { start, end } = node.position;
  const text = markdown.slice(start.offset, end.offset);
  const opener = node.type === "definition" ? text.indexOf("]:") : text.lastIndexOf("](");
  let from = opener + 2;
  while (/\s/.test(text[from])) from++;
  if (text[from] === "<") from++;
  let to = from;
  while (to < text.length && !/[\s>)]/.test(text[to])) to++;
  if (opener < 0 || to === from) throw new Error(`can't find the destination of ${node.url} at line ${start.line}`);
  return [start.offset + from, start.offset + to];
}

function plainText(node) {
  if (node.type === "text" || node.type === "inlineCode" || node.type === "html") return node.value;
  return (node.children ?? []).map(plainText).join("");
}

function convertPage(source, dest, plan, rewrites) {
  const markdown = readFileSync(path.join(repoRoot, source), "utf8");
  if (markdown.startsWith("---\n")) throw new Error(`${source} has front matter; the sync writes its own`);
  const tree = fromMarkdown(markdown, { extensions: [gfm()], mdastExtensions: [gfmFromMarkdown()] });

  const edits = [];
  visit(tree, ["link", "image", "definition"], (node) => {
    const rewrite = rewriteUrl(node.url, source, node.type, plan);
    if (!rewrite) return;
    edits.push({ range: destinationRange(markdown, node), url: rewrite.url });
    rewrites.push([source, rewrite.rule, node.url, rewrite.url]);
  });

  const h1 = tree.children.find((node) => node.type === "heading" && node.depth === 1);
  if (!h1) throw new Error(`${source} has no H1 to use as the title`);
  edits.push({ range: [h1.position.start.offset, h1.position.end.offset], url: "" });

  let body = markdown;
  for (const { range, url } of edits.sort((a, b) => b.range[0] - a.range[0])) {
    body = body.slice(0, range[0]) + url + body.slice(range[1]);
  }

  const frontMatter = [
    "---",
    `title: ${JSON.stringify(plainText(h1))}`,
    `editUrl: ${JSON.stringify(`${repoUrl}/edit/main/${source}`)}`,
    ...(dest.endsWith("index.md") ? ["sidebar:", "  label: Overview", "  order: 0"] : []),
    "---",
  ];
  return `${frontMatter.join("\n")}\n${body.replace(/^\s*\n/, "\n")}`;
}

function write(dest, content) {
  const file = path.join(docsOut, dest);
  mkdirSync(path.dirname(file), { recursive: true });
  writeFileSync(file, content);
}

// Serve every published schema under public/contracts/, so each is at /contracts/<name> below the
// site root. Its $id is at schemaIdPrefix; the schema-URL test checks the mapping between the two.
function syncSchemas() {
  const rows = [];
  for (const file of listFiles(schemasSource, true).filter((f) => f.endsWith(".schema.json")).sort()) {
    const rel = path.posix.relative(schemasSource, file);
    const outFile = path.join(siteRoot, "public/contracts", rel);
    mkdirSync(path.dirname(outFile), { recursive: true });
    cpSync(path.join(repoRoot, file), outFile);
    const schema = JSON.parse(readFileSync(outFile, "utf8"));
    if (!schema.$id.startsWith(schemaIdPrefix)) throw new Error(`${file}: $id ${schema.$id} is outside ${schemaIdPrefix}`);
    rows.push(`| [\`${rel}\`](/contracts/${rel}) | \`${schema.$id}\` |`);
  }
  write(
    "reference/contracts/schemas.md",
    [
      "---",
      "title: JSON Schemas",
      "sidebar:",
      "  order: 1",
      "---",
      "",
      `The published JSON Schemas, copied from [\`${schemasSource}\`](${repoUrl}/tree/main/${schemasSource}).`,
      "This site serves each one at `/contracts/<name>` below its root, which is the path of its `$id` below `https://benchhand.github.io/benchhand/`.",
      "",
      ":::caution[The `$id`s don't resolve yet]",
      "The `$id`s name `benchhand.github.io/benchhand`, and this site is published at a different address.",
      "Until the site is published at that host, or at a domain that redirects to it, a `$id` is an identifier, not a link that works.",
      "Use the first column to fetch a schema.",
      ":::",
      "",
      "| Schema, served by this site | `$id` |",
      "|---|---|",
      ...rows,
      "",
    ].join("\n"),
  );
  return rows.length;
}

function main() {
  for (const output of OUTPUTS) rmSync(path.join(siteRoot, output), { recursive: true, force: true });
  const plan = planCopies();
  const rewrites = [];
  for (const [source, dest] of plan.pages) write(dest, convertPage(source, dest, plan, rewrites));
  for (const [source, dest] of plan.assets) {
    mkdirSync(path.dirname(path.join(docsOut, dest)), { recursive: true });
    cpSync(path.join(repoRoot, source), path.join(docsOut, dest));
  }
  const schemaCount = syncSchemas();

  mkdirSync(path.join(siteRoot, ".cache"), { recursive: true });
  const tsv = ["source\trule\tfrom\tto", ...rewrites.map((row) => row.join("\t"))].join("\n");
  writeFileSync(path.join(siteRoot, ".cache/link-rewrites.tsv"), `${tsv}\n`);

  const byRule = Map.groupBy(rewrites, (row) => row[1]);
  console.log(`synced ${plan.pages.size} pages, ${plan.assets.size} images and ${schemaCount} schemas`);
  for (const [rule, rows] of byRule) console.log(`  ${rows.length} links: ${rule}`);
  console.log(`  every rewrite: ${toPosix(path.relative(process.cwd(), path.join(siteRoot, ".cache/link-rewrites.tsv")))}`);
}

main();
