// Each published schema's $id must map to a file the built site serves, with the schema's own bytes.
// The $ids stay at https://benchhand.github.io/benchhand/contracts/ (owner decision, 2026-11-27) and the
// site serves each schema at /contracts/<name> relative to its root, so the path below the $id prefix is
// the path below dist/contracts/. Run after `pnpm build`.
import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import path from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

import { base, repoRoot, schemaIdPrefix, site } from "../site-url.mjs";

const schemasDir = path.join(repoRoot, "packages/benchhand-contracts/src/benchhand_contracts/schemas");
const dist = fileURLToPath(new URL("../dist", import.meta.url));

const schemaFiles = readdirSync(schemasDir, { recursive: true })
  .filter((file) => file.endsWith(".schema.json"))
  .map((file) => path.join(schemasDir, file));

test("there are published schemas to check", () => {
  assert.ok(schemaFiles.length > 0, `no *.schema.json under ${schemasDir}`);
});

// The path of a schema below the site root: the $id with its prefix removed, under contracts/.
export function servedPath($id) {
  assert.ok($id.startsWith(schemaIdPrefix), `$id ${$id} is outside ${schemaIdPrefix}`);
  return `contracts/${$id.slice(schemaIdPrefix.length)}`;
}

test("the $id mapping puts a schema at /contracts/ below the site root", () => {
  assert.equal(servedPath(`${schemaIdPrefix}record/part.schema.json`), "contracts/record/part.schema.json");
  assert.throws(() => servedPath("https://example.org/contracts/record/part.schema.json"), /outside/);
});

for (const file of schemaFiles) {
  const source = readFileSync(file);
  const { $id } = JSON.parse(source.toString("utf8"));

  test(`${$id} is served at ${site}${base}${servedPath($id)}`, () => {
    const served = path.join(dist, ...servedPath($id).split("/"));
    assert.deepEqual(readFileSync(served), source, `${served} differs from ${file}`);
  });
}
