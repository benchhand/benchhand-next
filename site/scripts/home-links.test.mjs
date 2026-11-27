// SPDX-FileCopyrightText: 2026 Sjors Robroek
//
// SPDX-License-Identifier: MPL-2.0

// The links that components draw, which the links validator doesn't see because they are not Markdown:
// the hero's actions, the section map (components/SectionMap.astro) and the header's section links
// (components/SocialIcons.astro). Each must be a page of the built site. Run after `pnpm build`.
import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

const dist = fileURLToPath(new URL("../dist", import.meta.url));
const home = readFileSync(path.join(dist, "index.html"), "utf8");
// The site title links to the site root, so its href is the base the build used.
const base = home.match(/<a href="([^"]*)" class="site-title/)?.[1];

/** The hrefs of the <a> elements inside the first element whose class attribute starts with `className`;
 * that element holds no element of its own tag name. */
function hrefsIn(className) {
  const start = home.search(new RegExp(`class="${className}[ "]`));
  assert.ok(start >= 0, `no .${className} on the home page`);
  const tag = home.lastIndexOf("<", start);
  const name = home.slice(tag + 1).match(/^[a-z]+/)[0];
  const end = home.indexOf(`</${name}>`, start);
  return [...home.slice(start, end).matchAll(/<a [^>]*href="([^"]+)"/g)].map((m) => m[1]);
}

test("the home page names its base in the site title", () => {
  assert.ok(base?.endsWith("/"), `site title href ${base}`);
});

for (const [component, className, count] of [
  ["Hero", "bh-actions", 3],
  ["SectionMap", "bh-map", 5],
  ["SocialIcons", "bh-sections", 3],
]) {
  test(`every ${component} link is a page of the built site`, () => {
    const hrefs = hrefsIn(className);
    assert.equal(hrefs.length, count, hrefs.join(" "));
    for (const href of hrefs) {
      assert.ok(href.startsWith(base), `${href} is outside ${base}`);
      const page = path.join(dist, href.slice(base.length), "index.html");
      assert.ok(existsSync(page), `${href}: no ${path.relative(dist, page)}`);
    }
  });
}
