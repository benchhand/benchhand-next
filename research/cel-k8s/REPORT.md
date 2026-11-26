# How Kubernetes uses CEL, and what benchhand should adopt

Status: research only. Written 2026-11-26 in a worktree of benchhand-next. Nothing in this report is implemented, and no Kubernetes code was run.

## Verdict

Kubernetes solves the problem the CEL spike hit by never typing a union. Its schema model splits a schema into a type skeleton and a set of value validations. CEL types come from the skeleton only. `oneOf`, `anyOf`, `allOf` and `not` sit in the value-validation half, and the structural-schema rules forbid them from adding fields or types. The one sanctioned escape is `x-kubernetes-int-or-string`, which becomes CEL `dyn`, and every use of it needs a `type()` guard.

benchhand can take the same shape. Rule scopes (the activation schemas) should be structural by construction, and a loader check should reject a union on a path that a rule can reach. Most of the rest of the Kubernetes design carries over with small changes. Two parts do not carry over directly:

- **Environment versions.** Kubernetes picks the older environment by comparing a rule to the object already in storage. benchhand has no stored object to compare against, so it needs a declared profile in each rules file.
- **Static cost estimation.** Kubernetes uses cel-go's cost checker. `cel-expr-python` exposes no cost API (see section 3), so the estimator is a decision, not a free port.

### The five most important findings

1. **Unions are a skeleton problem, not a CEL problem.** `SchemaDeclType` reads only `type`, `properties`, `items`, `additionalProperties`, `format`, `enum` and the length bounds. Structural rules 2 and 3 force every field and every `type` to appear outside `oneOf`, `anyOf`, `allOf` and `not`. A Kubernetes union is a flat object of optional members plus a discriminator (KEP-1027). Sources: `apiserver/pkg/cel/common/schemas.go`; `apiextensions-apiserver/pkg/apiserver/schema/validation.go` lines 324 to 341; KEP-2335; KEP-1027.
2. **Two environments, chosen per expression.** `NewExpressions` is the environment at the compatibility version, and `StoredExpressions` is the superset. On update, an expression whose exact text exists in the old object compiles in the stored environment, and any other expression compiles in the new one. Runtime evaluation always uses the stored environment. Sources: `apiserver/pkg/cel/environment/environment.go`; `apiextensions-apiserver/pkg/apis/apiextensions/validation/validation.go` (`preexistingExpressions`); KEP-2876 "Function Library Updates".
3. **Cost is estimated from schema bounds, then multiplied by collection cardinality.** A missing `maxItems` or `maxLength` falls back to a bound derived from the 3 MiB request limit. Limits: 10,000,000 per rule and 100,000,000 per CRD at write time, then 1,000,000 per call and 10,000,000 per resource at runtime. Sources: `apiextensions-apiserver/pkg/apiserver/schema/cel/compilation.go`; `apiserver/pkg/apis/cel/config.go`; KEP-2876 "Estimated Cost Limits".
4. **Compile errors are structured field errors, and a rule never silently passes.** Each error carries the schema path of the rule (`...x-kubernetes-validations[0].rule`) and the cel-go issue text with a caret. CEL compilation is skipped when the schema itself has errors. A rule that fails to compile at runtime becomes a validation error on every request. A broken `messageExpression` does not disable its rule. Sources: `apiextensions-apiserver/pkg/apis/apiextensions/validation/validation.go` lines 1270 to 1320; `apiextensions-apiserver/pkg/apiserver/schema/cel/validation.go` (`validateExpressions`).
5. **Ratcheting is narrow on purpose.** A failure of a rule that does not use `oldSelf` becomes a warning when the failing subtree equals its old value (`DeepEqual`). Transition rules never ratchet, and nothing under `oneOf`, `anyOf` or `not` ratchets. The escape hatch is `optionalOldSelf`, which gives the rule an optional `oldSelf` so the author writes the grandfathering by hand. Sources: `apiextensions-apiserver/pkg/apiserver/schema/cel/validation.go` (`addErr`, `ratchetingOptions`); KEP-4008; CRD docs "Validation ratcheting".

benchhand already has a better ratchet key than `DeepEqual`. ADR-0019 records a fingerprint for every approved item, so a tightened rule can be ratcheted per item.

## Source snapshot

- Code paths are relative to `staging/src/k8s.io/` in `kubernetes/kubernetes`, `master` at `352bac4` when fetched. Paths outside staging start with `pkg/`.
- KEPs are in `kubernetes/enhancements`, `keps/sig-api-machinery/` unless noted: 2335 (structural schemas), 2876 (CRD validation rules), 3488 (ValidatingAdmissionPolicy), 3962 (MutatingAdmissionPolicy), 4008 (ratcheting), 1027 (unions), and `keps/sig-architecture/4330-compatibility-versions`.
- Docs are in `kubernetes/website` `content/en/docs/`: `reference/using-api/cel.md`, `tasks/extend-kubernetes/custom-resources/custom-resource-definitions.md`, `reference/access-authn-authz/validating-admission-policy.md`, and `mutating-admission-policy.md`.
- Where the docs and the code disagree, the report follows the code and says so.
- benchhand context: `docs/design-plan.md` section 5, ADR-0014, ADR-0017, ADR-0019, and `research/cel-spike/REPORT.md` on commit `47bc436`.

## 1. Schema to CEL types

### The pipeline

- A CRD carries an OpenAPI v3 schema. `apiextensions-apiserver/pkg/apiserver/schema/structural.go` converts it to a `Structural` value (`NewStructural`, `convert.go`) and rejects it if it is not structural (`validation.go`, `ValidateStructural`).
- `apiextensions-apiserver/pkg/apiserver/schema/cel/model/schemas.go` wraps `Structural` in an adaptor and calls `common.SchemaDeclType`.
- `apiserver/pkg/cel/common/schemas.go` holds the real conversion. It works on a small `Schema` interface (`apiserver/pkg/cel/common/adaptor.go`), so the same code serves a CRD's `Structural` and an `openapi.Schema` from kube-openapi (`apiserver/pkg/cel/openapi/adaptor.go`). ValidatingAdmissionPolicy type checking uses the second route.
- The result is a `DeclType` (`apiserver/pkg/cel/types.go`), which becomes a CEL type plus a field table. `apiserver/pkg/cel/common/typeprovider.go` registers it so cel-go's checker resolves `self.spec.replicas`.
- Each rule sees one typed variable, `self`, bound to the schema node that holds the rule. `oldSelf` is a second variable of the same type. The type name is `selfType<nanoseconds>`, regenerated on every compile so no rule can depend on it (`generateUniqueSelfTypeName` in `compilation.go`).

### Type mapping, as implemented

| OpenAPI | CEL | Where |
|---|---|---|
| object with `properties` | message type with a field table | `SchemaDeclType`, case `object` |
| object with `additionalProperties` | `map<string, V>` | same |
| array | `list<T>` | same, case `array` |
| `string` | `string` | same, case `string` |
| `string` with `format` `byte`, `duration`, `date`, `date-time` | `bytes`, `duration`, `timestamp`, `timestamp` | same |
| `integer` (any format) | `int` | same |
| `number` (any format) | `double` | same |
| `boolean` | `bool` | same |
| no `type`, or an unknown type | no CEL type; the field is left out | `SchemaDeclType` returns `nil` |
| `x-kubernetes-int-or-string` | `dyn` | start of `SchemaDeclType` |

### Why structural schemas exist

KEP-2335 gives the reason in two lines. OpenAPI "makes a fantastic output format able to describe anything, but a poor input format, because there's not 'one correct way' to do a given thing". Logical operators such as `not(anyOf(oneOf ...))` make "advanced CRD features difficult or even impossible to implement". The features it names are pruning, defaulting, server-side apply and OpenAPI publishing. CEL typing (KEP-2876) came later and depends on the same restriction.

The rules, from the CRD docs section "Specifying a structural schema" and the checks in `apiextensions-apiserver/pkg/apiserver/schema/validation.go`:

1. Every node has a non-empty `type`: the root, each object field (`properties`, `additionalProperties`) and each array item. Exceptions: a node with `x-kubernetes-int-or-string: true` and a node with `x-kubernetes-preserve-unknown-fields: true`.
2. Every field and item inside `allOf`, `anyOf`, `oneOf` or `not` must also be declared outside them.
3. `description`, `type`, `default`, `additionalProperties` and `nullable` may not be set inside those junctors. The error text is `must be empty to be structural`, `must be undefined to be structural` or `must be false to be structural`, each with the schema path (lines 324 to 341).
4. If `metadata` is specified, only `metadata.name` and `metadata.generateName` may be restricted.

An existing non-structural CRD keeps working. The check ratchets: `requireStructuralSchema(oldCRDSpec)` returns false when the stored spec is already non-structural, and the CRD gets a `NonStructuralSchema` condition (KEP-2335 summary; `validation.go` near line 158 in the KEP-4008 excerpt).

The consequence for rules: the only schema parts a rule can name are the ones on the skeleton. A `oneOf` branch can add a `required` or a `minimum`, but never a field. `schema.StripValueValidations()` in `apiextensions-apiserver/pkg/apiserver/schema/skeleton.go` is the code form of the split.

### Corner cases

**int-or-string.** The type is `dyn`, so the checker accepts any operation on it and errors appear at runtime. The code comment in `schemas.go` says "all access to values of this type must be guarded with a type check", for example `type(x) == string ? x.matches(...) : x < 5`. The runtime error for a wrong guess is `no such overload`, and `validation.go` (apiextensions `schema/cel`) rewrites it to "call arguments did not match a supported operator, function or macro signature ... This error can only occur when static type checking has been bypassed. int-or-string is typed as dynamic". The docs call the type a "union of int or string"; the code is `dyn`.

**preserve-unknown-fields.** `SchemaDeclType` ignores the flag ("we don't support validation rules on data we don't have schema information for"). Unknown keys are not reachable. A property with no type, and an array or map whose element type is unknown, are left out of the parent's field table, so a rule that names them fails with `undefined field`. KEP-2876 "Type System Integration" gives three reasons: no types or formats, unvalidated contents that make rules unsafe, and a ban on validating an embedded type without letting its author write rules on it.

**Embedded resources.** `x-kubernetes-embedded-resource` and the resource root get `kind`, `apiVersion`, `metadata.name` and `metadata.generateName` even if the schema omits them (`WithTypeAndObjectMeta`). Both name fields are capped at 253 characters (`cappedLengthStringType`) so the cost estimate stays bounded. No other `metadata` field is visible.

**list-type map and set.** The DeclType is still a plain `list<T>`. The list type acts at the value level: `UnstructuredToVal` (`apiserver/pkg/cel/common/valuesunstructured.go`, near line 109) builds a set-valued or map-valued list. Equality ignores order, and `+` is a union (set) or a keyed merge (map). KEP-2876 explains why a keyed list is not a CEL `map`: a key spans several fields, order matters to some users, and the checker could not type a composite key. `makeMapList` (`apiextensions-apiserver/pkg/apiserver/schema/cel/maplist.go`) uses the same keys to correlate old and new items for `oldSelf` and ratcheting.

**nullable.** Nullability is not in the DeclType. Three value-level rules apply:
- A `null` under a property of an object is treated as absent (`unstructuredMap.Find`, same file near line 702).
- A rule is only evaluated on a non-null value; the code comment in `validateExpressions` says a rule that needs to see the null must sit on the parent.
- `UnstructuredToVal(nil)` returns CEL `null` only if the schema is nullable, and an error otherwise.

**Absent optional fields.** Selecting an absent field is a runtime error (`no such key`), so rules guard with `has()`. The CEL docs add that `has()` is for fields and `in` is for map keys. This is the opposite of the `cel-expr-python` behaviour the spike measured (a protobuf default instead of an error).

**Property names.** Only names of the form `[a-zA-Z_.-/][a-zA-Z0-9_.-/]*` are visible, with `__dash__`, `__dot__`, `__slash__`, `__underscores__` and `__{keyword}__` escapes (`apiserver/pkg/cel/escaping.go`). A name that cannot be escaped is dropped from the field table.

## 2. Compile-time checks

### When rules compile

- CRD create and update run `ValidateCustomResourceDefinition` and `ValidateCustomResourceDefinitionUpdate` (`apiextensions-apiserver/pkg/apis/apiextensions/validation/validation.go`). `ValidateCustomResourceDefinitionOpenAPISchema` walks the schema. At each node with `x-kubernetes-validations` it calls `cel.Compile` (line 1277) with the type information for that node (`CELSchemaContext` in `cel_validation.go`).
- The API server then builds a runtime `Validator` for the CRD (`NewValidator`, `apiextensions-apiserver/pkg/apiserver/schema/cel/validation.go`). It recompiles every rule in the stored environment. The comment says compilation "is pre-checked at CRD creation/update time, so we don't expect compilation to fail"; if it does, "it is an internal bug".
- ValidatingAdmissionPolicy and MutatingAdmissionPolicy compile at create and update through `pkg/apis/admissionregistration/validation/validation.go` (`validateValidation`, `validateMessageExpression`, `validateVariable`, `validateMatchConditionsExpression`, `validateAuditAnnotation`). Each calls `Compiler.CompileCELExpression` (`apiserver/pkg/admission/plugin/cel/compile.go`).

### What is checked per rule

In `compileRule` (`apiextensions-apiserver/pkg/apiserver/schema/cel/compilation.go`), in order:

1. An empty rule is skipped. The schema check reports it separately as `Required: rule is not specified`.
2. `Env.Compile` parses and type-checks. Failures return `compilation failed: <cel-go issues>`.
3. The output type must be `bool`: `cel expression must evaluate to a bool`.
4. The checked AST is scanned for a reference to `oldSelf`, which sets `UsesOldSelf`. That flag drives transition and ratchet behaviour.
5. A program is built with a per-call cost limit and cost tracking.
6. The static cost is estimated (section 3).
7. If `messageExpression` is set, steps 2 to 6 repeat with a `string` output type.
8. If `fieldPath` is set, it is parsed and checked against the schema (`ValidFieldPath`).

The ValidatingAdmissionPolicy compiler takes a list of allowed output types per expression (`ExpressionAccessor.ReturnTypes()`), with messages `must evaluate to bool but got string`.

### How errors are reported

- Each failure becomes a `field.Error` (`k8s.io/apimachinery/pkg/util/validation/field`) with a path, an error type and a detail. `apiservercel.Error` has the types `RuleInvalid`, `RuleRequired` and an internal type (`apiserver/pkg/cel/errors.go`).
- Paths point at the rule: `spec.validation.openAPIV3Schema.properties[spec].properties[foo].x-kubernetes-validations[0].rule`, or `...[0].messageExpression`, `...[0].fieldPath`, `...[0].optionalOldSelf`. For ValidatingAdmissionPolicy it is `spec.validations[0].expression`.
- The detail for a syntax or type error is the cel-go issue text, which includes line and column and a caret. The ValidatingAdmissionPolicy docs show it:

  ```
  apps/v1, Kind=Deployment: ERROR: <input>:1:7: undefined field 'replicas'
   | object.replicas > 1
   | ......^
  ```

- All errors from one request are returned together, not just the first. Schema errors and CEL errors travel in separate lists (`OpenAPISchemaErrorList`). If any schema error exists at or below a node, CEL compilation for that node is skipped. The comment gives the reason: an invalid schema may not convert to a valid DeclType, and the resulting CEL errors "are not actionable (will go away once the schema errors are resolved)".
- A rule with a static problem that is not a compile error also has its own error and path. Examples: `oldSelf cannot be used on the uncorrelatable portion of the schema within <path>`, `optionalOldSelf may not be set if oldSelf is not used in rule`, a `reason` outside the supported set, `fieldPath must be a valid path`, `message must not contain line breaks`, and `message must be specified if rule contains line breaks` (`validation.go` lines 1230 to 1262).

### Rules that fail to compile later

- At write time the request is rejected. There is no way to store a rule that fails in the new environment.
- At runtime the `Validator` keeps the failed `CompilationResult`. For each evaluation it adds `field.Invalid(path, type, "rule compile error: ...")` and moves to the next rule. A failure of the whole compile step adds `rule compiler initialization error`. Evaluation never treats a broken rule as satisfied.
- For policies, `validator.compileError` produces one `EvalError` decision per request. The policy's `failurePolicy` then decides: `Fail` denies, `Ignore` admits (`apiserver/pkg/admission/plugin/policy/validating/validator.go`, `policyDecisionActionForError`). `matchConditions` follow the same rule, with one extra: a condition that evaluates to `false` skips the policy even if another condition errored.
- A `messageExpression` that fails to compile reports `MessageExpressionError` at write time, and the rule itself still compiles and runs. At runtime a failing `messageExpression` falls back to `message`, then to `failed rule: <rule>`.

## 3. Cost

### Static estimate at write time

- cel-go's `Env.EstimateCost(ast, estimator)` returns a min and max cost for the checked AST. Kubernetes supplies a `CostEstimator` (`apiserver/pkg/cel/library/cost.go`) for its own functions, and a `sizeEstimator` in `compilation.go`. The size estimator walks the schema along the AST path of each collection or string and returns that node's `MaxElements`.
- `MaxElements` comes from `SchemaDeclType` (`apiserver/pkg/cel/common/schemas.go`):
  - `maxLength` times 4 for strings. OpenAPI counts code points, and each can take up to four bytes.
  - `maxItems` for arrays and `maxProperties` for maps.
  - Without a bound, an estimate from the 3 MiB request limit: `(3 MiB - 2) / (minSerializedSize + 1)` for arrays, and `(3 MiB - 2) / (minSerializedSize + 6)` for maps.
  - `minSerializedSize` of an object is 2 plus, for each required field without a default, `len(name) + minSize(field) + 4`. Large item objects therefore allow fewer worst-case items.
  - Enums use the longest value. Formatted strings (`date-time`, `duration`) use fixed sizes from `apiserver/pkg/cel/limits.go`.
- A rule that sits under a collection is multiplied by the collection's maximum cardinality (`CELSchemaContext.childContext`, `getExpressionCost`, `multiplyWithOverflowGuard`). Nested lists therefore multiply. The CRD docs call this out: "Avoid nested lists and maps if possible where validation rules are used".
- The test for failure, in the CRD validation code:

  | Limit | Value | Where |
  |---|---|---|
  | per rule or `messageExpression`, after cardinality | 10,000,000 | `StaticEstimatedCostLimit` |
  | per CRD, sum of all rules | 100,000,000 | `StaticEstimatedCRDCostLimit` |

  Over the per-rule limit, the error is `field.Forbidden` at the rule path. The message, from `getCostErrorMessage`, names the factor over the limit and reads "more than 100x" past two orders of magnitude. It suggests `maxItems`, `maxProperties` and `maxLength`. Over the CRD limit, the four most expensive rules (those above 1% of the limit) are listed as contributors, plus one error at `openAPIV3Schema`.
- An update that leaves a version's schema unchanged skips the per-rule check (`suppressPerExpressionCost`), so a control-plane upgrade cannot reject an object that was accepted before.
- KEP-2876 "Estimated Cost Limits" explains the design. A static cost knows nothing about the data, so list sizes are unknown. The authors measured real evaluation time: iterating a 1,572k-element list takes under 2 s, and a list of 30k hundred-byte elements takes about 35 ms, each with a 5x safety factor. They concluded the 3 MiB request cap bounds every O(n) loop, so most rules need no `maxItems`, while O(n squared) rules are rejected unless the author adds bounds.

### Runtime budgets

All numbers are constants in `apiserver/pkg/apis/cel/config.go`:

| Constant | Value | Meaning |
|---|---|---|
| `PerCallLimit` | 1,000,000 | cost limit per expression evaluation; "roughly 0.1 second" |
| `RuntimeCELCostBudget` | 10,000,000 | budget across all rules for one custom resource or one policy binding evaluation; "roughly 1 second" |
| `RuntimeCELCostBudgetMatchConditions` | 2,500,000 | budget for match conditions, per webhook or per binding |
| `CheckFrequency` | 100 | comprehension iterations between context-cancellation checks |
| `MaxRequestSizeBytes` | 3 MiB | bound behind the size estimates |
| `MaxEvaluatedMessageExpressionSizeBytes` | 5 KiB | longest accepted `messageExpression` result |

- The runtime counter uses the same cost model as the estimate, but it counts branches and loop iterations that actually ran (KEP-2876 "Runtime Cost Budget").
- `Validator.validate` subtracts each rule's actual cost from the remaining budget. When the budget runs out, it adds `validation failed due to running out of cost budget, no further validation rules will be run` and returns a negative budget, which stops the walk (`validateExpressions`).
- An evaluation that hits the per-call limit stops the whole run with `call cost exceeds limit for rule`.
- `messageExpression` evaluation draws from the same remaining budget. The Go context carries request cancellation into evaluation.
- The validating policy path has no write-time estimate. A search of `apiserver/pkg/admission` found no `EstimateCost` call. It has only the runtime budget, passed as `runtimeCELCostBudget` into `ForInput`. KEP-3488 explains why: estimated cost cannot be offered for admission "with any kind of guarantees attached" while types are not enforced, and it says no estimated-cost enforcement is planned.
- Cost is part of the compatibility contract. `celcoststability_test.go` pins the exact actual cost of many expressions (for example `self.val1 == self.val6` costs 5), because a changed cost model could push a stored rule over budget.
- The base environment also pins `cel.CostModelVersion(0)` and `PresenceTestHasCost(false)` (`apiserver/pkg/cel/environment/base.go`).

### What benchhand has to decide

The Python binding that the plan names exposes no cost or limit API. The binding's type stubs, `cel_expr_python/cel.pyi` on `main` in `cel-expr/cel-python`, list `compile`, `eval`, `serialize`, `return_type`, an `Options` class that holds only `enable_pratt_parser`, and nothing for cost, iteration limits or depth. This was read from the stubs and not run. Static estimation would therefore have to be written in benchhand, which is why section "What benchhand should adopt" marks it adapt, not adopt.

## 4. Environment versioning

### The two environments

`apiserver/pkg/cel/environment/environment.go` defines:

- `NewExpressions`: "used to validate new or modified expressions in requests that write expressions to API resources". It is compatible with one Kubernetes major.minor version, "to ensure safe rollback".
- `StoredExpressions`: "used to compile and run CEL expressions that have been persisted to storage". It is "the most permissive environment available", compatible with all known versions.

An `EnvSet` holds both. It is built from `VersionedOptions`, each with:

- `IntroducedVersion`, and an optional `RemovedVersion`;
- `EnvOptions` (variables, libraries, language settings), `ProgramOptions` (cost limit, optimizations) and `DeclTypes`;
- an optional `FeatureEnabled` gate that applies to `NewExpressions` only.

`Extend` builds `newExpressions` with the options whose version window includes the compatibility version, and `storedExpressions` with a version of `MaxUint`. Everything introduced is present in the stored environment, and anything removed is gone.

### The compatibility version

- `DefaultCompatibilityVersion()` in `base.go` returns the API server's `MinCompatibilityVersion()`. KEP-4330 turned this into `N-1` of the binary version. The doc comment says a value older than `n-1` "indicates a wider range of version compatibility", and a value equal to the current version means "fast forward CEL features that can be used when rollback is no longer needed".
- KEP-4330 "CEL Environment Compatibility Versioning": a change is available for stored expressions "one version before they are allowed to be written by new expressions". It calls CEL versioning "a special case of validation ratcheting".
- The three-release rule in KEP-2876 "Function Library Updates": release N-1 knows nothing of the change, release N accepts it in stored expressions but not in new ones, release N+1 accepts it everywhere.

### Choosing the environment

- On create, every expression compiles in `NewExpressions`.
- On update, `findPreexistingExpressions` collects the rule and `messageExpression` strings from the old object into sets. `preexistingExpressions.RuleEnv` returns the stored environment if the string is in the set and the new one otherwise. The same pattern covers every expression field of the policy kinds (`validation.go` lines 1009, 1085, 1098, 1113, 1140 in `pkg/apis/admissionregistration/validation`).
- At runtime `NewValidator` uses `StoredExpressionsEnvLoader`.
- KEP-2876 records the alternative it rejected: each rule declares its own version. The stated cost is that "the API server would need to contain multiple versions of the CEL compiler, or it would need a compiler that can be configured to compile a CEL expression according to the language rules of an older version". Kubernetes sidesteps this because the two environments are the same compiler with different option sets.

### What the version gates

From `baseOpts` in `base.go` (versions are the code's `IntroducedVersion`; the docs table is a release behind for a few libraries, for example it lists IP and CIDR at 1.31):

| Introduced | Item |
|---|---|
| 1.0 (always) | homogeneous aggregate literals, UTC default time zone, eager declaration validation, cost model 0, `urls`, `regex`, `lists` v0, strings v0 |
| 1.27 | `authz` |
| 1.28 | cross-type numeric comparisons, optional types, `quantity` |
| 1.29 | AST validators for duration, timestamp, regex and aggregate literals; strings v2; `ext.Sets` |
| 1.30 | `ip`; `cidr` v0 |
| 1.31 | `format`; authz selectors |
| 1.32 | two-variable comprehensions |
| 1.33 | `semver` |
| 1.34 | `ext.Lists` |
| 1.37 | `lists` v1 (v0 removed) |
| 1.38 | `cidr` v1 (v0 removed) |

A library upgrade sets the old library's `RemovedVersion` to the new library's `IntroducedVersion`. The code comment requires the new library to be backward compatible. Language-level behaviour is pinned by options in the always-on entry: `cel.CostModelVersion(0)`, `cel.StrictTimestampParsing(false)` (restores parsing that stored expressions rely on), `cel.ExpressionNodeLimit(-1)`, and `PresenceTestHasCost(false)`. Each one cancels a cel-go upgrade that would have changed old behaviour.

### Guard tests

- `apiserver/pkg/cel/library/library_compatibility_test.go` keeps a hard-coded list of every function name per Kubernetes version. Adding a function without editing the list fails the test, which forces a version decision. A warning in the test points at KEP-2876.
- `apiserver/pkg/cel/environment/base_test.go` (`TestLibraryCoverage`, `TestKnownLibraries`) checks that each `VersionedOptions` has `Introduced < Removed` and that every library is registered.
- `environment_test.go` runs a matrix of (version, environment type) cases.
- `environment.UnversionedLib(...)` wraps a library constructor so the build breaks if the library later gains a version parameter. The comment explains: the default would otherwise move to the latest version "without controlled rollout".

## 5. Libraries

### How a library is declared

Each library in `apiserver/pkg/cel/library/` implements the `Library` interface in `libraries.go`: a `cel.SingletonLibrary` (`LibraryName()`, `CompileOptions()`, `ProgramOptions()`), a `Types()` list of opaque CEL types it adds, and a `declarations()` map from function name to overloads. `KnownLibraries()` lists them, which is what the compatibility test iterates. Library names all start with `kubernetes.` (the test enforces it). Versioned libraries take a functional option, for example `library.Lists(library.ListsVersion(1))`. Library code supplies call costs to the estimator (`cost.go`). A flag, `panicOnUnknown`, makes the estimator panic on an unrecognised function in unit tests.

### The libraries

| Library | Functions and types | Source file |
|---|---|---|
| lists | `isSorted`, `sum`, `min`, `max`, `indexOf`, `lastIndexOf`, `includes` (v1) | `lists.go` |
| regex | `find`, `findAll` | `regex.go` |
| urls | `url`, `isURL`, `getScheme`, `getHost`, `getHostname`, `getPort`, `getEscapedPath`, `getQuery` | `urls.go` |
| quantity | `quantity`, `isQuantity`, `add`, `sub`, `compareTo`, `isLessThan`, `isGreaterThan`, `asInteger`, `asApproximateFloat`, `sign`, `isInteger` | `quantity.go` |
| ip | `ip`, `isIP`, `family`, `isLoopback`, `isGlobalUnicast`, `isUnspecified`, link-local checks, `isCanonical` | `ip.go` |
| cidr | `cidr`, `isCIDR`, `containsIP`, `containsCIDR`, `masked`, `prefixLength`, `ip` | `cidr.go` |
| format | `format.named`, `format.dns1123Label()` and the other named formats, `Format.validate(string)` returning an optional list of errors | `format.go` |
| authz | `authorizer.group().resource().namespace().name().check(verb).allowed()`, `reason()`, `errored()`; selectors (`fieldSelector`, `labelSelector`) | `authz.go` |
| semver | `semver`, `isSemver`, `major`, `minor`, `patch` | `semverlib.go` |
| jsonpatch | `jsonpatch.escapeKey`, for mutating policies | `jsonpatch.go` |

Two points matter for benchhand:

- The `format` library exists so that a `messageExpression` can explain why a string is invalid, for example by returning `format.dns1123Label().validate(self.name)`. The docs say so directly.
- Kubernetes keeps the list short. KEP-2876 sets the bar: "Improving ease-of-use at the cost of fragmentation / incompatibility with older servers is not a good trade-off."

## 6. Rule features

All fields below are on `x-kubernetes-validations` items in a CRD schema; the policy kinds have close analogues.

### message and messageExpression

- `message` is a static string, trimmed. The schema check rejects an empty value and any line break (`message must not contain line breaks`). It must be present if the rule text has line breaks.
- `messageExpression` is a CEL expression with the same variables as `rule` and a `string` result type, checked at write time. `messageExpression` wins when both exist. If it errors, returns an empty string, returns a string with a line break, or exceeds 5 KiB, the static `message` is used, and failing that `failed rule: <rule>`. The error is only logged, at verbosity 2.
- A `messageExpression` that runs out of budget stops all further rules. In `evalMessageExpression`, an out-of-budget result has type `Invalid` and returns a negative budget.
- Rule and message share one environment, so both can call the `format` library.
- Policies add a third level: the final fallback is `failed expression: <expression>`.

### reason

`reason` is an optional enum on the rule: `FieldValueInvalid` (the default), `FieldValueForbidden`, `FieldValueRequired`, `FieldValueDuplicate`. It selects the error constructor in `fieldErrorForReason` (`field.Invalid`, `Forbidden`, `Required`, `Duplicate`) and the HTTP status of the first failure. Policy validations use a different set: `Unauthorized`, `Forbidden`, `Invalid`, `RequestEntityTooLarge`. The schema check rejects an unsupported value with `NotSupported` and the list of allowed values.

### fieldPath

`fieldPath` is a relative JSON path from the rule's schema node. `ValidFieldPath` (apiextensions `schema/cel/validation.go`) scans `.name`, `['key']` and `[index]` tokens and walks the structural schema. An unknown step fails with `does not refer to a valid field`. It is checked twice: during the schema validation and during compile, where it is normalised into `NormalizedRuleFieldPath`. A failing rule reports its error at the full path. The docs add that numeric array indexes are not supported.

### Transition rules and oldSelf

- A rule that mentions `oldSelf` is a transition rule (`UsesOldSelf`). It runs only on update, and only when the old value exists (`validateExpressions`: `compiled.UsesOldSelf && oldObj == nil` skips the rule).
- The path to the node must be correlatable. Old and new values pair up through an object field, or through a list item only if every list on the path has `x-kubernetes-list-type: map` (`MapIsCorrelatable`, `makeMapList`). A rule under a `set` or `atomic` list fails at write time: `oldSelf cannot be used on the uncorrelatable portion of the schema within <path>`.
- The `oldSelf` variable is declared in the environment from version 1.24 (`prepareEnvSet`).

### optionalOldSelf

`optionalOldSelf: true` always evaluates the rule. `oldSelf` becomes `optional_type(T)` (empty when no old value exists), so the rule has to call `oldSelf.hasValue()`, `orValue(...)` or `optMap(...)`. The docs give the pattern for a tightened constraint:

```
self.foo == "foo" || (oldSelf.hasValue() && oldSelf.value().foo != "foo")
```

The schema check rejects `optionalOldSelf` on a rule that never uses `oldSelf`. KEP-4008 first named the field `AppliesOnCreate` and showed this example: `len(self) >= 5 || (oldSelf != nil && len(oldSelf) < len(self))`.

### Validation ratcheting

- Behind the `CRDValidationRatcheting` feature gate; the docs say clusters older than v1.30 must enable it explicitly. The CRD docs state the rule: the server accepts an update that leaves the resource invalid "provided that each part of the resource that failed to validate was not changed by the update".
- For CEL, `addErr` in `validateExpressions` decides: if the rule does not use `oldSelf` and `correlation.shouldRatchetError()` is true, the error is added as an API warning (`warning.AddWarning`) instead of an error. `shouldRatchetError` is `CachedDeepEqual` on the current node's correlated old value, or on the nearest correlatable ancestor when the current node cannot be correlated.
- `ratchetingOptions` walks `key()` and `index()` along with the data. `apiVersion` and `kind` are never ratcheted.
- Exclusions, from the docs and KEP-4008:
  - `allOf`, `oneOf`, `anyOf` and `not`, and anything under them;
  - transition rules;
  - `x-kubernetes-list-type` and `x-kubernetes-list-map-keys`;
  - `required`;
  - the server's own metadata checks.
- In the CEL walk, `allOf` validators run with an empty correlation, "to mirror schema ratcheting behavior which does not ratchet allOf errors".
- KEP-4008 "Advanced Ratcheting" explains why `DeepEqual` is the base rule: the server cannot know in general how a tightened constraint should treat old data, so CEL gets `optionalOldSelf` to say it explicitly.

## 7. ValidatingAdmissionPolicy and MutatingAdmissionPolicy

### Shape

A policy is configuration with CEL inside. The CEL environment is built in `apiserver/pkg/admission/plugin/cel/compile.go`:

| Variable | Type | Notes |
|---|---|---|
| `object`, `oldObject` | `dyn` | `null` on delete, create respectively |
| `params` | `dyn` | declared only when `paramKind` is set |
| `request` | `kubernetes.AdmissionRequest` | typed; built by `BuildRequestType` |
| `namespaceObject` | object type from `BuildNamespaceType` | typed |
| `authorizer`, `authorizer.requestResource` | opaque authz types | declared only when authorizer use is allowed |
| `variables` | object type, one field per composed variable | see below |

`mustBuildEnvs` prebuilds one environment for every combination of `HasParams`, `HasAuthorizer` and `HasPatchTypes`, since the number of combinations is small.

### Typed `request`, dynamic `object`

- `request` has a fixed shape. It is built by hand in Go (`BuildRequestType`): `kind`, `resource`, `operation`, `userInfo` and others, with `options` as `dyn`. A misspelled `request.operatoin` fails to compile.
- `object` is `dyn` because a policy matches several kinds, and the schema may be missing at write time or differ between clusters. KEP-3488 lists the cases: version skew, deleted CRDs, one CRD with different schemas in different clusters, and aggregated API servers that publish no types. The CEL docs state the result: `request.namex` fails type checking, while `object.namex` passes.
- The KEP compared four designs: strict types, typed expressions with dynamic scopes, informational checking, and none. It picked informational checking.
- `typechecking.go` (`apiserver/pkg/admission/plugin/policy/validating`) runs after the policy is stored. It resolves every kind named in `matchConstraints` (at most 10, `maxTypesToCheck`), converts its OpenAPI schema with the same `SchemaDeclType`, recompiles with `object` and `oldObject` typed, and writes warnings to `status.typeChecking.expressionWarnings`. Policy behaviour does not change. The limits are listed in the docs: no wildcard kinds, no CRDs, and `paramKind` is not checked.
- MutatingAdmissionPolicy types its patch values differently. `Object` and `JSONPatch` are initialiser types resolved dynamically by name, `Object.spec.containers` and so on (`apiserver/pkg/cel/mutation/typeresolver.go`, `DynamicTypeResolver`). Compile time does not check them against the resource schema. The apply step converts the CEL result with the resource's type converter (`typeConverter.ObjectToTyped` in `policy/mutating/patch/smd.go`) before merging, so a bad shape fails there.

### paramKind and params

- `spec.paramKind` names a kind, usually a CRD. A separate binding object ties a policy to a concrete parameter object with `paramRef`, and a policy has any number of bindings, each with its own parameters.
- `params` is `dyn` in expressions. `parameterNotFoundAction` decides what happens when no parameter exists. The policy author owns the CRD that defines the parameter kind.

### matchConditions

- A list of up to 64 named CEL conditions (`validateMatchConditions`). All must be true for the policy to run.
- They see the same variables except `namespaceObject` and `variables`. They run before everything else, with their own budget (`RuntimeCELCostBudgetMatchConditions`).
- Error handling is explicit in the docs: any `false` skips the policy even if another condition errored. Otherwise `failurePolicy: Fail` rejects the request and `Ignore` skips the policy.

### variables (composition)

`apiserver/pkg/admission/plugin/cel/composition.go`:

- `spec.variables` is an ordered list of `{name, expression}`.
- Each is compiled in order, and its output type becomes the type of a field on the `variables` object type (`CompileAndStoreVariable`, `AddField`, `convertCelTypeToDeclType`). A later variable can use an earlier one, and no cycle is possible.
- At runtime `variables` is a lazy map (`apiserver/pkg/cel/lazy/lazy.go`). A variable evaluates on first use, and its result or error is memoised. Its cost is counted once in the request budget (`compositionContext.reportCost`). An error surfaces in the expression that read it: `composited variable "x" fails to evaluate`.
- The docs name two reasons to use it: the expression is too long, or part of it is reusable and expensive.

### auditAnnotations

A list of `{key, valueExpression}`. The expression must return a string or `null`. An empty string and `null` publish nothing, and any other type is reported as an error. An evaluation error follows `failurePolicy`. The key is checked as a qualified name prefixed with the policy name, and the value expression is at most 5 KiB (`maxAuditAnnotationValueExpressionLength`).

### Validation results

A `validation` has `expression`, `message`, `messageExpression` and `reason`. `failurePolicy` decides errors. A binding's `validationActions` (Deny, Warn, Audit) decide what a failure does. The result carries a decision per expression (`PolicyDecision`) with `Admit`, `Deny` or `EvalError`.

## 8. Testing

Kubernetes tests CEL in Go, with table-driven tests that keep data and expected results together.

### Unit tests

- `apiextensions-apiserver/pkg/apiserver/schema/cel/validation_test.go` (5,249 lines). `TestValidationExpressions` takes rows of `{schema, oldSchema, obj, oldObj, valid []string, errors map[rule]substring, costBudget, isRoot, expectedCost}`. `valid` lists rules that must evaluate true, and `errors` maps a rule to a substring its error must contain. Other tests in the file: `TestRatcheting`, `TestOptionalOldSelf` (and `...CheckForNull`, `...IsOptionalType`), `TestMessageExpression`, `TestReasonAndFldPath`, `TestValidateFieldPath`, `TestCELValidationLimit` (budget exhaustion), `TestCELValidationContextCancellation` and `TestCELMaxRecursionDepth`.
- `celcoststability_test.go` (2,194 lines) pins exact actual costs.
- `compilation_test.go`, `compilation_benchmark_test.go` and `rules_benchmark_test.go` cover compile results and speed.
- Environment and library tests are listed in section 4.
- Type-mapping tests: `model/schemas_test.go`, `model/types_test.go`, `apiserver/pkg/cel/openapi/schemas_test.go`, `compiling_test.go`, and the `values_test.go` family.

### A reusable evaluator

`apiserver/pkg/admission/testing/celtest` (`evaluator.go`, `testdata/*.yaml`) evaluates ValidatingAdmissionPolicy, MutatingAdmissionPolicy and webhook `matchConditions` from YAML inputs without a running API server. The package comment says it uses the same CEL environment and compiler as the API server at runtime, so compilation is identical. It does not run schema validation, conversion or defaulting, and it does not gate rules on `matchConditions` implicitly.

### Integration and end to end

`test/integration/apiserver/cel/` and `test/e2e/apimachinery/` (`crd_validation_rules.go`, `crd_validation_ratcheting.go`, `validatingadmissionpolicy.go`).

### Language-neutral artefacts

- Kubernetes does not run the cel-spec conformance suite from these packages. A search of the tree names found no such test. The shared artefacts are the YAML in `celtest/testdata` and the Go tables, which are not portable to another runtime.
- cel-go runs the conformance suite itself (`conformance/` in `google/cel-go`, with a `policy` subdirectory).
- An environment-as-data format exists. cel-go has `common/env` with `ConfigFromYAML` and `ConfigToYAML`, and `Config` carries extensions, features, limits and validators (`common/env/alias.go` in `google/cel-go`). The `cel-expr-python` stubs expose `NewEnvConfigFromYaml` and `EnvConfig.to_yaml()`. Kubernetes builds its environment in Go code (`base.go`) and does not use it in the files read. Whether the Python binding's YAML covers typed variables was not tested.

## What benchhand should adopt

Effort: S is under a day, M is one to three days, L is more than three days. "Lands" names the layer from the task.

| # | Idea | Verdict | Why | Lands | Effort |
|---|---|---|---|---|---|
| 1 | **Structural activation scopes.** Rule scopes are schemas with no `oneOf`/`anyOf` or `dyn` on any path a rule can reach. The type mapper reads the skeleton only and ignores value-validation keywords. | Adopt | It removes the loose union checking the spike measured (30 merges, 35 `dyn` fallbacks). It is how Kubernetes types CRDs. | `contracts` (a scope marker in TypeSpec); `contracts_gen` (skeleton extraction, union rejection with a schema path); flow loader | M |
| 2 | **Union handling inside a scope.** Model a tagged union as one flat model: a `kind` discriminator plus optional members, with a rule or schema check on which members go with which `kind`. Or have the activation builder project the union into typed per-variant lists. | Adopt (flat model first) | Kubernetes does this (KEP-1027). The projection is a fallback for records that must keep their `oneOf`. | `contracts` (activation models); flow loader (activation builders) | M |
| 3 | **A `dyn` escape hatch** for the rare case that cannot be flattened, with `type()` guards documented. | Adapt | Kubernetes allows exactly one such type. benchhand should allow none by default and list each exception in the scope definition. | `contracts_gen` (allow-list); docs | S |
| 4 | **Compile every expression at load with field-path errors.** Return all errors, not the first. Path format like `flow.yaml#/gates/PROVISIONAL/requires/0`, with the cel-go-style line, column and caret. Skip CEL checking under a node that has schema errors. | Adopt | Same goal as ADR-0014 ("a typo fails at load"). The error-list design is what makes it usable. | flow loader; provider protocol (errors for provider rule lists reported against the provider's file) | M |
| 5 | **Output-type check per slot.** `when`, `requires` and `guard` must be `bool`. `message_expr` must be `string`. A rule-list `then` has the type its schema gives it. | Adopt | Kubernetes enforces this at compile time. A wrong type is otherwise a runtime `no matching overload`. | flow loader | S |
| 6 | **Runtime never passes a broken rule.** A rule that fails to compile or evaluate yields a finding with coverage UNKNOWN, not PASS. | Adopt | This matches the plan ("a missing provider or hook returns UNKNOWN coverage, never PASS") and Kubernetes' `failurePolicy` handling. | flow loader; policy | S |
| 7 | **Cost: bounds on activation collections, a nesting lint and an evaluation timeout.** Contracts bound collections that scopes expose (`maxItems`, `maxLength`). The loader warns on a comprehension nested inside another over unbounded lists. The adapter enforces a wall-clock limit per evaluation. | Adapt | The binding has no cost API and D3 says this is guidance, not security, so a full estimator is not justified by the current threat model. | `contracts` (bounds); flow loader (lint); adapter | M |
| 8 | **Cost: static estimate and budgets** (per rule, per file, per run). | Adapt, defer | It needs a cost estimator, which cel-go has and the Python binding lacks. Revisit if third-party providers can ship rules, since that raises the threat from mistakes to abuse. | flow loader; provider protocol (a per-hook rules budget) | L |
| 9 | **Environment compatibility profile.** Each `flow.yaml`, `*.rules.yaml` and provider rules file declares an integer profile. The loader builds the environment for that profile from additive option sets. The writer tools (`validate`, provider publish) accept a new function only in files that declare a profile that includes it. Providers declare the profile range they need in `benchhand-provider.toml` and `initialize` negotiation. | Adapt | Kubernetes picks the old environment by comparing against a stored object. benchhand has no old object at load time, and a declared profile gives the same guarantee: an older file always loads. It avoids the rejected "version per expression" cost because profiles are option sets on one compiler. | flow loader; `contracts_gen` (profile table); provider protocol (manifest field); docs | M |
| 10 | **Diff-against-stored environment choice** (`preexistingExpressions`). | Skip | It needs the previous version of the file at validate time. Git could supply it, but a declared profile is simpler and testable. | none | none |
| 11 | **Pin runtime behaviour** the way `base.go` does: record the binding version and options in the adapter, and keep behaviour-changing options (timestamp parsing, numeric comparison, absent-field behaviour) in one place. | Adopt | `cel-expr-python` is 0.1.x. Kubernetes neutralised each cel-go behaviour change with an option for the same reason. | adapter; conformance suite | S |
| 12 | **Known-function list test**, and a test that every profile option has `introduced < removed`. | Adopt | Cheap guard that forces a profile decision whenever a library function appears. | tests; `contracts_gen` | S |
| 13 | **Library discipline.** Additive only; each library singleton-named with a `benchhand.` prefix; wrapped so a new version parameter breaks the build. No library ships before a rule needs it. | Adopt | Matches KEP-2876: the function set is hard to change later. | adapter; docs | S |
| 14 | **`messageExpression` for findings.** Rule items get `message` (static) and `message_expr` (CEL, `string`). Evaluation order: `message_expr`, then `message`, then `failed rule: <when>`. Result trimmed, one line, at most 5 KiB. A broken `message_expr` is reported at load and never disables the rule. | Adopt | It is the one place where a rule can name the failing item and value, which the agent needs. The fallback chain keeps a bad message from hiding a finding. | flow loader; finding contract in `contracts` (`message` stays the only text field); policy | S to M |
| 15 | **Finding `code` and `path`.** `code` is a closed enum, like `reason`. `path` is a record path, validated at load against the scope schema, like `fieldPath`. | Adapt | The envelope already has `findings`. A validated path points a gate card at the failing item. `reason` is only worth a copy if the code set is closed. | `contracts` (finding shape); flow loader (path validation) | M |
| 16 | **Transition rules.** A rule that uses `prev` (the earlier version or gate decision, like `prev_human_gate`) is skipped when `prev` does not exist. `prev` is optional-typed only where the author asks. | Adapt | The plan already uses `prev_human_gate`. Kubernetes' skip-when-absent default avoids writing a guard in every rule. | flow loader; scope schemas | S |
| 17 | **Ratcheting an existing record when a rule tightens.** A failure of a rule that has no `prev` becomes a warning-level finding (marked as pre-existing) when the item it names has the same fingerprint as at its last approval. Transition rules never ratchet. | Adapt | Same rule as Kubernetes, with the ADR-0019 fingerprint in place of `DeepEqual`. It lets a provider or contract release add a rule without failing every old project. | flow loader and the decision record (ADR-0019 fingerprints); policy | M to L; depends on the open "decision without a scope" question in ADR-0019 |
| 18 | **`optionalOldSelf` equivalent.** Let a rule see `prev` as an optional and write its own grandfathering. | Skip for now | The fingerprint rule covers the common case. Add it when a rule needs a gradual tightening, such as "closer to the new minimum". | none yet | S later |
| 19 | **Typed `params` for policy providers.** A policy provider's parameters get a type from the provider's contract and are checked at load. | Adopt, better than Kubernetes | Kubernetes types `params` as `dyn` because a `paramKind` may be absent at write time. benchhand knows the provider manifest before it loads rules. | provider protocol (manifest declares a params schema); flow loader | M |
| 20 | **Named sub-expressions (`variables`).** Ordered, typed by their compiled output, evaluated once per activation, usable in later expressions and in `message_expr`. | Adopt (after the first rule lists exist) | Several plan examples repeat `version.fast_checks.all(...)`. Ordering rules out cycles without a graph check. The Python binding has no lazy map, so evaluation order or inlining has to be built. | flow loader | M |
| 21 | **Informational type checking** of `object`-style dynamic scopes. | Skip | Kubernetes needs it for skew between kinds and clusters. benchhand's contracts are versioned and compiled against one version at a time, so strict checking is possible. | none | none |
| 22 | **`matchConditions` and `auditAnnotations` as separate features.** | Skip | Rule lists are already ordered first-match lists with a `when`. Decision records already hold the audit evidence (ADR-0019). | none | none |
| 23 | **Property-name escaping** (`__dash__` and friends). | Skip, replace with a lint | Contract fields are snake_case. A load-time lint that every activation property is a valid, non-reserved CEL identifier is cheaper than an escape scheme. | `contracts_gen` | S |
| 24 | **Absent versus null.** Absent fields are errors unless guarded by `has()`, and null counts as absent. | Adopt, via a `has()` lint | It is the safer semantics, and the spike measured that the primary runtime returns a protobuf default instead. The lint closes the gap without changing the runtime. | adapter; flow loader (lint over the CEL parse tree) | S |
| 25 | **Table-driven rule tests** with `valid` and `errors` columns, and a standalone `rules test` command that evaluates a rule file against sample records without the server (`celtest`). | Adopt | This is how Kubernetes keeps rules honest, and it matches the YAML suite the spike already built. | `tests/`; CLI | M |
| 26 | **Environment as data** (cel-go `common/env` Config YAML; `NewEnvConfigFromYaml` in the Python binding). | Adapt, later | It could serialise a profile so the Rust fallback and the primary load the same environment. Unverified whether it covers typed variables in the binding. | adapter | M |

### Suggested order

1. Items 1, 2, 4, 5 and 6 first. They decide the shape of the loader and the contracts, and they settle the open union question from the spike.
2. Items 9, 11, 12 and 13 next, before any rules file ships, because a profile is cheap on day one and awkward to add after providers publish rules.
3. Items 14, 15, 16 and 25 with the first rule lists.
4. Items 17 and 20 once Phase 2's decision record exists.
5. Items 7 and 8 only with a stated need.

### An illustration, not a decision

A rules file under the proposed shape:

```yaml
cel_profile: 1
scope: rules/checks-by-iteration      # a contract schema, structural, no unions
rules:
  - when: 'stage in ["parts","detail"] && iteration == "commit"'
    then: ["form_check", "check_changed_only"]
    message_expr: '"checks for " + stage + " at " + iteration'
```

The loader would report a typo as `rules/checks.rules.yaml#/rules/0/when: undefined field 'iteraton'` with the caret line, together with every other error in the file.

## Risks and gaps

- **Reading, not running.** Every claim about Kubernetes comes from reading its source, docs and KEPs on 2026-11-26. No Kubernetes code or `cel-expr-python` call was executed. A function name or constant could have moved since the fetch.
- **Docs and code differ in places.** Examples: the docs call int-or-string a union while the code makes it `dyn`, and the library table's start versions are a release behind `base.go` for IP, CIDR and format.
- **Cost estimation for benchhand is a gap, not an adoption.** The static design needs cel-go's checker cost API. Item 7 limits the damage but gives no proof a rule is cheap.
- **Profile design interacts with the runtime.** A profile can gate functions and libraries. It cannot gate semantic changes inside the CEL runtime itself (for example timestamp parsing). Those need the pinning in item 11 and the conformance suite.
- **Whether `cel-expr-python` can build an environment with a function subset** (needed for profiles) was not tested. The stubs show `NewEnv(extensions=, functions=)`, which suggests yes for added libraries, but the standard library's subsetting is not shown.
- **Ratcheting depends on an open decision.** ADR-0019 leaves open how a decision with no approval scope is treated. Item 17 has no clean baseline for migrated prototype decisions until that is settled.
- **The ratchet changes what a finding means.** Demoting a failure to a warning is only safe if the finding contract has a severity that gates ignore. That needs a contract change reviewed with the gate logic, and it should not be slipped in with the loader.
