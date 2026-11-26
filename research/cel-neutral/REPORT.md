# CEL across languages: engines, artefacts, and a design that gives Rust equal standing

Status: research only. Written 2026-11-26 in a worktree of benchhand-next. Every number below comes from code in `research/cel-neutral/` that ran in this worktree, unless it is marked untested. The Kubernetes research it aligns with is `research/cel-k8s/REPORT.md` on branch `pi-subagents/task-1-9f42c8d-df91-s0-t0`.

## Verdict

CEL can be language-neutral for benchhand. The artefacts below are neutral and were tested across engines:

- **Types:** a FileDescriptorSet generated from the published JSON Schemas.
- **Environment:** a cel-go environment YAML.
- **Compiled rule:** a `cel.expr.CheckedExpr` in a `google.protobuf.Any`.

cel-go, cel-expr-python and the Rust crate cel-core each check a rule against those artefacts and write a CheckedExpr. Those three engines and `@bufbuild/cel` in TypeScript evaluated every CheckedExpr the others wrote. A wrong field name fails the check in cel-go, cel-expr-python, cel-cxx, cel-core and cel-js.

Checking can be a step of its own. A runtime that has only an evaluator can run CheckedExprs that a checker wrote, and that is how the browser gets typed rules without a TypeScript checker.

Rust can have the same standing as Python as an evaluator, with one engine choice to make and one owner to find:

- **cel-core 0.5.1** is the only pure-Rust engine with a checker and CheckedExpr input and output. It passed 1639 of the 1640 tests in the shared suite. It has one maintainer and no commit in nine months. Its checker also accepts `decision.status == 1` (string against int), which cel-go and cel-cpp reject.
- **cel-cxx 0.2.5** wraps cel-cpp, the checker that cel-expr-python uses. It caught all seven bad rules. Its build runs Bazel inside `cargo build`, and its Rust API has no CheckedExpr input or output.
- **`cel` 0.16.1**, the most used Rust crate, has no checker and no protobuf support. A rule with a wrong field passes until a record lacks that field.

A pyo3 binding of our own over cel-core took 87 lines of Rust and builds a 2 MB abi3 wheel. It ran the typed demo and the shipped CheckedExprs from Python. So a Rust host component is cheap to reach from the Python host.

Recommendation, which is for the owner to decide:

- Keep cel-expr-python as the Python engine and checker at load.
- Make cel-core the Rust **candidate evaluator**, not a checker of record, behind the same small adapter and held to the supported-profile gate. Rust authoring and the pyo3 fallback validate rules with the reference checker. Promotion needs an owner for cel-core's upgrades, fixes or a fork. cel-cxx is a source-checking alternative, not a bundle evaluator.
- Use `@bufbuild/cel` in the browser, to evaluate CheckedExprs only.
- Use cel-go in CI as the reference checker and the conformance oracle, through `go/celcheck`: a small tool that builds the environment from the profile manifest with explicit options and writes CheckedExprs. One pinned cel-go version serves both. `tools/compiler` isn't the reference, because it appends the latest optional and bindings extensions. The `cel-expr` CLI writes no CheckedExpr, so it serves for authoring and `rules test` only.
- Generate the descriptor set and environment YAML with the contracts (ADR-0017).
- Write rule lists as cel-policy files (`.celpolicy`), **pending the owner's decision**. `benchhand rules compile` and CI compile them with the pinned cel-go reference checker into the rules bundle, and the host refuses a list whose compiled entry is missing or stale. Standalone expressions are still checked at load by cel-expr-python. A benchhand `{when, then}` list is a cel-policy `match` block whose final choice is unconditional; dispatch's final choice outputs `"unknown"`, which keeps no match → UNKNOWN.
- Vendor three of the six cel-expr/skills agent skills into a harness-plugins `rules` plugin: `cel-testing`, `cel-debugging`, and `cel-authoring` with its environment step replaced. As shipped, `cel-authoring` has the agent hand-write the environment and build descriptors with `protoc`, which the generated environment replaces.

For Rust, the owner's ask then comes down to a required Rust conformance job, a Rust adapter crate, and contract types for Rust providers. Whether a host component moves to Rust is a plan section 4 (D12) decision. As of this report, D12 says "no Rust".

## Engines per language

Each engine ran two tests. The typed demo (`typedemo/gate_guard.yaml`) checks six good rules and seven bad ones against the generated gate-guard scope. The shared suite (`conformance/`) is 1640 cel-spec tests, described in the conformance section. Registry and GitHub figures are from 2026-11-26.

### Rust

| | cel-core 0.5.1 | cel-cxx 0.2.5 | cel 0.16.1 | ferricel 0.14.0 | rscel 1.0.9 |
|---|---|---|---|---|---|
| What it is | Pure-Rust parser, checker and evaluator | Rust over cel-cpp through `cxx` | Pure-Rust parser and interpreter | Compiles CEL to a WebAssembly module | Pure-Rust interpreter |
| Checker | Yes | Yes, cel-cpp's (the one cel-expr-python uses) | No | No | No |
| Type declaration | `CelType` per variable; messages from a FileDescriptorSet through `ProstProtoRegistry` | FileDescriptorSet at runtime; one call per variable | None: values are dynamic, from serde | Bindings as JSON | Not checked |
| Env YAML | Adapter, 40 lines (`rust/src/lib.rs`) | Adapter, 15 lines (`rust-cxx/src/main.rs`) | Extension names only | Untested | Untested |
| CheckedExpr | Reads and writes (`cel-core-proto`) | Not in the Rust API | No | Untested | No |
| Protobuf messages | Yes, `prost-reflect` dynamic messages | Yes, as serialised bytes | No: no proto feature, so `google.protobuf.*` literals fail | Wrappers listed as supported | Untested |
| Typed demo: bad rules rejected at check | 6 of 7 (accepts `decision.status == 1`) | 7 of 7 | 0 of 7 | Not run | Not run |
| Shared suite | 1639 of 1640 | 1512 of 1640 (87 failures are `disableCheck` tests it can't run unchecked) | 1546 of 1640 | Not run | Not run |
| Own conformance claim | 100% of cel-spec over parse, check and eval | None stated | Full conformance as a goal; 688 upstream tests listed as ignored | Validated against cel-spec, with a skip list | "Flexible enough to bend the spec" |
| Build | `cargo build`, about 6 s incremental | `cargo build` runs Bazel 8.3.1 (it downloads it) to compile cel-cpp. The time wasn't measured: the previous run's cel-cpp build-script directories span 18:06 to 18:46, retries included. It needs a C++ toolchain and leaves a 785 MB `target/` | `cargo build` | `cargo build` | `cargo build` |
| Maintenance | 5 stars, last push 2026-02-16, 15 open issues, 17k downloads, one maintainer | 36 stars, last push 2026-10-12, 0 open issues, 5k downloads | 719 stars, last push 2026-11-24, 28 open issues, 6.9M downloads, a governance file | 4 stars, last push 2026-11-25; its README says a code assistant wrote it | Release 1.0.9 on 2026-11-15, 50k downloads |
| Licence | MIT OR Apache-2.0 | Apache-2.0 | MIT | Apache-2.0 | MIT |

`cel-interpreter` and `cel-parser` are the old names of `cel` and stopped at 0.10 in 2025-07. `cel-rs` 0.2.0 has had no release since 2024-03.

**A pyo3 binding of our own** (`rust-py/`, `py/rust_binding_demo.py`) wraps cel-core with three calls:

- `Env(env_yaml, descriptor_set)`;
- `check(expr)`, which returns CheckedExpr bytes;
- `eval(checked, activation)`, which takes serialised proto messages.

Measured:

- 87 lines of Rust plus a 7-line type stub.
- A 50 s release build, which compiled pyo3, cel-core and their dependencies (the shared `target/` held only debug builds). maturin builds a 2.0 MB `cp312-abi3` wheel for macOS arm64.
- The typed demo gives the same result as cel-core: 6 of 6 good rules, 6 of 7 bad rules rejected.
- It evaluated the CheckedExprs that cel-go and cel-expr-python wrote, 12 of 12.

The binding doesn't yet return maps, timestamps or messages to Python, and it has no wheel matrix. Finishing it is about one to three days (estimate). On top of that come a CI matrix and a release for each cel-core update. The matrix covers macOS, Linux (manylinux, x86-64 and arm64) and Windows wheels.

### TypeScript

| | @bufbuild/cel 0.6.2 | @marcbachmann/cel-js 8.0.0 | cel-js 0.8.2 |
|---|---|---|---|
| Checker | In `dist/` but not exported. Two unmerged pull requests would export it: #237 (2026-01) and #344 (2026-10). The internal checker throws "Unsupported expression kind" on any call or macro, so 0 of the 13 demo rules could be checked. | Public `env.check()` | Archived 2026-04 |
| Type declaration | protobuf-es registry from the FileDescriptorSet; `objectType(desc)` per variable | `registerType(name, {fields})` and `registerVariable`; the demo maps the descriptor set to it (`ts/typed_demo.ts`) | Not assessed |
| CheckedExpr | Evaluates one (`plan(env, checkedExpr)`); writes one only through the internal checker | No proto AST | Not assessed |
| Typed demo: bad rules rejected at check | 0 of 7 (all 7 fail at evaluation) | 5 of 7: a nullable scalar (a proto wrapper) has no cel-js type and becomes `dyn`, so `job.progress.fraction + "x"` passes | Not run |
| Shipped CheckedExprs evaluated | 18 of 18 (cel-go, cel-expr-python, cel-core) | Not possible | Not run |
| Shared suite | 1324 of 1640 (only the strings extension ships) | 1037 of 1640 | Not run |
| Defaults that differ from cel-spec | None found | Homogeneous list and map literals on, optional types off. The runner sets them back. | Not assessed |
| Browser bundle (esbuild, minified / gzip) | 278 KB / 68 KB; 285 KB / 70 KB with a protobuf registry and the strings extension | 82 KB / 24 KB, no dependencies | Not assessed |
| Node-only APIs | None (it bundled for `--platform=browser`) | None | Not assessed |
| Maintenance | Beta. 43 stars, last push 2026-11-13, 24 open issues | 217 stars, last push 2026-11-05, 22 open issues | Archived |
| Licence | Apache-2.0 | MIT | MIT |

### The reference engines

| | cel-go (`cel.dev/cel-go` v0.33.4) | cel-expr-python 0.1.4 |
|---|---|---|
| Checker | Yes | Yes (cel-cpp) |
| Env YAML | Reads it (`cel.FromConfig`) | Reads it (`cel.NewEnvConfigFromYaml`), message-typed variables included |
| CheckedExpr | Reads and writes | Reads and writes (`serialize`, `deserialize`) |
| Typed demo | 7 of 7 rejected; evaluated 12 of 12 shipped from Python and cel-core | 7 of 7 rejected; evaluated 12 of 12 shipped from cel-go and cel-core |
| Shared suite | 1611 of 1640 | 1610 of 1640 |

## Language-neutral artefacts

| Artefact | Written by | Read natively by | Read through an adapter | Not read | Tested here |
|---|---|---|---|---|---|
| **FileDescriptorSet** (`generated/types.binpb`, 4.8 KB) | `buf build --exclude-source-info` from the generated `.proto` | cel-go (`cel.TypeDescs`), cel-expr-python (`descriptor_pool`), cel-core (`ProstProtoRegistry`), cel-cxx (`with_file_descriptor_set`), @bufbuild/cel (`createFileRegistry`) | cel-js: the demo maps each message to `registerType` (about 30 lines) | cel 0.16 | Yes, every engine in the typed demo |
| **Env YAML** (cel-go `env.Config`; `generated/env/gate_guard.env.yaml`, `conformance/env.yaml`) | `gen/celgen.py`; cel-go can also write one from an `Env` | cel-go (`cel.FromConfig`), cel-expr-python (`cel.NewEnvConfigFromYaml`) | cel-core (40 lines), cel-cxx (15 lines), @bufbuild/cel (5 lines, variables only), cel-js (with the descriptor mapping) | cel 0.16 (no typed variables; the runner maps extension names) | Yes. cel-expr-python reads message-typed variables from it, which the Kubernetes report left unverified (its row 26) |
| **CheckedExpr** (`cel.expr.CheckedExpr` in a `google.protobuf.Any`; `generated/checked/<engine>/`) | cel-go, cel-expr-python, cel-core, the pyo3 binding | cel-go, cel-expr-python, cel-core, @bufbuild/cel, the pyo3 binding | none needed | cel-cxx's Rust API, cel-js, cel 0.16 | Yes: six rules, every writer to every reader, all `true` |
| **cel-spec SimpleTestFile** (`cel.expr.conformance.test`; `conformance/suite.json`) | cel-spec in textproto; @bufbuild/cel-spec ships it as protobuf JSON | The conformance runners in the cel-go, cel-cpp, cel-core, cel-rust and ferricel repositories (not run here) | Seven runners here, one per engine, 100 to 150 lines each, plus `conformance/compare.py` | | Yes, the JSON form, on every engine |
| **cel-spec `cel.expr.conformance.Environment`** (`env_config.proto`) | Not written here | Untested | Untested | Untested | No. It holds the env YAML's fields plus a `message_type_extension` FileDescriptorSet, so one file could carry both artefacts. |
| **cel-spec TestSuite** (`suite.proto`, the cel-go `celtest` format) | Not written here | cel-go `tools/celtest` (not run) | Untested | Untested | No |

Findings from the artefact tests:

- **A CheckedExpr is portable across engines.** cel-core read the ones cel-go and cel-expr-python wrote, and the other way round. @bufbuild/cel read all three. No engine needed the source text or a second check.
- **The bytes aren't stable, the message is.** Re-running cel-go's writer gave different bytes of the same length for all six rules. Decoded, the old and new CheckedExprs are `proto.Equal`, and re-encoding both with Go's `Deterministic` marshal option gives identical bytes (`go/cmpchecked`). Map entries in the reference and type maps change order. So a digest of a CheckedExpr has to come from a deterministic re-encoding, not from the bytes a writer emitted.
- **A CheckedExpr carries no environment identity.** It names message types and overload ids but not the descriptor set, the extension versions or the checker options. The rules bundle has to carry the profile digest ("The environment profile"), and the evaluator has to compare it with the digest of the profile it built.
- **The env YAML is not an identity.** Two engines read it as is. The other four need an adapter, and each adapter maps extension names by hand, which is where versions can drift. It also says nothing about checker options. The extension list is also the main source of conformance gaps (see the next sections).
- **JSON is the neutral encoding of the test files.** textproto needs descriptors at parse time in every language except Go and C++; the protobuf JSON form loads with a plain JSON parser.

## The environment profile

Equal env YAML and descriptor-set hashes don't prove that two engines run the same environment. Before this revision, the demos drifted in three ways:

- the gate-guard YAML enabled strings and optionals, while the TypeScript demo installed strings only;
- the policy compiler declared its variables in code and added bindings version 1 on its own;
- the browser policy demo declared variables in code, with no extensions.

### The manifest

`gen/profile.py` writes one manifest per structural scope, `generated/profile/<scope>.profile.json`, after `buf build`. It holds:

- `descriptor_set`: the file name and the SHA-256 of its exact bytes;
- `variables`: each declaration as a CEL type name, a primitive or a message;
- `extensions`: each extension with a pinned version, in cel-go's numbering;
- `options`: `cross_type_numeric_comparisons` and `homogeneous_aggregate_literals`, both `false`, from `scopes.yaml`'s `profile_options`;
- `container` and `manifest_version`.

The **profile digest** is the SHA-256 of the manifest's canonical JSON, RFC 8785 (JCS). It is never taken over protobuf bytes. `gen/profile.py` refuses a manifest with a float, a non-ASCII string or an integer above 2^53. For that subset, JCS is sorted keys with no whitespace, which each language's standard JSON encoder produces: Python's `json.dumps(sort_keys=True)`, Go's `encoding/json` with HTML escaping off, serde_json without `preserve_order`, and a key-sorting `JSON.stringify` in TypeScript. All four computed the same digests (`generated/profile/digests.txt`; gate_guard `48201f8857b0…`).

### Adapters build their environment from the manifest

| Adapter | File | Builds from the manifest | Refuses at load |
|---|---|---|---|
| cel-go | `go/profile/profile.go` | `env.Config` in memory, plus `cel.CrossTypeNumericComparisons` and `cel.HomogeneousAggregateLiterals` from the options | Through `cel.FromConfig`: an unknown extension or version |
| cel-expr-python | `py/celprofile.py` | env YAML text in memory, with versions | An extension version outside its inventory (`bindings` 0 only: it has no `bindings#1` library); options other than cel-cpp's defaults |
| cel-core | `rust/src/lib.rs` (`load_profile`, `env_from_profile`) | `EnvConfig` in memory | The same, against its inventory (`bindings` 0: the `cel.bind` macro, no runtime `cel.@block`) |
| @bufbuild/cel | `ts/celprofile.ts` | `celEnv` with the declared variables and, if listed, `strings` | Any extension but `strings` 4; a container |
| pyo3 binding | `py/rust_binding_demo.py` | env YAML text from `py/celprofile.py` | cel-core's rules |

Each adapter also checks the descriptor set against the manifest's SHA-256. No demo reads `generated/env/*.env.yaml` any more. That file stays as the cel-go form of the same declarations, for the `cel-expr` CLI (`cli/env_json.py`) and for tools that read env YAML.

An engine without a version switch (cel-cpp, cel-core, @bufbuild/cel) can't prove which version it implements. Its inventory lists the cel-go versions whose functions the shared suite exercised on it, so the version claim rests on the suite result.

### The bundle binds a CheckedExpr to its profile and source

Each writer puts a `bundle.json` beside its CheckedExprs: the profile digest, the checker identity, and the SHA-256 of each entry's source (and, for a policy, the source file). A reader refuses a bundle whose digest differs from its own profile's, and an entry whose source changed since it was checked. Each typed demo also feeds its own bundle back with a zeroed digest and with edited sources, and records both refusals. The bundle is the metadata the adapter's `program` step reads; a bare CheckedExpr can't support that check.

### The effective-environment test

`typedemo/gate_guard.yaml` has nine `profile` cases. Three use features the manifest enables: `upperAscii` and `format` from strings 4, and a mixed-type list literal. Six use features it excludes: math, optional syntax (`.?`), bindings (`cel.bind`), encoders, lists, and a double compared with an int. A case must evaluate as expected, or be refused, exactly as the manifest says. Results, from `results/typed-demo/<engine>.json`:

| Engine | Profile cases as the manifest says | Mismatches |
|---|---:|---|
| cel-go | 9 of 9 | none |
| cel-expr-python | 9 of 9 | none |
| cel-core | 8 of 9 | `cel.bind(x, 1, x == 1)` checks and evaluates with bindings excluded: the macro is built into cel-core's parser |
| @bufbuild/cel (unchecked evaluation) | 8 of 9 | `job.progress.fraction > 0` evaluates to `true`. A check-time option can't be enforced by an evaluator; it only holds for CheckedExprs a checker wrote in the profile |

### Known mismatches

- **cel-core's parser always expands `cel.bind`.** The adapter can't turn it off. A rule checked only by cel-core could use bindings outside the profile. Only reference-checked rules run on cel-core ("The engine roles").
- **@bufbuild/cel doesn't enforce check-time options or declarations.** It evaluates only CheckedExprs from the reference checker.
- **cel-go and cel-cpp number bindings differently.** cel-go declares `cel.@block` in bindings version 1, and cel-expr-python's env config has no version 1. So the profile that compiles policy `variables` (`checks_by_iteration_bindings`) is refused by all three evaluators' adapters. That profile is outside the supported one.
- **The `tools/compiler` route adds extensions the manifest doesn't list.** It isn't used as the checker ("The reference checker").

## The type pipeline

```text
contracts/*.tsp ──TypeSpec──▶ published JSON Schema (packages/benchhand-contracts/.../schemas)
                                   │
            scopes.yaml ──────────▶ gen/celgen.py ──▶ generated/scopes.txt (structural or refused, with reasons)
  (variable → schema pointer,       │
   omitted fields, extensions)      ├──▶ generated/proto/benchhand/contracts/**.proto ──buf build──▶ generated/types.binpb
                                    └──▶ generated/env/<scope>.env.yaml
records (JSON) ──each language's protobuf JSON parser, unknown fields ignored──▶ activation messages
```

What each step does:

1. **Scopes.** `scopes.yaml` names the variables a rule list sees. Each variable points at one node of a published schema, for example `decision: record/decision.schema.json#/$defs/gate_decision`. A scope can omit a field, and an omitted field isn't declared. So a rule that reads it fails the check, which is the right result for a field that has no single type.
2. **Structural check.** `celgen.py` walks every node a rule can reach and refuses a scope if a node has more than one shape. It refuses:
    - a `oneOf` or `anyOf` whose branches carry shapes (a union);
    - an `allOf` that merges shapes;
    - an untyped node (`true` or `{}`), which would be `dyn`;
    - an object with properties that isn't sealed;
    - a map of lists;
    - a field named with a CEL reserved word (`function` in `common.schema.json`).

    Validation-only keywords are ignored, as Kubernetes does: `pattern`, bounds, `if`/`then`/`else`, `not`, and a `oneOf` of `required` clauses. `generated/scopes.txt` shows the gate-guard scope typed as 12 messages with two fields omitted. Three unscoped roots are refused with the path and reason of each union. This is item 1 of the Kubernetes adopt table, at generation time.
3. **Type mapping.**

    | JSON Schema | proto3 | CEL |
    |---|---|---|
    | required `string`, `integer`, `number`, `boolean` | `string`, `int64`, `double`, `bool` | the same |
    | optional scalar | `optional` scalar (field presence) | the scalar; `has()` tells absent from the zero value |
    | nullable scalar (`[T, null]` or `oneOf` with `null`) | `google.protobuf.*Value` wrapper | `wrapper(T)`: null when absent |
    | sealed object | message | message |
    | `additionalProperties: {schema}` | `map<string, V>` | `map(string, V)` |
    | array | `repeated` | `list(T)` |
    | `enum` of strings | `string`, values in a comment | `string`: the values aren't checked |
4. **Descriptor set.** `buf build --exclude-source-info` compiles the generated `.proto` files to a 4.8 KB FileDescriptorSet. Re-running the generator into an empty directory reproduced `proto/`, `env/` and `scopes.txt` exactly, and the descriptor set byte for byte.
5. **Activation.** A record is JSON. Each language turns it into the declared message with its own protobuf JSON parser, set to ignore unknown fields, so omitted fields drop out:
    - Python: `json_format.ParseDict`;
    - Go: `protojson`;
    - Rust: `prost-reflect` `DynamicMessage::deserialize`;
    - TypeScript: protobuf-es `fromJson`.

    No generated Rust or TypeScript structs are needed to evaluate rules. The host's own Rust and TypeScript types still come from the same JSON Schemas through the D17 generators (`typify`, `json-schema-to-typescript`).

### The bad rules, per engine

The seven bad rules in `typedemo/gate_guard.yaml`, and where each engine stops them. "check" means the type check rejected it; "eval" means it got as far as evaluation.

| Bad rule | cel-go | cel-expr-python | cel-cxx | cel-core and the pyo3 binding | @bufbuild/cel | cel-js | cel 0.16 |
|---|---|---|---|---|---|---|---|
| `decision.approvel.channel` (wrong field) | check | check | check | check | eval: field not found | check | eval: no such key |
| `job.exitcode` (the field is `exitCode`) | check | check | check | check | eval: field not found | check | eval: no such key |
| `job.progress.fraction + "x"` (double + string) | check | check | check | check | eval: no overload | **passes the check** (the wrapper is `dyn`) | eval: unsupported operator |
| `part.mass_target > "1"` (double > string) | check | check | check | check | eval: no overload | **passes the check** (the wrapper is `dyn`) | eval: no overload |
| `decision.status == 1` (string == int) | check | check | check | **passes the check**, evaluates to `false` | eval: `false` | check | eval: `false` |
| `part.intent.route.size() > 0` (omitted union field) | check | check | check | check | eval: field not found | check | **evaluates to `true`**: the untyped record still has the field |
| `undeclared.x == 1` | check | check | check | check | eval: unresolved | check | eval: undeclared |
| **Rejected at check** | **7 of 7** | **7 of 7** | **7 of 7** | **6 of 7** | **0 of 7** | **5 of 7** | **0 of 7** |

Two gaps apply to every engine:

- **Enum values aren't checked.** The schema's `enum` becomes a CEL `string`, so `decision.status == "aproved"` passes the check and is always false. cel-expr-python type-checked it as `BOOL`. Kubernetes has the same gap. A load-time lint can compare string literals against the enum the field's schema lists.
- **Heterogeneous equality depends on the checker.** cel-core and the runtime semantics of every engine treat `string == int` as `false`, not as an error. Only a checker that follows cel-go stops it.

## Conformance

### The suite

`conformance/suite.json` is cel-spec's own simple tests in their protobuf JSON form (`cel.expr.conformance.test.SimpleTestFile`), exported by `ts/export_suite.ts` from @bufbuild/cel-spec 0.6.2. It keeps every test that needs no declarations, bindings, container or conformance message types and expects a scalar, a list, a map or an evaluation error. That is 1640 of cel-spec's 2344 tests in 21 files. `conformance/suite-summary.txt` counts the rest by reason; 507 of them need a container.

Each engine has one runner (`go/conformance`, `py/conformance.py`, `rust/src/bin/conformance.rs`, `rust-cxx/src/bin/conformance.rs`, `ts/conformance.ts`). A runner builds the environment from `conformance/env.yaml` and runs every test. It checks the test unless the test sets `disableCheck`, then evaluates. It writes each result as a `cel.expr.Value` in protobuf JSON. `conformance/compare.py` applies cel-spec's matching rules: maps ignore order, any NaN matches NaN, and an unset result means `true`. `conformance/run.sh` runs everything in about 15 seconds.

### Results

| File | Tests | cel-go | cel-expr-python | cel-core | cel-cxx | cel 0.16 | @bufbuild/cel | cel-js |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| basic | 39 | 39 | 39 | 39 | 35 | 39 | 39 | 36 |
| bindings_ext | 5 | 5 | 5 | 5 | 5 | 5 | 0 | 5 |
| block_ext | 22 | 0 | 0 | 22 | 0 | 0 | 0 | 0 |
| comparisons | 352 | 352 | 352 | 352 | 336 | 324 | 352 | 300 |
| conversions | 87 | 87 | 86 | 87 | 87 | 87 | 87 | 75 |
| dynamic | 53 | 53 | 53 | 53 | 43 | 17 | 53 | 0 |
| encoders_ext | 4 | 4 | 4 | 4 | 4 | 4 | 0 | 0 |
| fields | 48 | 45 | 47 | 48 | 41 | 42 | 41 | 35 |
| fp_math | 30 | 30 | 30 | 30 | 29 | 30 | 30 | 30 |
| integer_math | 64 | 64 | 64 | 64 | 61 | 64 | 64 | 62 |
| lists | 39 | 39 | 39 | 39 | 39 | 39 | 39 | 34 |
| logic | 30 | 30 | 30 | 30 | 21 | 30 | 30 | 25 |
| macros | 44 | 44 | 44 | 44 | 44 | 44 | 44 | 42 |
| macros2 | 46 | 46 | 40 | 46 | 46 | 46 | 8 | 0 |
| math_ext | 199 | 199 | 199 | 199 | 199 | 199 | 17 | 0 |
| optionals | 59 | 57 | 59 | 58 | 59 | 59 | 1 | 21 |
| parse | 192 | 192 | 192 | 192 | 175 | 192 | 192 | 166 |
| plumbing | 4 | 4 | 4 | 4 | 4 | 4 | 4 | 4 |
| string | 51 | 51 | 51 | 51 | 51 | 51 | 51 | 51 |
| string_ext | 199 | 197 | 199 | 199 | 172 | 199 | 199 | 97 |
| timestamps | 73 | 73 | 73 | 73 | 61 | 71 | 73 | 54 |
| **All** | **1640** | **1611** | **1610** | **1639** | **1512** | **1546** | **1324** | **1037** |
| Share | | 98.2% | 98.2% | 99.9% | 92.2% | 94.3% | 80.7% | 63.2% |
| Failures that are `disableCheck` tests the checker rejected | | 0 | 0 | 0 | 87 | 0 | 0 | 0 |

`results/summary.md` holds the same table, and `results/failures-<engine>.txt` lists every failure with the expected and actual result.

### The differences

| Engine | Failures | Causes |
|---|---:|---|
| cel-go v0.33.4 | 29 | `cel.block` isn't public (22). Three map literals that cel-spec rejects (two with a repeated key, one with a float key) evaluate instead of failing. Two optional lookups on a map return `false` instead of an error. `indexOf` and `lastIndexOf` with an out-of-range start return a value. |
| cel-expr-python 0.1.4 | 30 | `cel.block` (22). `transformMap` fails with "no overload for cel.@mapInsert" (6), a gap in the binding's comprehensions extension. `string(-0.0045)` gives `-0.0044999999999999997`. One repeated map key. |
| cel-core 0.5.1 | 1 | `optional_type` isn't declared. It is the only engine that runs `cel.block`. |
| cel-cxx 0.2.5 | 128 | 87 `disableCheck` tests: the Rust API compiles only with the checker, so tests that cel-spec runs unchecked fail at the check. `cel.block` (22). 12 timestamp and duration range errors aren't raised. Backtick-quoted field names are refused (6), which looks like a parser option off in cel-cxx's defaults (assumption). One repeated map key. cel-expr-python wraps the same cel-cpp and passes all of these, so the gaps come from cel-cxx's build or options, not from cel-cpp. |
| cel 0.16.1 | 94 | No protobuf support: wrapper and `google.protobuf.Value` literals fail with "unexpected type" (64). `cel.block` (22). Backtick field names don't parse (6). Two duration overflows aren't raised. |
| @bufbuild/cel 0.6.2 | 316 | Only the strings extension ships, so math (182), optionals (58), two-variable comprehensions (38), bindings (5) and encoders (4) fail. `cel.block` (22). Backtick field names (6). One repeated map key. |
| cel-js 8.0.0 | 603 | No extension libraries: math (199), strings (102), two-variable comprehensions (46), encoders (4). Optional types are partial (38). No `google.protobuf` struct literals (53 of `dynamic`). It also has standard-library gaps: there is no `int(uint)`, two equal byte literals compare `false`, and some timestamp conversions are missing. |

What this means for the design:

- **The engines agree on evaluating the core language.** cel-go, cel-expr-python and cel-core differ on 30 tests at most, and almost all of them are `cel.block`, which is an optimiser artefact rather than a rule-author feature. The suite tests good expressions, so this says the engines evaluate a checked rule alike. It doesn't say their checkers reject the same rules: cel-core accepts `decision.status == 1` and `cel.bind` outside the profile.
- **Extensions are the main divergence.** The environment for benchhand rules may enable only extensions every executing engine has. With @bufbuild/cel in the browser, that is strings alone, unless the browser only evaluates CheckedExprs that don't use the others. The adapter's load step should refuse an env YAML that names an extension the engine lacks; in this spike each adapter maps names by hand.
- **The shared suite misses the checker gap.** cel-core scores 99.9% and still accepts `decision.status == 1`. cel-spec's simple tests check that good expressions pass, not that bad ones fail. benchhand's own suite needs reject cases, like the seven in the typed demo, run on every checker.
- **cel-js is out.** At 63% with no CheckedExpr input, it can't run the rules the host checked.

## The cel-expr CLI and cel-go's compiler package

`cel-expr` (github.com/cel-expr/skills, `cmd/cel-expr`, Apache-2.0) is a cel-go CLI with the subcommands `env`, `compile`, `eval`, `conformance`, `prompt` and `mcp`. The repository has 4 stars and was last pushed on 2026-11-25.

### Two builds tested

| | v0.4.0 release (2026-08-27) | main at a41927f (2026-11-25) |
|---|---|---|
| Source | Signed release binary, macOS arm64 | `go install github.com/cel-expr/skills/cmd/cel-expr@a41927f`, about 60 s. **Unsigned and unreleased.** |
| Checksum | Matches `checksums.txt` (`46b1d1ef…ca1c`) | Not applicable |
| cosign signature and SLSA provenance | **Not verified.** cosign and slsa-verifier aren't installed, and the safety net refused the `checksums.txt.pem` download. The bundle's certificate names the workflow `cel-expr/skills/.github/workflows/release.yml@refs/tags/v0.4.0`, issued by GitHub Actions OIDC. I read that identity, but it isn't a verification. | Not applicable |
| `-format policy`, `-proto_db`, `conformance` | Not present | Present |
| Typed demo: good rules compiled | 6 of 6, exit 0 | 6 of 6, exit 0 |
| Typed demo: bad rules rejected | 7 of 7, exit 1, including `decision.status == 1` | 7 of 7, exit 1 |

A pinned install for CI should verify both the signature and the provenance, once a release carries `-format` and policy support.

### What it reads and writes

- **Environment.** JSON only; YAML is refused with a JSON parse error. The layout is cel-go's `env.Config`, but each variable has a `type` string (`list<string>`, a message name) where cel-go has `type_name` and `params`. The CLI converts its own `Config` struct to cel-go's. So our env YAML needs a mechanical conversion, `cli/env_json.py`, which is 12 lines for plain types. The generator could write both forms.
- **Types.** `-fds` takes a binary FileDescriptorSet; our `types.binpb` loads as is. `-proto_db` is a boolean, not a path: it resolves declared type names from the protobuf registry compiled into the binary (well-known and test types), or from a database a fork installs at init time. benchhand doesn't need it.
- **Errors.** cel-go's text: `ERROR: <input>:1:17: found no matching overload for '_==_' applied to '(string, int)'`, then the source line and a caret. For a policy file, the location is the YAML file, line and column. A rule's own path in a benchhand file, for example `flow.yaml#/gates/…`, still has to come from the host.
- **Output.** `compile` prints a JSON Schema of the fields the rule reads and of its output type. It writes **no CheckedExpr**, at either version; the source has no CheckedExpr code and no output flag. The inputSchema also has a bug: `has(part.mass_target)` reports the field as `boolean`, where the field is a `double`.
- **Tests.** `eval -tests` and `-bindings` take JSON test cases. Our JSON records are bound to the generated proto types. Each run prints pass or fail per case, node and branch coverage, and exits 1 when a case fails.

So the CLI can't replace `go/cmpchecked`, and it can't write the CheckedExprs that the browser and providers evaluate. It is a good tool for authoring and for a `rules test` step. As the CI reference checker, it covers checking only.

### The library route: `cel.dev/cel-go/tools/compiler`

cel-go is moving to the module path `cel.dev/cel-go`. From 2026-09-08, `github.com/google/cel-go/tools/compiler` holds only aliases, and the tagged modules are `cel.dev/cel-go` v0.33.4 and `cel.dev/cel-go/tools` and `/policy` v0.33.3. The package gives:

- `EnvironmentFile(path)`, which reads the env as YAML (cel-go's `env.Config`), or as a textproto or binary `cel.expr.conformance.Environment`.
- `TypeDescriptorSetFile(path)`. It infers the format from the extension and takes `.binarypb`, `.fds` or `.pb`, so buf's `.binpb` has to be copied under another name.
- `CompiledExpression{Path}`, which reads a CheckedExpr, and `FileExpression` for a `.cel` or `.celpolicy` file.
- `NewCompiler` **always appends the latest `optional` and `bindings` extensions** (`compiler.go`, `extensionOpt`), whatever the env file says.

So it can't be an exact-profile checker. `go/toolscompiler` runs the nine profile cases through it with the gate-guard env YAML, which names strings only. Two excluded features check: `part.?mass_target.hasValue()` and `cel.bind(x, 1, x == 1)` (`results/typed-demo/tools-compiler.json`, 7 of 9 as the profile says). A browser-profile rule could pass that checker and then fail in @bufbuild/cel.

### The reference checker

`go/celcheck` is the reference checker: cel-go with exactly the profile's environment. `go/profile` builds it from the manifest with explicit options (`cel.TypeDescs`, the declared variables, each listed extension at its pinned version through `cel.FromConfig`, and `cel.CrossTypeNumericComparisons`), and appends nothing. It has two commands:

- `celcheck rules <profile> <file>` checks accept, reject and profile cases and writes `generated/checked/cel-go-ref/` with its bundle. It exits non-zero when an accept case fails, a reject case checks, or a profile case that uses an excluded function or syntax checks.
- `celcheck policy <profile> <file> <name>` compiles a `.celpolicy` into `generated/checked-policy/<profile>/`, bound to the policy's source digest.

On the gate-guard profile it accepted 6 of 6, rejected 7 of 7, and refused all 6 excluded features while the 3 enabled ones checked (`results/typed-demo/celcheck.json`). The policy with `variables` fails to compile in the restricted profile (`undeclared reference to 'cel.@block'`), which is the intended refusal.

**One cel-go version.** The conformance oracle (`go/conformance`), the typed demo, `celcheck` and the `tools/compiler` probe all build from one module, `go/go.mod`, pinned to `cel.dev/cel-go` v0.33.4 (and `/policy` v0.33.3, which resolves against it). Moving the oracle from `github.com/google/cel-go` v0.30.0 left its suite total at 1611 of 1640; only the wording of the 22 `cel.block` errors changed (`conformance/results/failures-cel-go.txt`). So the oracle's score now describes the same cel-go build that checks the rules.

Use the `cel-expr` CLI beside `celcheck` for `rules test` and for authors.

## cel-policy

cel-policy (github.com/cel-expr/cel-policy, Apache-2.0, created 2026-05-07, 9 stars, last push 2026-08-18) defines a YAML policy format and holds its conformance suite. The suite has 28 policy cases, plus 16 compile-error cases that a conforming compiler must reject.

A policy has:

- a `name`;
- `imports`, which are type aliases;
- a `rule` with ordered, lazily evaluated and memoised `variables`;
- a `match` block (first-match) or an `aggregate` block, which collects every matching output into a list;
- choices with a `condition`, an optional `explanation`, and an `output` or a nested `rule`.

The compiler requires every output path to have the same type. A `match` with no unconditional last choice returns an optional, and an empty `aggregate` returns `[]`.

### benchhand's rule lists are a subset

A `*.rules.yaml` in the plan is an ordered, first-match list of `{when, then}`. That is a cel-policy `match` block: `when` is `condition` and `then` is `output`. `policy/checks_by_iteration.rules.yaml` and `policy/checks_by_iteration.celpolicy` hold plan section 5's "checks by iteration" list in both forms. Over our format, cel-policy adds:

- `variables`, the same idea as the Kubernetes report's row 20;
- `explanation`, a CEL string per choice, which is close to row 14 (`message_expr`);
- `aggregate`, for "run every check whose condition holds";
- the output-type agreement check, which is row 5 for rule lists;
- reachability errors, for example a choice after an unconditional one.

### Tested

| Step | Tool | Result |
|---|---|---|
| Compile the policy against the generated descriptor set | `cel-expr compile -format policy` (main, unsigned) | Exit 0. Output type `list(string)` |
| Compile a policy with a wrong field and a `string` output among `list(string)` outputs | the same | Exit 1, both errors, each at its file, line and column in the `.celpolicy`, with a caret |
| Evaluate four cases on real proto types | `cel-expr eval -format policy -tests policy/tests.json` | 4 of 4 pass; node coverage 80%, branch coverage 80% |
| Compile to one CheckedExpr | `go/celcheck policy` (over `cel.dev/cel-go/policy` v0.33.3) | `policy.Compile` returns one checked AST. With `variables` it is `cel.@block([iteration == "commit"], … @index0 …)`. Without them it is nested `?:` |
| Evaluate that CheckedExpr, with `variables` | cel-expr-python, cel-core, @bufbuild/cel | cel-expr-python 4 of 4. cel-core and @bufbuild/cel fail: neither has a runtime `cel.@block` |
| Evaluate that CheckedExpr, without `variables` | the same three | 4 of 4 on each |

### Which engines implement policies

- **The policy format** is implemented by cel-go (`cel.dev/cel-go/policy`), cel-cpp (`policy/cel_policy.cc`) and cel-java. Those three run the conformance suite.
- **cel-expr-python, cel-core and @bufbuild/cel have no policy parser.** They don't need one: a compiled policy is a single CheckedExpr. cel-expr-python also runs the `cel.@block` form, because cel-cpp's runtime has the block extension.
- **The `cel.@block` form is the portability limit.** In the shared suite, only cel-core passed `block_ext`, and only through its parser macro. At runtime it doesn't accept the `cel.@block` call that cel-go's composer writes. A policy that has to run on cel-core or in the browser can't use `variables` until those engines evaluate `cel.@block`. It also needs an unconditional last choice in each `match`, or the optional extension in every engine.

### Should benchhand adopt the format?

Recommended, **pending the owner's decision**: yes, for rule lists only, compiled ahead of load.

- **Rule lists are compiled, not checked at load.** `benchhand rules compile`, and the same step in CI, runs the pinned cel-go reference checker (see "The reference checker") on every `flow/*.celpolicy`. It writes each list's CheckedExpr into the rules bundle, with the list's output type, the SHA-256 of the exact source bytes, the profile digest and the checker identity.
- **The host refuses a missing or stale artefact.** At load, the host hashes each rule-list source and looks it up in the bundle. A list with no entry, a different source digest or a different profile digest stops the load. The error names the file and the command to run. The host then evaluates the CheckedExpr with cel-expr-python, which has no policy API (0.1.4) but reads the compiled form.
- **Standalone CEL is still checked at load.** Gate `requires`, edge guards, `void_scope` and every other single expression in `flow.yaml` are checked by cel-expr-python when the host loads them, as ADR-0014 requires now.
- **No match still means UNKNOWN.** cel-policy returns `optional.none()` from a `match` whose choices are all conditional, and that needs the optional extension in every evaluator, which the browser lacks. The supported profile therefore requires an unconditional final choice ("The supported policy profile"). A dispatch list ends with `- output: '"unknown"'`, the rule-list schema reserves the value `unknown`, and the host records it as UNKNOWN coverage, never PASS. A list whose outputs are lists ends with an explicit sentinel of the same type, so the compiler's output-type check still holds.
- **`flow.yaml` keeps its own schema.** Gates, edges and `void_scope` are structure, not rule lists.

The alternative is to compile policy source at load, inside the host, with a pinned compiler. That is either the same cel-go tool shipped with benchhand and run as a subprocess, or a Python port of cel-go's policy composer over cel-expr-python. The port would parse the YAML, check each condition and output, and compose the nested conditionals. An edit then takes effect without a compile step. The cost is a Go binary on the host's load path, or a second composer that must pass the cel-policy conformance suite to stay equal to cel-go's. The recommended path keeps one composer and moves the compile step to authoring time, at the cost of a compile step after every edit.

## The cel-expr/skills agent skills

cel-expr/skills ships six skills under `skills/` and an MCP server (`cel-expr mcp`). I read them at a41927f. The MCP server exposes `cel_create_environment`, `cel_compile`, `cel_evaluate`, `cel_evaluate_conformance` and `cel_generate_prompt`. It has a fixed-environment mode, in which the tools take no environment argument.

| Skill | Lines | What it does | Fit with the standard |
|---|---:|---|---|
| `cel-authoring` | 169 | Write an expression or a `.celpolicy` against an env JSON, compile it with `cel-expr`, and test it | **Conflicts on environments.** When it finds no `*_env.json`, the agent searches the code and writes an `envConfig` itself, and builds a descriptor set with `protoc` on the fly. Both break standard rule 1. It also advises namespaced simple variables (`request.path: string`) over message types, and enum variables declared as `int`. Its policy section matches standard rule 12. |
| `cel-debugging` | 165 | Fix compile and runtime errors: presence with `has()` or `.?`, overload mismatches, and narrowing `dyn` | Compatible. It narrows `dyn` toward simple types, the same direction as rule 2. Its map-lookup fixes (`'k' in m`) don't apply to message-typed scopes. |
| `cel-testing` | 104 | Derive test cases from `compile`'s inputSchema, then evaluate until branch and node coverage reach 100% | Compatible, and it fills a gap: the standard has no coverage rule. It installs with `go install …@latest`, which conflicts with pinning (rule 8). The inputSchema bug above (a `double` reported as `boolean` after `has()`) misleads its test generation. |
| `cel-optimize` | 248 | Simplify an expression and prove it equivalent with the cel-java verifier (a JAR from Maven Central, Java 8+) | Neutral. Its `cel.bind` rewrites run on every engine in the shared suite except @bufbuild/cel. Its optional-chaining rewrites need the optional extension, which @bufbuild/cel and cel-js lack (rule 9). |
| `cel-conformance-testing` | 209 | Write and run cel-spec conformance tests in textproto for cel-go, cel-cpp and cel-java | Aimed at contributors to the CEL implementations, not at rule authors. The project's suite in this report uses the protobuf JSON form instead. |
| `cel-doc-generator` | 259 | Write README files for extension libraries in the CEL repositories | Out of scope: it targets the cel-go, cel-cpp and cel-java repositories. |

None of the skills mentions CheckedExprs, a compiled bundle, structural scopes or a generated environment. Their model is an agent that writes an expression and its environment together, for one engine, cel-go.

### What to vendor into a harness-plugins `rules` plugin

- **Vendor `cel-testing`,** pinned to a released, verified `cel-expr`, with a coverage threshold as the check.
- **Vendor `cel-debugging`** as is.
- **Vendor the policy section and the error-fixing steps of `cel-authoring`.** Replace its "Locate or Create Environment" step with: use the generated env (converted to JSON with `cli/env_json.py` or written by the generator) and the generated descriptor set; if none exists for the scope, stop and ask for one to be generated. Drop the on-the-fly `protoc` alias.
- **Leave out `cel-optimize`** until a project needs it. It adds Java to the toolchain.
- **Leave out `cel-conformance-testing` and `cel-doc-generator`.**
- **Use the MCP server in fixed-environment mode only,** pointed at the generated environment. Its `cel_create_environment` tool is the hand-written environment in tool form.

Vendoring means a copy with a recorded upstream commit, as `reference/` does for the prototype. The changed steps are a local patch on top.

## The recommended design

### Where checking happens

The checker runs in two places, and an evaluator anywhere.

1. **At load, in the host.** The Python host checks every standalone expression (gate `requires`, edge guards, `void_scope`) with cel-expr-python against the profile, as ADR-0014 already requires: a typo fails at load. Errors carry the rule's file path, for example `flow.yaml#/gates/PROVISIONAL/requires/0`, and the line, column and caret (Kubernetes rows 4 and 5). Each slot's output type is checked too: `requires` and `when` must be `bool`. Rule lists aren't compiled at load: the host loads their CheckedExprs from the bundle and refuses a list whose entry is missing or stale ("Should benchhand adopt the format?").
2. **In CI, with cel-go as the reference.** `go/celcheck` checks every rule list and every rule that ships across a boundary, and its result decides. cel-expr-python checks the same rules as the host's checker of record for standalone expressions, and CI fails when the two disagree on whether a rule checks or on its output type. cel-core's check runs too, as a diagnostic that finds gaps like its `string == int`. The cel-go side is `go/celcheck`, which builds its environment from the profile manifest with explicit options and writes CheckedExprs. The `cel-expr` CLI runs the typed `rules test` cases (`eval -tests`, with coverage). cel-go's cost estimator also runs here, which gives Kubernetes row 8 (a static cost estimate) without a Python cost API.

A successful check produces a **compiled rules bundle**:

- the CheckedExpr of each rule, keyed by its file path. A rule list written as a `.celpolicy` is compiled by cel-go's policy compiler into one CheckedExpr for the whole list;
- the rule's output type;
- the digest of the env YAML and of the descriptor set it was checked against;
- the checker's identity (engine, version, options), as Kubernetes row 11 asks.

The host writes the bundle at load, as a cache, and on request (`benchhand rules compile`). A provider's publish step can write one too. The bundle shape is a contract like any other, so it is defined in `contracts/` (ADR-0017), not in an engine's code.

An evaluator only needs the bundle. It compares the two digests with its own environment and refuses a mismatch, then runs each CheckedExpr without checking again. That is how the browser runs typed rules with @bufbuild/cel, which has no public checker. A CheckedExpr's digest comes from a deterministic re-encoding, because writers emit map entries in any order.

So checking is a separate step that ships CheckedExprs, with one condition: the host still checks at load, because users and policy providers can change rules between releases.

Agents that write rules work against the same generated artefacts. The `rules` plugin's skills and the `cel-expr mcp` server in fixed-environment mode read the generated environment and descriptor set, and never author an environment.

### The engine roles

An engine's role decides what its results can prove:

- **Checker of record.** Its check decides whether a rule ships. cel-go (`go/celcheck`) checks rule lists and anything shipped across a boundary. cel-expr-python checks standalone expressions at load in the host. Both rejected 7 of 7 bad rules and refused all 6 excluded features.
- **Evaluator.** It runs only CheckedExprs that a checker of record wrote in the same profile, after the bundle check. Its own checker, if it has one, is diagnostic. cel-core and @bufbuild/cel have this role.
- **Source-checking alternative.** It checks and evaluates source, but can't read or write a CheckedExpr. cel-cxx has this role: its Rust API has no CheckedExpr input or output, so it can't run the bundle (standard rules 5 and 7).

**cel-core is a candidate evaluator, not a checker of record.** Its suite score (1639 of 1640) measures evaluation of good expressions. Its checker accepts `decision.status == 1`, and its parser expands `cel.bind` outside the profile ("Known mismatches"). So:

- A Rust tool that authors or checks rules, and the pyo3 fallback in the Python host, validate each rule with the reference checker before it ships or counts. The other way is an independent reject suite on cel-core that covers every check the profile relies on. The typed reject cases and the profile cases are the start of that suite. cel-core fails 2 of the 16 (`results/typed-demo/cel-core.json`).
- The CI differential check protects only shipped rules. A rule edited locally and checked only by cel-core is unchecked for this purpose.
- Promoting cel-core to a required engine needs an owner for its upgrades, for upstream fixes and, if upstream stalls, for a fork. A pinned version and an MIT OR Apache-2.0 licence allow a fork but don't supply anyone to maintain it. cel-core has one maintainer and no push since 2026-02-16.

### The engine in each runtime

| Runtime | Engine | Role | Checks | Evaluates | Reads |
|---|---|---|---|---|---|
| Python host | cel-expr-python | Checker of record for standalone expressions; evaluator | Yes, at load | Yes | profile manifest, descriptor set, bundle |
| CI, `benchhand rules compile` | cel-go (`go/celcheck`) | Reference checker, cost estimate, conformance oracle | Yes | The oracle | profile manifest, descriptor set; writes the bundle |
| Rust component or provider | cel-core, through the adapter crate | Candidate evaluator | Diagnostic only | Bundles in its profile | profile manifest, descriptor set, bundle |
| Rust, source checking | cel-cxx | Source-checking alternative | Yes | Source only | profile (adapter), descriptor set |
| Browser (preview host, gate card) | @bufbuild/cel | Evaluator, restricted profile only | No | Bundles in its profile | profile manifest, descriptor set, bundle |
| Python fallback | the pyo3 binding over cel-core | Evaluator; its checks need the reference checker | Diagnostic only | Yes | the same as cel-core |

A provider in any other language either takes the bundle from the host or uses its language's engine in one of these roles, and passes the same gate.

### The adapter interface

Every runtime wraps its engine in the same five operations. Each operation names a cross-language artefact, not a type from one engine:

```text
load(manifest, descriptor_set) -> Environment | [Issue]   refuse an extension version or option it doesn't implement
check(env, path, expr, slot)    -> CheckedExpr | [Issue]   absent where the engine has no checker
program(env, bundle_entry)      -> Program | [Issue]       refuse another profile's digest or a stale source
eval(program, activation)       -> Value | EvalError       activation: variable -> record (JSON) or message
identity()                      -> {engine, version, options}
```

- An `Issue` is `{path, line, column, message}`.
- A `Value` leaves the adapter as `cel.expr.Value` protobuf JSON, the encoding the conformance runners already use. So results compare across languages with one comparator.
- `eval` returns an error for a rule that fails to compile or evaluate, and the caller records it as a finding with coverage UNKNOWN, not PASS (Kubernetes row 6). The adapter tests assert this.

The spike has most of this per language already: the profile loaders (`go/profile`, `py/celprofile.py`, `rust/src/lib.rs`, `ts/celprofile.ts`) for `load` and the bundle check, `rust-py/src/lib.rs` (check, program and eval for Python over Rust), and the runners' value encoders.

### What gives Rust equal standing

Three things, all of which this design needs anyway:

1. **A required Rust job in CI.** It runs the supported-profile gate on cel-core as an evaluator, and records its own checker's results on the typed reject and profile cases as diagnostics.
2. **A Rust adapter crate** (`benchhand-cel`) with the five operations over cel-core. It reads the profile manifest and the bundle. Its `check` is labelled diagnostic until cel-core passes the reject suite.
3. **Contract types for Rust providers.** `typify` structs for host code (D17), plus the descriptor set for rule activations, so a Rust provider needs no second schema.

These three make Rust providers first-rate as evaluators, on the condition above: someone owns cel-core's upgrades, fixes or fork. A Rust host component is a different decision. The pyo3 measurement says crossing from the Python host into a Rust component is cheap: 87 lines for the CEL part, and one abi3 wheel per platform. Plan section 4 (D12) still says "Python host and core; no Rust". Moving the flow interpreter or another host component to Rust means changing D12, which is the owner's call.

### Alignment with the Kubernetes adopt table

| Kubernetes row | Part of this design that carries it |
|---|---|
| 1. Structural activation scopes | `celgen.py` refuses a union on a reachable path at generation; `scopes.txt` reports each refusal with its path |
| 2. Flat unions | Unchanged: a scope omits the union field until the contract flattens it |
| 3. `dyn` escape hatch | Not used. cel-js shows the cost: a field typed `dyn` lost two type errors in the demo |
| 4, 5. Compile at load with paths; output type per slot | Host check at load, all issues returned; the bundle records each output type |
| 6. Never pass a broken rule | The adapter's `eval` contract |
| 7, 8. Cost | Bounds and a timeout in every adapter; cel-go's static estimate in CI |
| 9. Environment profiles | One env YAML per profile, generated; the bundle records which one |
| 11. Pin runtime behaviour | `identity()` in every adapter and in the bundle |
| 12, 13. Known-function test; library discipline | `load` refuses unknown extensions; the extension list is the intersection of the executing engines |
| 24. Absent versus null | Optional scalars have presence and nullable ones are wrappers, so `has()` works in every engine that reads protos |
| 25. Table-driven rule tests | `typedemo/*.yaml` is that format; a `rules test` command runs it on the host engine |
| 26. Environment as data | Adopted now. cel-expr-python reads message-typed variables from the env YAML, which the Kubernetes report left unverified |

## Proposed changes to plan section 5 and ADR-0014

These are proposals. Nothing in `docs/` changes in this branch. The rule-list path is **pending the owner's decision**; the text below is the recommended path.

### Plan section 5, "Flow engine and rules (D14)"

Replace the **Rule lists** bullet. Current text: "Rule lists replace the tables. Each is an ordered, first-match list of `{when: <CEL>, then: <value>}`, validated against its schema:" Proposed, with the four sub-bullets kept and the dispatch one changed:

> - **Rule lists** replace the tables. Each is a cel-policy file (`flow/*.celpolicy`): one `match` block of `{condition, output}` choices, evaluated first-match, whose final choice is unconditional. The supported policy profile (plan section 5, CEL engines) limits the other features. Rule lists are compiled, not checked at load. `benchhand rules compile`, and the same step in CI, runs the pinned cel-go reference checker. It writes one CheckedExpr per list into the rules bundle, bound to the SHA-256 of the list's source bytes. The host refuses to load a list whose bundle entry is missing or stale, and names the command to run.
>   - **process-check dispatch:** process × operation × material → handlers. The final choice outputs `"unknown"`, a value the rule-list schema reserves, and the host records it as UNKNOWN coverage.

In the **Interpreter** bullet, "compiles every CEL expression once at start" becomes "compiles every standalone CEL expression in `flow.yaml` once at start, and loads the compiled rule lists from the bundle".

Replace the **Interpreter** bullet's type sentence. Current text: "CEL activation variables are typed from the contracts (D17), so the CEL type-checker catches wrong field names." Proposed:

> CEL activation variables are typed from the contracts (D17). `contracts_gen` generates, from the published JSON Schemas, a FileDescriptorSet and one cel-go environment YAML per rule scope. A scope is typed only when it is structural: a union on a path a rule can reach is refused at generation, with the path and the reason. The checker then catches wrong field names, wrong operand types and reads of omitted fields.

Replace the **CEL runtime** bullet. Current text: "`cel-expr-python`, Google's C++-backed binding, which is young (0.1.x). A Rust-backed binding is the fallback behind one small adapter interface. The conformance suite runs the same expressions on both." Proposed:

> - **CEL engines**, each behind the same five-operation adapter (`load`, `check`, `program`, `eval`, `identity`). Each engine has a role: checker of record, evaluator, or source-checking alternative. The Python host checks standalone expressions and evaluates with `cel-expr-python`. CI and `benchhand rules compile` check with the pinned `cel-go` reference checker. Rust components and providers evaluate bundles with `cel-core`, a candidate evaluator whose own checker is diagnostic; promoting it needs an owner for upgrades, fixes or a fork. `cel-cxx` is a source-checking alternative, not a bundle evaluator. The browser evaluates bundles in the restricted profile with `@bufbuild/cel`. A Python fallback is a pyo3 binding over `cel-core`, whose rules the reference checker validates.
> - **Compiled rules.** The rules bundle holds the CheckedExpr of every rule list, compiled by `benchhand rules compile` or CI, and of every standalone expression, checked by the host at load. Each entry has its output type, the SHA-256 of its source bytes, the profile digest and the checker's identity. An evaluator in any language runs the bundle without checking again and refuses an entry whose profile digest differs from its own. The bundle shape lives in `contracts/`.
> - **Conformance.** One suite runs on every engine in CI: cel-spec's simple tests in protobuf JSON, plus benchhand's typed accept and reject cases. CI also fails when cel-go, cel-expr-python and cel-core disagree on whether a shipped rule checks. The environment may enable only extensions that every executing engine has.

Plan section 4 (D12), the CEL row of the table: change Rust from `cel-rust` to `cel-core` (it reads and evaluates CheckedExprs; its checker is diagnostic) and TypeScript from `cel-js` to `@bufbuild/cel` (it evaluates CheckedExprs). If the owner wants a Rust host component, the "no Rust" choice under the table changes too; see the open questions.

### ADR-0014, "The flow is data, the rules are CEL"

ADR-0014 is accepted, so this is an amendment to its Consequences, or a new ADR that ADR-0014 links to; the owner picks. Proposed text:

> CEL is compiled and type-checked before it runs, against types generated from the contracts. A standalone expression is checked at load. A rule list is a cel-policy file, compiled by a pinned reference checker ahead of load; the host refuses a rule list whose compiled form is missing or doesn't match its source. The generated artefacts are a FileDescriptorSet and a cel-go environment YAML per rule scope, and only structural scopes are typed. A rule crosses a language boundary as a `cel.expr.CheckedExpr`, together with the digest of the environment it was checked against. Every runtime runs its own CEL engine behind one adapter interface, and every engine passes one shared conformance suite in CI. That suite includes rules that must fail the check. The engine choices and the suite live in plan section 5, not in this ADR, so changing an engine doesn't reopen the decision.

## CEL adoption standard

This section applies to any project that adopts CEL, so it can become a harness-plugins steering standard. Each rule names the check that enforces it.

1. **Rules are CEL strings, and the type environment is data.** Generate a FileDescriptorSet and a cel-go environment YAML from the schema that is the source of truth. Never hand-write either one. Check: a CI job regenerates both and fails on a diff.
2. **Type structural scopes only.** Every node a rule can reach has one shape. Refuse a union (`oneOf`, `anyOf`, a merging `allOf`) and an untyped node on a reachable path, with its path and reason. Flatten the union in the schema, or omit the field from the scope. Don't type it `dyn`. Check: the generator exits non-zero on a refused scope.
3. **Map nullability on purpose.** A nullable scalar becomes a protobuf wrapper and an optional scalar gets field presence, so `has()` works. An absent field is an error unless a rule guards it with `has()`.
4. **Check before the first evaluation.** Check every rule when it loads, or in a compile step before it can run, and return every issue with its file path, line and column. Check each slot's output type. A rule that fails to check or to evaluate never counts as a pass. Check: the adapter tests.
5. **Ship a checked rule as a CheckedExpr.** A rule crosses a process or language boundary as a `cel.expr.CheckedExpr` in a `google.protobuf.Any`. It carries the digests of the environment YAML and descriptor set it was checked against. An evaluator refuses a digest that differs from its own. Digest a deterministic re-encoding, never the writer's bytes.
6. **Wrap the engine in one adapter per runtime,** with the same operations everywhere: load the environment, check, build a program from a CheckedExpr, evaluate, and report the engine's identity. Values leave the adapter as `cel.expr.Value` protobuf JSON.
7. **Choose engines by evidence.** The criteria are: a checker, CheckedExpr input and output, environment YAML input, the project's suite result, maintenance and licence. As of 2026-11, the choices are:
    - Go: cel-go.
    - Python: cel-expr-python.
    - Rust: cel-core as an evaluator of reference-checked CheckedExprs, with a named owner. cel-cxx checks source where a C++ toolchain and Bazel are acceptable, but can't run a bundle.
    - TypeScript: @bufbuild/cel, evaluating CheckedExprs only.

    An engine without a checker may only run rules a checker has already checked.
8. **Run one conformance suite on every engine in CI.** Use cel-spec's simple tests in protobuf JSON, plus the project's own typed cases. The typed cases include rules that must fail the check: a wrong field, a wrong operand type, a read of an omitted field and an undeclared variable. Also fail CI when the checkers disagree on a shipped rule. Pin each engine's version and options, and record them. For the cel-go reference, use a small tool that builds the environment from the profile manifest with explicit options, and test that an excluded function or syntax fails to check. Use one pinned cel-go version for the checker and the conformance oracle. The `cel-expr` CLI can run typed test cases, but it writes no CheckedExpr. Install it only from a release whose signature and provenance you verify.
9. **Enable only shared extensions.** The environment names only extensions that every engine that runs the rules has, at a pinned version. The adapter's load step refuses any other.
10. **Bound the cost.** Bound every collection a scope exposes in the schema, set an evaluation timeout in every adapter, and run a static cost estimate (cel-go's) on shipped rules in CI.
11. **Leave enum values to a lint.** A string enum becomes a CEL `string`, so the checker doesn't catch a misspelt value. Add a load-time lint that compares string literals with the enum of the field they are compared to.
12. **Write a rule list as a cel-policy file.** An ordered first-match list is a cel-policy `match` block. Compile it with a policy compiler (cel-go, cel-cpp or cel-java), which checks that every output has the same type and that no choice is unreachable. Ship the one CheckedExpr it produces. Use policy `variables` only if every engine that runs the policy evaluates `cel.@block`. Check: the policy conformance cases and the project's suite on each evaluator.
13. **Point rule-writing agents at the generated environment.** Agent skills and MCP tools for CEL read the generated environment and descriptor set, and never write their own: use the `cel-expr` MCP server in fixed-environment mode. When no generated environment covers a scope, the agent stops and asks for one. Check: the plugin's skills carry no environment-authoring step.

## Reproduce the results

From `research/cel-neutral/`, with the builds already in place:

| What | Command | Time here |
|---|---|---|
| Regenerate the types | `cd py && uv run python ../gen/celgen.py ../scopes.yaml --out ../generated`, then `cd ../generated && buf build --exclude-source-info -o types.binpb` | seconds |
| Typed demo, per engine | The `typed_demo` program in `go/`, `py/`, `rust/`, `rust-cxx/` (binary `cel_neutral_cxx`) and `ts/` | seconds each |
| Typed demo through the pyo3 binding | `cd rust-py && maturin build --release`, then `cd py && uv run --with <wheel> python rust_binding_demo.py` | 50 s build |
| Shared suite on all seven engines | `conformance/run.sh` | 15 s |
| The `cel-expr` CLI on the typed demo | `cd py && uv run python ../cli/env_json.py ../generated/env/gate_guard.env.yaml ../cli/gate_guard.env.json`, then `cli/compile_demo.sh <cel-expr> cli/gate_guard.env.json` | seconds |
| The reference checker on the typed demo; the `tools/compiler` probe | `cd go && go run ./celcheck rules gate_guard ../typedemo/gate_guard.yaml`; `go run ./toolscompiler` | seconds |
| The rule list as a policy | `cel-expr eval -format policy -env cli/checks_by_iteration.env.json -fds generated/types.binpb -expr policy/checks_by_iteration.celpolicy -tests policy/tests.json`; `cd go && go run ./celcheck policy <profile> ../policy/<name>.celpolicy <name>`; then the `policy_demo` program in `py/`, `rust/` and `ts/` | seconds each |

The typed demo exits non-zero on cel-core (the `string == int` rule), on @bufbuild/cel (no checker) and on cel-js (the two `dyn` wrappers). Each exit code reports an engine finding listed above.

Builds in this worktree:

- The cel-cxx release build, with its Bazel build of cel-cpp, came from the previous run. This run added a second binary to it, which relinked in 14 s without rebuilding cel-cpp.
- The pyo3 binding compiled cel-core again in the release profile (50 s, pure Rust).
- No other engine was built from source.

`target/`, `node_modules/`, `.venv/` and the raw `results/*.jsonl` are ignored and not committed.

## Untested, and the risks

- **ferricel and rscel weren't run.** Their rows come from their documentation.
- **A CheckedExpr against a different environment wasn't tested.** The bundle's digest check is a design requirement, not a measured behaviour.
- **Two cel-cxx causes are assumptions.** The backtick and timestamp-range failures are read as defaults in cel-cxx's build. They weren't traced into its cel-cpp version.
- **cel-core in a browser was out of scope.** It compiles to WebAssembly in principle; that would give one Rust engine in every runtime, but this run built no new engine.
- **The `cel.expr.conformance.Environment` proto and the `celtest` suite format weren't exercised.**
- **cel-core's maintenance is the main risk** of the Rust choice: one maintainer, and no push since 2026-02-16. A pinned version and the gate limit the damage, and the licence (MIT OR Apache-2.0) allows a fork. None of those supplies a maintainer, so promotion waits for an owner.
- **@bufbuild/cel is beta, and its checker isn't public.** The browser plan depends only on its evaluator reading CheckedExprs. That worked in 0.6.2 for all 18 shipped rules here; whether its own test suite covers checked input is unverified.
- **The suite covers 1640 of cel-spec's 2344 simple tests.** The rest need declarations, bindings or the conformance message types, and adding them means a typed-value encoder in every runner.
- **The `cel-expr` signature and provenance weren't verified,** and the policy tests used an unsigned build of main. Only the checksum of the v0.4.0 release was checked.
- **The cel-policy conformance suite wasn't run** on any engine. Only one benchhand rule list, in two variants, was compiled and evaluated.
- **The cel-expr/skills skills weren't run with an agent.** Their review comes from reading them.

## Open questions for the owner

1. **What does Rust's equal standing cover?** Rust providers only, which this design gives without a plan change? Or a Rust host component, such as the flow interpreter behind pyo3, which changes D12's "no Rust"?
2. **Who owns cel-core, if it is promoted?** It is the only Rust candidate evaluator that reads CheckedExprs and passed 1639 of 1640, but it has one maintainer and two checker mismatches, so it evaluates and doesn't check of record. cel-cxx shares cel-cpp's checker with the Python host, but needs Bazel and a C++ toolchain in every Rust build and can't run a bundle.
3. **Is the rules bundle user-facing?** It could be a `benchhand rules compile` command whose output lives in the project, or an internal cache the host writes at load and hands to the browser and providers.
4. **Does the browser evaluate rules, or only show results the host computed?** If it only shows results, @bufbuild/cel isn't needed and the extension set isn't limited to strings.
5. **Amend ADR-0014 or write a new ADR** for the artefacts, the bundle and the engine set?
6. **Report the gaps upstream?** The gaps are cel-core's `string == int` check, cel-expr-python's `transformMap`, and cel-cxx's `disableCheck` entry point and timestamp range.
