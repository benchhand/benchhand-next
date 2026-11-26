# CEL across languages: engines, artefacts, and a design that gives Rust equal standing

Status: research only. Written 2026-11-26 in a worktree of benchhand-next. Every number below comes from code in `research/cel-neutral/` that ran in this worktree, unless it is marked untested. The Kubernetes research it aligns with is `research/cel-k8s/REPORT.md` on branch `pi-subagents/task-1-9f42c8d-df91-s0-t0`.

## Verdict

CEL can be language-neutral for benchhand. The artefacts below are neutral and were tested across engines:

- **Types:** a FileDescriptorSet generated from the published JSON Schemas.
- **Environment:** a cel-go environment YAML.
- **Compiled rule:** a `cel.expr.CheckedExpr` in a `google.protobuf.Any`.

cel-go, cel-expr-python and the Rust crate cel-core each check a rule against those artefacts and write a CheckedExpr. Those three engines and `@bufbuild/cel` in TypeScript evaluated every CheckedExpr the others wrote. A wrong field name fails the check in cel-go, cel-expr-python, cel-cxx, cel-core and cel-js.

Checking can be a step of its own. A runtime that has only an evaluator can run CheckedExprs that a checker wrote, and that is how the browser gets typed rules without a TypeScript checker.

Rust can have the same standing as Python now, with one engine choice to make:

- **cel-core 0.5.1** is the only pure-Rust engine with a checker and CheckedExpr input and output. It passed 1639 of the 1640 tests in the shared suite. It has one maintainer and no commit in nine months. Its checker also accepts `decision.status == 1` (string against int), which cel-go and cel-cpp reject.
- **cel-cxx 0.2.5** wraps cel-cpp, the checker that cel-expr-python uses. It caught all seven bad rules. Its build runs Bazel inside `cargo build`, and its Rust API has no CheckedExpr input or output.
- **`cel` 0.16.1**, the most used Rust crate, has no checker and no protobuf support. A rule with a wrong field passes until a record lacks that field.

A pyo3 binding of our own over cel-core took 87 lines of Rust and builds a 2 MB abi3 wheel. It ran the typed demo and the shipped CheckedExprs from Python. So a Rust host component is cheap to reach from the Python host.

Recommendation, which is for the owner to decide:

- Keep cel-expr-python as the Python engine and checker at load.
- Make cel-core the Rust engine, behind the same small adapter, pinned and held to the shared suite.
- Use `@bufbuild/cel` in the browser, to evaluate CheckedExprs only.
- Use cel-go in CI as the reference checker and the conformance oracle.
- Generate the descriptor set and environment YAML with the contracts (ADR-0017).

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
| Build | `cargo build`, about 6 s incremental | `cargo build` runs Bazel 8.3.1 (it downloads it) to compile cel-cpp: about 6 minutes in this worktree, a 785 MB `target/`, and a C++ toolchain | `cargo build` | `cargo build` | `cargo build` |
| Maintenance | 5 stars, last push 2026-02-16, 15 open issues, 17k downloads, one maintainer | 36 stars, last push 2026-10-12, 0 open issues, 5k downloads | 719 stars, last push 2026-11-24, 28 open issues, 6.9M downloads, a governance file | 4 stars, last push 2026-11-25; its README says a code assistant wrote it | Release 1.0.9 on 2026-11-15, 50k downloads |
| Licence | MIT OR Apache-2.0 | Apache-2.0 | MIT | Apache-2.0 | MIT |

`cel-interpreter` and `cel-parser` are the old names of `cel` and stopped at 0.10 in 2025-07. `cel-rs` 0.2.0 has had no release since 2024-03.

**A pyo3 binding of our own** (`rust-py/`, `py/rust_binding_demo.py`) wraps cel-core with three calls:

- `Env(env_yaml, descriptor_set)`;
- `check(expr)`, which returns CheckedExpr bytes;
- `eval(checked, activation)`, which takes serialised proto messages.

Measured:

- 87 lines of Rust plus a 7-line type stub.
- A 50 s release build after the shared `target/` was warm. maturin builds a 2.0 MB `cp312-abi3` wheel for macOS arm64.
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

| | cel-go 0.30.0 | cel-expr-python 0.1.4 |
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
- **A CheckedExpr carries no environment identity.** It names message types and overload ids but not the descriptor set or extension versions. An evaluator given a CheckedExpr from a different environment fails late or not at all (untested). The bundle has to carry the digest of the env YAML and descriptor set, and the evaluator has to compare it.
- **The env YAML is the weakest artefact.** Two engines read it as is. The other four need an adapter, and each adapter maps extension names by hand, which is where versions can drift. The extension list is also the main source of conformance gaps (see the next sections).
- **JSON is the neutral encoding of the test files.** textproto needs descriptors at parse time in every language except Go and C++; the protobuf JSON form loads with a plain JSON parser.

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
| cel-go 0.30.0 | 29 | `cel.block` isn't public (22). Three map literals that cel-spec rejects (two with a repeated key, one with a float key) evaluate instead of failing. Two optional lookups on a map return `false` instead of an error. `indexOf` and `lastIndexOf` with an out-of-range start return a value. |
| cel-expr-python 0.1.4 | 30 | `cel.block` (22). `transformMap` fails with "no overload for cel.@mapInsert" (6), a gap in the binding's comprehensions extension. `string(-0.0045)` gives `-0.0044999999999999997`. One repeated map key. |
| cel-core 0.5.1 | 1 | `optional_type` isn't declared. It is the only engine that runs `cel.block`. |
| cel-cxx 0.2.5 | 128 | 87 `disableCheck` tests: the Rust API compiles only with the checker, so tests that cel-spec runs unchecked fail at the check. `cel.block` (22). 12 timestamp and duration range errors aren't raised. Backtick-quoted field names are refused (6), which looks like a parser option off in cel-cxx's defaults (assumption). One repeated map key. cel-expr-python wraps the same cel-cpp and passes all of these, so the gaps come from cel-cxx's build or options, not from cel-cpp. |
| cel 0.16.1 | 94 | No protobuf support: wrapper and `google.protobuf.Value` literals fail with "unexpected type" (64). `cel.block` (22). Backtick field names don't parse (6). Two duration overflows aren't raised. |
| @bufbuild/cel 0.6.2 | 316 | Only the strings extension ships, so math (182), optionals (58), two-variable comprehensions (38), bindings (5) and encoders (4) fail. `cel.block` (22). Backtick field names (6). One repeated map key. |
| cel-js 8.0.0 | 603 | No extension libraries: math (199), strings (102), two-variable comprehensions (46), encoders (4). Optional types are partial (38). No `google.protobuf` struct literals (53 of `dynamic`). It also has standard-library gaps: there is no `int(uint)`, two equal byte literals compare `false`, and some timestamp conversions are missing. |

What this means for the design:

- **The checkers agree on the core language.** cel-go, cel-expr-python and cel-core differ on 30 tests at most, and almost all of them are `cel.block`, which is an optimiser artefact rather than a rule-author feature. So a rule that one of these three checks will mean the same thing on the others.
- **Extensions are the main divergence.** The environment for benchhand rules may enable only extensions every executing engine has. With @bufbuild/cel in the browser, that is strings alone, unless the browser only evaluates CheckedExprs that don't use the others. The adapter's load step should refuse an env YAML that names an extension the engine lacks; in this spike each adapter maps names by hand.
- **The shared suite misses the checker gap.** cel-core scores 99.9% and still accepts `decision.status == 1`. cel-spec's simple tests check that good expressions pass, not that bad ones fail. benchhand's own suite needs reject cases, like the seven in the typed demo, run on every checker.
- **cel-js is out.** At 63% with no CheckedExpr input, it can't run the rules the host checked.

## The recommended design

### Where checking happens

The checker runs in two places, and an evaluator anywhere.

1. **At load, in the host.** The Python host checks every rule with cel-expr-python against the generated descriptor set and env YAML, as ADR-0014 already requires: a typo fails at load. Errors carry the rule's file path, for example `flow.yaml#/gates/PROVISIONAL/requires/0`, and the line, column and caret (Kubernetes rows 4 and 5). Each slot's output type is checked too: `requires` and `when` must be `bool`.
2. **In CI, with cel-go as the reference.** CI checks every rules file that ships with cel-go, cel-expr-python and cel-core. It fails when they disagree on whether a rule checks or on its output type. That differential check is what finds a checker gap like cel-core's `string == int`. cel-go's cost estimator also runs here, which gives Kubernetes row 8 (a static cost estimate) without a Python cost API.

A successful check produces a **compiled rules bundle**:

- the CheckedExpr of each rule, keyed by its file path;
- the rule's output type;
- the digest of the env YAML and of the descriptor set it was checked against;
- the checker's identity (engine, version, options), as Kubernetes row 11 asks.

The host writes the bundle at load, as a cache, and on request (`benchhand rules compile`). A provider's publish step can write one too. The bundle shape is a contract like any other, so it is defined in `contracts/` (ADR-0017), not in an engine's code.

An evaluator only needs the bundle. It compares the two digests with its own environment and refuses a mismatch, then runs each CheckedExpr without checking again. That is how the browser runs typed rules with @bufbuild/cel, which has no public checker. A CheckedExpr's digest comes from a deterministic re-encoding, because writers emit map entries in any order.

So checking is a separate step that ships CheckedExprs, with one condition: the host still checks at load, because users and policy providers can change rules between releases.

### The engine in each runtime

| Runtime | Engine | Checks | Evaluates | Reads |
|---|---|---|---|---|
| Python host | cel-expr-python | Yes, at load | Yes | env YAML, descriptor set, CheckedExpr |
| Rust component or provider | cel-core, through the adapter crate; cel-cxx as the fallback if cel-core stalls | Yes | Yes | env YAML (adapter), descriptor set, CheckedExpr |
| Browser (preview host, gate card) | @bufbuild/cel | No | CheckedExprs from the bundle | descriptor set, CheckedExpr |
| CI | cel-go | Yes, the reference, plus cost | The conformance oracle | env YAML, descriptor set, CheckedExpr |
| Python fallback | the pyo3 binding over cel-core | Yes | Yes | the same as cel-core |

A provider in any other language either takes CheckedExprs from the host or uses its language's engine, and passes the same suite.

### The adapter interface

Every runtime wraps its engine in the same five operations. Each operation names a cross-language artefact, not a type from one engine:

```text
load(env_yaml, descriptor_set)  -> Environment | [Issue]   refuse an unknown extension or version
check(env, path, expr, slot)    -> CheckedExpr | [Issue]   absent where the engine has no checker
program(env, checked_expr)      -> Program | [Issue]       refuse a CheckedExpr from another environment
eval(program, activation)       -> Value | EvalError       activation: variable -> record (JSON) or message
identity()                      -> {engine, version, options}
```

- An `Issue` is `{path, line, column, message}`.
- A `Value` leaves the adapter as `cel.expr.Value` protobuf JSON, the encoding the conformance runners already use. So results compare across languages with one comparator.
- `eval` returns an error for a rule that fails to compile or evaluate, and the caller records it as a finding with coverage UNKNOWN, not PASS (Kubernetes row 6). The adapter tests assert this.

The spike has most of this per language already: `rust/src/lib.rs` (load), `rust-py/src/lib.rs` (check, program and eval for Python over Rust), and the runners' value encoders. cel-expr-python's adapter is the thinnest, because the binding reads both artefacts itself.

### What gives Rust equal standing

Three things, all of which this design needs anyway:

1. **A required Rust job in CI.** It runs the shared suite, the typed accept and reject cases, and the differential check on cel-core.
2. **A Rust adapter crate** (`benchhand-cel`) with the five operations over cel-core. It reads the same generated artefacts and the bundle.
3. **Contract types for Rust providers.** `typify` structs for host code (D17), plus the descriptor set for rule activations, so a Rust provider needs no second schema.

These three make Rust providers first-rate. A Rust host component is a different decision. The pyo3 measurement says crossing from the Python host into a Rust component is cheap: 87 lines for the CEL part, and one abi3 wheel per platform. Plan section 4 (D12) still says "Python host and core; no Rust". Moving the flow interpreter or another host component to Rust means changing D12, which is the owner's call.

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
