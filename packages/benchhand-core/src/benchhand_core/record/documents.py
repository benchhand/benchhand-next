"""Where each record document lives under the project root, which contract shapes it and in which format."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from benchhand_core.record.model import MANUFACTURING_DOCUMENTS

HW = "hw"


@dataclass(frozen=True)
class DocumentSpec:
    path: str  # relative to the project root, with / separators
    contract: str  # contracts/record/<contract>.schema.json; for a CSV file, the row contract
    format: Literal["yaml", "csv"]


PRODUCT = DocumentSpec(f"{HW}/product.yaml", "product", "yaml")
REQUIREMENTS = DocumentSpec(f"{HW}/requirements.yaml", "requirements", "yaml")
INTERFACES = DocumentSpec(f"{HW}/interfaces.yaml", "interfaces", "yaml")
ASSEMBLY = DocumentSpec(f"{HW}/assembly.yaml", "assembly", "yaml")
BOM = DocumentSpec(f"{HW}/bom.csv", "bom-row", "csv")
VERIFICATION = DocumentSpec(f"{HW}/verification.csv", "verification-row", "csv")
POLICY = DocumentSpec(f"{HW}/policy.yaml", "policy", "yaml")

PARTS_DIR = f"{HW}/parts"
DECISIONS_DIR = f"{HW}/decisions"
MANUFACTURING_DIR = f"{HW}/manufacturing"
GUIDELINES_DIR = f"{MANUFACTURING_DIR}/guidelines"
DECISION_CONTRACT = "decision"


def part(pn: str) -> DocumentSpec:
    return DocumentSpec(f"{PARTS_DIR}/{pn}/part.yaml", "part", "yaml")


def manufacturing(name: str) -> DocumentSpec:
    if name not in MANUFACTURING_DOCUMENTS:
        raise ValueError(
            f"{name!r} is not a manufacturing document; expected one of {MANUFACTURING_DOCUMENTS}"
        )
    return DocumentSpec(f"{MANUFACTURING_DIR}/{name}.yaml", f"manufacturing-{name}", "yaml")


def guideline(stem: str) -> DocumentSpec:
    return DocumentSpec(f"{GUIDELINES_DIR}/{stem}.yaml", "manufacturing-guideline", "yaml")


def decision_path(file_name: str) -> str:
    return f"{DECISIONS_DIR}/{file_name}"
