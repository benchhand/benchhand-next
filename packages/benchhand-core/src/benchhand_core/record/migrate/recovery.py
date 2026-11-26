"""How an apply is undone, and what keeps two migrations apart.

Before apply writes anything, it copies the exact bytes of every file it will change (its preimages; not a
snapshot of hw/) to .benchhand/migrate-backups/<UTC time>/hw/<path>. Beside them, manifest.json lists each
path (relative to hw/), the sha256 of its preimage and of its migrated bytes. Each file, the manifest and
their directories are synced, and each file is read back against the manifest. Last, a COMPLETE marker that
holds the manifest's sha256 is published atomically (temp file, sync, rename, directory sync). Only then does
apply write. No target is written before COMPLETE, so every manifest's preimages are original bytes.

Two files under hw/ keep migrations apart:
- hw/.benchhand-migrate.owner, created with O_CREAT|O_EXCL by every apply, resume and undo and removed when it
  ends, names the process (pid, host, start time) that is running one now. A second process is refused.
- hw/.benchhand-migrate.lock is durable recovery state: it names the backup of the apply that holds the
  record. It stays when an apply stops after its backup is COMPLETE, so the next run must --resume with that
  backup or --undo it.

A backup is never deleted by the service. One that a stopped apply left unfinished is marked ABANDONED, and
--resume makes a new backup beside it; the user may delete old backups by hand. A symbolic link at the
backup directory or any of its ancestors under the project is refused before the service creates or reads
it. The owner file keeps out a second migration only: stop every other process that writes under hw/ first.
"""

from __future__ import annotations

import hashlib
import json
import os
import shlex
import socket
import stat
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from benchhand_core.record import documents
from benchhand_core.record.finding import Finding, Severity, error
from benchhand_core.record.migrate.inventory import LOCK_NAME, OWNER_NAME, TEMP_SUFFIX

BACKUPS = ".benchhand/migrate-backups"
LOCK_PATH = f"{documents.HW}/{LOCK_NAME}"
OWNER_PATH = f"{documents.HW}/{OWNER_NAME}"
MANIFEST = "manifest.json"
COMPLETE = "COMPLETE"
ABANDONED = "ABANDONED"
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


def publish(target: Path, data: bytes) -> None:
    """Write `target` atomically: a synced temp file beside it, renamed over it, then the directory synced."""
    handle, temporary = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.", suffix=TEMP_SUFFIX)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
    fsync_directory(target.parent)


def _unlink_synced(path: Path) -> None:
    path.unlink()
    fsync_directory(path.parent)


def is_link(path: Path) -> bool:
    try:
        return stat.S_ISLNK(os.lstat(path).st_mode)
    except FileNotFoundError:
        return False


def linked_part(base: Path, relative: str) -> str | None:
    """The first of `relative`'s parts below `base`, itself included, that is a symbolic link, as a path
    relative to `base`; None when there is none."""
    parts = PurePosixPath(relative).parts
    for depth in range(1, len(parts) + 1):
        if is_link(base.joinpath(*parts[:depth])):
            return PurePosixPath(*parts[:depth]).as_posix()
    return None


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
    """The project root a backup path names, by its spelling, or None when it is not
    <project>/.benchhand/migrate-backups/<name>."""
    backup = backup.absolute()
    if backup.parent.name != PurePosixPath(BACKUPS).name or backup.parent.parent.name != ".benchhand":
        return None
    return backup.parent.parent.parent


def backup_link(root: Path, backup: Path) -> str | None:
    """The project-relative path of a symbolic link at `backup` (a backup of `root`) or at any of its
    ancestors under `root`; None when there is none."""
    return linked_part(root, f"{BACKUPS}/{backup.name}")


def _makedirs(root: Path, backup: Path) -> None:
    """Create `backup` and its missing ancestors under `root`, refusing a symbolic link among them."""
    for directory in (root / ".benchhand", root / BACKUPS):
        if is_link(directory):
            raise OSError(f"{directory.relative_to(root)} is a symbolic link")
        directory.mkdir(exist_ok=True)
    if backup_link(root, backup) is not None:
        raise OSError(f"{BACKUPS} or {backup.name} is a symbolic link")
    backup.mkdir(exist_ok=False)


def write_backup(root: Path, backup: Path, preimages: list[Preimage]) -> None:
    """Write the preimages, the manifest and then COMPLETE to `backup`, syncing each and reading each file
    back; raises OSError when any step fails, before COMPLETE exists."""
    _makedirs(root, backup)
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
    publish(backup / COMPLETE, f"{sha256((backup / MANIFEST).read_bytes())}\n".encode())


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
    """Whether `backup` has a COMPLETE marker that holds its manifest's sha256."""
    try:
        marker = (backup / COMPLETE).read_text(encoding="utf-8").strip()
        return marker == sha256((backup / MANIFEST).read_bytes())
    except OSError:
        return False


def sync_complete(backup: Path) -> None:
    """Sync the COMPLETE marker and the directories that name it again, before a resume or an undo writes."""
    handle = os.open(backup / COMPLETE, os.O_RDONLY)
    try:
        os.fsync(handle)
    finally:
        os.close(handle)
    fsync_directory(backup)
    fsync_directory(backup.parent)


def abandon(backup: Path, reason: str) -> bool:
    """Mark an unfinished backup ABANDONED, leaving every file in it; False when there is no directory."""
    if not backup.is_dir():
        return False
    publish(backup / ABANDONED, f"{reason}\n".encode())
    return True


# --- the lock: recovery state ---------------------------------------------------------------------------


def write_lock(root: Path, backup: Path) -> None:
    """Point the lock at `backup`, atomically and durably. Only the owner calls it."""
    record = {"started": datetime.now(UTC).isoformat(), "backup": str(backup)}
    publish(root / LOCK_PATH, (json.dumps(record) + "\n").encode())


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
    elif isinstance(held, Path):
        action = (
            f"If a migration is running, wait for it. If one stopped before its backup was COMPLETE, it "
            f"wrote nothing: run {resume_command(root)} to start again"
        )
    else:
        action = (
            f"The lock was left by a migration that stopped while it started, before it wrote anything: "
            f"if no migration is running, delete {LOCK_PATH}"
        )
    return error(
        "migrate.locked",
        LOCK_PATH,
        "a migration holds this record's lock"
        + (f" ({held})" if isinstance(held, str) else f", with backup {held}" if held else ""),
        action=action + ".",
    )


def clear_lock(root: Path) -> Finding | None:
    try:
        _unlink_synced(root / LOCK_PATH)
    except FileNotFoundError:
        return None
    except OSError as failure:
        return cleanup_failed(LOCK_PATH, failure, f"Delete {LOCK_PATH} by hand.")
    return None


# --- the owner: the process running a migration now -----------------------------------------------------


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _owned_by(root: Path) -> str:
    """Who an existing owner file names, for a refusal."""
    try:
        record = json.loads((root / OWNER_PATH).read_text(encoding="utf-8"))
        pid, host = int(record["pid"]), str(record["host"])
        state = ""
        if host == socket.gethostname():
            state = ", which is running" if _alive(pid) else ", which is no longer running"
        return f"process {pid} on {host}{state}, since {record['started']}"
    except (OSError, ValueError, KeyError, TypeError):
        return "a process that did not finish writing the owner file"


def acquire_owner(root: Path) -> Path | Finding:
    """Create the owner file with O_CREAT|O_EXCL and sync it and hw/; a refusal when another process owns
    the record."""
    owner = root / OWNER_PATH
    try:
        handle = os.open(owner, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except FileExistsError:
        return error(
            "migrate.locked",
            OWNER_PATH,
            f"another process is migrating or undoing this record: {_owned_by(root)}",
            action=f"Wait for it to finish. If it is not running (it was killed), delete {OWNER_PATH}, "
            "then run the command again.",
        )
    record = {"pid": os.getpid(), "host": socket.gethostname(), "started": datetime.now(UTC).isoformat()}
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(json.dumps(record) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        fsync_directory(owner.parent)
    except BaseException:  # this process never owned the record: let the next one in
        owner.unlink(missing_ok=True)
        raise
    return owner


def owner_refusal(root: Path) -> Finding | None:
    """The refusal for a dry run while another process owns the record."""
    if not (root / OWNER_PATH).exists():
        return None
    return error(
        "migrate.locked",
        OWNER_PATH,
        f"another process is migrating or undoing this record: {_owned_by(root)}",
        action=f"Wait for it to finish. If it is not running (it was killed), delete {OWNER_PATH}.",
    )


def release_owner(owner: Path) -> Finding | None:
    try:
        _unlink_synced(owner)
    except OSError as failure:
        return cleanup_failed(OWNER_PATH, failure, f"Delete {OWNER_PATH} by hand.")
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


def sync_parents(root: Path, paths: list[str]) -> None:
    """Sync the directory of each of `paths` (project-relative), so that a rename a stopped run made before
    its directory sync is durable; raises OSError."""
    for directory in sorted({(root / path).parent for path in paths}):
        fsync_directory(directory)
