#!/usr/bin/env bash

# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

# Compile every policy in policy/bad/ with the reference checker in the checks_by_iteration profile and
# record each exit code and first error line in results/policy-bad.txt. A file named not_caught_* is
# one the compiler accepts; every other file must fail.
#
# Usage (from research/cel-neutral): policy/bad/run.sh
set -u
out=results/policy-bad.txt
: > "$out"
status=0
cd go || exit 2
go build -o /tmp/celcheck-policy-bad ./celcheck || exit 2
for f in ../policy/bad/*.celpolicy; do
  name=$(basename "$f" .celpolicy)
  msg=$(/tmp/celcheck-policy-bad policy checks_by_iteration "$f" "probe_$name" 2>&1)
  rc=$?
  rm -f "../generated/checked-policy/checks_by_iteration/probe_$name.binpb"
  want=1
  case "$name" in not_caught_*) want=0 ;; esac
  ok=ok
  if [ "$rc" != "$want" ]; then ok=BAD; status=1; fi
  echo "$ok $name exit=$rc: $(printf '%s\n' "$msg" | head -1)" >> "../$out"
done
# The probes rewrote the bundle; rewrite it for the supported list.
/tmp/celcheck-policy-bad policy checks_by_iteration ../policy/checks_by_iteration_flat.celpolicy checks_by_iteration_flat > /dev/null
rm -f /tmp/celcheck-policy-bad
cd ..
cat "$out"
exit $status
