"""migrate(): convert a prototype hw/ record (record_version 2, or PR #319's record version 1) to record
version 3.

A dry run, the default, writes nothing under the project. It returns every file change (the rules applied
and a unified diff) and every finding, and it validates the migrated record in a temporary stage of
symbolic links, so `remaining` lists what the migration cannot fix. Apply builds the migrated tree beside
hw/ (unchanged files hard-linked, each changed file written to a temp file and renamed into place), validates
it, swaps it in for hw/ with two renames and re-reads the record. When any step fails the original hw/ is
put back, so the tree is as it was. A file no rule touches keeps its bytes; OS and tool junk is never read.
"""

from __future__ import annotations

import difflib
import os
import re
import shutil
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path

from benchhand_core.record import documents
from benchhand_core.record.errors import RECORD_VERSION, RecordMissingError
from benchhand_core.record.finding import Finding, Severity, error, info
from benchhand_core.record.formats import FormatError, parse_yaml
from benchhand_core.record.ignore import is_junk
from benchhand_core.record.migrate.rule import Rule
from benchhand_core.record.migrate.rules import RULES
from benchhand_core.record.validate import validate

SOURCE_VERSIONS = (1, 2)  # the prototype's record_version 2, and PR #319's record version 1 (the same format)
STAGE_PREFIX = ".hw.migrate-"
BEFORE = "hw.before"


class MigrationStatus(StrEnum):
    current = "current"  # already record_version 3; nothing to do
    ready = "ready"  # a dry run whose changes apply cleanly
    refused = "refused"  # a refusal, or the migrated record does not validate; nothing was written
    applied = "applied"


def _lines(text: str) -> list[str]:
    """`text`'s lines, each with its line break; only LF ends a line (a CR stays at the end of its line)."""
    return re.findall(r"[^\n]*\n|[^\n]+", text)


@dataclass(frozen=True)
class FileChange:
    path: str  # relative to the project root, with / separators
    rules: tuple[str, ...]  # the ids of the rules that changed it, in the order they ran
    before: str
    after: str

    def diff(self) -> str:
        """The unified diff of the change, with git's a/ and b/ prefixes."""
        lines = difflib.unified_diff(
            _lines(self.before),
            _lines(self.after),
            fromfile=f"a/{self.path}",
            tofile=f"b/{self.path}",
        )
        no_newline = "\n\\ No newline at end of file\n"
        return "".join(line if line.endswith("\n") else line + no_newline for line in lines)


@dataclass(frozen=True)
class Migration:
    """What migrate() found, and, for apply, what it did."""

    status: MigrationStatus
    from_version: int | None
    changes: tuple[FileChange, ...] = ()
    findings: tuple[Finding, ...] = ()  # what the version check and the rules report: notes and refusals
    remaining: tuple[Finding, ...] = ()  # validation findings of the migrated record

    @property
    def refusals(self) -> tuple[Finding, ...]:
        found = (*self.findings, *self.remaining)
        return tuple(finding for finding in found if finding.severity == Severity.error)


def _version_refusal(found: object) -> Finding:
    shown = "missing" if found is None else repr(found)[:40]
    return error(
        "record.version_unsupported",
        documents.PRODUCT.path,
        f"record_version {shown} is not one the migration reads: it converts the prototype's record_version "
        f"2 (and the record version 1 of prototype PR #319) to {RECORD_VERSION}",
        pointer="/record_version",
        action="Open the record with the benchhand release that wrote it; nothing was changed.",
    )


def _unreadable(path: str, reason: str) -> Finding:
    return error(
        "record.unreadable",
        path,
        reason[:300],
        action="Fix the file so that it reads as its format, then migrate again; nothing was changed.",
    )


def _read(root: Path, path: str) -> str:
    return (root / path).read_bytes().decode("utf-8")


def source_version(root: Path) -> tuple[int | None, tuple[Finding, ...]]:
    """The record_version of hw/product.yaml, or the findings that refuse the record."""
    path = documents.PRODUCT.path
    if not (root / documents.HW).is_dir():
        return None, tuple(RecordMissingError(documents.HW, "the project has no hw/ directory").findings())
    try:
        data = parse_yaml(_read(root, path))
    except FileNotFoundError:
        return None, tuple(RecordMissingError(path).findings())
    except (OSError, UnicodeDecodeError, FormatError) as failure:
        return None, (_unreadable(path, f"cannot read: {failure}"),)
    found = data.get("record_version") if isinstance(data, dict) else None
    if isinstance(found, bool) or found not in (*SOURCE_VERSIONS, RECORD_VERSION):
        return None, (_version_refusal(found),)
    return found, ()


def _files(root: Path) -> dict[str, list[Rule]]:
    """Each file some rule names, with its rules in table order; junk and anything but a file skipped."""
    files: dict[str, list[Rule]] = {}
    for rule in RULES:
        for pattern in rule.documents:
            for found in sorted(root.glob(pattern)):
                relative = found.relative_to(root)
                if found.is_file() and not is_junk(relative):
                    files.setdefault(relative.as_posix(), []).append(rule)
    return dict(sorted(files.items()))


def _migrate_file(root: Path, path: str, rules: list[Rule]) -> tuple[FileChange | None, list[Finding]]:
    try:
        before = _read(root, path)
    except (OSError, UnicodeDecodeError) as failure:
        return None, [_unreadable(path, f"cannot read: {failure}")]
    text, applied, findings = before, [], []
    for rule in rules:
        try:
            rewrite = rule.transform(path, text)
        except FormatError as failure:
            return None, [*findings, _unreadable(path, f"{rule.id}: {failure}")]
        findings.extend(rewrite.findings)
        if rewrite.text != text:
            text = rewrite.text
            applied.append(rule.id)
    change = FileChange(path, tuple(applied), before, text) if text != before else None
    return change, findings


def _plan(root: Path, from_version: int) -> Migration:
    changes: list[FileChange] = []
    findings: list[Finding] = []
    for path, rules in _files(root).items():
        change, found = _migrate_file(root, path, rules)
        findings.extend(found)
        if change is not None:
            changes.append(change)
    refused = any(finding.severity == Severity.error for finding in findings)
    status = MigrationStatus.refused if refused else MigrationStatus.ready
    return Migration(status, from_version, tuple(changes), tuple(findings))


# --- staging ------------------------------------------------------------------------------------------

Link = Callable[[Path, Path], None]


def _symlink(source: Path, target: Path) -> None:
    target.symlink_to(source)


def _hardlink(source: Path, target: Path) -> None:
    """`target` names `source`'s bytes without reading them: a hard link, or a copy where links fail."""
    if source.is_symlink():
        target.symlink_to(os.readlink(source))
        return
    try:
        os.link(source, target)
    except OSError:
        shutil.copy2(source, target)


def _write(target: Path, text: str, like: Path) -> None:
    """Write `text` to a temp file beside `target`, with `like`'s mode, then rename it into place."""
    handle, temporary = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.", suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="") as stream:
            stream.write(text)
        shutil.copymode(like, temporary)
        os.replace(temporary, target)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def _stage(root: Path, stage: Path, changes: tuple[FileChange, ...], link: Link) -> None:
    """Lay out hw/ under `stage` with every change made and every other entry linked to the original."""
    changed = {change.path: change.after for change in changes}
    for directory, directories, files in os.walk(root / documents.HW):
        here = Path(directory)
        relative = here.relative_to(root)
        (stage / relative).mkdir()
        shutil.copystat(here, stage / relative)
        for name in [*directories, *files]:
            source, path = here / name, (relative / name).as_posix()
            if path in changed:
                _write(stage / path, changed[path], like=source)
            elif name in files or source.is_symlink():
                link(source, stage / path)


def _validated(stage: Path) -> tuple[Finding, ...]:
    return tuple(validate(stage))


def _blocking(findings: tuple[Finding, ...]) -> bool:
    return any(finding.severity == Severity.error for finding in findings)


# --- applying -----------------------------------------------------------------------------------------


def _changed_meanwhile(root: Path, changes: tuple[FileChange, ...]) -> tuple[Finding, ...]:
    found = []
    for change in changes:
        try:
            current = _read(root, change.path)
        except (OSError, UnicodeDecodeError):
            current = None
        if current != change.before:
            found.append(
                error(
                    "migrate.changed_meanwhile",
                    change.path,
                    "the file changed after the migration read it",
                    action="Migrate again; nothing was changed.",
                )
            )
    return tuple(found)


def _swap(root: Path, stage: Path) -> tuple[Finding, ...]:
    """Put the staged hw/ in place of the original and re-read it; put the original back if that fails."""
    hw, before = root / documents.HW, stage / BEFORE
    os.rename(hw, before)
    try:
        os.rename(stage / documents.HW, hw)
        remaining = _validated(root)
    except BaseException:
        _restore(hw, before, stage)
        raise
    if _blocking(remaining):
        _restore(hw, before, stage)
    return remaining


def _restore(hw: Path, before: Path, stage: Path) -> None:
    if hw.exists():
        os.rename(hw, stage / documents.HW)
    os.rename(before, hw)


def _apply(root: Path, plan: Migration) -> Migration:
    meanwhile = _changed_meanwhile(root, plan.changes)
    if meanwhile:
        return replace(plan, status=MigrationStatus.refused, findings=(*plan.findings, *meanwhile))
    stage = Path(tempfile.mkdtemp(prefix=STAGE_PREFIX, dir=root))
    try:
        _stage(root, stage, plan.changes, _hardlink)
        remaining = _validated(stage)
        if not _blocking(remaining):
            remaining = _swap(root, stage)
    finally:
        _remove_stage(root, stage)
    status = MigrationStatus.refused if _blocking(remaining) else MigrationStatus.applied
    return replace(plan, status=status, remaining=remaining)


def _remove_stage(root: Path, stage: Path) -> None:
    """Remove the stage, unless hw/ is missing: the stage then holds the original, as hw.before."""
    if (root / documents.HW).is_dir():
        shutil.rmtree(stage, ignore_errors=True)


def migrate(root: Path, *, apply: bool = False) -> Migration:
    """Migrate the record of the project at `root` to record version 3: a dry run unless `apply`."""
    found, refusals = source_version(root)
    if refusals or found is None:
        return Migration(MigrationStatus.refused, found, findings=refusals)
    if found == RECORD_VERSION:
        note = info(
            "migrate.current",
            documents.PRODUCT.path,
            f"the record is already record_version {RECORD_VERSION}; nothing to migrate",
            pointer="/record_version",
        )
        return Migration(MigrationStatus.current, found, findings=(note,))
    plan = _plan(root, found)
    if plan.status == MigrationStatus.refused:
        return plan
    if apply:
        return _apply(root, plan)
    with tempfile.TemporaryDirectory(prefix="benchhand-migrate-") as stage:
        _stage(root, Path(stage), plan.changes, _symlink)
        remaining = _validated(Path(stage))
    status = MigrationStatus.refused if _blocking(remaining) else MigrationStatus.ready
    return replace(plan, status=status, remaining=remaining)
