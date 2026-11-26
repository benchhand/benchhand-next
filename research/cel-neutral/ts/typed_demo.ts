// The typed demo on the TypeScript engines, from the gate_guard profile manifest and FileDescriptorSet.
//
// @bufbuild/cel 0.6.2: types come from a protobuf-es registry built from the FileDescriptorSet. Its
// checker ships in dist/ but isn't exported (PRs bufbuild/cel-es#237 and #344 are open), so this imports it
// by file path. plan() takes a CheckedExpr, so it also evaluates what the other engines checked.
// @marcbachmann/cel-js 8.0.0: a public checker over native type declarations, which this derives from the
// same FileDescriptorSet. It has no proto AST, so it can't take a shipped CheckedExpr.
import { readFileSync, readdirSync, mkdirSync, writeFileSync, existsSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { parse as parseYaml } from "yaml";
import { fromBinary, fromJson, toBinary, create } from "@bufbuild/protobuf";
import type { DescMessage, DescField } from "@bufbuild/protobuf";
import { AnySchema } from "@bufbuild/protobuf/wkt";
import { parse, plan, isCelError } from "@bufbuild/cel";
import { envFromProfile, loadProfile, messageDesc, readBundle, verifyBundle, writeBundle, writeResults, ProfileError } from "./celprofile.ts";
import type { Bundle, Result } from "./celprofile.ts";
import { CheckedExprSchema, type CheckedExpr } from "@bufbuild/cel-spec/cel/expr/checked_pb.js";
import { Environment } from "@marcbachmann/cel-js";
// Not exported by the package: the checker, imported from the same dist/ so it shares module state.
import { check } from "./node_modules/@bufbuild/cel/dist/esm/check.js";

type Rule = { expr: string; expect?: boolean; why?: string; feature?: string; refuse?: boolean };
type Demo = { scope: string; accept: Rule[]; reject: Rule[]; profile: Rule[] };

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const generated = join(root, "generated");
const demo = parseYaml(readFileSync(join(root, "typedemo/gate_guard.yaml"), "utf8")) as Demo;
const profile = loadProfile(generated, demo.scope);
const registry = profile.registry;
const config = { variables: profile.manifest.variables.map((v) => ({ name: v.name, type_name: v.type })) };
const activation = JSON.parse(readFileSync(join(generated, `activation/${demo.scope}.json`), "utf8"));
const firstLine = (e: unknown) => String(e instanceof Error ? e.message : e).split("\n")[0];
let failures = 0;
const records: Result[] = [];
const show = (v: unknown) => (isCelError(v) ? v.message : String(v));

function record(kind: string, c: string, ok: boolean, detail: string, writer?: string) {
  records.push({ engine: "bufbuild-cel", kind, case: c, writer, ok, detail });
  console.log(`${ok ? "ok " : "BAD"} ${kind}${writer ? ` from ${writer}` : ""} ${JSON.stringify(c)}: ${detail}`);
}

function bufbuildDemo(): void {
  const env = envFromProfile(profile);
  // Omitted (non-structural) fields aren't declared, so the binding drops them.
  const bindings = Object.fromEntries(
    config.variables.map((v) => [
      v.name,
      fromJson(messageDesc(registry, v.type_name), activation[v.name], { registry, ignoreUnknownFields: true }),
    ]),
  );
  const out = join(generated, "checked/ts-bufbuild");
  // The unexported checker handles only identifiers, selects and constants in 0.6.2: any call or macro
  // throws "Unsupported expression kind". A rule it can't check is evaluated unchecked, and counted. An
  // unchecked evaluation never counts as a rejection: @bufbuild/cel is an evaluator, not a checker.
  const unsupported = (e: unknown) => firstLine(e).startsWith("Unsupported expression kind");
  let uncheckable = 0;
  const sources = new Map<string, string>();
  demo.accept.forEach((rule, i) => {
    let checked: CheckedExpr | undefined;
    try {
      checked = check(env, parse(rule.expr));
    } catch (e) {
      if (!unsupported(e)) throw e;
      uncheckable += 1;
    }
    const got = plan(env, checked ?? parse(rule.expr))(bindings);
    const how = checked ? "checked" : "checker unsupported, ran unchecked";
    record("accept", rule.expr, got === (rule.expect ?? true), `${how}: ${show(got)}`);
    if (checked) {
      mkdirSync(out, { recursive: true });
      const any = create(AnySchema, { typeUrl: "type.googleapis.com/cel.expr.CheckedExpr", value: toBinary(CheckedExprSchema, checked) });
      writeFileSync(join(out, `accept-${i}.binpb`), toBinary(AnySchema, any));
      sources.set(`accept-${i}.binpb`, rule.expr);
    }
  });
  if (sources.size > 0) writeBundle(out, profile, { engine: "bufbuild-cel", version: "0.6.2" }, sources);
  for (const rule of demo.reject) {
    try {
      check(env, parse(rule.expr));
      record("reject", rule.expr, false, `type-checked; expected: ${rule.why}`);
    } catch (e) {
      if (!unsupported(e)) {
        record("reject", rule.expr, true, firstLine(e));
        continue;
      }
      uncheckable += 1;
      let got: unknown;
      try {
        got = show(plan(env, parse(rule.expr))(bindings));
      } catch (err) {
        got = firstLine(err);
      }
      record("reject", rule.expr, false, `checker unsupported; unchecked eval -> ${got}`);
    }
  }
  for (const rule of demo.profile) {
    let got: unknown;
    try {
      got = plan(env, parse(rule.expr))(bindings);
    } catch (e) {
      got = new Error(firstLine(e));
    }
    const failed = got instanceof Error || isCelError(got);
    const detail = `${rule.feature}: unchecked eval -> ${got instanceof Error ? got.message : show(got)}`;
    record("profile", rule.expr, rule.refuse ? failed : got === (rule.expect ?? true), detail);
  }
  console.log(`@bufbuild/cel checker: ${uncheckable} of ${demo.accept.length + demo.reject.length} rules uncheckable`);
  const acceptSources = new Map(demo.accept.map((r, i) => [`accept-${i}.binpb`, r.expr] as [string, string]));
  for (const engine of readdirSync(join(generated, "checked")).sort()) {
    if (engine === "ts-bufbuild") continue;
    let entries: Map<string, Uint8Array>;
    try {
      entries = readBundle(join(generated, "checked", engine), profile, acceptSources);
    } catch (e) {
      if (!(e instanceof ProfileError)) throw e;
      record("bundle", engine, false, `refused: ${e.message}`);
      continue;
    }
    for (const [name, data] of entries) {
      const i = Number(name.replace(/\D/g, ""));
      try {
        const got = plan(env, fromBinary(CheckedExprSchema, fromBinary(AnySchema, data).value))(bindings);
        record("shipped", name, got === (demo.accept[i].expect ?? true), show(got), engine);
      } catch (e) {
        record("shipped", name, false, firstLine(e), engine);
      }
    }
  }
  tampered();
  failures += records.filter((r) => !r.ok).length;
  writeResults(root, "bufbuild-cel", records);
  console.log(`@bufbuild/cel: ${failures} failures, profile ${profile.digest.slice(0, 12)}`);
}

// A bundle from another profile, and an entry whose source changed, must both be refused.
function tampered(): void {
  const dir = join(generated, "checked/go");
  if (!existsSync(join(dir, "bundle.json"))) return;
  const own = JSON.parse(readFileSync(join(dir, "bundle.json"), "utf8")) as Bundle;
  const edited = new Map(own.entries.map((e) => [e.file, "edited"] as [string, string]));
  const cases: [string, Bundle, Map<string, string>][] = [
    ["other profile", { ...own, profile_sha256: "0".repeat(64) }, new Map()],
    ["stale source", own, edited],
  ];
  for (const [what, bundle, sources] of cases) {
    try {
      verifyBundle(dir, bundle, profile, sources);
      record("bundle", what, false, "accepted");
    } catch (e) {
      record("bundle", what, e instanceof ProfileError, `refused: ${firstLine(e)}`);
    }
  }
}

// cel-js type names for a proto field. A nullable scalar (a wrapper) has no cel-js equivalent but dyn.
const SCALARS: Record<string, string> = { string: "string", int64: "int", double: "double", bool: "bool" };
const WRAPPERS = new Set(["StringValue", "Int64Value", "DoubleValue", "BoolValue"].map((n) => `google.protobuf.${n}`));

function celJsType(field: DescField): string {
  const leaf = (scalar?: number, message?: DescMessage): string => {
    if (message) return WRAPPERS.has(message.typeName) ? "dyn" : message.typeName;
    return SCALARS[SCALAR_NAMES[scalar ?? 0]] ?? "dyn";
  };
  switch (field.fieldKind) {
    case "list":
      return `list<${leaf(field.scalar, field.message)}>`;
    case "map":
      return `map<string, ${leaf(field.scalar, field.message)}>`;
    case "message":
      return leaf(undefined, field.message);
    default:
      return leaf(field.scalar);
  }
}
// ScalarType numbers from descriptor.proto.
const SCALAR_NAMES: Record<number, string> = { 1: "double", 3: "int64", 8: "bool", 9: "string" };

function celJsDemo(): void {
  let localFailures = 0;
  const env = new Environment();
  const messages = [...registry].filter((t) => t.kind === "message" && !t.typeName.startsWith("google.")) as DescMessage[];
  // cel-js resolves a field's type when the type is registered, so register leaves first.
  const registered = new Set<string>();
  const deps = (d: DescMessage) =>
    d.fields.map((f) => f.message?.typeName).filter((n): n is string => !!n && !WRAPPERS.has(n) && n !== d.typeName);
  while (registered.size < messages.length) {
    for (const desc of messages) {
      if (registered.has(desc.typeName) || !deps(desc).every((n) => registered.has(n))) continue;
      env.registerType(desc.typeName, { fields: Object.fromEntries(desc.fields.map((f) => [f.name, celJsType(f)])) });
      registered.add(desc.typeName);
    }
  }
  for (const v of config.variables) env.registerVariable(v.name, v.type_name);
  for (const rule of demo.accept) {
    const result = env.check(rule.expr);
    let got: unknown = result.valid ? undefined : result.error?.message;
    if (result.valid) {
      try {
        got = env.evaluate(rule.expr, activation);
      } catch (e) {
        got = firstLine(e);
      }
    }
    const ok = got === (rule.expect ?? true);
    localFailures += ok ? 0 : 1;
    console.log(`${ok ? "ok " : "BAD"} cel-js accept ${JSON.stringify(rule.expr)} -> ${firstLine(got)}`);
  }
  for (const rule of demo.reject) {
    const result = env.check(rule.expr);
    if (!result.valid) {
      console.log(`ok  cel-js reject ${JSON.stringify(rule.expr)}: ${firstLine(result.error?.message)}`);
      continue;
    }
    localFailures += 1;
    console.log(`BAD cel-js reject ${JSON.stringify(rule.expr)} type-checked; expected: ${rule.why}`);
  }
  console.log(`@marcbachmann/cel-js: ${localFailures} failures`);
  failures += localFailures;
}

bufbuildDemo();
celJsDemo();
process.exit(failures > 0 ? 1 : 0);
