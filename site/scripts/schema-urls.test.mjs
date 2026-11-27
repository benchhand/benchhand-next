// Each published schema's $id must be a URL this site serves, with the schema's own bytes.
// Run after `pnpm build`, with the same DOCS_SITE and DOCS_BASE as the build.
import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import path from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

import { base, repoRoot, site } from "../site-url.mjs";

const schemasDir = path.join(repoRoot, "packages/benchhand-contracts/src/benchhand_contracts/schemas");
const dist = fileURLToPath(new URL("../dist", import.meta.url));

const schemaFiles = readdirSync(schemasDir, { recursive: true })
  .filter((file) => file.endsWith(".schema.json"))
  .map((file) => path.join(schemasDir, file));

test("there are published schemas to check", () => {
  assert.ok(schemaFiles.length > 0, `no *.schema.json under ${schemasDir}`);
});

for (const file of schemaFiles) {
  const source = readFileSync(file);
  const { $id } = JSON.parse(source.toString("utf8"));

  test(`${$id} is served by the built site`, () => {
    const prefix = `${site}${base}`;
    assert.ok($id.startsWith(prefix), `$id ${$id} is outside the site at ${prefix}`);
    const served = path.join(dist, ...$id.slice(prefix.length).split("/"));
    assert.deepEqual(readFileSync(served), source, `${served} differs from ${file}`);
  });
}
