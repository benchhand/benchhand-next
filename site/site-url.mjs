// The public URL of the site and the repository it documents, read by astro.config.mjs,
// the sync script and the schema-URL test.
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

// The contracts' $ids are https://benchhand.github.io/benchhand/contracts/..., so the defaults
// serve each published schema at its $id. Set DOCS_BASE=/ for a local preview.
export const site = process.env.DOCS_SITE ?? "https://benchhand.github.io";

const rawBase = process.env.DOCS_BASE ?? "/benchhand";

// The base with a leading and a trailing slash: "/" or "/benchhand/".
export const base = rawBase.replace(/^\/*/, "/").replace(/\/*$/, "/").replace(/^\/+$/, "/");

export const repoRoot = fileURLToPath(new URL("..", import.meta.url));

// release.toml is the one place that names the repository (ADR-0015).
const releaseToml = readFileSync(new URL("../release.toml", import.meta.url), "utf8");
const repoMatch = releaseToml.match(/^repo\s*=\s*"([^"]+)"/m);
if (!repoMatch) throw new Error("release.toml has no repo = \"owner/name\" line");

export const repo = repoMatch[1];
export const repoUrl = `https://github.com/${repo}`;
