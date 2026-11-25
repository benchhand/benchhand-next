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
// - A declaration with `@extension("x-inline", true)` is written in place of every reference to it. It
//   gives a schema that the hand-written form had inline a place to carry decorators.
// - JSON Schema that TypeSpec has no syntax for (if/then/else, not, dependentRequired, propertyNames, a
//   schema without a type of its own such as `union X { unknown }` plus keywords) is an @extension value.
//   A $ref in one is written as it is published, relative to the contract file; generation fails if it
//   doesn't resolve.
// - Patterns use [0-9], never \d: tests/test_contracts.py holds them to the dialect ECMAScript and
//   pydantic's Rust regex engine read alike.

import "./common/finding.tsp";
import "./jobs/job.tsp";
import "./provider/manifest.tsp";
import "./provider/protocol.tsp";
import "./record/assembly.tsp";
import "./record/bom-row.tsp";
import "./record/common.tsp";
import "./record/decision.tsp";
import "./record/drawing.tsp";
import "./record/interfaces.tsp";
import "./record/manufacturing-capabilities.tsp";
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
