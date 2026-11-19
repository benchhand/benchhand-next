# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

"""A seam for test_cad_model's KeptFileRecoveryTests, active only while this folder is on PYTHONPATH and
CAD_TEST_STORE_SEAM holds a JSON object: `folders` (any of "parts" and "manufacturing" in a staged version, and
"states" for build's states folder), and the flags `exdev` and `fsync_fails`.

Once `cad_model.py run` loads cad-record `store.py`, the first `place_object` into each named folder fails its
hash. During its undo, a writer that takes no lock renames FOREIGN1 onto the target just before the undo moves it
aside, and FOREIGN2 just before the undo puts FOREIGN1 back. The undo then cannot put FOREIGN1 back, so the store
keeps it. With `exdev`, a rename into the store's recovery folder fails as it does across filesystems. With
`fsync_fails`, every fsync during that placement fails. Every other call runs unchanged.
"""

from __future__ import annotations

import errno
import hashlib
import importlib.machinery
import json
import os
from pathlib import Path
from typing import Any

_SEAM = os.environ.get("CAD_TEST_STORE_SEAM")


class _Mismatch:
    """A digest that matches no object."""

    @staticmethod
    def hexdigest() -> str:
        return "0" * 64


def _folder_of(target: Path) -> str | None:
    """The seam's name for the folder that `target` lies in, or None."""
    if any(part.startswith("cad-model-states-") for part in target.parts):
        return "states"
    if any(".partial-" in part for part in target.parts):
        return next((name for name in ("parts", "manufacturing") if name in target.parts), None)
    return None


def _foreign(active: dict[str, Any], number: int) -> None:
    """A writer that takes no lock renames FOREIGN<number> onto the active target."""
    target, folder = active["target"], active["folder"]
    made = target.with_name(f"foreign{number}.tmp")
    made.write_bytes(f"FOREIGN{number} {folder}".encode())
    os.rename(made, target)


def _before_rename(active: dict[str, Any], seam: dict[str, Any], source: Path, target: Path) -> None:
    """What the seam does before the store renames `source` onto `target` during an armed placement."""
    if seam.get("exdev") and target.parent.name == "recovery":
        raise OSError(errno.EXDEV, "Cross-device link")
    if source == active["target"]:
        _foreign(active, 1)  # just before the undo moves the target aside
    elif target == active["target"] and source.name.endswith(".aside"):
        _foreign(active, 2)  # just before the undo puts the moved-aside file back


def _arm(store: Any, seam: dict[str, Any]) -> None:
    pending, active = list(seam["folders"]), {}
    place_object, rename2, file_digest, fsync = store.Store.place_object, store._rename2, hashlib.file_digest, os.fsync

    def placing(self: Any, digest: str, target: Path) -> bool:
        target = Path(target)
        folder = _folder_of(target)
        if folder not in pending:
            return bool(place_object(self, digest, target))
        pending.remove(folder)
        active.update(target=target, folder=folder)
        try:
            return bool(place_object(self, digest, target))
        finally:
            active.clear()

    def hashing(stream: Any, *args: Any, **kwargs: Any) -> Any:
        found = file_digest(stream, *args, **kwargs)
        return _Mismatch() if active and str(getattr(stream, "name", "")).endswith(".link") else found

    def renaming(source: Path, target: Path, **kwargs: Any) -> None:
        if active:
            _before_rename(active, seam, Path(source), Path(target))
        rename2(source, target, **kwargs)

    def syncing(fd: int) -> None:
        if active and seam.get("fsync_fails"):
            raise OSError(errno.EIO, "Input/output error")
        fsync(fd)

    store.Store.place_object, store._rename2, hashlib.file_digest, os.fsync = placing, renaming, hashing, syncing


if _SEAM:
    _exec_module = importlib.machinery.SourceFileLoader.exec_module

    def _exec_then_arm(self: Any, module: Any) -> None:
        _exec_module(self, module)
        if module.__name__ == "cad_record_store":
            _arm(module, json.loads(_SEAM))

    importlib.machinery.SourceFileLoader.exec_module = _exec_then_arm  # type: ignore[method-assign]
