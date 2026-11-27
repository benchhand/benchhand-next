# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

"""The in-memory record: a project's hw/ documents as the models generated from contracts/record/."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from benchhand_contracts.base import ContractModel
from benchhand_contracts.models.record import (
    assembly_schema,
    bom_row_schema,
    decision_schema,
    interfaces_schema,
    manufacturing_capabilities_schema,
    manufacturing_evidence_schema,
    manufacturing_findings_schema,
    manufacturing_guideline_schema,
    manufacturing_materials_schema,
    manufacturing_selection_schema,
    part_schema,
    policy_schema,
    product_schema,
    requirements_schema,
    verification_row_schema,
)

Product = product_schema.BenchhandProductRecordHwProductYaml
Requirements = requirements_schema.BenchhandRequirementsRecordHwRequirementsYaml
Interfaces = interfaces_schema.BenchhandInterfacesRecordHwInterfacesYaml
Assembly = assembly_schema.BenchhandAssemblyRecordHwAssemblyYaml
BomRow = bom_row_schema.BenchhandEbomRowHwBomCsv
VerificationRow = verification_row_schema.BenchhandVerificationMatrixRowHwVerificationCsv
Part = part_schema.BenchhandPartRecordHwPartsPnPartYaml
Policy = policy_schema.BenchhandGatePolicyHwPolicyYaml
DecisionFrontMatter = decision_schema.BenchhandDecisionRecordFrontMatterHwDecisionsDrSlugMd
DecisionFront = decision_schema.GateDecision | decision_schema.DesignDecision
Guideline = manufacturing_guideline_schema.BenchhandManufacturingGuidelineSetHwManufacturingGuidelinesYaml
MANUFACTURING_MODELS: dict[str, type[ContractModel]] = {
    "capabilities": (
        manufacturing_capabilities_schema.BenchhandManufacturingCapabilityProfilesHwManufacturingCapabilitiesYaml
    ),
    "materials": manufacturing_materials_schema.BenchhandMaterialProfilesHwManufacturingMaterialsYaml,
    "selection": (
        manufacturing_selection_schema.BenchhandMaterialProcessAndArchitectureSelectionHwManufacturingSelectionYaml
    ),
    "findings": manufacturing_findings_schema.BenchhandFindingDispositionsHwManufacturingFindingsYaml,
    "evidence": manufacturing_evidence_schema.BenchhandEvidenceLedgerHwManufacturingEvidenceYaml,
}
MANUFACTURING_DOCUMENTS = tuple(MANUFACTURING_MODELS)


def as_json(document: ContractModel) -> Any:
    """A document as its file states it: the JSON its contract validates, keys named as in the file."""
    return document.model_dump(mode="json", by_alias=True, exclude_unset=True)


@dataclass(frozen=True)
class Decision:
    """A decision record file: its front matter (decision.schema.json), slug and verbatim Markdown body."""

    slug: str
    front: DecisionFront
    body: str

    @property
    def id(self) -> str:
        return self.front.id

    @property
    def file_name(self) -> str:
        return f"{self.id}-{self.slug}.md"

    @property
    def approves(self) -> bool:
        """Whether citing this decision approves: a gate approved or a design accepted."""
        status = (self.front.kind, self.front.status.value)
        return status in (("gate", "approved"), ("design", "accepted"))


@dataclass
class Record:
    """Every record document of one project. Parts are keyed by their directory name, decisions by the id in
    their file name, manufacturing documents by name (capabilities, materials, selection, findings, evidence)
    and guideline sets by file stem. Optional documents that are absent are left out (policy is None)."""

    product: Product
    requirements: Requirements
    interfaces: Interfaces
    assembly: Assembly
    bom: list[BomRow]
    verification: list[VerificationRow]
    parts: dict[str, Part] = field(default_factory=dict)
    decisions: dict[str, Decision] = field(default_factory=dict)
    manufacturing: dict[str, ContractModel] = field(default_factory=dict)
    guidelines: dict[str, Guideline] = field(default_factory=dict)
    policy: Policy | None = None
