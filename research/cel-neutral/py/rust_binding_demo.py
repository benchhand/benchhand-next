"""The typed demo through cel_core_py, our pyo3 binding over cel-core: Rust checks and evaluates for Python.

Run with the wheel from ../rust-py (`maturin build --release`): `uv run --with <wheel> python rust_binding_demo.py`.
It checks every accept and reject rule, evaluates its own CheckedExprs, and evaluates the ones cel-go and
cel-expr-python wrote.
"""

from __future__ import annotations

import json
import sys

import cel_core_py
from google.protobuf.message import Message
from typed_demo import GENERATED, ROOT, as_message, load_pool
from yaml import safe_load


def serialise(message: object) -> bytes:
    assert isinstance(message, Message)
    return message.SerializeToString()


def main() -> int:
    demo = safe_load((ROOT / "typedemo/gate_guard.yaml").read_text())
    env_yaml = (GENERATED / f"env/{demo['scope']}.env.yaml").read_text()
    fds = (GENERATED / "types.binpb").read_bytes()
    env = cel_core_py.Env(env_yaml, fds)
    pool = load_pool(GENERATED / "types.binpb")
    types = {v["name"]: v["type_name"] for v in safe_load(env_yaml)["variables"]}
    records = json.loads((GENERATED / f"activation/{demo['scope']}.json").read_text())
    activation = {n: serialise(as_message(pool, types[n], v)) for n, v in records.items()}
    failures = 0
    for case in demo["accept"]:
        got = env.eval(env.check(case["expr"]), activation)
        failures += got != case["expect"]
        print(f"{'ok ' if got == case['expect'] else 'BAD'} accept {case['expr']!r} -> {got!r}")
    for case in demo["reject"]:
        try:
            env.check(case["expr"])
        except ValueError as exc:
            print(f"ok  reject {case['expr']!r}: {str(exc).splitlines()[0]}")
            continue
        failures += 1
        print(f"BAD reject {case['expr']!r} type-checked; expected: {case['why']}")
    for engine in ("go", "python"):
        for i, case in enumerate(demo["accept"]):
            got = env.eval((GENERATED / f"checked/{engine}/accept-{i}.binpb").read_bytes(), activation)
            failures += got != case["expect"]
            print(f"{'ok ' if got == case['expect'] else 'BAD'} shipped from {engine} accept-{i} -> {got!r}")
    print(f"cel_core_py: {failures} failures")
    return int(failures > 0)


if __name__ == "__main__":
    sys.exit(main())
