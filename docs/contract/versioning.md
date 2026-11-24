# Contract versioning and generated code

Decision: [ADR-0017](../adr/0017-contracts.md). The JSON Schema 2020-12 files under `contracts/` are the only source of message and record shapes. Everything else is generated from them and is checked in CI.

## Generated outputs

`just contracts` reads every `contracts/**/*.schema.json` file and writes the outputs below. A new schema file is picked up without a change to the generator. Each output directory is replaced as a whole, so the outputs of a deleted schema disappear too. Each generated file names its source and says that it must not be edited.

| Output | Location | Tool |
|---|---|---|
| pydantic v2 models, one module per schema | `packages/benchhand-contracts/src/benchhand_contracts/_generated/` | datamodel-code-generator, pinned in `pyproject.toml` |
| Schema copies for the runtime validator | `_generated/schemas/` | copied byte for byte |
| Conformance fixtures | `_generated/examples/<path>.examples.json` | `tools/gen/contracts_gen/examples.py` |
| TypeScript types | `ui/shared/contracts/<path>.ts` | json-schema-to-typescript, pinned in `ui/shared/package.json` |
| Ajv standalone validators | `ui/shared/contracts/<path>.validate.js` and `.validate.d.ts` | Ajv, pinned in `ui/shared/package.json` |
| Reference pages | `docs/contract/generated/` | `tools/gen/contracts_gen/docs.py` |

The Python runtime validator is `benchhand_contracts.validate(schema_id, instance)`. The schema id is a contract's `$id`, or a `$id` with a JSON pointer fragment such as `#/$defs/InitializeParams`. A mismatch raises `ContractViolation`, which carries `pointer` (the JSON pointer to the bad value) and `schema_path` (the failing keyword). An unknown id raises `UnknownSchemaError`. `format` is an annotation on both the Python and the TypeScript side.

Rules for schema authors:

- Every file has a `$id` and an `x-version` (semver).
- A `$ref` to another file is relative to the referring file, for example `protocol.schema.json#/$defs/HookKind`. The generator refuses absolute `$ref` URIs, because the tools would fetch them over the network.
- Every `examples` entry must validate against its schema. The generator fails on one that doesn't.

## Conformance fixtures

Each `examples` block at a schema root or in a `$defs` entry becomes one case in the fixture file. The case's `schema_id` is the contract `$id`, with `#/$defs/<name>` for a definition. `valid` holds the examples as written. `invalid` holds variants of them, each with one mutation applied:

- `remove-property`: the first top-level property whose removal the schema rejects.
- `add-unknown-property`: an extra `x-conformance-unknown` property, when the schema rejects it.
- `wrong-type`: the first top-level value, or else the whole instance, replaced by a value of another JSON type.

A variant is kept only if the schema rejects it, so every `invalid` entry is known to be invalid. Each entry records the index of its source example, the mutation and the JSON pointer of the changed location.

## Drift check

`just contracts-check` runs two checks. CI runs it as a step of the `check` job, with full history so that the release tags are there.

1. **Drift.** The generator writes every output into a temporary directory, and the check fails if any file there is missing from the tree, differs from it, or is absent while the tree has it. Fix it with `just contracts` and commit the result.
2. **Breaking changes.** Each schema is compared with its version at the release tag, which is the nearest `v*` tag reachable from `HEAD`. With no such tag, the check prints that it is skipping and passes. `python -m contracts_gen breaking --base <rev>` compares with another revision.

## What counts as breaking

A change is breaking when the new schema can reject an instance that the old schema accepted, or when a published name disappears. The check walks the old and new schema in parallel through `properties`, `patternProperties`, `$defs`, `items`, `prefixItems`, `additionalProperties`, `allOf`, `anyOf`, `oneOf`, `not` and `if`/`then`/`else`, and reports these rules at each location:

| Rule | Breaking when |
|---|---|
| `schema-removed` | A schema file is deleted. |
| `definition-removed` | A `$defs` entry is removed. |
| `property-removed` | A property is removed from `properties`. |
| `required-added` | A name is added to `required` or to a `dependentRequired` list. |
| `type-narrowed` | `type` drops a type that it allowed before. `integer` to `number` is a widening. |
| `enum-added`, `enum-value-removed` | An `enum` is added, or loses a value. |
| `ref-changed`, `const-changed`, `pattern-changed`, `multipleOf-changed`, `contentMediaType-changed`, `contentEncoding-changed` | The keyword is added or its value changes. A `$ref` to a different target counts, even if the targets look alike. |
| `bound-tightened` | A `minimum`, `minLength`, `minItems` or other lower bound is added or raised; an upper bound is added or lowered; `uniqueItems` becomes `true`. |
| `schema-constrained` | `additionalProperties`, `unevaluatedProperties`, `items` or `unevaluatedItems` is added with a value other than `true` or `{}`, or a `true` schema gets constraints. |
| `schema-closed` | A schema becomes `false`. |
| `branches-reduced` | `anyOf`, `oneOf` or `prefixItems` loses a branch, or is added where there was none. |
| `constraint-added` | `allOf` gains a branch, or `not`, `if`, `contains`, `propertyNames` or `dependentSchemas` is added. |

Additive changes are minor: a new schema file, a new `$defs` entry, a new optional property, a new `enum` value, a wider type or a looser bound. This matches the compatibility rule of the [provider protocol](provider-protocol.md#9-compatibility): a new hook, feature, optional field or error code is a minor change.

The check is conservative. It doesn't follow `$ref`s into other definitions, so a change inside a definition is reported where the definition is, not where it is used. A change it reports may be harmless in context; announce it with a major bump anyway, or argue it in review.

## Version bumps

- A breaking change needs a higher major `x-version` than the schema had at the release tag, for example `1.4.0` to `2.0.0`. The check passes a schema whose major version went up, whatever else changed.
- An additive change raises the minor version. A fix that changes no accepted instance, for example a description, raises the patch version. The check doesn't enforce minor and patch bumps.
