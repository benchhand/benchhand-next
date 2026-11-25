// Print the contracts' JSON Schema declarations, in source order, for tools/gen (ADR-0017).
//
// The emitted bundle lists declarations in the order the emitter reached them, so the normaliser takes
// the order of the published $defs from here instead. The TypeSpec compiler reads the source, so a
// backticked name, an @id, a template or a declaration in a nested namespace needs no parsing of our own.
//
// Usage: node scripts/declarations.mjs <main.tsp>. Prints {"declarations": [...], "namespaces": [...]}:
// - declarations: {"id", "file"} of each declaration the emitter writes, sorted by file and position;
// - namespaces: {"baseUri", "extensions"} of each @jsonSchema namespace, with the @extension values on
//   the namespace itself, which the emitter doesn't write.
import { compile, NodeHost, getSourceLocation, formatDiagnostic } from "@typespec/compiler";
import { findBaseUri, getExtensions, getId, getJsonSchemaTypes } from "@typespec/json-schema";
import { relative, resolve } from "node:path";

const main = resolve(process.argv[2] ?? "main.tsp");
const program = await compile(NodeHost, main, { noEmit: true, warningAsError: true });
if (program.diagnostics.length > 0) {
  for (const diagnostic of program.diagnostics) console.error(formatDiagnostic(diagnostic));
  process.exit(1);
}

const root = resolve(main, "..");
const declarations = [];
const namespaces = [];
for (const type of getJsonSchemaTypes(program)) {
  const baseUri = findBaseUri(program, type);
  const extensions = Object.fromEntries(getExtensions(program, type).map(({ key, value }) => [key, value]));
  if (type.kind === "Namespace") {
    namespaces.push({ baseUri, extensions });
    continue;
  }
  const id = getId(program, type) ?? (baseUri && new URL(`${type.name}.json`, baseUri).href);
  if (!id) {
    console.error(`${type.name} has no @id and its namespace no @baseUri`);
    process.exit(1);
  }
  const location = getSourceLocation(type);
  declarations.push({ id, file: relative(root, location.file.path), position: location.pos });
}
declarations.sort((a, b) => (a.file === b.file ? a.position - b.position : a.file < b.file ? -1 : 1));
const output = {
  declarations: declarations.map(({ id, file }) => ({ id, file })),
  namespaces,
};
process.stdout.write(`${JSON.stringify(output, null, 2)}\n`);
