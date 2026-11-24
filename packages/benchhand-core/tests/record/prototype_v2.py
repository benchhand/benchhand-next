"""Convert a prototype hw/ record (record_version 2) to record_version 3, for test fixtures only.

The migrate service is a later lane; this is the smallest conversion that turns the reference examples into
records of the current contracts. docs/contract/record-migration.md lists every change applied here.
"""

from __future__ import annotations

import csv
import io
import re
import shutil
from pathlib import Path
from typing import Any

import yaml

REFERENCE_ROOT = Path(__file__).resolve().parents[4] / "reference"
LAMP_ARM_HW = REFERENCE_ROOT / "examples" / "lamp-arm" / "hw"
TEMPLATE_HW = REFERENCE_ROOT / "skills" / "cad-record" / "assets" / "project-template" / "hw"

HEAT_SET_RENAMES = {
    "hole_d": "hole_diameter_mm",
    "hole_tol": "hole_deviation_mm",
    "depth_min": "min_depth_mm",
}
BOM_COLUMN_RENAMES = {
    "specification_ref": "specification_reference",
    "specification_rev": "specification_revision",
}
VERIFICATION_COLUMN_RENAMES = {"requirement_id": "requirement"}
MADR_FRONT = re.compile(r"\A---\n(?P<front>.*?)\n---\n(?P<body>.*)\Z", re.DOTALL)
TITLE = re.compile(r"^# (?P<title>.+)$", re.MULTILINE)


def _load(path: Path) -> Any:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _dump(path: Path, document: Any) -> None:
    path.write_text(yaml.safe_dump(document, sort_keys=False, allow_unicode=True), encoding="utf-8")


def convert_product(product: dict[str, Any]) -> dict[str, Any]:
    product["record_version"] = 3
    profile = product.get("flow", {}).get("profile")
    if profile is not None:
        profile.pop("human_approval", None)
        profile.get("asked", {}).pop("human_approval", None)
    return product


def rename_heat_set_keys(node: Any) -> Any:
    """Rename the heat-set insert keys wherever a heat-set entry (a mapping with an `insert`) appears."""
    if isinstance(node, list):
        return [rename_heat_set_keys(item) for item in node]
    if not isinstance(node, dict):
        return node
    renames = HEAT_SET_RENAMES if "insert" in node else {}
    return {renames.get(key, key): rename_heat_set_keys(value) for key, value in node.items()}


def convert_evidence(ledger: dict[str, Any]) -> dict[str, Any]:
    for entry in ledger.get("entries", []):
        configuration = entry.get("configuration", {})
        if "part_rev" in configuration:
            configuration["rev"] = configuration.pop("part_rev")
        waiver = entry.get("waiver", {})
        if "expires" in waiver:
            waiver["valid_until"] = waiver.pop("expires")
    return ledger


def convert_findings(findings: dict[str, Any]) -> dict[str, Any]:
    for disposition in findings.get("dispositions", []):
        waiver = disposition.get("waiver", {})
        if "expires" in waiver:
            waiver["valid_until"] = waiver.pop("expires")
    return findings


def rename_csv_columns(text: str, renames: dict[str, str]) -> str:
    rows = list(csv.reader(io.StringIO(text)))
    if rows:
        rows[0] = [renames.get(column, column) for column in rows[0]]
    out = io.StringIO()
    csv.writer(out, lineterminator="\n").writerows(rows)
    return out.getvalue()


def convert_decision(text: str, file_name: str) -> str:
    """A MADR decision (status, date, superseded-by, decision-makers…) as a kind: design decision."""
    match = MADR_FRONT.match(text)
    if match is None:
        raise ValueError(f"{file_name}: no MADR front matter")
    madr = yaml.safe_load(match["front"])
    title = TITLE.search(match["body"])
    if title is None:
        raise ValueError(f"{file_name}: no title")
    front: dict[str, Any] = {
        "id": file_name[:6],
        "kind": "design",
        "title": title["title"].strip(),
        "date": str(madr["date"]),
        "status": "superseded" if madr.get("superseded-by") else madr["status"],
    }
    if madr.get("superseded-by"):
        front["superseded_by"] = list(madr["superseded-by"])
    for key in ("decision-makers", "consulted", "informed"):
        if madr.get(key):
            front[key.replace("-", "_")] = list(madr[key])
    rendered = yaml.safe_dump(front, sort_keys=False, allow_unicode=True)
    return f"---\n{rendered}---\n{match['body']}"


def _convert_yaml_documents(hw: Path) -> None:
    if (product := hw / "product.yaml").exists():
        _dump(product, convert_product(_load(product)))
    if (interfaces := hw / "interfaces.yaml").exists():
        _dump(interfaces, rename_heat_set_keys(_load(interfaces)))
    if (evidence := hw / "manufacturing" / "evidence.yaml").exists():
        _dump(evidence, convert_evidence(_load(evidence)))
    if (findings := hw / "manufacturing" / "findings.yaml").exists():
        _dump(findings, convert_findings(_load(findings)))


def _convert_csv_documents(hw: Path) -> None:
    for name, renames in (("bom.csv", BOM_COLUMN_RENAMES), ("verification.csv", VERIFICATION_COLUMN_RENAMES)):
        path = hw / name
        if path.exists():
            path.write_text(rename_csv_columns(path.read_text(encoding="utf-8"), renames), encoding="utf-8")


def _convert_decisions(hw: Path) -> None:
    for path in sorted((hw / "decisions").glob("DR-*.md")):
        path.write_text(convert_decision(path.read_text(encoding="utf-8"), path.name), encoding="utf-8")


def convert_tree(source_hw: Path, target_hw: Path) -> Path:
    """Copy `source_hw` to `target_hw` and convert the copy to record_version 3; returns `target_hw`."""
    shutil.copytree(source_hw, target_hw)
    _convert_yaml_documents(target_hw)
    _convert_csv_documents(target_hw)
    _convert_decisions(target_hw)
    return target_hw
