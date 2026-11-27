// The public URL of the site and the repository it documents, read by astro.config.mjs,
// the sync script and the schema-URL test.
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

export const repoRoot = fileURLToPath(new URL("..", import.meta.url));

// release.toml is the one place that names the repository (ADR-0015).
const releaseToml = readFileSync(new URL("../release.toml", import.meta.url), "utf8");
const repoMatch = releaseToml.match(/^repo\s*=\s*"([^"]+)"/m);
if (!repoMatch) throw new Error('release.toml has no repo = "owner/name" line');

export const repo = repoMatch[1];
export const repoUrl = `https://github.com/${repo}`;

// The one config value for where the site is published: DOCS_URL, the full URL of the site root.
// It defaults to the repository's GitHub Pages site, https://<owner>.github.io/<name>/.
// A custom domain is DOCS_URL=https://docs.example.org/, and a local copy is DOCS_URL=http://localhost:4321/.
const [owner, name] = repo.split("/");
const docsUrl = new URL(process.env.DOCS_URL || `https://${owner}.github.io/${name}/`);

// Astro's `site` is the origin and its `base` the path below it, with a leading and a trailing slash.
export const site = docsUrl.origin;
export const base = `/${docsUrl.pathname.replace(/^\/+|\/+$/g, "")}/`.replace(/^\/\/$/, "/");

// The `$id` prefix of every published schema. The `$id`s stay at the prototype's host (owner
// decision, 2026-11-27). The site serves each schema at `contracts/<name>` below its root, so a
// site hosted at this URL, or at a domain that redirects to it, resolves them.
export const schemaIdPrefix = "https://benchhand.github.io/benchhand/contracts/";
