"""celgen refuses two scopes that project one schema node with different fields.

Run from the repository root: uv run --offline pytest research/cel-neutral/gen/test_celgen.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import celgen  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
PART = "record/part.schema.json"


def run(tmp_path: Path, scopes: dict) -> tuple[int, str]:
    scopes_file = tmp_path / "scopes.yaml"
    scopes_file.write_text(yaml.safe_dump({"scopes": scopes}))
    out = tmp_path / "out"
    code = celgen.main([str(scopes_file), "--out", str(out)])
    return code, (out / "scopes.txt").read_text()


def part_scope(omit: list[str]) -> dict:
    return {"variables": {"part": {"schema": PART}}, "omit": omit}


def test_conflicting_projections_of_one_node_are_refused(tmp_path: Path) -> None:
    both = [f"{PART}#/properties/intent", f"{PART}#/properties/drawing"]
    code, report = run(tmp_path, {"a": part_scope(both), "b": part_scope([*both, f"{PART}#/properties/supplier"])})
    assert code == 1
    assert "scope b: conflicting projection of benchhand.contracts.record.part.Part" in report
    assert "supplier" in report


def test_equal_projections_of_one_node_share_the_message(tmp_path: Path) -> None:
    both = [f"{PART}#/properties/intent", f"{PART}#/properties/drawing"]
    code, report = run(tmp_path, {"a": part_scope(both), "b": part_scope(both)})
    assert code == 0
    assert "conflicting projection" not in report


def test_the_committed_scopes_have_no_conflict(tmp_path: Path) -> None:
    code, report = run(tmp_path, yaml.safe_load((ROOT / "scopes.yaml").read_text())["scopes"])
    assert code == 0, report
    assert "conflicting projection" not in report
