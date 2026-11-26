// The benchhand contracts (ADR-0017). Every message and record shape is declared here, and nowhere else.
// `just contracts` compiles this to one JSON Schema 2020-12 bundle and tools/gen/contracts_gen/normalise.py
// splits it into the published per-contract schemas, from which the models, types, validators, fixtures and
// docs are generated.
//
// Conventions:
// - One file is one published contract. Its namespace's @baseUri is ".../contracts/<dir>/<contract>/" and
//   holds the contract's $defs; the declaration whose @id is ".../contracts/<dir>/<contract>.schema.json" is
//   its root. A def-only contract (record/common, record/drawing) has `union <Name> { unknown }` as its root.
// - Objects are closed (`seal-object-schemas`); `...Record<unknown>` opens one.
// - The emitter keeps only one of two declarations with the same name, even in different namespaces, so
//   names are unique across all files. A def whose name another contract also uses gets a unique name and
//   an @id that carries the published one.
// - A TypeSpec form comes first: @minProperties on a property, a typed default (`mode?: Mode = Mode.fast`),
//   @@example (checked against the type, so an enum value is its member), and a type as an @extension
//   value where the value is one schema reference.
// - A scalar or enum used once is written where it is used, as a declaration expression
//   (`name: @minLength(1) scalar extends string`; tspconfig.yaml enables the experimental feature). One
//   used more than once, from another contract, by a member in an example or default, as a variant of a
//   union declaration, or as a template argument such as `Record<...>` (TypeSpec 1.18's checker fails
//   on a declaration expression there: ManifestTimeoutsValue, DrawingProductDrawingStandardsValue), and a
//   model or union that carries @extension values, is a declaration with `@extension("x-inline", true)`:
//   it is written in place of every reference to it.
// - JSON Schema that TypeSpec has no syntax for (if/then/else, not, dependentRequired, propertyNames on a
//   model, a oneOf of required sets, minProperties on a closed model, a schema without a type of its own
//   such as `union X { unknown }` plus keywords) is an @extension value. A $ref in one is written as it
//   is published, relative to the contract file; generation fails if it doesn't resolve.
// - Keyword order is the normaliser's KEYWORD_ORDER, which decides the first violation Python reports.
//   `@extension("x-keyword-order", #[...])` on a namespace or a schema, and "x-required-order" on a
//   model, keep an order the hand-written contracts had; the published schemas don't carry either.
// - Patterns use [0-9], never \d: tests/test_contracts.py holds them to the dialect ECMAScript and
//   pydantic's Rust regex engine read alike.

import "./common/cel.tsp";
import "./common/finding.tsp";
import "./envelope/envelope.tsp";
import "./flow/flow.tsp";
import "./flow/rules.tsp";
import "./jobs/job.tsp";
import "./policy/contribution.tsp";
import "./provider/manifest.tsp";
import "./provider/protocol.tsp";
import "./record/assembly.tsp";
import "./record/bom-row.tsp";
import "./record/bundle-manifest.tsp";
import "./record/common.tsp";
import "./record/decision.tsp";
import "./record/drawing.tsp";
import "./record/evidence-assessment.tsp";
import "./record/interfaces.tsp";
import "./record/manufacturing-capabilities.tsp";
import "./record/manufacturing-check-result.tsp";
import "./record/manufacturing-evidence.tsp";
import "./record/manufacturing-findings.tsp";
import "./record/manufacturing-guideline.tsp";
import "./record/manufacturing-materials.tsp";
import "./record/manufacturing-selection.tsp";
import "./record/part.tsp";
import "./record/policy.tsp";
import "./record/product.tsp";
import "./record/requirements.tsp";
import "./record/verification-row.tsp";
