"""The TEST capability profile of the corpus: `fixtures/test_capabilities.yaml`, loaded as plain documents.

`materials()` and `capabilities()` are the lists a record's manufacturing/materials.yaml and
manufacturing/capabilities.yaml hold (cad-record's fixtures `record(capabilities=..., materials=...)` takes them).
Calibrations for MATERIAL: overhang_angle 45-50 deg, bridge_span 5-6 mm, min_wall 1.2-1.6 mm, min_feature
2.0-2.4 mm, in a 200 mm cube envelope. Each call returns fresh copies, so callers may edit them.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

PATH = Path(__file__).resolve().parent / "fixtures" / "test_capabilities.yaml"
PRINTER = "test_printer"
MATERIAL = "test_polymer"


def _load() -> dict[str, Any]:
    import yaml

    data = yaml.safe_load(PATH.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def materials() -> list[dict[str, Any]]:
    return copy.deepcopy(_load()["materials"])


def capabilities() -> list[dict[str, Any]]:
    return copy.deepcopy(_load()["profiles"])
