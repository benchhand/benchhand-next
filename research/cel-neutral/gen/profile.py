# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

"""Write one environment profile manifest per structural scope, and its digest.

A manifest is the identity of the environment a rule is checked and evaluated in:

- `descriptor_set`: the SHA-256 of the exact bytes of `generated/types.binpb`;
- `variables`: each declaration, as a CEL type name (a primitive or a message);
- `extensions`: each extension with its pinned version;
- `options`: the checker and parser options from `scopes.yaml`'s `profile_options`;
- `checkers_of_record`: the checkers (engine and version) whose CheckedExprs an evaluator may run.

The digest is the SHA-256 of the manifest's canonical JSON (RFC 8785, JCS). A manifest holds only ASCII
strings, integers, booleans, arrays and objects, and for that subset JCS is sorted keys and no whitespace,
which `canonical_json` checks. The digest is never taken over protobuf bytes, whose encoding isn't
canonical across writers.

Usage: python gen/profile.py <scopes.yaml> --generated <generated dir>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import yaml

MANIFEST_VERSION = 1


def check_scalar(value: object, where: str) -> None:
    if isinstance(value, str):
        if not value.isascii():
            raise ValueError(f"{where}: {value!r} isn't ASCII")
    elif isinstance(value, bool) or value is None:
        return
    elif isinstance(value, int):
        if abs(value) > 2**53:
            raise ValueError(f"{where}: {value} isn't exactly representable in JCS")
    else:
        raise ValueError(f"{where}: {type(value).__name__} isn't allowed in a manifest")


def check_subset(value: object, where: str = "$") -> None:
    """Refuse a value outside the JSON subset for which sorted-key compact JSON is RFC 8785."""
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str) or not key.isascii():
                raise ValueError(f"{where}: key {key!r} isn't an ASCII string")
            check_subset(item, f"{where}.{key}")
    elif isinstance(value, list):
        for i, item in enumerate(value):
            check_subset(item, f"{where}[{i}]")
    else:
        check_scalar(value, where)


def canonical_json(value: object) -> bytes:
    check_subset(value)
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def digest(manifest: dict) -> str:
    return hashlib.sha256(canonical_json(manifest)).hexdigest()


def manifest_for(env: dict, options: dict, checkers: list[dict], descriptor_set: bytes) -> dict:
    return {
        "manifest_version": MANIFEST_VERSION,
        "name": env["name"],
        "descriptor_set": {"file": "types.binpb", "sha256": hashlib.sha256(descriptor_set).hexdigest()},
        "container": env.get("container", ""),
        "variables": [{"name": v["name"], "type": v["type_name"]} for v in env["variables"]],
        "extensions": [{"name": e["name"], "version": int(e["version"])} for e in env.get("extensions", [])],
        "options": dict(sorted(options.items())),
        "checkers_of_record": [{"engine": c["engine"], "version": str(c["version"])} for c in checkers],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write one environment profile manifest per scope.")
    parser.add_argument("scopes", type=Path)
    parser.add_argument("--generated", type=Path, required=True)
    args = parser.parse_args(argv)
    scopes = yaml.safe_load(args.scopes.read_text())
    options, checkers = scopes["profile_options"], scopes["profile_checkers_of_record"]
    descriptor_set = (args.generated / "types.binpb").read_bytes()
    out = args.generated / "profile"
    out.mkdir(exist_ok=True)
    lines = []
    for env_file in sorted((args.generated / "env").glob("*.env.yaml")):
        manifest = manifest_for(yaml.safe_load(env_file.read_text()), options, checkers, descriptor_set)
        path = out / f"{manifest['name']}.profile.json"
        path.write_text(json.dumps(manifest, indent=1) + "\n")
        lines.append(f"{digest(manifest)}  {path.name}")
    (out / "digests.txt").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
