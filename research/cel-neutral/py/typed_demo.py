"""The typed demo on cel-expr-python, built from the gate_guard profile manifest and checked at compile.

It writes each accepted rule's CheckedExpr with a bundle.json (profile digest, checker, source digests),
evaluates the bundles the other engines wrote after checking their profile and sources, runs the profile
cases, and writes every outcome to results/typed-demo/cel-expr-python.json.
"""

from __future__ import annotations

import json
import sys

import yaml
from cel_expr_python import cel
from celprofile import (
    GENERATED,
    ROOT,
    Profile,
    ProfileError,
    env_yaml,
    load_profile,
    read_bundle,
    verify_bundle,
    write_bundle,
    write_results,
)
from google.protobuf import descriptor_pb2, descriptor_pool, json_format, message_factory

ENGINE = "cel-expr-python"
CHECKER = {"engine": ENGINE, "version": "0.1.4", "options": "cel-cpp defaults"}


def load_pool(descriptor_set: bytes) -> descriptor_pool.DescriptorPool:
    fds = descriptor_pb2.FileDescriptorSet.FromString(descriptor_set)
    pool = descriptor_pool.DescriptorPool()
    for file in fds.file:
        pool.Add(file)
    return pool


def as_message(pool: descriptor_pool.DescriptorPool, type_name: str, value: dict) -> object:
    cls = message_factory.GetMessageClass(pool.FindMessageTypeByName(type_name))
    # Omitted (non-structural) fields aren't declared, so the binding drops them.
    return json_format.ParseDict(value, cls(), ignore_unknown_fields=True, descriptor_pool=pool)


def new_env(profile: Profile) -> tuple[cel.Env, descriptor_pool.DescriptorPool]:
    pool = load_pool(profile.descriptor_set)
    return cel.NewEnv(descriptor_pool=pool, config=cel.NewEnvConfigFromYaml(env_yaml(profile.manifest))), pool


def record(
    records: list[dict], kind: str, case: str, outcome: tuple[bool, str], writer: str | None = None
) -> None:
    ok, detail = outcome
    records.append(
        {"engine": ENGINE, "kind": kind, "case": case, "writer": writer, "ok": ok, "detail": detail}
    )
    print(f"{'ok ' if ok else 'BAD'} {kind}{f' from {writer}' if writer else ''} {case!r}: {detail}")


def compile_or_error(env: cel.Env, expr: str) -> tuple[cel.Expression | None, str]:
    try:
        return env.compile(expr), ""
    except RuntimeError as exc:
        return None, str(exc).splitlines()[0]


def run_cases(env: cel.Env, data: dict, demo: dict, records: list[dict]) -> dict[str, str]:
    """Accept, reject and profile cases; returns the sources of the CheckedExprs written."""
    out = GENERATED / "checked/python"
    out.mkdir(parents=True, exist_ok=True)
    sources = {}
    for i, case in enumerate(demo["accept"]):
        expr, err = compile_or_error(env, case["expr"])
        got = expr.eval(data=data).value() if expr else err
        record(records, "accept", case["expr"], (got == case["expect"], repr(got)))
        if expr:
            (out / f"accept-{i}.binpb").write_bytes(expr.serialize())
            sources[f"accept-{i}.binpb"] = case["expr"]
    for case in demo["reject"]:
        _, err = compile_or_error(env, case["expr"])
        record(records, "reject", case["expr"], (bool(err), err or f"type-checked; expected: {case['why']}"))
    for case in demo["profile"]:
        expr, err = compile_or_error(env, case["expr"])
        if case.get("refuse"):
            record(
                records,
                "profile",
                case["expr"],
                (bool(err), err or f"checked; {case['feature']} should be refused"),
            )
        else:
            got = expr.eval(data=data).value() if expr else err
            record(records, "profile", case["expr"], (got == case["expect"], f"{case['feature']}: {got!r}"))
    return sources


def eval_shipped(env: cel.Env, profile: Profile, data: dict, demo: dict, records: list[dict]) -> None:
    """Evaluate the bundles the other engines wrote, without parsing or checking them here."""
    sources = {f"accept-{i}.binpb": c["expr"] for i, c in enumerate(demo["accept"])}
    expect = {f"accept-{i}.binpb": c["expect"] for i, c in enumerate(demo["accept"])}
    for engine_dir in sorted(p for p in (GENERATED / "checked").iterdir() if p.name != "python"):
        try:
            entries = read_bundle(engine_dir, profile, sources)
        except ProfileError as exc:
            record(records, "bundle", engine_dir.name, (False, f"refused: {exc}"))
            continue
        for name, data_bytes in sorted(entries.items()):
            got = env.deserialize(data_bytes).eval(data=data).value()
            record(records, "shipped", name, (got == expect[name], repr(got)), engine_dir.name)


def refuses_tampered_bundle(profile: Profile, records: list[dict]) -> None:
    """A bundle from another profile, and an entry whose source changed, must both be refused."""
    own = json.loads((GENERATED / "checked/python/bundle.json").read_text())
    for what, bundle, sources in [
        ("other profile", {**own, "profile_sha256": "0" * 64}, {e["file"]: "" for e in own["entries"]}),
        ("stale source", own, {e["file"]: "edited" for e in own["entries"]}),
    ]:
        try:
            verify_bundle(GENERATED / "checked/python", bundle, profile, sources)
            record(records, "bundle", what, (False, "accepted"))
        except ProfileError as exc:
            record(records, "bundle", what, (True, f"refused: {exc}"))


def main() -> int:
    demo = yaml.safe_load((ROOT / "typedemo/gate_guard.yaml").read_text())
    profile = load_profile(demo["scope"])
    env, pool = new_env(profile)
    types = {v["name"]: v["type"] for v in profile.manifest["variables"]}
    activation = json.loads((GENERATED / f"activation/{demo['scope']}.json").read_text())
    data = {name: as_message(pool, types[name], value) for name, value in activation.items()}
    records: list[dict] = []
    sources = run_cases(env, data, demo, records)
    write_bundle(GENERATED / "checked/python", CHECKER, profile, sources)
    refuses_tampered_bundle(profile, records)
    eval_shipped(env, profile, data, demo, records)
    write_results(ENGINE, records)
    failures = sum(not r["ok"] for r in records)
    print(f"{ENGINE}: {failures} failures, profile {profile.digest[:12]}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
