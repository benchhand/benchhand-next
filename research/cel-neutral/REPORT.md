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
