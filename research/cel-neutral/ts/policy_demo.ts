// Evaluate the compiled cel-policy CheckedExprs (generated/checked-policy/*.binpb) on @bufbuild/cel 0.6.2.
// cel-go's policy compiler wrote them (../go-policy); @bufbuild/cel has no policy support and no public
// checker, so this only evaluates the shipped CheckedExpr on policy/tests.json.
import { readFileSync, readdirSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { createFileRegistry, fromBinary, fromJson } from "@bufbuild/protobuf";
import { FileDescriptorSetSchema, AnySchema } from "@bufbuild/protobuf/wkt";
import { celEnv, objectType, plan, isCelError, isCelList, CelScalar } from "@bufbuild/cel";
import { CheckedExprSchema } from "@bufbuild/cel-spec/cel/expr/checked_pb.js";

type Case = { testCase: string; bindings: { stage: string; iteration: string; part: object }; expected: string[] };

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const registry = createFileRegistry(fromBinary(FileDescriptorSetSchema, readFileSync(join(root, "generated/types.binpb"))));
const part = registry.getMessage("benchhand.contracts.record.part.Part");
if (!part) throw new Error("no Part message");
const env = celEnv({ registry, variables: { stage: CelScalar.STRING, iteration: CelScalar.STRING, part: objectType(part) } });
const tests = JSON.parse(readFileSync(join(root, "policy/tests.json"), "utf8")) as Case[];
let failures = 0;
for (const file of readdirSync(join(root, "generated/checked-policy")).sort()) {
  const any = fromBinary(AnySchema, readFileSync(join(root, "generated/checked-policy", file)));
  const checked = fromBinary(CheckedExprSchema, any.value);
  for (const t of tests) {
    const bindings = { ...t.bindings, part: fromJson(part, t.bindings.part as never, { registry }) };
    let got: unknown;
    try {
      got = plan(env, checked)(bindings);
    } catch (e) {
      got = e instanceof Error ? e.message : String(e);
    }
    const shown = isCelList(got) ? [...got] : isCelError(got) ? got.message : got;
    const ok = JSON.stringify(shown) === JSON.stringify(t.expected);
    failures += ok ? 0 : 1;
    console.log(`${ok ? "ok " : "BAD"} ${file} ${JSON.stringify(t.testCase)} -> ${JSON.stringify(shown)}`);
  }
}
console.log(`@bufbuild/cel policy: ${failures} failures`);
process.exit(failures > 0 ? 1 : 0);
