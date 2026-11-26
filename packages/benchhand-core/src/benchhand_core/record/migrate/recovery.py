"""How an apply can be undone, and what keeps it from racing another migration.

Apply writes in place, so before it writes anything it needs a recovery point: either hw/ is inside a git
work tree with nothing to commit (`git restore hw` undoes the migration), or a complete copy of hw/ written
to .benchhand/backups/<UTC time>/hw first. An exclusive lock file, hw/.benchhand-migrate.lock, keeps a second
migration out. It does not stop other writers: stop every other process that writes under hw/ first.
"""

from __future__ import annotations

import hashlib
import os
import shlex
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from benchhand_core.record import documents
from benchhand_core.record.finding import Finding, Severity, error
from benchhand_core.record.ignore import is_junk
from benchhand_core.record.migrate.inventory import LOCK_NAME, TEMP_SUFFIX, Inventory, is_own

BACKUPS = ".benchhand/backups"
LOCK_PATH = f"{documents.HW}/{LOCK_NAME}"


@dataclass(frozen=True)
class RecoveryPoint:
    command: str  # the exact command that puts hw/ back as it was before the migration
    backup: Path | None = None


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# --- git ------------------------------------------------------------------------------------------------


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[bytes] | None:
    try:
        return subprocess.run(["git", "-C", str(root), *args], capture_output=True, check=False, timeout=120)
    except (OSError, subprocess.TimeoutExpired):
        return None


def _paths(output: bytes) -> list[str]:
    return [item.decode("utf-8", "replace") for item in output.split(b"\0") if item]


def _counted(path: str) -> bool:
    """Whether a git status entry counts as a pending change: junk and the service's own files do not."""
    return not is_junk(PurePosixPath(path)) and not is_own(PurePosixPath(path).name)


def git_recovery(root: Path) -> RecoveryPoint | str:
    """`git restore hw` as the recovery point, or why git cannot be one."""
    inside = _git(root, "rev-parse", "--is-inside-work-tree")
    if inside is None or inside.returncode != 0 or inside.stdout.strip() != b"true":
        return "hw/ is not inside a git work tree"
    status = _git(root, "status", "--porcelain=v1", "-z", "--untracked-files=all", "--", documents.HW)
    if status is None or status.returncode != 0:
        return "git status failed"
    pending = [entry[3:] for entry in _paths(status.stdout) if len(entry) > 3 and _counted(entry[3:])]
    if pending:
        return f"hw/ has {len(pending)} uncommitted changes or untracked files (first: {pending[0]})"
    return RecoveryPoint(f"git -C {shlex.quote(str(root))} restore -- {documents.HW}")


def untracked(root: Path, paths: list[str]) -> list[str]:
    """The `paths` git does not track (an ignored file, say), which git restore cannot bring back."""
    listed = _git(root, "ls-files", "-z", "--", *paths)
    tracked = set(_paths(listed.stdout)) if listed is not None and listed.returncode == 0 else set()
    return [path for path in paths if path not in tracked]


def no_recovery_point(reason: str) -> Finding:
    return error(
        "migrate.no_recovery_point",
        documents.HW,
        f"apply writes in place and needs a way back: {reason}",
        action="Commit hw/ to git (git add hw && git commit) so that git restore hw undoes the migration, "
        "or pass --backup to write a complete copy to .benchhand/backups/ first; nothing was changed.",
    )


# --- backup ---------------------------------------------------------------------------------------------


def fsync_directory(path: Path) -> None:
    handle = os.open(path, os.O_RDONLY)
    try:
        os.fsync(handle)
    finally:
        os.close(handle)


def _copy_file(source: Path, target: Path) -> None:
    data = source.read_bytes()
    with open(target, "xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    os.chmod(target, source.stat().st_mode & 0o7777)
    if sha256(target.read_bytes()) != sha256(data):
        raise OSError(f"{target}: the copy does not read back as written")


def write_backup(root: Path, inventory: Inventory) -> RecoveryPoint:
    """Copy every file of `inventory` (symbolic links as links) to .benchhand/backups/<UTC time>/hw, sync it
    to disk and read each file back; raises OSError when any step fails."""
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
    backup = root / BACKUPS / stamp / documents.HW
    backup.mkdir(parents=True, exist_ok=False)
    directories = {backup}
    for relative in sorted({*inventory.files, *inventory.links}):
        source = root / relative
        target = backup / PurePosixPath(relative).relative_to(documents.HW)
        target.parent.mkdir(parents=True, exist_ok=True)
        directories.update([target.parent, *target.parent.parents])
        if relative in inventory.links:
            os.symlink(os.readlink(source), target)
        else:
            _copy_file(source, target)
    for directory in sorted(path for path in directories if path == root or root in path.parents):
        fsync_directory(directory)
    command = f"cp -Rp {shlex.quote(str(backup))}/. {shlex.quote(str(root / documents.HW))}/"
    return RecoveryPoint(command, backup)


# --- the lock -------------------------------------------------------------------------------------------


def acquire_lock(root: Path) -> Path | Finding:
    lock = root / LOCK_PATH
    try:
        handle = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except FileExistsError:
        return error(
            "migrate.locked",
            LOCK_PATH,
            "another migration holds the lock on this record",
            action=f"Wait for it to finish. If no migration is running (a crash left the lock), delete "
            f"{LOCK_PATH} and migrate again; nothing was changed.",
        )
    with os.fdopen(handle, "w", encoding="utf-8") as stream:
        stream.write(f"pid {os.getpid()} at {datetime.now(UTC).isoformat()}\n")
    return lock


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


def write_durably(target: Path, data: bytes) -> None:
    """Write `data` to a temp file beside `target` with its mode, sync it, rename it over `target` and sync
    the directory, so a crash leaves either the old or the new file."""
    handle, temporary = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.", suffix=TEMP_SUFFIX)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, target.stat().st_mode & 0o7777)
        os.replace(temporary, target)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
    fsync_directory(target.parent)
