# ADR-0020: The CEL rule pipeline

Status: accepted. Source: the owner, 2026-11-27, on `research/cel-neutral/REPORT.md` and `research/cel-k8s/REPORT.md`. It supersedes part of [ADR-0014](0014-flow-rules-cel.md): rule lists are cel-policy files compiled before load, not CEL checked at load, and the types "generated from the contracts" are a descriptor set and a profile manifest. It refines section 5 of [the plan](../design-plan.md).

## Context

ADR-0014 makes every condition in the flow a CEL expression, compiled and type-checked at load against types generated from the contracts (ADR-0017). Two research reports tested how to do that.

`research/cel-k8s/REPORT.md` read how Kubernetes types CEL from schemas. Kubernetes takes CEL types from a structural skeleton of the schema, in which a union can't appear, and it ignores validation-only keywords.

`research/cel-neutral/REPORT.md` ran seven engines against artefacts generated from the published JSON Schemas. This ADR rests on these findings:

- A FileDescriptorSet generated from the published schemas types the rules. A wrong field name fails the check in cel-go and in cel-expr-python, and both rejected all seven bad rules of the typed demo.
- A `cel.expr.CheckedExpr` that cel-go writes is evaluated by cel-expr-python without the source and without a second check, for the six good rules of the typed demo. A CheckedExpr carries no environment identity, and a writer's bytes aren't reproducible between runs.
- Equal env YAML and descriptor-set hashes don't prove that two engines run the same environment. Extension versions and checker options drifted between the demos until each engine built its environment from one manifest.
- cel-go's policy compiler turns a cel-policy `match` block into one CheckedExpr. The research compiled one benchhand rule list, "checks by iteration", in two forms and ran its four test cases on the three evaluators tested on it: cel-expr-python, cel-core and @bufbuild/cel. The flat form, without `variables`, compiles to nested `?:` and passed 4 of 4 on all three. The form with `variables` compiles to `cel.@block`, which passed on cel-expr-python and failed on the other two. The cel-policy conformance suite wasn't run on any engine.
- cel-go's `tools/compiler` package always appends the latest `optional` and `bindings` extensions, so it can't check against an exact environment. The `cel-expr` CLI writes no CheckedExpr.
- The research ran 1,640 of cel-spec's 2,344 simple tests: those that need no declarations, bindings, container or conformance message types. On that subset cel-go passes 1,611 and cel-expr-python 1,610. `cel.block`, which no rule author writes, accounts for 22 of cel-go's 29 failures and 22 of cel-expr-python's 30. These scores are diagnostic data about the subset.

The owner decided on 2026-11-27:

1. benchhand has no Rust. D12 stands: the host is Python. cel-core is the Rust engine of the general CEL steering, and that choice is informational for benchhand.
2. The browser UI evaluates no rule. It shows the results the server computed, so benchhand has no TypeScript CEL engine.
3. Rule lists use the cel-policy format in a restricted profile.
4. A pinned cel-go tool compiles rule lists, in CI for benchhand's own and through `benchhand rules compile` for a user's own.
5. No upstream issues are filed for the engine gaps the research found.

## Decision

### The environment profile manifest

Each rule scope has one environment profile manifest. `contracts_gen` generates it from the published JSON Schemas, together with the FileDescriptorSet, and nobody writes it by hand. The manifest holds:

- `descriptor_set`: the descriptor set's file name and the SHA-256 of its exact bytes. The generator writes `.proto` files from the schemas and compiles them to the descriptor set;
- `variables`: each declaration with its CEL type, a primitive or a message of the descriptor set;
- `extensions`: each enabled extension with its pinned version, in cel-go's numbering;
- `options`: the checker options, set explicitly. `cross_type_numeric_comparisons` and `homogeneous_aggregate_literals` are both `false`;
- `checkers_of_record`: the checkers, as engine and version, whose bundles the host may run. For benchhand that is the pinned cel-go tool;
- `container` and `manifest_version`.

A profile enables an extension only at a version that both cel-go and cel-expr-python implement. cel-expr-python has no `bindings` version 1, so no profile enables it.

Each engine's adapter builds its environment from the manifest and keeps its own inventory of the extension versions it implements. Before it builds the environment, it hashes the descriptor-set bytes it loaded and refuses them when the SHA-256 differs from the manifest's. The profile digest covers only the manifest, so without this check a replaced descriptor set would leave the digest and every bundle check unchanged. Both the cel-go tool and the host make the check. At load an adapter also refuses an extension version outside its inventory, or an option it can't set. The inventory is the adapter's, because cel-go passes an unknown extension version through without an error. The generator also writes each scope's cel-go env YAML for tools that read that format. No engine in benchhand reads it.

### The JCS digest

The profile digest is the SHA-256 of the manifest's canonical JSON under RFC 8785 (JCS). RFC 8785 is normative: the canonical bytes are what it defines, whatever encoder an adapter uses. The digest is never taken over protobuf bytes or over the env YAML.

The generator refuses a manifest with a float, a non-ASCII string, or an integer `n` with |n| > 2^53, in either sign. The bound keeps every integer exactly representable as a double. Without the negative bound, a decoder that reads JSON numbers as doubles would round `-9007199254740993` while another keeps it, and the two digests would differ.

The cel-go tool and the host must produce the same canonical bytes for the same manifest. A cross-adapter test vector in CI enforces it: a manifest, its canonical bytes and its digest, which each adapter must reproduce. The vector covers key order, escaping, both integer bounds and the end of the output: the canonical bytes end at the closing brace, with no trailing newline, although some encoders append one.

### Structural scopes

A scope names the variables a rule sees. Each variable points at one node of a published schema, and the scope may omit fields. An omitted field isn't declared, so a rule that reads it fails the check.

The generator walks every node a rule can reach. It refuses the scope when a node has more than one shape, and it reports the path and the reason. It refuses:

- a `oneOf` or `anyOf` whose branches carry shapes;
- an `allOf` that merges shapes;
- an untyped node (`true` or `{}`), which would be `dyn`;
- an object with properties that isn't sealed;
- a map of lists;
- a message or `null`, because it has two readings of absence (`null` and `{}`);
- a field named with a CEL reserved word.

No path a rule can reach is typed `dyn`, and there is no exception list. A real union is flattened in the contract into a discriminator plus optional members, as Kubernetes does (KEP-1027), or the scope omits it. Validation-only keywords don't change the shape, so the generator ignores them: `pattern`, bounds, `if`/`then`/`else`, `not`, and a `oneOf` of `required` clauses. A two-branch union of a scalar and `null` is a nullable scalar.

| JSON Schema | proto3 | CEL |
|---|---|---|
| required `string`, `integer`, `number`, `boolean` | `string`, `int64`, `double`, `bool` | the same |
| optional scalar | `optional` scalar | the scalar |
| nullable scalar | `google.protobuf.*Value` wrapper | `wrapper(T)`, null when absent |
| sealed object | message | message |
| `additionalProperties: {schema}` | `map<string, V>` | `map(string, V)` |
| array | `repeated` | `list(T)` |
| `enum` of strings | `string` | `string`; the values aren't checked |

### Presence semantics

A record enters the activation through cel-expr-python's protobuf JSON parser against the descriptor set, with unknown fields ignored. What a rule then sees depends on the field's kind. The table restates the one the research measured on four engines through the activation path (`research/cel-neutral/REPORT.md`, "Presence: missing, explicit null and zero"):

| Field kind | proto3 | Missing | Explicit `null` | Zero (`""`, `0`, `false`, `{}`) |
|---|---|---|---|---|
| Nullable scalar | `google.protobuf.*Value` | reads `null`; `has()` is false; arithmetic on it is an evaluation error | the same as missing: `has()` is false, `== null` is true | `has()` is true; reads the zero |
| Optional scalar | `optional T` | reads the zero; `has()` is false | the parser loads it as missing: `has()` is false | `has()` is true |
| Required scalar | plain `T` | reads the zero; `has()` is false | the parser loads it as missing: `has()` is false | `has()` is **false**: proto3 can't tell zero from missing |
| Message | message | `has()` is false; selecting through it reads defaults | the same as missing | `{}` is present: `has()` is true |

What `has()` can tell apart:

- **Missing from zero:** a nullable scalar, an optional scalar and a message. For a message, `{}` is present and missing isn't. A required scalar can't: at its zero value it looks missing.
- **Missing from explicit `null`:** no kind. For a nullable scalar and a message the two collapse by design, and both mean absent. For an optional or a required scalar the parser loads a `null` as missing, although the schema may forbid that `null`.
- **A missing value's reading:** a nullable scalar reads `null`, an optional or a required scalar reads its zero, and selecting through a missing message reads defaults.

So:

- The host validates every record against its JSON Schema before activation. A `null` the schema forbids then fails validation instead of reaching a rule as "missing".
- A rule that must tell a value from its absence guards the read with `has()`. That works for a nullable scalar, an optional scalar and a message, and never for a required scalar at its zero value.
- The loader's presence lint flags a bare read of an optional or nullable field outside a `has()` guard, and a `has()` on a required scalar.

### The restricted cel-policy profile

A rule list is a cel-policy file, `flow/*.celpolicy`. The profile is an allow-list of what the flat "checks by iteration" list exercised on the three evaluators tested on it:

- a `name`, and a `rule` with one `match` block, evaluated first-match;
- each choice has a `condition` and an `output`;
- the final choice has no condition, so it always matches.

The profile has no `variables`, no `aggregate` and no nested `rule`. Every other cel-policy field, `explanation` and `imports` included, is outside it. The compile step refuses an excluded feature before the policy compiler runs, in every profile. A feature joins the profile only when the CheckedExpr the compiler emits for it passes the supported-profile gate on cel-expr-python.

The final choice keeps "no match means UNKNOWN". A dispatch list ends with `- output: '"unknown"'`. The rule-list schema reserves the value `unknown`, and the host records it as UNKNOWN coverage, never PASS. Every other list's final choice outputs an explicit default of the same type as its other outputs, so the compiler's output-type check still holds.

The policy compiler checks output-type assignability, a literal `false` condition, and a literally true choice before the last one. A condition that is always false without being the literal passes it.

### Compilation and the rules bundle

The pinned cel-go tool lives in `tools/celcheck/`, a Go module pinned to one `cel.dev/cel-go` version and its matching `policy` module. It verifies the descriptor-set bytes against the manifest, then builds its environment from the manifest with explicit options and appends nothing. It compiles each rule list into one CheckedExpr in a `google.protobuf.Any`, and writes the rules bundle.

A bundle's identity is three things:

- the profile digest;
- the checker: the cel-go version and the tool's version, which must be a checker of record in the manifest;
- the SHA-256 of each entry's exact payload bytes, taken when the tool writes them.

Each entry also carries the rule list's path, its output type and the SHA-256 of its exact source bytes. A recompile writes new bytes and a new bundle together, and nothing compares two encodings. The profile manifest and the rules bundle are contracts in `contracts/` (ADR-0017), like every other shape.

Who compiles what:

- **benchhand's own rule lists** are compiled in CI. CI fails when a shipped bundle entry is stale.
- **A user's own rule lists**, from a project or a policy provider, are compiled by `benchhand rules compile`. It runs the same tool at the same version.

At load the host:

1. refuses a descriptor set whose bytes don't match the manifest's SHA-256;
2. builds its environment from the manifest and computes the profile digest;
3. refuses a bundle whose profile digest differs;
4. refuses a bundle whose checker isn't of record in the manifest;
5. refuses an entry whose payload SHA-256 differs;
6. hashes each rule-list source and refuses a list with no entry, or with an entry whose source SHA-256 differs.

A refusal stops the load. It names the file and the command to run, `benchhand rules compile`. After the checks, the host evaluates each CheckedExpr with cel-expr-python without checking it again.

**The tool ships as a platform wheel.** `benchhand-celcheck` is a separate distribution that holds the statically linked tool binary, one wheel per platform benchhand supports. `benchhand` depends on it with an exact pin. A platform wheel and not a managed download like FreeCAD's (ADR-0005), because:

- `uvx benchhand@<ver>` installs it with the package (D2). It needs no extra step and no consent prompt, it works offline once uv has cached it, and it is in the container image.
- The exact pin locks the checker of record to the release, the same version the manifest names. A managed download would need a second version list kept in step with it.
- PyPI and uv verify the wheel hashes, so benchhand writes no download or checksum code for it.
- FreeCAD is a managed download because it is large, has its own release cycle and isn't a Python package. None of that holds for a Go binary, which cross-compiles as a static file with cgo off.

### Standalone expressions

A standalone CEL expression is checked at load by cel-expr-python, against the manifest of its scope. These are the flow `when` expressions, the gate `requires`, the edge guards, `void_scope` and the approval-scope selector (ADR-0019). The loader returns all issues at once, each with the expression's path in its file (for example `flow.yaml#/gates/PROVISIONAL/requires/0`), the line, the column and a caret. It also checks each slot's output type: `requires`, guards and `when` are `bool`. Standalone expressions don't enter the rules bundle.

### Engine roles

- **cel-go**, through the pinned tool, is the reference checker and the checker of record for rule lists. In CI it is also the conformance oracle, and its static cost estimate is reported as an estimate. It runs in CI and under `benchhand rules compile`, never on the host's load path.
- **cel-expr-python** is the checker of record for standalone expressions at load, and the only evaluator in benchhand. It sits behind one adapter with five operations: `load`, `check`, `program`, `eval` and `identity`. A rule that fails to evaluate yields a finding with UNKNOWN coverage, never PASS.
- **No other engine runs in benchhand.** cel-core is the steering's Rust engine, and benchhand doesn't use it. @bufbuild/cel isn't needed, because the browser evaluates no rule. cel-go's `tools/compiler` isn't the checker, because it appends extensions. The `cel-expr` CLI writes no CheckedExpr, so it can't be a checker of record.

### The supported-profile gate

In CI, each engine passes the supported-profile cases of its role, for every profile:

- **The cel-go tool:**
  - accept, reject, profile and presence cases;
  - reject cases for a wrong field, a wrong operand type, a read of an omitted field and an undeclared variable;
  - profile cases in which an enabled feature checks and an excluded one fails;
  - a refusal fixture for each excluded cel-policy feature;
  - tampered-bundle cases on its bundles, all refused: another profile's digest, an edited source, a substituted payload and a checker not of record.
- **cel-expr-python:**
  - the same accept, reject, profile and presence cases, with the presence cases run through the activation path (parse a record, then evaluate);
  - the tampered-bundle cases, refused by the host's verifier;
  - every CheckedExpr the cel-go tool shipped, evaluated to its expected value.
- **Both checkers of record** check every standalone expression that benchhand ships. CI fails when they disagree on whether it checks, or on its output type.
- **The cel-spec simple tests**, in protobuf JSON, run on both engines against a committed failure baseline. The suite starts as the research's subset, 1,640 of cel-spec's 2,344 simple tests. A missing engine, a new failure or a new pass fails the run. The scores are diagnostic data about that subset.
- **Each adapter** has a test that an unknown extension version is refused at load, and a refusal fixture: a descriptor set whose bytes differ from the manifest's SHA-256, refused before any environment is built.
- **The JCS vector:** the cel-go tool and the host reproduce its canonical bytes and digest exactly.

## Consequences

- benchhand stays Python at runtime. Go joins the CI toolchain, and the tool's binary ships in a wheel. The host doesn't run Go when it loads a flow.
- A rule-list edit takes effect only after a compile step.
- A contract change that alters a scope changes its profile digest, which makes every bundle in that profile stale. CI recompiles benchhand's own. A project or a policy provider runs `benchhand rules compile` after a benchhand upgrade, and the refusal names that command.
- The release builds a wheel matrix for `benchhand-celcheck`, and every install carries the binary, also when a project has no rules of its own.
- Rule lists can't use `variables`, `aggregate`, nested rules or explanations. A sub-expression that several conditions share is repeated in each.
- The checker doesn't check enum values. `decision.status == "aproved"` passes the check and is always false.
- Cost has no bound. cel-go's static estimate in CI is an estimate: the `strings` extension at version 4 has no cost model, and the input limits the estimate assumes aren't validated. cel-expr-python has no cost API, and whether it can interrupt an evaluation is unverified.
- cel-expr-python (0.1.x) is the only evaluator. The plan's old Rust-backed fallback is gone with D12.
- The plan's Steps place the work: Phase 2 builds the generator targets, the contracts, the tool and the bundle check; Phase 3 adds `benchhand rules compile` and the platform wheel; Phase 7 publishes the wheel.
- ADR-0014's "compiled and type-checked at load" now holds for standalone expressions only.

## Alternatives

- **Compile policy source at load, in the host.** The cel-go tool would run as a subprocess on every load, so a compiler fault becomes a load failure. A Python port of cel-go's policy composer over cel-expr-python would be a second composer that must pass the cel-policy conformance suite to stay equal to cel-go's. Rejected: one composer, run at authoring time.
- **Keep `{when, then}` YAML lists and compose them in the host.** That needs the same composer, and it loses cel-policy's output-type and reachability checks.
- **cel-expr-python as the only checker, with no Go.** cel-expr-python 0.1.4 has no policy API and no cost estimate, and it would leave no independent oracle.
- **cel-go's `tools/compiler` or the `cel-expr` CLI as the checker.** The first appends extensions the manifest doesn't list. The second writes no CheckedExpr.
- **A Rust host component over cel-core, through pyo3.** It would change D12. cel-core's checker also accepts `decision.status == 1`, and its parser expands `cel.bind` outside the profile.
- **Evaluate rules in the browser with @bufbuild/cel.** The UI shows server results instead. A browser evaluator would also limit every profile to the `strings` extension.
- **A managed download of the tool, like FreeCAD's.** See "The tool ships as a platform wheel".
- **Type unions as `dyn`.** In the research, cel-js typed two fields `dyn` and two type errors passed its check.
- **Take the digest over the env YAML or protobuf bytes.** The env YAML doesn't name checker options, and protobuf bytes aren't reproducible.

## Open items

- **Merging rule lists.** Policy providers contribute rule lists, "merged in a defined order" (plan section 5). Each list compiles to its own CheckedExpr and ends with an unconditional choice, so an earlier list always answers. The merge has to happen in the source before the compile, or as a defined order of evaluating separate lists. Phase 2 decides which, with the policy contract.
- **Where a user's bundle lives.** It sits next to the sources it covers, but its path and file name in a project and in a provider package aren't chosen. Phase 2 picks them with the bundle contract.
- **How a scope is declared.** It could be a marker in TypeSpec (Kubernetes adopt item 1) or a scope file beside the contracts, as in the research (`scopes.yaml`). Phase 2 picks.
- **The first profile's extensions.** The research's gate-guard profile enabled `strings` only. The list is chosen with the first rule lists.
- **An enum lint.** The research recommends a load-time lint that compares string literals with the enum of the field they are compared to. It isn't decided.
- **The presence lint** is specified here, and no code exists for it yet.
- **A fallback evaluator** if cel-expr-python stalls. The shipped cel-go binary could evaluate through a subprocess, but that would put Go on the load path. Nothing is chosen.
- **The wheel's size and build time** are unmeasured.
