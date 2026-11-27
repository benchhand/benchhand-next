// SPDX-FileCopyrightText: 2026 Sjors Robroek
//
// SPDX-License-Identifier: MPL-2.0

// Evaluate the compiled cel-policy bundles (generated/checked-policy/<profile>/) on @bufbuild/cel 0.6.2.
// The reference checker (go/celcheck) wrote them; @bufbuild/cel has no policy support and no public
// checker, so this only evaluates the shipped CheckedExprs on policy/tests.json. Each bundle directory is
// named after its profile: the environment is built from that manifest, and the bundle is refused when
// the digest differs, when this adapter can't implement the profile, or when a source changed.
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { fromBinary, fromJson } from "@bufbuild/protobuf";
import { AnySchema } from "@bufbuild/protobuf/wkt";
import { plan, isCelError, isCelList } from "@bufbuild/cel";
import { CheckedExprSchema } from "@bufbuild/cel-spec/cel/expr/checked_pb.js";
import { envFromProfile, loadProfile, messageDesc, readBundle, writeResults } from "./celprofile.ts";
import type { Bundle, Result } from "./celprofile.ts";

type Case = { testCase: string; bindings: { stage: string; iteration: string; part: object }; expected: string[] };

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const generated = join(root, "generated");
const tests = JSON.parse(readFileSync(join(root, "policy/tests.json"), "utf8")) as Case[];
const records: Result[] = [];
const record = (kind: string, c: string, ok: boolean, detail: string) => {
  records.push({ engine: "bufbuild-cel", kind, case: c, ok, detail });
  console.log(`${ok ? "ok " : "BAD"} ${kind} ${c}: ${detail}`);
};

function runBundle(dir: string): void {
  const name = dir.split("/").pop() as string;
  const bundle = JSON.parse(readFileSync(join(dir, "bundle.json"), "utf8")) as Bundle;
  const sources = new Map(bundle.entries.map((e) => [e.file, readFileSync(join(root, e.source ?? ""), "utf8")] as [string, string]));
  let profile;
  let entries: Map<string, Uint8Array>;
  try {
    profile = loadProfile(generated, name);
    entries = readBundle(dir, profile, sources);
  } catch (e) {
    record("bundle", name, false, `refused: ${e instanceof Error ? e.message : e}`);
    return;
  }
  const env = envFromProfile(profile);
  const partType = profile.manifest.variables.find((v) => v.name === "part")?.type ?? "";
  const part = messageDesc(profile.registry, partType);
  for (const [file, data] of entries) {
    const checked = fromBinary(CheckedExprSchema, fromBinary(AnySchema, data).value);
    for (const t of tests) {
      const bindings = { ...t.bindings, part: fromJson(part, t.bindings.part as never, { registry: profile.registry }) };
      let got: unknown;
      try {
        got = plan(env, checked)(bindings);
      } catch (e) {
        got = e instanceof Error ? e.message : String(e);
      }
      const shown = isCelList(got) ? [...got] : isCelError(got) ? got.message : got;
      record("policy", `${name}/${file} ${t.testCase}`, JSON.stringify(shown) === JSON.stringify(t.expected), JSON.stringify(shown));
    }
  }
}

const policyDir = join(generated, "checked-policy");
for (const entry of readdirSync(policyDir).sort()) {
  if (statSync(join(policyDir, entry)).isDirectory()) runBundle(join(policyDir, entry));
}
writeResults(root, "policy-bufbuild-cel", records);
const failures = records.filter((r) => !r.ok).length;
console.log(`@bufbuild/cel policy: ${failures} failures`);
process.exit(failures > 0 ? 1 : 0);
