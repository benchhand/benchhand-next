"""The typed demo through cel_core_py, our pyo3 binding over cel-core: Rust checks and evaluates for Python.

Run with the wheel from ../rust-py (`maturin build --release`): `uv run --with <wheel> python rust_binding_demo.py`.
The binding's environment comes from the gate_guard profile manifest. It checks every accept and reject
rule, evaluates its own CheckedExprs, and evaluates the bundles of the two checkers of record (the
reference checker and cel-expr-python) after verifying their profile, checker, payloads and sources.
"""

from __future__ import annotations

import json
import sys

import cel_core_py
from celprofile import GENERATED, ROOT, ProfileError, env_yaml, load_profile, read_bundle
from google.protobuf.message import Message
from typed_demo import as_message, load_pool
from yaml import safe_load


def serialise(message: object) -> bytes:
    assert isinstance(message, Message)
    return message.SerializeToString()


def main() -> int:
    demo = safe_load((ROOT / "typedemo/gate_guard.yaml").read_text())
    profile = load_profile(demo["scope"])
    env = cel_core_py.Env(env_yaml(profile.manifest), profile.descriptor_set)
    pool = load_pool(profile.descriptor_set)
    types = {v["name"]: v["type"] for v in profile.manifest["variables"]}
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
    sources = {f"accept-{i}.binpb": c["expr"] for i, c in enumerate(demo["accept"])}
    expect = {f"accept-{i}.binpb": c["expect"] for i, c in enumerate(demo["accept"])}
    for engine in ("cel-go-ref", "python"):
        try:
            entries = read_bundle(GENERATED / f"checked/{engine}", profile, sources)
        except ProfileError as exc:
            failures += 1
            print(f"BAD bundle {engine}: refused: {exc}")
            continue
        for name, checked in sorted(entries.items()):
            got = env.eval(checked, activation)
            failures += got != expect[name]
            print(f"{'ok ' if got == expect[name] else 'BAD'} shipped from {engine} {name} -> {got!r}")
    print(f"cel_core_py: {failures} failures")
    return int(failures > 0)


if __name__ == "__main__":
    sys.exit(main())
