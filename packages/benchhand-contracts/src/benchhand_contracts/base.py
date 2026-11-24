"""The base class of every generated model."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ContractModel(BaseModel):
    """Keeps the keys a schema object leaves open: without ``additionalProperties`` JSON Schema allows
    them, and pydantic's default would drop them. A model of a closed object sets ``extra="forbid"``."""

    model_config = ConfigDict(extra="allow")
