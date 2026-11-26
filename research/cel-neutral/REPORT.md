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
