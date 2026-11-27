// SPDX-FileCopyrightText: 2026 Sjors Robroek
//
// SPDX-License-Identifier: MPL-2.0

// remark-base-links gives root-relative links the site base, in the Markdown body and in the hero
// actions of the front matter, which is where the links validator reads the hero's links.
import assert from "node:assert/strict";
import { test } from "node:test";

import { fromMarkdown } from "mdast-util-from-markdown";

import remarkBaseLinks from "../src/remark-base-links.mjs";

function run(base, markdown, frontmatter) {
  const tree = fromMarkdown(markdown);
  const file = { data: { astro: { frontmatter } } };
  remarkBaseLinks({ base })(tree, file);
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

test("at the domain root, nothing changes", () => {
  const { urls, links } = run("/", "[a](/reference/)", hero());
  assert.deepEqual(urls, ["/reference/"]);
  assert.deepEqual(links, ["/getting-started/install/", "/benchhand-next/reference/", "https://example.org/", "#top"]);
});

test("a page without a hero is fine", () => {
  assert.deepEqual(run("/benchhand-next/", "[a](/x/)", {}).urls, ["/benchhand-next/x/"]);
});
