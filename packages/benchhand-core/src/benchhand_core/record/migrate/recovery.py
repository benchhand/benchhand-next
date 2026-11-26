"""How an apply is undone, and what keeps it from racing another migration.

Before apply writes anything, it copies the exact bytes of every file it will change (its preimages; not a
snapshot of hw/) to .benchhand/migrate-backups/<UTC time>/hw/<path>. Beside them, manifest.json lists each
path (relative to hw/), the sha256 of its preimage and of its migrated bytes. Each file, the manifest and
their directories are synced; each file is read back against the manifest; a COMPLETE marker is written and
synced last. Only then does apply write. `benchhand record migrate --undo <backup>` puts those files back, so
the record is as it was, whatever else is under hw/ and whatever git's state.

The lock, hw/.benchhand-migrate.lock, is created with O_EXCL and names the backup it belongs to. It keeps a
second migration out. It does not stop other writers: stop every other process that writes under hw/ first.
An apply that stops after its backup is COMPLETE leaves the lock, so the next run must either --resume with
that backup or --undo it; a second backup of a partly migrated tree is never made.
"""

from __future__ import annotations

import hashlib
import json
import os
import shlex
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from benchhand_core.record import documents
from benchhand_core.record.finding import Finding, Severity, error
from benchhand_core.record.migrate.inventory import LOCK_NAME, TEMP_SUFFIX

BACKUPS = ".benchhand/migrate-backups"
LOCK_PATH = f"{documents.HW}/{LOCK_NAME}"
MANIFEST = "manifest.json"
COMPLETE = "COMPLETE"
MANIFEST_FORMAT = 1


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def undo_command(backup: Path) -> str:
    return f"benchhand record migrate --undo {shlex.quote(str(backup))}"


def resume_command(root: Path) -> str:
    return f"benchhand record migrate --apply --resume {shlex.quote(str(root / documents.HW))}"


def fsync_directory(path: Path) -> None:
    handle = os.open(path, os.O_RDONLY)
    try:
        os.fsync(handle)
    finally:
        os.close(handle)


def _write_new(target: Path, data: bytes) -> None:
    with open(target, "xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


# --- the backup -----------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Preimage:
    """One file apply will change: its hw/-relative path, its bytes now, and the sha256 of its migrated
    bytes."""

    path: str
    data: bytes
    migrated_sha256: str


@dataclass(frozen=True)
class Entry:
    path: str  # relative to hw/
    sha256: str  # of the preimage
    migrated_sha256: str


def new_backup(root: Path) -> Path:
    """The path of a new backup for `root`; nothing is created."""
    return root / BACKUPS / datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")


def project_of(backup: Path) -> Path | None:
    """The project root a backup path belongs to, or None when it is not under .benchhand/migrate-backups/."""
    backup = backup.absolute()
    if backup.parent.name != PurePosixPath(BACKUPS).name or backup.parent.parent.name != ".benchhand":
        return None
    return backup.parent.parent.parent


def _inside(root: Path, path: Path) -> None:
    resolved = path.resolve()
    if resolved != root and root not in resolved.parents:
        raise OSError(f"{path} resolves to {resolved}, outside the project")


def write_backup(root: Path, backup: Path, preimages: list[Preimage]) -> None:
    """Write the preimages, the manifest and then COMPLETE to `backup`, syncing each and reading each file
    back; raises OSError when any step fails, before COMPLETE exists."""
    backup.mkdir(parents=True, exist_ok=False)
    _inside(root, backup)
    files = backup / documents.HW
    directories = {backup, files, backup.parent, backup.parent.parent, root}
    files.mkdir()
    for preimage in preimages:
        target = files / preimage.path
        target.parent.mkdir(parents=True, exist_ok=True)
        directories.update(parent for parent in target.parents if files in parent.parents or parent == files)
        _write_new(target, preimage.data)
    entries = [
        {"path": item.path, "sha256": sha256(item.data), "migrated_sha256": item.migrated_sha256}
        for item in preimages
    ]
    manifest_text = json.dumps({"format": MANIFEST_FORMAT, "files": entries}, indent=2)
    _write_new(backup / MANIFEST, manifest_text.encode())
    for directory in sorted(directories, key=lambda path: len(path.parts), reverse=True):
        fsync_directory(directory)
    manifest = read_manifest(backup)
    if isinstance(manifest, str):
        raise OSError(manifest)
    _write_new(backup / COMPLETE, b"complete\n")
    fsync_directory(backup)


def read_manifest(backup: Path) -> list[Entry] | str:
    """The manifest's entries, each preimage read back and hashed, or why the backup cannot be used."""
    try:
        data = json.loads((backup / MANIFEST).read_bytes())
        entries = [Entry(item["path"], item["sha256"], item["migrated_sha256"]) for item in data["files"]]
        if data.get("format") != MANIFEST_FORMAT:
            return f"{MANIFEST} has format {data.get('format')!r}, not {MANIFEST_FORMAT}"
    except (OSError, ValueError, KeyError, TypeError) as failure:
        return f"cannot read {MANIFEST}: {failure}"
    for entry in entries:
        parts = PurePosixPath(entry.path).parts
        if not parts or ".." in parts or PurePosixPath(entry.path).is_absolute():
            return f"{MANIFEST} lists {entry.path!r}, which is not a path under hw/"
        try:
            found = sha256((backup / documents.HW / entry.path).read_bytes())
        except OSError as failure:
            return f"cannot read the preimage of {entry.path}: {failure.strerror or failure}"
        if found != entry.sha256:
            return f"the preimage of {entry.path} does not match its sha256 in {MANIFEST}"
    return entries


def is_complete(backup: Path) -> bool:
    return (backup / COMPLETE).is_file()


# --- the lock -------------------------------------------------------------------------------------------


def acquire_lock(root: Path, backup: Path) -> Path | Finding:
    """Create the lock, naming `backup`, and sync it; a refusal when the lock exists."""
    lock = root / LOCK_PATH
    try:
        handle = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except FileExistsError:
        return locked(root, read_lock(root))
    record = {"pid": os.getpid(), "started": datetime.now(UTC).isoformat(), "backup": str(backup)}
    with os.fdopen(handle, "w", encoding="utf-8") as stream:
        stream.write(json.dumps(record) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    fsync_directory(lock.parent)
    return lock


def read_lock(root: Path) -> Path | str | None:
    """The backup a lock names; None when there is no lock; why it cannot be read otherwise."""
    try:
        return Path(json.loads((root / LOCK_PATH).read_text(encoding="utf-8"))["backup"])
    except FileNotFoundError:
        return None
    except (OSError, ValueError, KeyError, TypeError) as failure:
        return f"cannot read the lock: {failure}"


def locked(root: Path, held: Path | str | None) -> Finding:
    """The refusal for a record whose lock is held: the commands that finish or undo the migration."""
    if isinstance(held, Path) and is_complete(held):
        action = (
            f"If a migration is running, wait for it. If one stopped (a crash), finish it with: "
            f"{resume_command(root)}; or put the files it changed back with: {undo_command(held)}"
        )
    else:
        action = (
            f"If a migration is running, wait for it. If one stopped before its backup was COMPLETE, it "
            f"wrote nothing: run {resume_command(root)} to start again, or delete {LOCK_PATH}"
        )
    return error(
        "migrate.locked",
        LOCK_PATH,
        "a migration holds this record's lock"
        + (f" ({held})" if isinstance(held, str) else f", with backup {held}" if held else ""),
        action=action + ".",
    )


def release_lock(lock: Path) -> Finding | None:
    try:
        lock.unlink()
    except OSError as failure:
        return cleanup_failed(LOCK_PATH, failure, f"Delete {LOCK_PATH} by hand.")
    return None


def cleanup_failed(path: str, failure: OSError, fix: str) -> Finding:
    return Finding(
        code="migrate.cleanup_failed",
        severity=Severity.warning,
        path=path,
        message=f"cannot remove it: {failure.strerror or failure}",
        action=fix,
    )


# --- writing --------------------------------------------------------------------------------------------


class ChangedMeanwhile(Exception):
    """The target no longer holds the bytes the write expected to replace."""


class NotDurable(Exception):
    """The target was replaced, but syncing its directory failed: the rename may not survive a power loss."""

    def __init__(self, failure: OSError) -> None:
        super().__init__(str(failure))
        self.failure = failure


def write_durably(target: Path, data: bytes, expected_sha256: str) -> None:
    """Write `data` to a temp file beside `target` with its mode and sync it; then, if `target` still holds
    the bytes of `expected_sha256`, rename the temp file over it and sync the directory. A crash leaves the
    old or the new file. Raises ChangedMeanwhile (nothing replaced), OSError, or NotDurable (replaced)."""
    handle, temporary = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.", suffix=TEMP_SUFFIX)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, target.stat().st_mode & 0o7777)
        if sha256(target.read_bytes()) != expected_sha256:
            raise ChangedMeanwhile(str(target))
        os.replace(temporary, target)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
    try:
        fsync_directory(target.parent)
    except OSError as failure:
        raise NotDurable(failure) from failure
