#!/usr/bin/env bash

# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

# Compile every accept and reject rule of the typed demo with a cel-expr binary, and print each exit code
# with the first lines of its output.
# Usage: cli/compile_demo.sh <cel-expr binary> <env.json>   (run from research/cel-neutral)
set -u
bin=$1
env=$2
here=$(cd "$(dirname "$0")/.." && pwd)
rules=()
while IFS= read -r l; do rules+=("$l"); done < <(cd "$here/py" && uv run --offline python -c "
import yaml
d = yaml.safe_load(open('../typedemo/gate_guard.yaml'))
for k in ('accept', 'reject'):
    for r in d[k]:
        print(k + '\t' + r['expr'])
")
for line in "${rules[@]}"; do
  kind=${line%%$'\t'*}
  expr=${line#*$'\t'}
  out=$("$bin" compile -env "$env" -fds "$here/generated/types.binpb" -expr "$expr" 2>&1)
  code=$?
  printf '%s exit=%s %s\n    %s\n' "$kind" "$code" "$expr" "$(printf '%s' "$out" | head -3 | tr '\n' '~' | cut -c1-260)"
done
