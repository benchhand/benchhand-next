// SPDX-FileCopyrightText: 2026 Sjors Robroek
//
// SPDX-License-Identifier: MPL-2.0

// A placeholder in a contract's file path, such as the <PN> of hw/parts/<PN>/part.yaml, is text on every
// built page that names it, not an HTML tag that hides it (bhn-vi9). The pages come from the generator
// (tools/gen markdown_prose) and from the contracts index (section-indexes.mjs). Run after `pnpm build`.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

const dist = fileURLToPath(new URL("../dist", import.meta.url));

for (const page of [
  "reference/contracts",
  "reference/contracts/record/part",
  "reference/contracts/record/manufacturing-selection",
  "reference/contracts/domain-model/record/part",
  "reference/contracts/domain-model/record/manufacturing-selection",
]) {
  test(`${page} shows hw/parts/<PN>/part.yaml`, () => {
    const html = readFileSync(path.join(dist, page, "index.html"), "utf8");
    const main = html.slice(html.indexOf("<main"));
    // Astro writes an escaped < as &lt; or &#x3C;, and may leave > as it is.
    assert.match(main, /hw\/parts\/(&lt;|&#x3C;|&#60;)PN(&gt;|>)\/part\.yaml/);
    assert.doesNotMatch(main, /<(pn|v|s)>/i);
  });
}
