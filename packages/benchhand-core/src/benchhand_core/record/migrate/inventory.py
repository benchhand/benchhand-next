"""What migrate() may read under hw/: every file, found by a walk whose errors are fatal, without OS and tool
junk, sealed history, or the service's own lock and temporary files.

A symbolic link whose target resolves outside the project refuses the record (`migrate.symlink_outside`):
validating the migrated copy would read through it.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import Path, PurePosixPath

from benchhand_core.record import documents
from benchhand_core.record.finding import Finding, error
from benchhand_core.record.ignore import is_junk

# Version snapshots, check bundles and releases are sealed: their bytes are what a digest or a seal states,
# so no rule rewrites them, even when they hold v2 forms.
SEALED = ("hw/versions", "hw/checks", "hw/releases")
LOCK_NAME = ".benchhand-migrate.lock"
TEMP_SUFFIX = ".benchhand-migrate.tmp"


class ScanError(Exception):
    """A directory under hw/ that could not be listed."""

    def __init__(self, path: str, reason: str) -> None:
        super().__init__(f"{path}: {reason}")
        self.path = path
        self.reason = reason

    def finding(self) -> Finding:
        return error(
            "migrate.scan_failed",
            self.path,
            f"cannot list this directory: {self.reason[:200]}; the migration reads every file under hw/",
            action="Fix the directory's permissions, then migrate again; nothing was changed.",
        )


def is_own(name: str) -> bool:
    """The service's lock file, or a temporary file it writes beside a file it changes."""
    return name == LOCK_NAME or name.endswith(TEMP_SUFFIX)


def is_sealed(path: str) -> bool:
    return any(path == sealed or path.startswith(f"{sealed}/") for sealed in SEALED)


def matches(pattern: str, path: str) -> bool:
    """Whether `path` matches the glob `pattern`, segment by segment (* never crosses a /)."""
    parts, wanted = PurePosixPath(path).parts, PurePosixPath(pattern).parts
    return len(parts) == len(wanted) and all(map(fnmatchcase, parts, wanted))


@dataclass(frozen=True)
class Inventory:
    """Every file under hw/ that migrate() may read, project-relative with / separators, in name order."""

    files: tuple[str, ...]
    links: frozenset[str]  # the entries among them, and the directories, that are symbolic links

    def readable(self) -> tuple[str, ...]:
        return tuple(path for path in self.files if not is_sealed(path))


def _outside(root: Path, link: Path, relative: str) -> Finding | None:
    target = link.resolve()
    if target == root or root in target.parents:
        return None
    return error(
        "migrate.symlink_outside",
        relative,
        f"this symbolic link resolves to {target}, outside the project",
        action="Replace the link with a copy of what it points to, or move its target into the project, "
        "then migrate again; nothing was changed.",
    )


def _fail(failure: OSError) -> None:
    raise failure


def scan(root: Path) -> tuple[Inventory, list[Finding]]:
    """The inventory of `root`/hw, and a refusal per symbolic link that leaves the project. Raises ScanError
    when a directory cannot be listed, so no subtree is silently left out."""
    root = root.resolve()
    files: list[str] = []
    links: set[str] = set()
    findings: list[Finding] = []
    try:
        for directory, directories, names in os.walk(root / documents.HW, onerror=_fail):
            here = Path(directory)
            for name in sorted([*directories, *names]):
                path = here / name
                relative = path.relative_to(root).as_posix()
                if is_junk(PurePosixPath(relative)) or is_own(name):
                    if name in directories:
                        directories.remove(name)
                    continue
                if path.is_symlink():
                    links.add(relative)
                    outside = _outside(root, path, relative)
                    if outside is not None:
                        findings.append(outside)
                if name in names or (path.is_symlink() and not path.is_dir()):
                    files.append(relative)
    except OSError as failure:
        where = Path(failure.filename or root / documents.HW)
        relative = where.relative_to(root).as_posix() if root in where.parents else documents.HW
        raise ScanError(relative, failure.strerror or str(failure)) from failure
    return Inventory(tuple(sorted(files)), frozenset(links)), findings


def copy_for_validation(root: Path, inventory: Inventory, target: Path) -> None:
    """Copy every file of `inventory` outside sealed history to `target`, a fresh project root. A symbolic
    link (whose target is inside the project) becomes a link to its resolved target."""
    (target / documents.HW).mkdir(parents=True)
    for relative in [*inventory.readable(), *sorted(inventory.links - set(inventory.files))]:
        if is_sealed(relative):
            continue
        source, copy = root / relative, target / relative
        copy.parent.mkdir(parents=True, exist_ok=True)
        if relative in inventory.links:
            copy.symlink_to(source.resolve())
        else:
            copy.write_bytes(source.read_bytes())


def copy_complete(inventory: Inventory, target: Path) -> Finding | None:
    """A refusal when the copy at `target` does not hold exactly the files of `inventory` it should."""
    copied, _ = scan(target)
    expected = {path for path in inventory.readable()} | {
        link for link in inventory.links if not is_sealed(link)
    }
    found = set(copied.files) | set(copied.links)
    if found == expected:
        return None
    missing, extra = sorted(expected - found), sorted(found - expected)
    return error(
        "migrate.scan_incomplete",
        documents.HW,
        f"the validation copy differs from the files read: {len(missing)} missing (first {missing[:3]}), "
        f"{len(extra)} extra (first {extra[:3]})",
        action="Stop every other process that writes under hw/, then migrate again; nothing was changed.",
    )
