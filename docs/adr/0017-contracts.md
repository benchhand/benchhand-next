# ADR-0017: Contracts are generated from one TypeSpec source and enforced

Status: accepted, revised 2026-11-25: the source moved from hand-written JSON Schema to TypeSpec. Source: [the approved plan](../design-plan.md), and the TypeSpec spike and format comparison in `~/personal/dev/typespec-spike` (`REPORT.md`, `research/`, and one branch per candidate).

## Context

The prototype's schemas, CLI outputs and prose drifted apart. The first fix, JSON Schema written by hand under `contracts/`, used three different generators. Writing tagged unions and reusable shapes by hand was verbose.

A spike measured TypeSpec against 29 conformance fixtures, with Ajv 2020 as the reference. Protobuf, quicktype, Smithy and Typical were then measured by the same rule (a schema, then one established generator per language) on the same fixtures and scorer. No candidate beat TypeSpec for any target:

- Smithy ties only after 8 OpenAPI overrides outside its IDL, which `smithy diff` can't see.
- Protobuf's JSON mapping can't carry a `kind`-tagged union or a key that is present but null, and its published JSON Schema doesn't compile in Ajv.
- quicktype enforces types, not value constraints.
- Typical has no JSON format.

## Decision

TypeSpec under `contracts/` is the only source of shapes. `tsp compile` emits one JSON Schema 2020-12 bundle with sealed objects. The bundle is an unpublished intermediate: a small, tested normaliser splits it into one published schema per contract, with the `$id` values and file-relative `$ref` layout of the hand-written contracts. The published schemas are committed, and every generator and validator reads them. No OpenAPI document is emitted.

Generated from the published schemas, never edited by hand:

| Target | Route |
|---|---|
| Pydantic v2 models | `datamodel-code-generator` |
| TypeScript types and validators (UIs) | `json-schema-to-typescript` types, Ajv standalone validators |
| Conformance fixtures and reference docs | `tools/gen` |
| MCP tool schemas and CEL type declarations | the published JSON Schema |

OpenAPI 3.2.0, `@hey-api/openapi-ts` for TypeScript and Zod, and a Redocly lint gate arrive with the first HTTP or Zod consumer.

CI fails on any of these:
- `tsp format --check`, or a compile warning (`--warn-as-error`);
- a schema that fails the Sourcemeta `jsonschema metaschema` check, the bundle or a published one, or a published schema that fails `jsonschema lint`;
- drift after regenerating;
- a conformance fixture that fails;
- a breaking change without a major version bump.

Every boundary validates at runtime, in both directions.

The spike's scores, of 29 fixtures, are the evidence for the routes, now and later:

| Target | Route measured | Score |
|---|---|---|
| Pydantic v2 | normalised JSON Schema to `datamodel-code-generator` | 28 |
| TypeScript and Zod | OpenAPI 3.1 to `@hey-api/openapi-ts`, configured | 28 |
| Rust | typify with a `jsonschema` crate pass | 29 |
| Go | ogen with `x-ogen-time-format` | 28 |

## Known issues and how they are handled

- **Unicode `\d`:** Pydantic's Rust regex engine treats `\d` as Unicode digits. Patterns use `[0-9]`, and a pattern lint enforces it.
- **Lowercase `t` and `z` in date-times:** the Zod route rejects them, while Ajv accepts them. The job contract's `Timestamp` has a pattern that takes an RFC 3339-shaped date-time with an uppercase `T` and an explicit offset, `Z` or numeric, and tests pin it in Python and Ajv. The pattern doesn't check calendar dates.
- **Dropped descriptions:** datamodel-code-generator, and hey-api when it arrives, drop some field descriptions. The reference docs come from the published JSON Schema, and a test fails when a description is on no page.
- **Schema normaliser:** it rewrites `unevaluatedProperties` to `additionalProperties` where that is exact, bundle refs to file-relative ones, and the emitter's keyword order to a fixed one. Python reports the first of two violations at one place in keyword order, so the order is part of the diagnostic.
- **No validating root:** each published document schema validates its document at the root. The TypeSpec bundle is an unpublished intermediate, which the normaliser splits into one file per contract, and it refuses a contract without a root.

## Consequences

- Hand-written copies of message shapes are not allowed.
- The hand-written JSON Schema moved to TypeSpec in Phase 1 without a shape change, apart from the `Timestamp` pattern. The generated models kept their public names, so the record service and tests didn't change. `tools/equiv/` holds the evidence: a decoded comparison with the hand-written schemas, and a replay of the tests' instances, the fixtures and their mutations in Python and Ajv.
- The record additions of plan sections 12a and 12b are Phase 2 work, in the design plan's Phase 2 list. They are not deferred past it.
- Rust and Go have no consumer in benchhand yet. If one appears, the spike's routes above are where to start.
