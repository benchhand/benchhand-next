#!/usr/bin/env bash

# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

# Run the shared conformance suite on every engine, then compare. Reuses the existing builds: the cel-cxx
# runner needs rust-cxx/target/release/conformance, whose first build compiles cel-cpp with Bazel.
#
# This is the gate, so it never skips an engine: a missing runner binary fails the run, and compare.py
# fails on an engine with no results or on a change from expected/suite-failures.json.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
cxx="$here/../rust-cxx/target/release/conformance"
if [[ ! -x "$cxx" ]]; then
  echo "FAIL cel-cxx: no runner; build it with 'cd rust-cxx && cargo build --release --bin conformance'" >&2
  exit 1
fi
# Stale results from an earlier run must not stand in for an engine that fails to run now.
rm -f "$here"/results/*.jsonl
cd "$here/../ts" && node export_suite.ts
cd "$here/../ts" && node conformance.ts
cd "$here/../py" && uv run --offline python conformance.py
cd "$here/../go" && go run ./conformance
cd "$here/../rust" && cargo run --offline -q --bin conformance
"$cxx"
python3 "$here/compare.py"
