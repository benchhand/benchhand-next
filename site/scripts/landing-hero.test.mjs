// SPDX-FileCopyrightText: 2026 Sjors Robroek
//
// SPDX-License-Identifier: MPL-2.0

// The landing page's hero sends readers into the documentation: "Get started" opens the first page
// of the Start sidebar group's getting-started pages, and "Browse the docs" opens the /docs/ index.
// The planning documents are not a call to action.
import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import path from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

const docsDir = fileURLToPath(new URL("../src/content/docs", import.meta.url));
const landing = readFileSync(path.join(docsDir, "index.mdx"), "utf8");
const frontMatter = landing.match(/^---\n([\s\S]*?)\n---\n/)[1];

// The hero's `- text: …` / `link: …` pairs, in order.
function heroActions() {
  const actions = frontMatter.slice(frontMatter.indexOf("actions:"));
  return [...actions.matchAll(/- text: (.+)\n\s+link: (.+)/g)].map(([, text, link]) => ({ text, link }));
}

// The route of the getting-started page with the lowest `sidebar.order`, which the sidebar lists first.
function firstGettingStartedRoute() {
  const pages = readdirSync(path.join(docsDir, "getting-started")).map((file) => {
    const text = readFileSync(path.join(docsDir, "getting-started", file), "utf8");
    return { file, order: Number(text.match(/^sidebar:\n\s+order: (\d+)$/m)[1]) };
  });
  const first = pages.sort((a, b) => a.order - b.order)[0];
  return `/getting-started/${first.file.replace(/\.mdx?$/, "")}/`;
}

test("the hero has a Get started button and a Browse the docs button, and nothing else", () => {
  assert.deepEqual(heroActions(), [
    { text: "Get started", link: firstGettingStartedRoute() },
    { text: "Browse the docs", link: "/docs/" },
  ]);
});

test("the landing page doesn't link the design plan", () => {
  assert.doesNotMatch(landing, /design-plan|repo:docs\//);
});
