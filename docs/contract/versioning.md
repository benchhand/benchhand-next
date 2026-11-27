# Contract versioning and generated code

Decision: [ADR-0017](../adr/0017-contracts.md). The TypeSpec files under `contracts/` are the only source of message and record shapes. They compile to the published JSON Schema 2020-12 contracts, everything else is generated from those, and all of it is checked in CI.

## Generated outputs

`just contracts` compiles `contracts/main.tsp` with `tsp compile --warn-as-error` into one JSON Schema bundle, an unpublished intermediate. `tools/gen/contracts_gen/normalise.py` splits it into one published schema per contract and writes the emitter's idioms in plain form, for example `unevaluatedProperties` as `additionalProperties`. Every other output below is generated from the published schemas. A new `.tsp` file imported by `main.tsp` is picked up without a change to the generator. Everything is generated into a scratch directory first, and each output directory is then replaced as a whole, so the outputs of a deleted schema disappear too and a failed run leaves the previous outputs in place. Each generated file except the published schemas names its source and says that it must not be edited. A published schema carries only its `$id`, which names its source: `<dir>/<name>.schema.json` comes from `contracts/<dir>/<name>.tsp`.

| Output | Location | Tool |
|---|---|---|
| pydantic v2 models, one module per schema | `packages/benchhand-contracts/src/benchhand_contracts/models/` | datamodel-code-generator, pinned in `pyproject.toml` |
| Published schemas, also read by the runtime validator | `benchhand_contracts/schemas/<path>.schema.json` | `@typespec/json-schema` with sealed objects, then `tools/gen/contracts_gen/normalise.py` |
| Conformance fixtures | `benchhand_contracts/examples/<path>.examples.json` | `tools/gen/contracts_gen/examples.py` |
| TypeScript types | `ui/shared/contracts/<path>.ts` | json-schema-to-typescript, pinned in `ui/shared/package.json` |
| Ajv standalone validators | `ui/shared/contracts/<path>.validate.js` and `.validate.d.ts` | Ajv, pinned in `ui/shared/package.json` |
| Reference pages | `docs/contract/generated/` | `tools/gen/contracts_gen/docs.py` |

The Python runtime validator is `benchhand_contracts.validate(schema_id, instance)`. The schema id is a contract's `$id`, or a `$id` with a JSON pointer fragment such as `#/$defs/InitializeParams`. A mismatch raises `ContractViolation`, which carries `pointer` (the JSON pointer to the bad value) and `schema_path` (where the failing keyword is, after every `$ref`: the `$id` of the contract that holds it and a JSON pointer, such as `…/record/common.schema.json#/$defs/revision/pattern`). `benchhand_contracts.violations(schema_id, instance)` returns every `ContractViolation` instead, the one `validate` raises first. An unknown id raises `UnknownSchemaError`. The Python and the TypeScript validators agree on every instance: `format` is an annotation on both sides, `pattern` is an ECMAScript regular expression on both sides (Python uses `regress`, so `$` never matches before a trailing newline), and NaN and Infinity are rejected wherever they appear.

The models of the published `<dir>/<name>.schema.json` (source `contracts/<dir>/<name>.tsp`) are in `benchhand_contracts.models.<dir>.<name>_schema`, with `-` in a path becoming `_`, for example `benchhand_contracts.models.provider.protocol_schema`. `benchhand_contracts.Finding` is the model of `common/finding.schema.json`. The schemas and fixtures are package data, so an installed `benchhand-contracts` wheel validates without a checkout of this repository.

Rules for contract authors (`contracts/main.tsp` lists the TypeSpec conventions):

- Each `.tsp` file is one published contract. Its root declaration has the contract's `@id`, for example `…/contracts/record/part.schema.json`, and an `x-version` (semver). The namespace's `@baseUri`, `…/contracts/record/part/`, holds its `$defs`. The normaliser refuses a contract without a root, so each published document schema validates its document at the root. `record/common` and `record/drawing` are libraries of `$defs`, with a root that accepts anything.
- A published `$ref` to another file is relative to the referring file, for example `protocol.schema.json#/$defs/HookKind`. A `$ref` written by hand in an `@extension` value takes that form too, and generation fails if it doesn't resolve. The generator refuses absolute `$ref` URIs, because the tools would fetch them over the network.
- Every `examples` entry must validate against its schema, wherever the `examples` block is: at the root, in a `$defs` entry or in a nested subschema. The generator fails on one that doesn't.
- Every object shape in `provider/protocol.schema.json` has `examples`, so each message shape has conformance fixtures. A test enforces it.
- A `pattern` (and a `patternProperties` key) is written in the portable dialect, which means the same in ECMAScript with the `u` flag (Ajv, and `regress` in the Python validator) and in the Rust regex engine that pydantic uses for the generated models. The dialect is literal characters, `^`, `$`, `|`, groups `( )` and `(?: )`, the quantifiers `*`, `+`, `?` and `{n}`, `{n,}`, `{n,m}`, bracket classes with ranges, and the escapes `\n`, `\r`, `\t`, `\f`, `\v`, `\uXXXX` and a backslash before one of `^$\.*+?()[]{}|/` (or `-` inside a class). Anything else is refused, because the engines read it differently: `\d`, `\w`, `\s` and `\b` and their negations differ on non-ASCII text, `.` stops at different line breaks, and a lookaround makes pydantic check that model's patterns with Python's `re`, whose `$` also matches before a trailing newline. Write a class out instead, such as ECMAScript's whitespace set for `\s`, and state a rule that needs a lookahead as a sibling `not: {"pattern": ...}`. The generated models leave `not` out, so they never refuse a value the schema accepts. `tests/test_contracts.py` enforces the dialect.

## Conformance fixtures

Each `examples` block at a schema root or in a `$defs` entry becomes one case in the fixture file. The case's `schema_id` is the contract `$id`, with `#/$defs/<name>` for a definition. `valid` holds the examples as written. `invalid` holds variants of them, each with one mutation applied:

- `remove-property`: the first top-level property whose removal the schema rejects.
- `add-unknown-property`: an extra `x-conformance-unknown` property, when the schema rejects it.
- `wrong-type`: the first top-level value, or else the whole instance, replaced by a value of another JSON type.

A variant is kept only if the schema rejects it, so every `invalid` entry is known to be invalid. Each entry records the index of its source example, the mutation and the JSON pointer of the changed location. A case whose schema has a validation keyword must get at least one `invalid` entry; the generator fails when none of the mutations is rejected, and the fix is an example that a mutation can break. Nested `examples` blocks are validated but don't become cases, because only the root and the `$defs` entries have a TypeScript validator of their own.

## Drift check

`just contracts-check` runs these checks. CI runs it as a step of the `check` job, with full history so that the release tags are there.

1. **Format.** `tsp format --check` on every `.tsp` file.
2. **Schemas.** The Sourcemeta `jsonschema metaschema` on the bundle and the published schemas, and `jsonschema lint` on the published schemas. The `contracts-lint` recipe in the `justfile` lists each rule it leaves out, and why. The `required_properties_in_properties` findings that stay are listed by location in `tools/gen/contracts_gen/lint.py`, and any other finding fails.
3. **Drift.** The generator writes every output into a temporary directory, and the check fails if any file there is missing from the tree, differs from it, or is absent while the tree has it. Fix it with `just contracts` and commit the result.
4. **Breaking changes.** Each published schema is compared with its version at the release tag, which is the nearest `v*` tag reachable from `HEAD`. With no such tag, the check prints that it is skipping and passes. `python -m contracts_gen breaking --base <rev>` compares with another revision.

CI also runs `just contracts-drift`: it regenerates in place and fails if `git status --porcelain` lists a generated file.

The tools are pinned: TypeSpec (`@typespec/compiler` and `@typespec/json-schema` 1.18.0) and the Sourcemeta JSON Schema CLI (`@sourcemeta/jsonschema` 17.3.3) in `contracts/package.json`, and the Python and UI generators as listed above.

## What counts as breaking

A change is breaking when the new schema can reject an instance that the old schema accepted, or when a published name disappears. The check is conservative: it accepts a change only when it can show that the change widens the schema, and reports every other change to a validation keyword. Annotations (`title`, `description`, `$comment`, `examples`, `default`, `deprecated`, `readOnly`, `writeOnly`, `format` and `x-*`) never count.

The check walks the old and new schema in parallel through `properties`, `$defs`, `allOf`, `anyOf`, `items`, `additionalProperties`, `unevaluatedProperties`, `unevaluatedItems`, `propertyNames` and `then`/`else`. An absent subschema there counts as `true`, so adding `else: {"required": ["reason"]}` to a conditional is a `schema-constrained` change. It reports these rules at each location:

| Rule | Breaking when |
|---|---|
| `schema-removed` | A schema file is deleted. |
| `definition-removed` | A `$defs` entry is removed. |
| `property-removed` | A property is removed from `properties`. |
| `required-added` | A name is added to `required` or to a `dependentRequired` list. |
| `type-narrowed` | `type` drops a type that it allowed before. `integer` to `number` is a widening. |
| `enum-added`, `enum-value-removed` | An `enum` is added, or loses a value. |
| `ref-changed`, `const-changed`, `pattern-changed`, `multipleOf-changed`, `contentMediaType-changed`, `contentEncoding-changed` | The keyword is added or its value changes. A `$ref` to a different target counts, even if the targets look alike. |
| `bound-tightened` | A `minimum`, `minLength`, `minItems` or other lower bound is added or raised (an absent `minContains` is 1); an upper bound is added or lowered; `uniqueItems` becomes `true`. |
| `schema-constrained` | A subschema that accepted everything, or was absent, gets constraints, for example a new `allOf` branch, `then`, `else` or `additionalProperties` schema. |
| `schema-closed` | A schema becomes `false`, for example `additionalProperties: false` is added. |
| `branches-reduced` | `anyOf` loses a branch, or is added where there was none. |
| `constraint-added` | `oneOf`, `not`, `if`, `contains` or `dependentSchemas` is added. |
| `unproven-change` | Anything else changes, as described below. |

`oneOf`, `not`, `if`, `contains` and `dependentSchemas` are strict keywords. Removing one widens the schema. Any other change to it is `unproven-change`, even a wider subschema:

- a wider `oneOf` branch can overlap another, so an instance that matched one branch now matches two;
- `not` and `if` invert their subschema;
- `contains` is bounded by `maxContains`.

A `$defs` entry referenced from under a strict keyword, and every entry it references in turn, must stay the same apart from annotations. The exception is a `oneOf` whose branches are provably disjoint: their types don't overlap, or one branch is an object that requires a property the other can't have, because the other forbids it with `additionalProperties: false` or gives it a different `const` or `enum`. Such a `oneOf` is compared like `anyOf`. The protocol envelopes are disjoint this way, so a new `Method` value is a minor change. A keyword without a rule, such as `prefixItems` or `patternProperties`, is `unproven-change` on any change.

Additive changes are minor: a new schema file, a new `$defs` entry, a new optional property, a new `enum` value, a wider type or a looser bound. A new optional property counts as additive even when the object accepted unknown properties before, unless `additionalProperties` gave those a schema. This matches the compatibility rule of the [provider protocol](provider-protocol.md#9-compatibility): a new hook, feature, optional field or error code is a minor change.

The check doesn't follow `$ref`s into other definitions outside strict keywords, so a change inside a definition is reported where the definition is, not where it is used. A change it reports may be harmless in context; announce it with a major bump anyway, or argue it in review.

## Version bumps

Before the first release nothing is published, so a narrowing keeps its version. `jobs/job.schema.json` 1.0.0 narrowed `Timestamp` this way when the contracts moved to TypeSpec: a `pattern` now refuses a lowercase `t` or `z` and a space for the `T` (ADR-0017), where `format: date-time` alone was an annotation that accepted any string. `just contracts-equivalence` shows that this is the only change in what the contracts accept. With the pattern taken out, the published schemas give the hand-written verdict on each of the 186,516 instances, 522 replayed and 185,994 mutants: the same list of violations in Python, and the same validity and first error in Ajv. The results are in `tools/equiv/results/`. The recipe is migration evidence against the hand-written contracts at `41598c2`, so it runs on demand and is not a CI gate: a later contract change rightly differs from them.

`record/policy.schema.json` 1.1.0 added the optional `rigor`, `standard` or `regulated`, where an absent value means `standard`. The change is additive, so it raised the minor version.

`record/part.schema.json` 1.1.0 added the optional `render`, `shown`, `ghost` or `hidden`, where an absent value means `shown` (prototype PR #332). The change is additive, so it raised the minor version.

`record/part.schema.json` 1.2.0 lets a purchase name a commodity designation (prototype PR #331). `purchase` gains the optional `designation` and `reference_catalogue`, and `identity` leaves `required`. An `anyOf` asks for `identity` or `designation` instead. The breaking-change check reports a new `anyOf` as `branches-reduced`. The change still widens the schema: every purchase that 1.1.0 accepted names an `identity`, so it meets the first branch. With no release tag reachable the check skips, so the widening is argued here and raises the minor version. The new `designation` definition is a `oneOf` whose two branches differ in their `kind` constant, so they are disjoint.

`record/common.schema.json` 1.1.0 widened the `obligation_id` pattern: a part anchor can now carry an `@occurrence` after its PN and a `:region` after its `#feature`, so two checks of one part at different occurrences or regions get different ids. Every id the pattern accepted before, it still accepts. The breaking-change check reports any changed `pattern` as `pattern-changed`. With no release tag reachable it skips, so the widening is argued here and raises the minor version.

`provider/protocol.schema.json` 1.1.0 added the `cad-app/unfold` method, with `CadAppUnfoldParams` and `CadAppUnfoldResult` (CAD-libraries decision D-44). A new hook is a minor change (provider protocol, section 9), so the protocol version stays 1.

- A breaking change needs a higher major `x-version` than the schema had at the release tag, for example `1.4.0` to `2.0.0`. The check passes a schema whose major version went up, whatever else changed.
- An additive change raises the minor version. A fix that changes no accepted instance, for example a description, raises the patch version. The check doesn't enforce minor and patch bumps.

## Provisional contracts

`record/bundle-manifest.schema.json` (version `0.1.0`) is provisional. It holds only the keys of a sealed directory's `manifest.json` that the evidence service reads: `files`, `version_manifest_sha256` and each built part's `source_sha256`. It accepts every other key unread. Phase 2's versioning work (snapshot, seal and verify) owns it and extends it, and gives it version `1.0.0` when it is complete.

`envelope/envelope.schema.json` (version `0.1.0`) is provisional. It is the result of every MCP tool call ([result envelope](envelope.md)). Phase 2 fills its `next_actions` from the flow engine, and Phase 3 gives each tool's `payload` its own schema. Version `1.0.0` comes with the MCP tools.

`flow/flow.schema.json` (version `0.1.0`) is provisional. It is the shape of `flow.yaml` ([flow definition](flow.md)), and Phase 2 writes the file and its interpreter. Its `ApprovalScope`, `ApprovedItem`, `ApprovedItemState` and `reapproval_scope` carry `x-status: provisional` as well, because Phase 2's scoped approvals (ADR-0019) own them. `GateDecisionRequest.channel` refers to the decision record's channel, written in place in `record/decision.schema.json`, so the decision schema didn't change. Its `by` and `quote` are `NonblankText`, defined in `flow/flow`, so `record/common`'s `text` didn't change either. `flow/rules.schema.json` (version `0.1.0`) is provisional too. It is the shape of a `*.celpolicy` rule-list file in the restricted cel-policy profile of ADR-0020. `flow.yaml` and a policy contribution refer to these files by kind. On 2026-11-27 it gained a choice's optional `explanation`, on every choice of a list or on none. No release tag reachable from `HEAD` holds the schema, so the breaking-change check skips it. Version `0.1.0` was never published, and the schema stays at `0.1.0`.

`common/cel.schema.json` (version `0.1.0`) is provisional. It is the one CEL expression type (ADR-0014). Every CEL field refers to it by `$ref`, which is how the flow interpreter finds the expressions, and the generator refuses a string or a list of strings whose description says CEL. The type has no `format`: `jsonschema lint` refuses a format outside the specification, prefixed or not.

`policy/contribution.schema.json` (version `0.1.0`) is provisional. It is what a policy provider adds to the flow ([policy](policy.md#provider-contributions)). Phase 2 builds the merge in the flow interpreter, in the composition the owner decided on 2026-11-27 (ADR-0020, "Open items"), and the provider protocol's `policy/evaluate` result doesn't refer to it yet.

## The acceptance digest

The v3 acceptance digest (`evidence_sha256` of `record/evidence-assessment`) covers every source artifact the record names. It also covers the files the prototype's digest covers: the ledgers, `verification.csv`, cited artifacts and bundle manifests, the sealed packet manifests, and every file under `hw/manufacturing/sources/`. The prototype's digest covers only the artifacts that its source readers collect, so a bought part's procurement specification falls outside it. A v3 digest is therefore not byte-compatible with a prototype digest. That is safe: migrate refuses a frozen record whose digest inputs change, and a v3 freeze records a new digest.
