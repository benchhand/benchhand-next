"""The Python side of the environment profile: load a manifest, check it, build cel-expr-python's env.

The manifest (generated/profile/<name>.profile.json, written by gen/profile.py) is the only input. This
module verifies the descriptor set against the manifest's SHA-256, refuses an extension version or option
this engine doesn't implement, and computes the profile digest itself (RFC 8785 JCS over the manifest,
which for the manifest's ASCII, integer-only subset is sorted keys with no whitespace).

A bundle directory holds CheckedExprs and a bundle.json. Its identity is the profile digest, the checker
(engine and version), and the SHA-256 of each entry's exact payload bytes; each entry also carries the
SHA-256 of its source. verify_bundle refuses another profile, a checker that isn't of record, a payload
that isn't the one shipped, and, when the caller has the sources, a stale source.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
GENERATED = ROOT / "generated"
RESULTS = ROOT / "results"

# What cel-expr-python 0.1.4 implements. The extension versions are cel-go's numbering; cel-cpp has no
# version switch, so these are the versions whose functions the shared suite exercised on this engine.
# Bindings is 0: its env config has no `bindings#1` library ("CompilerLibrary not registered"), which is
# the cel-go version that declares cel.@block.
EXTENSIONS = {"strings": {4}, "optional": {2}, "bindings": {0}, "math": {1}, "encoders": {0}}
# cel-cpp's checker defaults; this binding exposes no switch for them.
OPTIONS = {"cross_type_numeric_comparisons": False, "homogeneous_aggregate_literals": False}


class ProfileError(Exception):
    """The manifest, a bundle, or an entry doesn't match what this engine can run."""


@dataclass
class Profile:
    manifest: dict
    digest: str
    descriptor_set: bytes


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def profile_digest(manifest: dict) -> str:
    return sha256(json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode())


def load_profile(name: str) -> Profile:
    manifest = json.loads((GENERATED / f"profile/{name}.profile.json").read_text())
    descriptor_set = (GENERATED / manifest["descriptor_set"]["file"]).read_bytes()
    if sha256(descriptor_set) != manifest["descriptor_set"]["sha256"]:
        raise ProfileError(f"{name}: the descriptor set doesn't match the manifest's SHA-256")
    for ext in manifest["extensions"]:
        if ext["version"] not in EXTENSIONS.get(ext["name"], set()):
            raise ProfileError(f"{name}: cel-expr-python has no {ext['name']} version {ext['version']}")
    if manifest["options"] != OPTIONS:
        raise ProfileError(f"{name}: options {manifest['options']} differ from this engine's {OPTIONS}")
    return Profile(manifest, profile_digest(manifest), descriptor_set)


def env_yaml(manifest: dict) -> str:
    """The manifest as the cel-go env YAML that cel-expr-python reads."""
    config: dict = {"name": manifest["name"]}
    if manifest["container"]:
        config["container"] = manifest["container"]
    if manifest["extensions"]:
        config["extensions"] = [{"name": e["name"], "version": e["version"]} for e in manifest["extensions"]]
    config["variables"] = [{"name": v["name"], "type_name": v["type"]} for v in manifest["variables"]]
    return yaml.safe_dump(config, sort_keys=False)


def write_bundle(directory: Path, checker: dict, profile: Profile, sources: dict[str, str]) -> None:
    entries = [
        {
            "file": f,
            "payload_sha256": sha256((directory / f).read_bytes()),
            "source_sha256": sha256(s.encode()),
        }
        for f, s in sorted(sources.items())
    ]
    bundle = {"profile_sha256": profile.digest, "checker": checker, "entries": entries}
    (directory / "bundle.json").write_text(json.dumps(bundle, indent=1) + "\n")


def load_bundle(directory: Path) -> dict:
    path = directory / "bundle.json"
    if not path.exists():
        raise ProfileError(f"{directory.name}: no bundle.json, so the profile is unknown")
    return json.loads(path.read_text())


def is_checker_of_record(profile: Profile, checker: dict) -> bool:
    return checker in profile.manifest["checkers_of_record"]


def read_bundle(directory: Path, profile: Profile, sources: dict[str, str] | None) -> dict[str, bytes]:
    """verify_bundle on directory/bundle.json, requiring a checker of record."""
    return verify_bundle(directory, load_bundle(directory), profile, sources)


def verify_bundle(
    directory: Path,
    bundle: dict,
    profile: Profile,
    sources: dict[str, str] | None,
    require_checker_of_record: bool = True,
) -> dict[str, bytes]:
    """Each entry's payload, after checking the profile digest, the checker of record (when required),
    each payload's SHA-256, and each source's SHA-256 when sources is not None. An evaluator that has only
    the bundle passes None: the bundle's producer verified the sources, and the host does at load."""
    if bundle["profile_sha256"] != profile.digest:
        raise ProfileError(
            f"{directory.name}: checked in profile {bundle['profile_sha256'][:12]}, not {profile.digest[:12]}"
        )
    checker = bundle["checker"]
    if require_checker_of_record and not is_checker_of_record(profile, checker):
        raise ProfileError(
            f"{directory.name}: {checker.get('engine')} {checker.get('version')} isn't a checker of record"
        )
    out = {}
    for entry in bundle["entries"]:
        payload = (directory / entry["file"]).read_bytes()
        if sha256(payload) != entry["payload_sha256"]:
            raise ProfileError(
                f"{directory.name}/{entry['file']}: the payload isn't the one the checker shipped"
            )
        if sources is not None:
            source = sources.get(entry["file"])
            if source is None or sha256(source.encode()) != entry["source_sha256"]:
                raise ProfileError(
                    f"{directory.name}/{entry['file']}: stale, the source changed since it was checked"
                )
        out[entry["file"]] = payload
    return out


def write_results(engine: str, records: list[dict]) -> None:
    out = RESULTS / "typed-demo"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{engine}.json").write_text(json.dumps(records, indent=1) + "\n")
