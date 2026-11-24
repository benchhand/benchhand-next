"""benchhand-contracts: models and validators generated from contracts/ (ADR-0017).

The models are in ``benchhand_contracts._generated``, one module per contract. Conformance fixtures
are in ``_generated/examples``.
"""

from .validation import ContractViolation, UnknownSchemaError, validate

__all__ = ["ContractViolation", "UnknownSchemaError", "validate"]
