// Judge every replay case, and every mutant replay.py made, with Ajv 2020, the engine of the generated
// TypeScript validators, against the hand-written and the published schemas (ADR-0017).
//
// Usage: node tools/equiv/replay.mjs <work dir>, after replay.py. Compares whether each instance is valid
// and Ajv's first error (instance path, keyword and schema path), since a generated validator reports
// only that one. The evidence for the one intended narrowing is a second comparison, on every instance:
// the published schemas with the Timestamp pattern taken out must give exactly the hand-written verdict,
// with no difference left. It also checks that Ajv and Python agree on every published verdict. Exits 1 otherwise.
import { createReadStream, readFileSync, readdirSync, statSync } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import readline from "node:readline";
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

const sameVerdict = (a, b) => a.valid === b.valid && a.first === b.first;
const oldAjv = ajvFor(path.join(work, "old"));
const newAjv = ajvFor(published);
const withoutPatternAjv = ajvFor(published, (schema) => {
  if (schema.$id === jobId) delete schema.$defs.Timestamp.pattern;
  return schema;
});

function comparison(title) {
  return { title, count: 0, counts: {}, differ: 0, firstChanged: 0, withoutPattern: 0, disagree: 0, shown: [] };
}

function add(result, testCase, python) {
  const before = judge(oldAjv, testCase);
  const after = judge(newAjv, testCase);
  // Every instance is judged without the pattern too: an unchanged verdict can hide a changed reason.
  const left = !sameVerdict(judge(withoutPatternAjv, testCase), before);
  const key = `${before.valid}/${after.valid}`;
  result.count += 1;
  result.counts[key] = (result.counts[key] ?? 0) + 1;
  if (after.valid !== python) result.disagree += 1;
  if (left) result.withoutPattern += 1;
  const differ = !sameVerdict(before, after);
  if (differ) result.differ += 1;
  if (differ && before.first !== after.first) result.firstChanged += 1;
  if (left || (differ && result.shown.length < 6)) {
    result.shown.push(
      `    ${left ? "DIFFERS WITHOUT THE PATTERN" : "only with the pattern"}: ${testCase.source}, ` +
        `${testCase.schema_id.split("/contracts/")[1]}, ${JSON.stringify(testCase.instance).slice(0, 60)}\n` +
        `      hand-written: ${before.first ?? before.valid}\n      published:    ${after.first ?? after.valid}`,
    );
  }
}

function report(result) {
  console.log(`${result.title}: ${result.count} instances`);
  console.log(`  valid hand-written/published: ${JSON.stringify(result.counts)}`);
  console.log(`  hand-written vs published: ${result.differ} differ, the first error in ${result.firstChanged}`);
  console.log(`  hand-written vs published without the Timestamp pattern: ${result.withoutPattern} differ`);
  console.log(result.shown.slice(0, 12).join("\n"));
  console.log(`  ajv and python disagree on ${result.disagree} published verdicts`);
  return result.withoutPattern + result.disagree;
}

const cases = JSON.parse(readFileSync(path.join(work, "cases.json"), "utf8"));
const python = JSON.parse(readFileSync(path.join(work, "python.json"), "utf8"));
const replay = comparison("ajv replay");
cases.forEach((testCase, index) => add(replay, testCase, python[index]));

// mutants.jsonl: one {"case": {...}, "python": <published validity>} per line, written by replay.py.
const mutation = comparison("ajv mutations of each instance the published schemas accept");
const lines = readline.createInterface({ input: createReadStream(path.join(work, "mutants.jsonl")) });
for await (const line of lines) {
  const { case: testCase, python: verdict } = JSON.parse(line);
  add(mutation, testCase, verdict);
}
const failures = report(replay) + report(mutation);
process.exit(failures ? 1 : 0);
