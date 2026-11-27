# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

"""Run the shared conformance suite on cel-expr-python and write results/python.jsonl.

The environment comes from conformance/env.yaml through the binding's own env YAML reader.
"""

from __future__ import annotations

import base64
import json
import math
import sys
from pathlib import Path

from cel_expr_python import cel

ROOT = Path(__file__).resolve().parents[1] / "conformance"


def encode(value: cel.Value) -> dict:
    """The cel.expr.Value protobuf JSON for an evaluation result."""
    kind = value.type().name()
    plain = value.value()
    if kind.startswith("LIST"):
        return {"listValue": {"values": [encode(item) for item in plain]}}
    if kind.startswith("MAP"):
        # The binding hands map keys back as Python values, so a key's int or uint kind is inferred.
        entries = [{"key": encode_key(key), "value": encode(item)} for key, item in plain.items()]
        return {"mapValue": {"entries": entries}}
    return encode_scalar(kind, plain)


def encode_key(key: object) -> dict:
    if isinstance(key, bool):
        return {"boolValue": key}
    if isinstance(key, int):
        return {"int64Value": str(key)}
    return {"stringValue": key}


def encode_scalar(kind: str, plain: object) -> dict:
    if kind == "INT":
        return {"int64Value": str(plain)}
    if kind == "UINT":
        return {"uint64Value": str(plain)}
    if kind == "DOUBLE":
        assert isinstance(plain, float)
        return {"doubleValue": double_json(plain)}
    if kind == "STRING":
        return {"stringValue": plain}
    if kind == "BYTES":
        assert isinstance(plain, bytes | bytearray)
        return {"bytesValue": base64.b64encode(plain).decode()}
    if kind == "BOOL":
        return {"boolValue": plain}
    if kind == "NULL":
        return {"nullValue": None}
    return {"unsupported": f"{kind}: {plain!r}"}


def double_json(x: float) -> float | str:
    if math.isnan(x):
        return "NaN"
    if math.isinf(x):
        return "Infinity" if x > 0 else "-Infinity"
    return x


def run(env: cel.Env, test: dict) -> dict:
    try:
        parsed = env.compile(test["expr"], disable_check=True)
    except Exception as exc:  # noqa: BLE001 - every engine failure is a result
        return {"outcome": "parse_error", "message": first_line(exc)}
    expr = parsed
    if not test.get("disableCheck"):
        try:
            expr = env.compile(test["expr"])
        except Exception as exc:  # noqa: BLE001
            return {"outcome": "check_error", "message": first_line(exc)}
    try:
        result = expr.eval(data={})
    except Exception as exc:  # noqa: BLE001
        return {"outcome": "eval_error", "message": first_line(exc)}
    if result.type().name() == "ERROR":
        return {"outcome": "eval_error", "message": first_line(result.value())}
    return {"outcome": "value", "value": encode(result)}


def first_line(x: object) -> str:
    return str(x).splitlines()[0] if str(x) else ""


def main() -> int:
    env = cel.NewEnv(config=cel.NewEnvConfigFromYaml((ROOT / "env.yaml").read_text()))
    out = (ROOT / "results").joinpath("cel-expr-python.jsonl")
    out.parent.mkdir(exist_ok=True)
    with out.open("w") as fh:
        for file in json.loads((ROOT / "suite.json").read_text()):
            for section in file["sections"]:
                for test in section["tests"]:
                    row = {"file": file["name"], "section": section["name"], "name": test["name"]}
                    fh.write(json.dumps(row | run(env, test)) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
