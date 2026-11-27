# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

"""benchhand-contracts: models and validators generated from contracts/ (ADR-0017).

The stable API:

- ``validate(schema_id, instance)`` raises ``ContractViolation`` when an instance doesn't match the
  contract with that ``$id``, and ``UnknownSchemaError`` when no packaged contract has the id.
  ``violations(schema_id, instance)`` returns every violation instead, the one ``validate`` raises first.
- ``benchhand_contracts.models.<dir>.<name>_schema`` holds the pydantic models of
  ``contracts/<dir>/<name>.schema.json``, for example ``benchhand_contracts.models.provider.protocol_schema``.
- ``Finding`` is the model of ``contracts/common/finding.schema.json``.

The schemas ship as package data in ``benchhand_contracts/schemas`` and the conformance fixtures in
``benchhand_contracts/examples``, so an installed wheel needs no repository checkout.
"""

from .models.common.finding_schema import BenchhandFinding as Finding
from .validation import ContractViolation, UnknownSchemaError, validate, violations

__all__ = ["ContractViolation", "Finding", "UnknownSchemaError", "validate", "violations"]
