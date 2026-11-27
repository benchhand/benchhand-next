// The TypeScript side of the environment profile: load a manifest, check it, and build the @bufbuild/cel
// environment from it, plus the bundle.json that binds CheckedExprs to a profile, a checker and their
// exact payload bytes.
//
// The profile digest is the SHA-256 of the manifest's RFC 8785 (JCS) encoding. A manifest holds only
// ASCII strings, integers, booleans, arrays and objects; for that subset JCS is JSON.stringify with keys
// sorted at every level.
import { createHash } from "node:crypto";
import { readFileSync, writeFileSync, existsSync } from "node:fs";
import { join, basename } from "node:path";
import { createFileRegistry, fromBinary } from "@bufbuild/protobuf";
import type { DescMessage, Registry } from "@bufbuild/protobuf";
import { FileDescriptorSetSchema } from "@bufbuild/protobuf/wkt";
import { celEnv, objectType, CelScalar } from "@bufbuild/cel";
import type { CelEnv } from "@bufbuild/cel";
import { strings } from "@bufbuild/cel/ext";

export type Manifest = {
  name: string;
  descriptor_set: { file: string; sha256: string };
  container: string;
  variables: { name: string; type: string }[];
  extensions: { name: string; version: number }[];
  options: { cross_type_numeric_comparisons: boolean; homogeneous_aggregate_literals: boolean };
  checkers_of_record: Checker[];
};

export type Checker = { engine: string; version: string };
export type Profile = { manifest: Manifest; digest: string; registry: Registry };
// Identity: the profile digest, the checker, and the SHA-256 of each entry's exact payload bytes.
export type Bundle = {
  profile_sha256: string;
  checker: Checker;
  entries: { file: string; payload_sha256: string; source_sha256: string; source?: string }[];
};

// What @bufbuild/cel 0.6.2 implements: only the strings extension ships. It has no version switch; 4 is
// the cel-go version whose functions the shared suite exercised on it (string_ext 199 of 199).
const EXTENSIONS: Record<string, number[]> = { strings: [4] };
// @bufbuild/cel has no checker of its own in use, so check-time options can't differ: they are the
// options the checker that wrote the CheckedExpr applied.
const OPTIONS = { cross_type_numeric_comparisons: false, homogeneous_aggregate_literals: false };
const PRIMITIVES: Record<string, (typeof CelScalar)[keyof typeof CelScalar]> = {
  string: CelScalar.STRING,
  int: CelScalar.INT,
  uint: CelScalar.UINT,
  double: CelScalar.DOUBLE,
  bool: CelScalar.BOOL,
  bytes: CelScalar.BYTES,
};

export class ProfileError extends Error {}

export const sha256 = (data: Uint8Array | string) => createHash("sha256").update(data).digest("hex");

function canonical(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (value && typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>).sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0));
    return `{${entries.map(([k, v]) => `${JSON.stringify(k)}:${canonical(v)}`).join(",")}}`;
  }
  return JSON.stringify(value);
}

export function loadProfile(generated: string, name: string): Profile {
  const manifest = JSON.parse(readFileSync(join(generated, `profile/${name}.profile.json`), "utf8")) as Manifest;
  const fdsBytes = readFileSync(join(generated, manifest.descriptor_set.file));
  if (sha256(fdsBytes) !== manifest.descriptor_set.sha256) {
    throw new ProfileError(`${name}: the descriptor set doesn't match the manifest's SHA-256`);
  }
  for (const ext of manifest.extensions) {
    if (!(EXTENSIONS[ext.name] ?? []).includes(ext.version)) {
      throw new ProfileError(`${name}: @bufbuild/cel has no ${ext.name} version ${ext.version}`);
    }
  }
  if (canonical(manifest.options) !== canonical(OPTIONS)) {
    throw new ProfileError(`${name}: options ${canonical(manifest.options)} differ from ${canonical(OPTIONS)}`);
  }
  if (manifest.container) throw new ProfileError(`${name}: a container isn't mapped in this adapter`);
  const registry = createFileRegistry(fromBinary(FileDescriptorSetSchema, fdsBytes));
  return { manifest, digest: sha256(canonical(manifest)), registry };
}

export function messageDesc(reg: Registry, name: string): DescMessage {
  const desc = reg.getMessage(name);
  if (!desc) throw new Error(`no message ${name}`);
  return desc;
}

// The @bufbuild/cel environment for a profile: its declarations and extensions, nothing else.
export function envFromProfile(profile: Profile): CelEnv {
  const { manifest, registry } = profile;
  const variables = Object.fromEntries(
    manifest.variables.map((v) => [v.name, PRIMITIVES[v.type] ?? objectType(messageDesc(registry, v.type))]),
  );
  const funcs = manifest.extensions.some((e) => e.name === "strings") ? strings : [];
  return celEnv({ registry, variables, funcs });
}

export function writeBundle(dir: string, profile: Profile, checker: Checker, sources: Map<string, string>) {
  const entries = [...sources]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([file, src]) => ({ file, payload_sha256: sha256(readFileSync(join(dir, file))), source_sha256: sha256(src) }));
  const bundle: Bundle = { profile_sha256: profile.digest, checker, entries };
  writeFileSync(join(dir, "bundle.json"), JSON.stringify(bundle, null, 1) + "\n");
}

export function loadBundle(dir: string): Bundle {
  const path = join(dir, "bundle.json");
  if (!existsSync(path)) throw new ProfileError(`${basename(dir)}: no bundle.json, so the profile is unknown`);
  return JSON.parse(readFileSync(path, "utf8")) as Bundle;
}

export const isCheckerOfRecord = (profile: Profile, c: Checker) =>
  profile.manifest.checkers_of_record.some((r) => r.engine === c.engine && r.version === c.version);

// verifyBundle on dir/bundle.json, requiring a checker of record.
export function readBundle(dir: string, profile: Profile, sources: Map<string, string> | null): Map<string, Uint8Array> {
  return verifyBundle(dir, loadBundle(dir), profile, sources);
}

// Each entry's payload, after checking the profile digest, the checker of record (when required), each
// payload's SHA-256, and each source's SHA-256 when sources isn't null. An evaluator that has only the
// bundle passes null: the producer verified the sources, and the host does again at load.
export function verifyBundle(
  dir: string,
  bundle: Bundle,
  profile: Profile,
  sources: Map<string, string> | null,
  requireCheckerOfRecord = true,
): Map<string, Uint8Array> {
  const name = basename(dir);
  if (bundle.profile_sha256 !== profile.digest) {
    throw new ProfileError(`${name}: checked in profile ${bundle.profile_sha256.slice(0, 12)}, not ${profile.digest.slice(0, 12)}`);
  }
  if (requireCheckerOfRecord && !isCheckerOfRecord(profile, bundle.checker)) {
    throw new ProfileError(`${name}: ${bundle.checker.engine} ${bundle.checker.version} isn't a checker of record`);
  }
  const out = new Map<string, Uint8Array>();
  for (const entry of bundle.entries) {
    const payload = readFileSync(join(dir, entry.file));
    if (sha256(payload) !== entry.payload_sha256) {
      throw new ProfileError(`${name}/${entry.file}: the payload isn't the one the checker shipped`);
    }
    const src = sources?.get(entry.file);
    if (sources && (src === undefined || sha256(src) !== entry.source_sha256)) {
      throw new ProfileError(`${name}/${entry.file}: stale, the source changed since it was checked`);
    }
    out.set(entry.file, payload);
  }
  return out;
}

export type Result = { engine: string; kind: string; case: string; writer?: string; ok: boolean; detail: string };

export function writeResults(root: string, name: string, records: Result[]) {
  writeFileSync(join(root, `results/typed-demo/${name}.json`), JSON.stringify(records, null, 1) + "\n");
}
