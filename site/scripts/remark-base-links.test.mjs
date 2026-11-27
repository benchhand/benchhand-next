// SPDX-FileCopyrightText: 2026 Sjors Robroek
//
// SPDX-License-Identifier: MPL-2.0

// remark-base-links resolves root-relative and "repo:" links, in the Markdown body and in the hero
// actions of the front matter, which is where the links validator reads the hero's links.
import assert from "node:assert/strict";
import { test } from "node:test";

import { fromMarkdown } from "mdast-util-from-markdown";

import remarkBaseLinks from "../src/remark-base-links.mjs";

const repoUrl = "https://github.com/owner/name";

function run(base, markdown, frontmatter) {
  const tree = fromMarkdown(markdown);
  const file = { data: { astro: { frontmatter } } };
  remarkBaseLinks({ base, repoUrl })(tree, file);
  const urls = [];
  const walk = (node) => {
    if (node.url !== undefined) urls.push(node.url);
    for (const child of node.children ?? []) walk(child);
  };
  walk(tree);
  return { urls, links: (frontmatter.hero?.actions ?? []).map((action) => action.link) };
}

const hero = () => ({
  hero: {
    actions: [{ link: "/getting-started/install/" }, { link: "/benchhand-next/reference/" }, { link: "https://example.org/" }, { link: "#top" }],
  },
});

test("under a base, body links and hero action links get the base once; other links are kept", () => {
  const { urls, links } = run("/benchhand-next/", "[a](/reference/) [b](//cdn.example/x) [c](https://example.org/)", hero());
  assert.deepEqual(urls, ["/benchhand-next/reference/", "//cdn.example/x", "https://example.org/"]);
  assert.deepEqual(links, ["/benchhand-next/getting-started/install/", "/benchhand-next/reference/", "https://example.org/", "#top"]);
});

test("at the domain root, root-relative links are kept", () => {
  const { urls, links } = run("/", "[a](/reference/)", hero());
  assert.deepEqual(urls, ["/reference/"]);
  assert.deepEqual(links, ["/getting-started/install/", "/benchhand-next/reference/", "https://example.org/", "#top"]);
});

test("a repo: link goes to the file on GitHub under any base", () => {
  for (const base of ["/", "/benchhand-next/"]) {
    const { urls, links } = run(base, "[plan](repo:docs/design-plan.md)", { hero: { actions: [{ link: "repo:CLA.md" }] } });
    assert.deepEqual(urls, [`${repoUrl}/blob/main/docs/design-plan.md`]);
    assert.deepEqual(links, [`${repoUrl}/blob/main/CLA.md`]);
  }
});

test("a page without a hero is fine", () => {
  assert.deepEqual(run("/benchhand-next/", "[a](/x/)", {}).urls, ["/benchhand-next/x/"]);
});
