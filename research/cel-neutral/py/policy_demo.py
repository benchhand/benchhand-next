"""Evaluate the compiled cel-policy bundles (generated/checked-policy/<profile>/) on cel-expr-python.

cel-go's policy compiler wrote them; this binding has no policy support, so it only evaluates the shipped
CheckedExprs, on the cases in policy/tests.json. Each bundle directory is named after the profile it was
compiled in. The environment is built from that profile's manifest, and the bundle is refused when its
profile digest differs or when an entry's .celpolicy source changed since it was compiled.
"""

from __future__ import annotations

import json
import sys

from celprofile import GENERATED, ROOT, ProfileError, load_profile, read_bundle, write_results
from typed_demo import as_message, new_env

ENGINE = "cel-expr-python"


def policy_sources(bundle_dir) -> dict[str, str]:
    bundle = json.loads((bundle_dir / "bundle.json").read_text())
    return {e["file"]: (ROOT / e["source"]).read_text() for e in bundle["entries"]}


def run_bundle(bundle_dir, tests: list[dict], records: list[dict]) -> None:
    try:
        profile = load_profile(bundle_dir.name)
        entries = read_bundle(bundle_dir, profile, policy_sources(bundle_dir))
    except (ProfileError, FileNotFoundError) as exc:
        records.append(
            {"engine": ENGINE, "kind": "bundle", "case": bundle_dir.name, "ok": False, "detail": str(exc)}
        )
        print(f"BAD {bundle_dir.name}: refused: {exc}")
        return
    env, pool = new_env(profile)
    part_type = next(v["type"] for v in profile.manifest["variables"] if v["name"] == "part")
    for name, checked in sorted(entries.items()):
        program = env.deserialize(checked)
        for case in tests:
            data = dict(case["bindings"])
            data["part"] = as_message(pool, part_type, data["part"])
            result = program.eval(data=data)
            got = result.value()
            got = [x.value() for x in got] if result.type().name() != "ERROR" else str(got)
            ok = got == case["expected"]
            case_id = f"{bundle_dir.name}/{name} {case['testCase']}"
            records.append(
                {"engine": ENGINE, "kind": "policy", "case": case_id, "ok": ok, "detail": repr(got)}
            )
            print(f"{'ok ' if ok else 'BAD'} {case_id} -> {got!r}")


def main() -> int:
    tests = json.loads((ROOT / "policy/tests.json").read_text())
    records: list[dict] = []
    for bundle_dir in sorted(p for p in (GENERATED / "checked-policy").iterdir() if p.is_dir()):
        run_bundle(bundle_dir, tests, records)
    write_results(f"policy-{ENGINE}", records)
    failures = sum(not r["ok"] for r in records)
    print(f"{ENGINE} policy: {failures} failures")
    return int(failures > 0)


if __name__ == "__main__":
    sys.exit(main())
