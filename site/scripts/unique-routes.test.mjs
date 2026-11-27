// SPDX-FileCopyrightText: 2026 Sjors Robroek
//
// SPDX-License-Identifier: MPL-2.0

// No two pages of the synced site may share a route: `x.md` beside `x/index.md` is a duplicate slug,
// which Astro reports as a warning and which leaves one of the two pages unreachable. Run after `pnpm sync`.
import assert from "node:assert/strict";
import { readdirSync } from "node:fs";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

const docsDir = fileURLToPath(new URL("../src/content/docs", import.meta.url));

const routeOf = (file) => file.replace(/\.mdx?$/, "").replace(/(^|\/)index$/, "");

test("every page of src/content/docs has a route of its own", () => {
  const files = readdirSync(docsDir, { recursive: true })
    .map((file) => file.split("\\").join("/"))
    .filter((file) => /\.mdx?$/.test(file));
  assert.ok(files.length > 50, "run `pnpm sync` first: src/content/docs is nearly empty");
  const byRoute = Map.groupBy(files, routeOf);
  const shared = [...byRoute].filter(([, pages]) => pages.length > 1);
  assert.deepEqual(shared, []);
});
