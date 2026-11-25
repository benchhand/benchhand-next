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

TypeSpec under `contracts/` is the only source of shapes. It emits JSON Schema 2020-12 (sealed objects) and OpenAPI 3.1. Both are committed, and the JSON Schema is published.

Generated from them, never edited by hand:

| Target | Route | Score (of 29) |
|---|---|---|
| Pydantic v2 | normalised JSON Schema to `datamodel-code-generator` | 28 |
| TypeScript and Zod (UIs) | OpenAPI 3.1 to `@hey-api/openapi-ts`, configured | 28 |
| MCP tool schemas, CEL type declarations, reference docs | the emitted JSON Schema | n/a |

CI fails on any of these:
- `tsp format --check` or a compile warning;
- drift after regenerating;
- a failed OpenAPI lint or JSON Schema meta-validation;
- a conformance fixture that fails;
- a breaking change without a major version bump.

Every boundary validates at runtime, in both directions.

## Known issues and how they are handled

- **Unicode `\d`:** Pydantic's Rust regex engine treats `\d` as Unicode digits. Patterns use `[0-9]`, and a pattern lint enforces it.
- **Lowercase `t` and `z` in date-times:** the Zod route rejects them, while Ajv accepts them. The contract narrows date-time to uppercase `T` and `Z`, and a fixture pins it.
- **Dropped descriptions:** hey-api and datamodel-code-generator drop some field descriptions. A docs check lists which ones survive. The reference docs come from the JSON Schema, so no description is lost to the person reading them.
- **Schema normaliser:** a small, tested script prepares the emitted JSON Schema for the generators. It rewrites `unevaluatedProperties` to `additionalProperties` and bundle refs to `#/$defs`.
- **No validating root:** each published document schema validates its document at the root. The TypeSpec bundle is an unpublished intermediate, which the normaliser splits into one file per contract, and it refuses a contract without a root.

## Consequences

- Hand-written copies of message shapes are not allowed.
- The current JSON Schema sources move to TypeSpec in Phase 2, together with the record additions in plan sections 12a and 12b. The generated models must keep their public names, so the record service and tests don't change.
- The move kept the existing TypeScript route: json-schema-to-typescript types and Ajv standalone validators, generated from the published JSON Schema. It kept every generated name and the `benchhand_contracts` API, and needs no OpenAPI document. OpenAPI 3.1 and hey-api arrive with the first Zod consumer in the UIs.
- Rust and Go have no consumer in benchhand yet. If one appears, its routes are typify with a `jsonschema` crate pass (29 of 29) and ogen with `x-ogen-time-format` (28 of 29).
