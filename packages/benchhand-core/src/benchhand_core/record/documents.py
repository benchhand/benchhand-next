"""Where each record document lives under the project root, which contract shapes it and in which format."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from benchhand_contracts.base import ContractModel

from benchhand_core.record.model import (
    MANUFACTURING_DOCUMENTS,
    MANUFACTURING_MODELS,
    Assembly,
    BomRow,
    Guideline,
    Interfaces,
    Part,
    Policy,
    Product,
    Requirements,
    VerificationRow,
)

HW = "hw"


@dataclass(frozen=True)
class DocumentSpec:
    path: str  # relative to the project root, with / separators
    contract: str  # contracts/record/<contract>.schema.json; for a CSV file, the row contract
    format: Literal["yaml", "csv"]
    model: type[ContractModel]  # the generated model of the contract: of the document, or of one CSV row


PRODUCT = DocumentSpec(f"{HW}/product.yaml", "product", "yaml", Product)
REQUIREMENTS = DocumentSpec(f"{HW}/requirements.yaml", "requirements", "yaml", Requirements)
INTERFACES = DocumentSpec(f"{HW}/interfaces.yaml", "interfaces", "yaml", Interfaces)
ASSEMBLY = DocumentSpec(f"{HW}/assembly.yaml", "assembly", "yaml", Assembly)
BOM = DocumentSpec(f"{HW}/bom.csv", "bom-row", "csv", BomRow)
VERIFICATION = DocumentSpec(f"{HW}/verification.csv", "verification-row", "csv", VerificationRow)
POLICY = DocumentSpec(f"{HW}/policy.yaml", "policy", "yaml", Policy)

PARTS_DIR = f"{HW}/parts"
DECISIONS_DIR = f"{HW}/decisions"
MANUFACTURING_DIR = f"{HW}/manufacturing"
GUIDELINES_DIR = f"{MANUFACTURING_DIR}/guidelines"
DECISION_CONTRACT = "decision"


def part(pn: str) -> DocumentSpec:
    return DocumentSpec(f"{PARTS_DIR}/{pn}/part.yaml", "part", "yaml", Part)


def manufacturing(name: str) -> DocumentSpec:
    if name not in MANUFACTURING_DOCUMENTS:
        raise ValueError(
            f"{name!r} is not a manufacturing document; expected one of {MANUFACTURING_DOCUMENTS}"
        )
    return DocumentSpec(
        f"{MANUFACTURING_DIR}/{name}.yaml", f"manufacturing-{name}", "yaml", MANUFACTURING_MODELS[name]
    )


def guideline(stem: str) -> DocumentSpec:
    return DocumentSpec(f"{GUIDELINES_DIR}/{stem}.yaml", "manufacturing-guideline", "yaml", Guideline)


def decision_path(file_name: str) -> str:
    return f"{DECISIONS_DIR}/{file_name}"
