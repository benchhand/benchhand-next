// The typed demo on the TypeScript engines, from the same env YAML and FileDescriptorSet.
//
// @bufbuild/cel 0.6.2: types come from a protobuf-es registry built from the FileDescriptorSet. Its
// checker ships in dist/ but isn't exported (PRs bufbuild/cel-es#237 and #344 are open), so this imports it
// by file path. plan() takes a CheckedExpr, so it also evaluates what the other engines checked.
// @marcbachmann/cel-js 8.0.0: a public checker over native type declarations, which this derives from the
// same FileDescriptorSet. It has no proto AST, so it can't take a shipped CheckedExpr.
import { readFileSync, readdirSync, mkdirSync, writeFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { parse as parseYaml } from "yaml";
import { createFileRegistry, fromBinary, fromJson, toBinary, create } from "@bufbuild/protobuf";
import type { DescMessage, DescField, Registry } from "@bufbuild/protobuf";
import { FileDescriptorSetSchema, AnySchema } from "@bufbuild/protobuf/wkt";
import { celEnv, objectType, parse, plan, isCelError } from "@bufbuild/cel";
import { strings } from "@bufbuild/cel/ext";
import { CheckedExprSchema, type CheckedExpr } from "@bufbuild/cel-spec/cel/expr/checked_pb.js";
import { Environment } from "@marcbachmann/cel-js";
// Not exported by the package: the checker, imported from the same dist/ so it shares module state.
import { check } from "./node_modules/@bufbuild/cel/dist/esm/check.js";

type Rule = { expr: string; expect?: boolean; why?: string };
type Demo = { scope: string; accept: Rule[]; reject: Rule[] };
type EnvConfig = { variables: { name: string; type_name: string }[] };

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const generated = join(root, "generated");
const demo = parseYaml(readFileSync(join(root, "typedemo/gate_guard.yaml"), "utf8")) as Demo;
const config = parseYaml(readFileSync(join(generated, `env/${demo.scope}.env.yaml`), "utf8")) as EnvConfig;
const fds = fromBinary(FileDescriptorSetSchema, readFileSync(join(generated, "types.binpb")));
const registry = createFileRegistry(fds);
const activation = JSON.parse(readFileSync(join(generated, `activation/${demo.scope}.json`), "utf8"));
const firstLine = (e: unknown) => String(e instanceof Error ? e.message : e).split("\n")[0];
let failures = 0;

function messageDesc(reg: Registry, name: string): DescMessage {
  const desc = reg.getMessage(name);
  if (!desc) throw new Error(`no message ${name}`);
  return desc;
}

function bufbuildDemo(): void {
  const variables = Object.fromEntries(config.variables.map((v) => [v.name, objectType(messageDesc(registry, v.type_name))]));
  const env = celEnv({ registry, variables, funcs: strings });
  // Omitted (non-structural) fields aren't declared, so the binding drops them.
  const bindings = Object.fromEntries(
    config.variables.map((v) => [
      v.name,
      fromJson(messageDesc(registry, v.type_name), activation[v.name], { registry, ignoreUnknownFields: true }),
    ]),
  );
  const out = join(generated, "checked/ts-bufbuild");
  // The unexported checker handles only identifiers, selects and constants in 0.6.2: any call or macro
  // throws "Unsupported expression kind". A rule it can't check is evaluated unchecked, and counted.
  const unsupported = (e: unknown) => firstLine(e).startsWith("Unsupported expression kind");
  let uncheckable = 0;
  demo.accept.forEach((rule, i) => {
    let checked: CheckedExpr | undefined;
    try {
      checked = check(env, parse(rule.expr));
    } catch (e) {
      if (!unsupported(e)) throw e;
      uncheckable += 1;
    }
    const got = plan(env, checked ?? parse(rule.expr))(bindings);
    const ok = got === (rule.expect ?? true);
    failures += ok ? 0 : 1;
    const how = checked ? "checked" : "checker unsupported, ran unchecked";
    console.log(`${ok ? "ok " : "BAD"} accept (${how}) ${JSON.stringify(rule.expr)} -> ${isCelError(got) ? got.message : got}`);
    if (checked) {
      // Only a checked rule writes a file, so the other engines never meet an empty directory.
      mkdirSync(out, { recursive: true });
      const any = create(AnySchema, {
        typeUrl: "type.googleapis.com/cel.expr.CheckedExpr",
        value: toBinary(CheckedExprSchema, checked),
      });
      writeFileSync(join(out, `accept-${i}.binpb`), toBinary(AnySchema, any));
    }
  });
  for (const rule of demo.reject) {
    try {
      check(env, parse(rule.expr));
      failures += 1;
      console.log(`BAD reject ${JSON.stringify(rule.expr)} type-checked; expected: ${rule.why}`);
    } catch (e) {
      if (!unsupported(e)) {
        console.log(`ok  reject ${JSON.stringify(rule.expr)}: ${firstLine(e)}`);
        continue;
      }
      uncheckable += 1;
      const got = plan(env, parse(rule.expr))(bindings);
      console.log(`NOT reject ${JSON.stringify(rule.expr)}: checker unsupported; unchecked eval -> ${isCelError(got) ? got.message : got}`);
    }
  }
  console.log(`@bufbuild/cel checker: ${uncheckable} of ${demo.accept.length + demo.reject.length} rules uncheckable`);
  for (const engine of readdirSync(join(generated, "checked")).sort()) {
    if (engine === "ts-bufbuild") continue;
    demo.accept.forEach((rule, i) => {
      const any = fromBinary(AnySchema, readFileSync(join(generated, "checked", engine, `accept-${i}.binpb`)));
      try {
        const got = plan(env, fromBinary(CheckedExprSchema, any.value))(bindings);
        const ok = got === (rule.expect ?? true);
        failures += ok ? 0 : 1;
        console.log(`${ok ? "ok " : "BAD"} shipped from ${engine} accept-${i} -> ${isCelError(got) ? got.message : got}`);
      } catch (e) {
        failures += 1;
        console.log(`BAD shipped from ${engine} accept-${i}: ${firstLine(e)}`);
      }
    });
  }
  console.log(`@bufbuild/cel: ${failures} failures`);
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
