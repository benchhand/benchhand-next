"""The typed demo on cel-expr-python: env YAML plus the generated FileDescriptorSet, checked at compile.

Also writes each accepted rule's CheckedExpr, so other engines can evaluate what this one checked.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml
from cel_expr_python import cel
from google.protobuf import descriptor_pb2, descriptor_pool, json_format, message_factory

ROOT = Path(__file__).resolve().parents[1]
GENERATED = ROOT / "generated"


def load_pool(path: Path) -> descriptor_pool.DescriptorPool:
    fds = descriptor_pb2.FileDescriptorSet.FromString(path.read_bytes())
    pool = descriptor_pool.DescriptorPool()
    for file in fds.file:
        pool.Add(file)
    return pool


def as_message(pool: descriptor_pool.DescriptorPool, type_name: str, value: dict) -> object:
    cls = message_factory.GetMessageClass(pool.FindMessageTypeByName(type_name))
    # Omitted (non-structural) fields aren't declared, so the binding drops them.
    return json_format.ParseDict(value, cls(), ignore_unknown_fields=True, descriptor_pool=pool)


def main() -> int:
    demo = yaml.safe_load((ROOT / "typedemo/gate_guard.yaml").read_text())
    env_yaml = (GENERATED / f"env/{demo['scope']}.env.yaml").read_text()
    pool = load_pool(GENERATED / "types.binpb")
    env = cel.NewEnv(descriptor_pool=pool, config=cel.NewEnvConfigFromYaml(env_yaml))
    types = {v["name"]: v["type_name"] for v in yaml.safe_load(env_yaml)["variables"]}
    activation = json.loads((GENERATED / f"activation/{demo['scope']}.json").read_text())
    data = {name: as_message(pool, types[name], value) for name, value in activation.items()}
    failures = 0
    checked_dir = GENERATED / "checked/python"
    checked_dir.mkdir(parents=True, exist_ok=True)
    for i, case in enumerate(demo["accept"]):
        expr = env.compile(case["expr"])
        got = expr.eval(data=data).value()
        ok = got == case["expect"]
        failures += not ok
        (checked_dir / f"accept-{i}.binpb").write_bytes(expr.serialize())
        print(f"{'ok ' if ok else 'BAD'} accept {case['expr']!r} -> {got!r}")
    for case in demo["reject"]:
        try:
            env.compile(case["expr"])
        except RuntimeError as exc:
            first = str(exc).splitlines()[0]
            print(f"ok  reject {case['expr']!r}: {first}")
            continue
        failures += 1
        print(f"BAD reject {case['expr']!r} type-checked; expected: {case['why']}")
    failures += eval_shipped(env, data, demo["accept"])
    print(f"cel-expr-python: {failures} failures")
    return 1 if failures else 0


def eval_shipped(env: cel.Env, data: dict, accept: list[dict]) -> int:
    """Evaluate the Any-wrapped CheckedExprs the other engines wrote, without parsing or checking them here."""
    failures = 0
    for engine_dir in sorted(p for p in (GENERATED / "checked").iterdir() if p.name != "python"):
        for i, case in enumerate(accept):
            got = env.deserialize((engine_dir / f"accept-{i}.binpb").read_bytes()).eval(data=data).value()
            ok = got == case["expect"]
            failures += not ok
            print(f"{'ok ' if ok else 'BAD'} shipped from {engine_dir.name} accept-{i} -> {got!r}")
    return failures


if __name__ == "__main__":
    sys.exit(main())
