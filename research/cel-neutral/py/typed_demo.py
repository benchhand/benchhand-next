"""The typed demo on cel-expr-python, built from the gate_guard profile manifest and checked at compile.

It writes each accepted rule's CheckedExpr with a bundle.json (profile digest, checker, payload and source
digests), evaluates the bundles the other engines wrote after verifying them, runs the profile and
tampered-bundle cases, and writes every outcome to results/typed-demo/cel-expr-python.json.
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

import yaml
from cel_expr_python import cel
from celprofile import (
    GENERATED,
    ROOT,
    Profile,
    ProfileError,
    env_yaml,
    is_checker_of_record,
    load_bundle,
    load_profile,
    verify_bundle,
    write_bundle,
    write_results,
)
from google.protobuf import descriptor_pb2, descriptor_pool, json_format, message_factory

ENGINE = "cel-expr-python"
CHECKER = {"engine": ENGINE, "version": "0.1.4"}


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
    for case in demo["presence"]:
        record(records, "presence", case["expr"], presence_outcome(env, case))
    return sources


def edited_record(base: dict, case: dict) -> dict:
    """The case's variable record with one field removed, set to JSON null, or set to its zero value."""
    rec = json.loads(json.dumps(base[case["variable"]]))
    if case["state"] == "missing":
        rec.pop(case["field"], None)
    else:
        rec[case["field"]] = None if case["state"] == "null" else case["zero"]
    return rec


def presence_records(
    env: cel.Env, pool: descriptor_pool.DescriptorPool, base: dict, demo: dict
) -> list[dict]:
    """Presence through the activation path: protobuf JSON parsing of an edited record, then evaluation."""
    records: list[dict] = []
    types = demo["types"]
    for case in demo["presence_records"]:
        name = f"{case['variable']}.{case['field']} {case['state']}: {case['expr']}"
        data = {n: as_message(pool, types[n], v) for n, v in base.items()}
        try:
            data[case["variable"]] = as_message(pool, types[case["variable"]], edited_record(base, case))
        except json_format.ParseError as exc:
            record(records, "presence_record", name, (False, f"parser refused: {exc}"))
            continue
        got = env.compile(case["expr"]).eval(data=data).value()
        record(records, "presence_record", name, (got == case["expect"], repr(got)))
    return records


def presence_outcome(env: cel.Env, case: dict) -> tuple[bool, str]:
    expr, err = compile_or_error(env, case["expr"])
    if expr is None:
        return False, f"{case['meaning']}: {err}"
    result = expr.eval(data={})
    failed = result.type().name() == "ERROR"
    got = str(result.value()).splitlines()[0] if failed else result.value()
    ok = failed if case.get("error") else (not failed and got == case["expect"])
    return ok, f"{case['meaning']}: {'error ' if failed else ''}{got!r}"


def eval_shipped(env: cel.Env, profile: Profile, data: dict, demo: dict, records: list[dict]) -> None:
    """Evaluate the bundles the other engines wrote, without parsing or checking them here. A bundle from
    a checker of record is the gate case (kind "shipped"); another writer's bundle is verified the same way
    except for the checker and evaluated as a portability diagnostic (kind "portability")."""
    sources = {f"accept-{i}.binpb": c["expr"] for i, c in enumerate(demo["accept"])}
    expect = {f"accept-{i}.binpb": c["expect"] for i, c in enumerate(demo["accept"])}
    for engine_dir in sorted(p for p in (GENERATED / "checked").iterdir() if p.name != "python"):
        try:
            bundle = load_bundle(engine_dir)
            entries = verify_bundle(engine_dir, bundle, profile, sources, require_checker_of_record=False)
        except ProfileError as exc:
            record(records, "bundle", engine_dir.name, (False, f"refused: {exc}"))
            continue
        kind = "shipped" if is_checker_of_record(profile, bundle["checker"]) else "portability"
        for name, data_bytes in sorted(entries.items()):
            got = env.deserialize(data_bytes).eval(data=data).value()
            record(records, kind, name, (got == expect[name], repr(got)), engine_dir.name)


def substituted(directory: Path, scratch: Path) -> Path:
    """A copy of a bundle directory with accept-0's payload replaced by accept-1's."""
    shutil.copytree(directory, scratch / directory.name)
    swapped = scratch / directory.name
    (swapped / "accept-0.binpb").write_bytes((directory / "accept-1.binpb").read_bytes())
    return swapped


def refuses_tampered_bundle(profile: Profile, demo: dict, records: list[dict]) -> None:
    """The reference checker's bundle, wrong in each way it can be, must be refused: another profile, a
    stale source, a substituted payload, a checker not of record. With no sources it must still verify."""
    ref = GENERATED / "checked/cel-go-ref"
    own = load_bundle(ref)
    sources = {f"accept-{i}.binpb": c["expr"] for i, c in enumerate(demo["accept"])}
    edited = {name: "edited" for name in sources}
    with tempfile.TemporaryDirectory() as scratch:
        swapped = substituted(ref, Path(scratch))
        for what, directory, bundle, srcs in [
            ("other profile", ref, {**own, "profile_sha256": "0" * 64}, sources),
            ("stale source", ref, own, edited),
            ("substituted payload", swapped, own, sources),
            (
                "not a checker of record",
                ref,
                {**own, "checker": {"engine": "cel-core", "version": "0.5.1"}},
                sources,
            ),
        ]:
            try:
                verify_bundle(directory, bundle, profile, srcs)
                record(records, "bundle", what, (False, "accepted"))
            except ProfileError as exc:
                record(records, "bundle", what, (True, f"refused: {exc}"))
    try:
        verify_bundle(ref, own, profile, None)
        record(records, "bundle", "evaluator without sources", (True, "verified"))
    except ProfileError as exc:
        record(records, "bundle", "evaluator without sources", (False, f"refused: {exc}"))


def main() -> int:
    demo = yaml.safe_load((ROOT / "typedemo/gate_guard.yaml").read_text())
    profile = load_profile(demo["scope"])
    env, pool = new_env(profile)
    types = {v["name"]: v["type"] for v in profile.manifest["variables"]}
    activation = json.loads((GENERATED / f"activation/{demo['scope']}.json").read_text())
    data = {name: as_message(pool, types[name], value) for name, value in activation.items()}
    records: list[dict] = []
    sources = run_cases(env, data, demo, records)
    records += presence_records(env, pool, activation, {**demo, "types": types})
    write_bundle(GENERATED / "checked/python", CHECKER, profile, sources)
    refuses_tampered_bundle(profile, demo, records)
    eval_shipped(env, profile, data, demo, records)
    write_results(ENGINE, records)
    failures = sum(not r["ok"] for r in records)
    print(f"{ENGINE}: {failures} failures, profile {profile.digest[:12]}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
