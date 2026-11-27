// Every "Edit page" link in the built site must target a file that git tracks: the generated pages
// switch the link off (`editUrl: false`), and every other page's link names its source. Run after `pnpm build`.
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { readdirSync, readFileSync } from "node:fs";
import path from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

import { repoRoot, repoUrl } from "../site-url.mjs";

const dist = fileURLToPath(new URL("../dist", import.meta.url));
const editPrefix = `${repoUrl}/edit/main/`;

const tracked = new Set(execFileSync("git", ["ls-files", "-z"], { cwd: repoRoot, maxBuffer: 1 << 28 }).toString("utf8").split("\0"));

// Each HTML page of the build with an edit link, with the repository path the link targets.
function editTargets() {
  const found = [];
  for (const file of readdirSync(dist, { recursive: true }).filter((f) => f.endsWith(".html"))) {
    const html = readFileSync(path.join(dist, file), "utf8");
    for (const [, href] of html.matchAll(/href="([^"]+)"/g)) {
      if (href.startsWith(editPrefix)) found.push({ page: file.split(path.sep).join("/"), target: decodeURI(href.slice(editPrefix.length)) });
    }
  }
  return found;
}

test("the build has edit links to check", () => {
  assert.ok(editTargets().length > 50, "expected an edit link on each hand-written and synced page");
});

test("every edit link targets a path tracked in git", () => {
  const untracked = editTargets().filter(({ target }) => !tracked.has(target));
  assert.deepEqual(untracked, [], "these pages' edit links target untracked files: set editUrl: false, or point the link at the tracked source");
});

test("generated pages have no edit link", () => {
  const pages = [
    "planned/index.html",
    "reference/contracts/schemas/index.html",
    "reference/python-api/index.html",
    "reference/python-api/benchhand-contracts/index.html",
  ];
  const withLink = new Set(editTargets().map(({ page }) => page));
  for (const page of pages) assert.ok(!withLink.has(page), `${page} is generated and must not link to an edit page`);
});
