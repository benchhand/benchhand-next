#!/usr/bin/env bash
# Run the shared conformance suite on every engine, then compare. Reuses the existing builds: the cel-cxx
# runner needs rust-cxx/target/release/conformance, whose first build compiles cel-cpp with Bazel.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
cd "$here/../ts" && node export_suite.ts
cd "$here/../ts" && node conformance.ts
cd "$here/../py" && uv run --offline python conformance.py
cd "$here/../go" && go run ./conformance
cd "$here/../rust" && cargo run --offline -q --bin conformance
if [[ -x "$here/../rust-cxx/target/release/conformance" ]]; then
  "$here/../rust-cxx/target/release/conformance"
else
  echo "skipped cel-cxx: build rust-cxx with 'cargo build --release --bin conformance' first" >&2
fi
python3 "$here/compare.py"
