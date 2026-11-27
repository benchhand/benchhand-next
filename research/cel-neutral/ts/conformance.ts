// SPDX-FileCopyrightText: 2026 Sjors Robroek
//
// SPDX-License-Identifier: MPL-2.0

// Run the shared conformance suite on @bufbuild/cel 0.6.2 and @marcbachmann/cel-js 8.0.0, and write
// results/bufbuild-cel.jsonl and results/cel-js.jsonl.
//
// Neither reads conformance/env.yaml; this maps the extensions each one has. @bufbuild/cel ships only the
// strings extension and its checker isn't public, so every test runs unchecked. cel-js ships no extension
// libraries; it runs with optional types on and homogeneous literals off, which is what cel-spec expects.
import { readFileSync, writeFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { celEnv, parse, plan, isCelError, isCelList, isCelMap, isCelUint } from "@bufbuild/cel";
import { strings } from "@bufbuild/cel/ext";
import { Environment } from "@marcbachmann/cel-js";

type Test = { name: string; expr: string; disableCheck?: boolean };
type SuiteFile = { name: string; sections: { name: string; tests: Test[] }[] };
type Outcome = { outcome: string; value?: unknown; message?: string };

const root = join(dirname(fileURLToPath(import.meta.url)), "../conformance");
const suite = JSON.parse(readFileSync(join(root, "suite.json"), "utf8")) as SuiteFile[];
const firstLine = (e: unknown) => String(e instanceof Error ? e.message : e).split("\n")[0];

function doubleJson(x: number): number | string {
  if (Number.isNaN(x)) return "NaN";
  if (!Number.isFinite(x)) return x > 0 ? "Infinity" : "-Infinity";
  return x;
}

function scalarJson(v: unknown): Record<string, unknown> | undefined {
  if (v === null) return { nullValue: null };
  if (typeof v === "bigint") return { int64Value: v.toString() };
  if (typeof v === "number") return { doubleValue: doubleJson(v) };
  if (typeof v === "string") return { stringValue: v };
  if (typeof v === "boolean") return { boolValue: v };
  if (v instanceof Uint8Array) return { bytesValue: Buffer.from(v).toString("base64") };
  return undefined;
}

// cel.expr.Value protobuf JSON for a @bufbuild/cel result.
function bufJson(v: unknown): Record<string, unknown> {
  if (isCelUint(v)) return { uint64Value: v.value.toString() };
  if (isCelList(v)) return { listValue: { values: [...v].map(bufJson) } };
  if (isCelMap(v)) return { mapValue: { entries: [...v].map(([key, value]) => ({ key: bufJson(key), value: bufJson(value) })) } };
  return scalarJson(v) ?? { unsupported: String(v) };
}

// cel.expr.Value protobuf JSON for a cel-js result. A map is a plain object or a Map.
function celJsJson(v: unknown): Record<string, unknown> {
  const s = scalarJson(v);
  if (s) return s;
  const ctor = (v as object)?.constructor?.name;
  if (ctor === "UnsignedInt") return { uint64Value: String(v) };
  if (Array.isArray(v)) return { listValue: { values: v.map(celJsJson) } };
  const pairs = v instanceof Map ? [...v] : Object.entries(v as object);
  return { mapValue: { entries: pairs.map(([key, value]) => ({ key: celJsJson(key), value: celJsJson(value) })) } };
}

const bufEnv = celEnv({ funcs: strings });
function runBufbuild(t: Test): Outcome {
  let parsed;
  try {
    parsed = parse(t.expr);
  } catch (e) {
    return { outcome: "parse_error", message: firstLine(e) };
  }
  try {
    const got = plan(bufEnv, parsed)({});
    return isCelError(got) ? { outcome: "eval_error", message: got.message } : { outcome: "value", value: bufJson(got) };
  } catch (e) {
    return { outcome: "eval_error", message: firstLine(e) };
  }
}

const celJs = new Environment({ homogeneousAggregateLiterals: false, enableOptionalTypes: true });
function runCelJs(t: Test): Outcome {
  let program;
  try {
    program = celJs.parse(t.expr);
  } catch (e) {
    return { outcome: "parse_error", message: firstLine(e) };
  }
  if (!t.disableCheck) {
    const result = program.check();
    if (!result.valid) return { outcome: "check_error", message: firstLine(result.error?.message) };
  }
  try {
    return { outcome: "value", value: celJsJson(program({})) };
  } catch (e) {
    return { outcome: "eval_error", message: firstLine(e) };
  }
}

for (const [engine, run] of [["bufbuild-cel", runBufbuild], ["cel-js", runCelJs]] as const) {
  const rows: string[] = [];
  for (const file of suite) {
    for (const section of file.sections) {
      for (const t of section.tests) rows.push(JSON.stringify({ file: file.name, section: section.name, name: t.name, ...run(t) }));
    }
  }
  writeFileSync(join(root, `results/${engine}.jsonl`), rows.join("\n") + "\n");
}
