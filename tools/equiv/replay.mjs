// Judge every replay case with Ajv 2020, the engine of the generated TypeScript validators, against the
// hand-written and the published schemas (ADR-0017).
//
// Usage: node tools/equiv/replay.mjs <work dir>, after replay.py. Compares whether each instance is valid
// and Ajv's first error (instance path, keyword and schema path), since a generated validator reports
// only that one. A difference is explained only when the published schemas without the Timestamp
// pattern, the one intended narrowing, give exactly the hand-written verdict. It also checks that Ajv and Python agree on every published verdict. Exits 1 otherwise.
import { readFileSync, readdirSync, statSync } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const require = createRequire(path.join(repo, "ui/shared/package.json"));
const Ajv2020 = require("ajv/dist/2020.js").default;
const work = process.argv[2];
const published = path.join(repo, "packages/benchhand-contracts/src/benchhand_contracts/schemas");
const jobId = "https://benchhand.github.io/benchhand/contracts/jobs/job.schema.json";

function schemaFiles(dir) {
  return readdirSync(dir).flatMap((name) => {
    const full = path.join(dir, name);
    if (statSync(full).isDirectory()) return schemaFiles(full);
    return full.endsWith(".schema.json") ? [full] : [];
  });
}

function extensionKeywords(node, found) {
  if (Array.isArray(node)) node.forEach((item) => extensionKeywords(item, found));
  else if (node && typeof node === "object") {
    for (const [key, value] of Object.entries(node)) {
      if (key.startsWith("x-")) found.add(key);
      extensionKeywords(value, found);
    }
  }
}

// The options of ui/shared/scripts/gen-contracts.mjs, so that this judges as the generated validators do.
function ajvFor(dir, change = (schema) => schema) {
  const ajv = new Ajv2020({
    strictSchema: true,
    strictNumbers: true,
    strictTypes: false,
    strictTuples: false,
    strictRequired: false,
    validateFormats: false,
  });
  const schemas = schemaFiles(dir).map((file) => change(JSON.parse(readFileSync(file, "utf8"))));
  const keywords = new Set();
  schemas.forEach((schema) => extensionKeywords(schema, keywords));
  [...keywords].sort().forEach((keyword) => ajv.addKeyword(keyword));
  schemas.forEach((schema) => ajv.addSchema(schema));
  return ajv;
}

function judge(ajv, testCase) {
  let validate;
  try {
    validate = ajv.getSchema(testCase.schema_id);
  } catch {
    return { valid: "unresolvable" };
  }
  if (!validate) return { valid: "unresolvable" };
  const valid = validate(testCase.instance);
  const first = valid ? null : validate.errors[0];
  return { valid, first: first && `${first.instancePath || "/"} ${first.keyword} ${first.schemaPath}` };
}

const oldAjv = ajvFor(path.join(work, "old"));
const newAjv = ajvFor(published);
const counterfactualAjv = ajvFor(published, (schema) => {
  if (schema.$id === jobId) delete schema.$defs.Timestamp.pattern;
  return schema;
});
const cases = JSON.parse(readFileSync(path.join(work, "cases.json"), "utf8"));
const python = JSON.parse(readFileSync(path.join(work, "python.json"), "utf8"));
const counts = {};
let differ = 0;
let unexplained = 0;
let firstChanged = 0;
let disagreements = 0;
const shown = [];
cases.forEach((testCase, index) => {
  const before = judge(oldAjv, testCase);
  const after = judge(newAjv, testCase);
  const key = `${before.valid}/${after.valid}`;
  counts[key] = (counts[key] ?? 0) + 1;
  if (after.valid !== python[index]) disagreements += 1;
  if (before.valid === after.valid && before.first === after.first) return;
  differ += 1;
  if (before.first !== after.first) firstChanged += 1;
  const without = judge(counterfactualAjv, testCase);
  const ok = without.valid === before.valid && without.first === before.first;
  if (!ok) unexplained += 1;
  shown.push(
    `    ${ok ? "explained" : "UNEXPLAINED"}: ${testCase.source}, ${testCase.schema_id.split("/contracts/")[1]}, ` +
      `${JSON.stringify(testCase.instance).slice(0, 60)}\n      hand-written: ${before.first ?? before.valid}\n` +
      `      published:    ${after.first ?? after.valid}`,
  );
});
console.log(`ajv replay: ${cases.length} instances`);
console.log(`  valid hand-written/published: ${JSON.stringify(counts)}`);
console.log(`  verdicts that differ: ${differ}, of which the first error changed: ${firstChanged}`);
console.log(`  explained by the Timestamp pattern: ${differ - unexplained}`);
console.log(`  unexplained: ${unexplained}`);
shown.sort((a, b) => a.includes("UNEXPLAINED") - b.includes("UNEXPLAINED")).reverse();
console.log(shown.slice(0, 12).join("\n"));
console.log(`ajv and python disagree on ${disagreements} published verdicts`);
process.exit(unexplained || disagreements ? 1 : 0);
