"""The acceptance digest pinned to the prototype's (evidence.py:1320 acceptance_digest and :306
expected_digest at release.toml reference_commit 412b5d9). The golden values are the prototype functions'
output on these inputs."""

from __future__ import annotations

from benchhand_core.record.evidence.digest import acceptance_digest, expected_digest

INVENTORY = {
    "hw/verification.csv": "a" * 64,
    "hw/manufacturing/evidence.yaml": "b" * 64,
    "hw/manufacturing/sources/datasheet \u00e9.pdf": "c" * 64,
    "hw/checks/v1/cad/manifest.json": "d" * 64,
}


def test_acceptance_digest_matches_the_prototype() -> None:
    assert acceptance_digest(INVENTORY) == "4303385450ac7a64c6e8ebb3201881e3ee2ba7d1d873cb401a7d66313d472e9c"


def test_acceptance_digest_ignores_inventory_order() -> None:
    assert acceptance_digest(dict(reversed(INVENTORY.items()))) == acceptance_digest(INVENTORY)


def test_expected_digest_of_no_obligations_matches_the_prototype() -> None:
    assert expected_digest([]) == "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945"
