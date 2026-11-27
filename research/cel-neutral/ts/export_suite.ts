// SPDX-FileCopyrightText: 2026 Sjors Robroek
//
// SPDX-License-Identifier: MPL-2.0

// Export the shared conformance suite: cel-spec's own simple tests, in their protobuf JSON form
// (cel.expr.conformance.test.SimpleTestFile), taken from @bufbuild/cel-spec 0.6.2.
//
// Written to ../conformance/suite.json. Kept: every test that needs no declarations, bindings, container or message types, and expects a scalar,
// list or map value or an evaluation error. Those are the tests every runner can drive with the same small
// value encoder. Dropped tests are counted per reason in suite-summary.txt.
import { writeFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { tests } from "@bufbuild/cel-spec/testdata/conformance.js";

type SimpleTest = { name: string; expr: string; value?: Record<string, unknown>; evalError?: unknown } & Record<
  string,
  unknown
>;
type Node = { name: string; tests?: { original: SimpleTest }[]; suites?: Node[] };

const KINDS = new Set(["int64Value", "uint64Value", "doubleValue", "stringValue", "bytesValue", "boolValue", "nullValue"]);

// Why a test can't run on every runner, or undefined when it can.
function dropReason(t: SimpleTest): string | undefined {
  for (const key of ["typeEnv", "bindings", "container", "typedResult", "checkOnly"]) {
    if (key in t) return key;
  }
  if (/TestAllTypes|cel\.expr\.conformance/.test(t.expr)) return "conformance message types";
  // An unset result matcher means the expression must evaluate to true (simple.proto).
  if (t.evalError || !t.value) return undefined;
  return plainValue(t.value) ? undefined : `value kind ${Object.keys(t.value)[0]}`;
}

function plainValue(v: Record<string, unknown>): boolean {
  const [kind] = Object.keys(v);
  if (KINDS.has(kind)) return true;
  if (kind === "listValue") return ((v.listValue as { values?: Record<string, unknown>[] }).values ?? []).every(plainValue);
  if (kind === "mapValue") {
    const entries = (v.mapValue as { entries?: { key: Record<string, unknown>; value: Record<string, unknown> }[] }).entries ?? [];
    return entries.every((e) => plainValue(e.key) && plainValue(e.value));
  }
  return false;
}

const here = join(dirname(fileURLToPath(import.meta.url)), "../conformance");
const dropped = new Map<string, number>();
const files: { name: string; sections: { name: string; tests: SimpleTest[] }[] }[] = [];
let kept = 0;
for (const file of (tests as Node).suites ?? []) {
  const sections = [];
  for (const section of file.suites ?? []) {
    const keep = [];
    const names = new Set<string>();
    for (const { original } of section.tests ?? []) {
      const why = dropReason(original);
      if (why) {
        dropped.set(why, (dropped.get(why) ?? 0) + 1);
        continue;
      }
      // A few cel-spec sections repeat a test name; results are keyed by name, so a repeat gets a suffix.
      let name = original.name;
      for (let n = 2; names.has(name); n++) name = `${original.name}#${n}`;
      names.add(name);
      keep.push({ ...original, name });
    }
    kept += keep.length;
    if (keep.length) sections.push({ name: section.name, tests: keep });
  }
  if (sections.length) files.push({ name: file.name, sections });
}
writeFileSync(join(here, "suite.json"), JSON.stringify(files, null, 1) + "\n");
const lines = [`kept ${kept} tests in ${files.length} files`, ...[...dropped].sort((a, b) => b[1] - a[1]).map(([k, n]) => `dropped ${n}: ${k}`)];
writeFileSync(join(here, "suite-summary.txt"), lines.join("\n") + "\n");
console.log(lines.join("\n"));
