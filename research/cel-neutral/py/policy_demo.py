"""Evaluate the compiled cel-policy CheckedExprs (generated/checked-policy/*.binpb) on cel-expr-python.

The policy was compiled by cel-go's policy compiler (../go-policy); this binding has no policy support, so it
only evaluates the shipped CheckedExpr, on the test cases in policy/tests.json.
"""

from __future__ import annotations

import json
import sys

from cel_expr_python import cel
from typed_demo import GENERATED, ROOT, as_message, load_pool


def main() -> int:
    pool = load_pool(GENERATED / "types.binpb")
    env = cel.NewEnv(
        descriptor_pool=pool, config=cel.NewEnvConfigFromYaml((ROOT / "policy/env.yaml").read_text())
    )
    tests = json.loads((ROOT / "policy/tests.json").read_text())
    failures = 0
    for path in sorted((GENERATED / "checked-policy").glob("*.binpb")):
        try:
            program = env.deserialize(path.read_bytes())
        except Exception as exc:  # noqa: BLE001 - an engine refusing the CheckedExpr is the finding
            print(f"BAD {path.stem}: deserialize failed: {str(exc).splitlines()[0]}")
            failures += len(tests)
            continue
        for case in tests:
            data = dict(case["bindings"])
            data["part"] = as_message(pool, "benchhand.contracts.record.part.Part", data["part"])
            result = program.eval(data=data)
            got = result.value()
            got = [x.value() for x in got] if result.type().name() != "ERROR" else str(got)
            ok = got == case["expected"]
            failures += not ok
            print(f"{'ok ' if ok else 'BAD'} {path.stem} {case['testCase']!r} -> {got!r}")
    print(f"cel-expr-python policy: {failures} failures")
    return int(failures > 0)


if __name__ == "__main__":
    sys.exit(main())
