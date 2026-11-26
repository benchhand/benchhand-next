"""migrate(): convert a prototype hw/ record (record_version 2, or PR #319's record version 1) to record
version 3.

A dry run, the default, writes nothing under the project. It returns every file change (the rules applied
and a unified diff) and every finding, and it validates a real copy of the migrated record in a temporary
directory, so `remaining` lists what the migration cannot fix.

Apply writes in place. It needs a recovery point first (recovery.py: a clean git work tree, or --backup) and
holds hw/.benchhand-migrate.lock. Under the lock it plans again, validates the migrated copy, and checks
that no file was added or removed since. It then writes only the changed files, each checked against the
bytes it planned from, synced and renamed into place, with hw/product.yaml last. Every rule changes nothing
on its own output, so a rerun after an interrupted apply finishes it; until then the recovery point puts
hw/ back. Another process writing under hw/ must be stopped first: the lock keeps out only a second
migration.
"""

from __future__ import annotations

import difflib
import re
import shutil
import tempfile
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path
from typing import Any

from benchhand_core.record import documents
from benchhand_core.record.errors import RECORD_VERSION, RecordMissingError
from benchhand_core.record.finding import Finding, Severity, error, info
from benchhand_core.record.formats import FormatError, parse_yaml
from benchhand_core.record.migrate import inventory as scanning
from benchhand_core.record.migrate import recovery
from benchhand_core.record.migrate.inventory import Inventory, ScanError
from benchhand_core.record.migrate.recovery import RecoveryPoint
from benchhand_core.record.migrate.rule import Rule
from benchhand_core.record.migrate.rules import RULES
from benchhand_core.record.validate import validate

SOURCE_VERSIONS = (1, 2)  # the prototype's record_version 2, and PR #319's record version 1 (the same format)
# The files whose bytes the prototype's acceptance digest (flow.frozen.evidence_sha256) hashes, of those a
# rule may change (prototype evidence.py LEDGER_FILES).
DIGEST_INPUTS = ("hw/verification.csv", "hw/manufacturing/evidence.yaml", "hw/manufacturing/findings.yaml")


class MigrationStatus(StrEnum):
    current = "current"  # already record_version 3; nothing to do
    ready = "ready"  # a dry run whose changes apply cleanly
    refused = "refused"  # a refusal, or the migrated record does not validate; nothing was written
    applied = "applied"
    failed = "failed"  # apply stopped after writing; `recovery` puts hw/ back, or a rerun finishes it


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
    findings: tuple[Finding, ...] = ()  # what the checks and the rules report: notes and refusals
    remaining: tuple[Finding, ...] = ()  # validation findings of the migrated record
    written: tuple[str, ...] = ()  # the files apply wrote, in the order it wrote them
    recovery: str | None = None  # the command that puts hw/ back as it was, once apply has a recovery point
    backup: Path | None = None  # the --backup copy

    @property
    def refusals(self) -> tuple[Finding, ...]:
        found = (*self.findings, *self.remaining)
        return tuple(finding for finding in found if finding.severity == Severity.error)


def _blocking(findings: tuple[Finding, ...] | list[Finding]) -> bool:
    return any(finding.severity == Severity.error for finding in findings)


# --- reading --------------------------------------------------------------------------------------------


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


def source_version(root: Path) -> tuple[int | None, Any, tuple[Finding, ...]]:
    """The record_version of hw/product.yaml and its parsed data, or the findings that refuse the record."""
    path = documents.PRODUCT.path
    if not (root / documents.HW).is_dir():
        missing = RecordMissingError(documents.HW, "the project has no hw/ directory")
        return None, None, tuple(missing.findings())
    try:
        data = parse_yaml((root / path).read_bytes().decode("utf-8"))
    except FileNotFoundError:
        return None, None, tuple(RecordMissingError(path).findings())
    except (OSError, UnicodeDecodeError, FormatError) as failure:
        return None, None, (_unreadable(path, f"cannot read: {failure}"),)
    found = data.get("record_version") if isinstance(data, dict) else None
    if isinstance(found, bool) or found not in (*SOURCE_VERSIONS, RECORD_VERSION):
        return None, data, (_version_refusal(found),)
    return found, data, ()


# --- planning -------------------------------------------------------------------------------------------


def _rules_of(path: str) -> list[Rule]:
    return [rule for rule in RULES if any(scanning.matches(pattern, path) for pattern in rule.documents)]


def _migrate_file(root: Path, path: str, rules: list[Rule]) -> tuple[FileChange | None, list[Finding]]:
    try:
        before = (root / path).read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError) as failure:
        return None, [_unreadable(path, f"cannot read: {failure}")]
    text = before
    applied: list[str] = []
    findings: list[Finding] = []
    for rule in rules:
        try:
            rewrite = rule.run(path, text)
        except FormatError as failure:
            return None, [*findings, _unreadable(path, f"{rule.id}: {failure}")]
        findings.extend(rewrite.findings)
        if rewrite.text != text:
            text = rewrite.text
            applied.append(rule.id)
    change = FileChange(path, tuple(applied), before, text) if text != before else None
    return change, findings


def _layout_findings(inventory: Inventory, changes: list[FileChange]) -> list[Finding]:
    return [
        error(
            "migrate.unsupported_layout",
            change.path,
            "this file is a symbolic link; a migration replaces a file, not a link",
            action="Replace the link with a copy of the file it points to, then migrate again.",
        )
        for change in changes
        if change.path in inventory.links
    ]


def _frozen_anchor(product: Any, changes: list[FileChange]) -> list[Finding]:
    flow = product.get("flow") if isinstance(product, dict) else None
    anchored = [change.path for change in changes if change.path in DIGEST_INPUTS]
    if not isinstance(flow, dict) or not flow.get("frozen") or not anchored:
        return []
    return [
        error(
            "migrate.frozen_anchor",
            documents.PRODUCT.path,
            f"the record is frozen, and the migration would change {', '.join(anchored)}, whose bytes the "
            "freeze's acceptance digest (flow.frozen.evidence_sha256) states",
            pointer="/flow/frozen",
            action="A frozen record cannot be migrated: its freeze cannot be re-anchored until the Phase 2 "
            "flow engine records an engineering change for it; nothing was changed.",
        )
    ]


@dataclass(frozen=True)
class _Plan:
    migration: Migration
    inventory: Inventory


def _plan(root: Path, from_version: int, product: Any) -> _Plan:
    try:
        inventory, findings = scanning.scan(root)
    except ScanError as failure:
        return _Plan(
            Migration(MigrationStatus.refused, from_version, findings=(failure.finding(),)),
            Inventory((), frozenset()),
        )
    changes: list[FileChange] = []
    for path in inventory.readable():
        rules = _rules_of(path)
        if not rules:
            continue
        change, found = _migrate_file(root, path, rules)
        findings.extend(found)
        if change is not None:
            changes.append(change)
    findings.extend(_layout_findings(inventory, changes))
    findings.extend(_frozen_anchor(product, changes))
    status = MigrationStatus.refused if _blocking(findings) else MigrationStatus.ready
    return _Plan(Migration(status, from_version, tuple(changes), tuple(findings)), inventory)


def _validate_copy(root: Path, plan: _Plan) -> tuple[tuple[Finding, ...], list[Finding]]:
    """The validation findings of a real copy of the migrated record, and any refusal or cleanup warning
    about the copy itself."""
    directory = Path(tempfile.mkdtemp(prefix="benchhand-migrate-"))
    notes: list[Finding] = []
    try:
        copy = directory / "project"
        scanning.copy_for_validation(root, plan.inventory, copy)
        for change in plan.migration.changes:
            (copy / change.path).write_bytes(change.after.encode("utf-8"))
        incomplete = scanning.copy_complete(plan.inventory, copy)
        if incomplete is not None:
            return (), [incomplete]
        return tuple(validate(copy)), notes
    except ScanError as failure:
        return (), [failure.finding()]
    finally:
        try:
            shutil.rmtree(directory)
        except OSError as failure:
            notes.append(recovery.cleanup_failed(documents.HW, failure, f"Delete {directory} by hand."))


def _checked(root: Path, from_version: int, product: Any) -> _Plan:
    """The plan, with the validation of its migrated copy in `remaining`."""
    plan = _plan(root, from_version, product)
    if plan.migration.status == MigrationStatus.refused:
        return plan
    remaining, notes = _validate_copy(root, plan)
    findings = (*plan.migration.findings, *notes)
    refused = _blocking(remaining) or _blocking(notes)
    status = MigrationStatus.refused if refused else MigrationStatus.ready
    return _Plan(
        replace(plan.migration, status=status, findings=findings, remaining=remaining), plan.inventory
    )


# --- applying -------------------------------------------------------------------------------------------


def _changed_meanwhile(path: str, why: str, point: RecoveryPoint | None) -> Finding:
    action = "Stop every other process that writes under hw/, then migrate again"
    if point is not None:
        action += f"; to undo what this run wrote, run: {point.command}"
    return error("migrate.changed_meanwhile", path, why, action=action + ".")


def _same_files(root: Path, plan: _Plan) -> Finding | None:
    """A refusal when a file was added under hw/ or removed since the plan read it."""
    try:
        now, _ = scanning.scan(root)
    except ScanError as failure:
        return failure.finding()
    if now.files == plan.inventory.files and now.links == plan.inventory.links:
        return None
    added = sorted(set(now.files) - set(plan.inventory.files))
    removed = sorted(set(plan.inventory.files) - set(now.files))
    shown = (added or removed or [documents.HW])[0]
    return _changed_meanwhile(
        shown,
        f"files changed under hw/ while the migration ran: {len(added)} added, {len(removed)} removed",
        None,
    )


def _write_order(changes: tuple[FileChange, ...]) -> list[FileChange]:
    """hw/product.yaml last: until it says record_version 3, a rerun migrates the rest."""
    return sorted(changes, key=lambda change: change.path == documents.PRODUCT.path)


def _write(root: Path, change: FileChange) -> bool:
    """Write one planned change; False when the file no longer holds the bytes it was planned from."""
    target = root / change.path
    if recovery.sha256(target.read_bytes()) != recovery.sha256(change.before.encode("utf-8")):
        return False
    recovery.write_durably(target, change.after.encode("utf-8"))
    return True


def _write_failed(path: str, failure: OSError, point: RecoveryPoint) -> Finding:
    return error(
        "migrate.write_failed",
        path,
        f"cannot write it: {failure.strerror or failure}; the files before it in `written` are migrated",
        action=f"Fix the cause and migrate again to finish, or put hw/ back with: {point.command}",
    )


def _write_all(root: Path, migration: Migration, point: RecoveryPoint) -> Migration:
    written: list[str] = []
    for change in _write_order(migration.changes):
        try:
            if not _write(root, change):
                refusal = _changed_meanwhile(
                    change.path, "the file changed after the migration read it", point
                )
                return _stopped(migration, written, refusal)
        except OSError as failure:
            return _stopped(migration, written, _write_failed(change.path, failure, point))
        written.append(change.path)
    remaining = tuple(validate(root))
    if _blocking(remaining):
        note = error(
            "migrate.invalid_result",
            documents.HW,
            "the migrated record does not validate, though its copy did",
            action=f"Put hw/ back with: {point.command}",
        )
        return replace(
            migration,
            status=MigrationStatus.failed,
            remaining=remaining,
            written=tuple(written),
            findings=(*migration.findings, note),
        )
    return replace(migration, status=MigrationStatus.applied, remaining=remaining, written=tuple(written))


def _stopped(migration: Migration, written: list[str], refusal: Finding) -> Migration:
    status = MigrationStatus.failed if written else MigrationStatus.refused
    return replace(migration, status=status, written=tuple(written), findings=(*migration.findings, refusal))


def _recovery_point(root: Path, plan: _Plan, backup: bool) -> RecoveryPoint | Finding:
    if backup:
        try:
            return recovery.write_backup(root, plan.inventory)
        except OSError as failure:
            return error(
                "migrate.backup_failed",
                recovery.BACKUPS,
                f"cannot write the backup: {failure.strerror or failure}",
                action="Free space or fix permissions under .benchhand/, then migrate again.",
            )
    point = recovery.git_recovery(root)
    if isinstance(point, str):
        return recovery.no_recovery_point(point)
    missing = recovery.untracked(root, [change.path for change in plan.migration.changes])
    if missing:
        return recovery.no_recovery_point(f"git does not track {', '.join(missing[:3])}")
    return point


def _apply_locked(root: Path, from_version: int, product: Any, backup: bool) -> Migration:
    plan = _checked(root, from_version, product)
    if plan.migration.status == MigrationStatus.refused:
        return plan.migration
    point = _recovery_point(root, plan, backup)
    if isinstance(point, Finding):
        return replace(
            plan.migration, status=MigrationStatus.refused, findings=(*plan.migration.findings, point)
        )
    migration = replace(plan.migration, recovery=point.command, backup=point.backup)
    if point.backup is not None:
        note = info(
            "migrate.backup_written",
            documents.HW,
            f"the record before the migration is in {point.backup}",
            action=f"To put hw/ back, run: {point.command}",
        )
        migration = replace(migration, findings=(*migration.findings, note))
    meanwhile = _same_files(root, plan)
    if meanwhile is not None:
        return replace(migration, status=MigrationStatus.refused, findings=(*migration.findings, meanwhile))
    return _write_all(root, migration, point)


def _apply(root: Path, from_version: int, product: Any, backup: bool) -> Migration:
    lock = recovery.acquire_lock(root)
    if isinstance(lock, Finding):
        return Migration(MigrationStatus.refused, from_version, findings=(lock,))
    try:
        result = _apply_locked(root, from_version, product, backup)
    finally:
        released = recovery.release_lock(lock)
    return result if released is None else replace(result, findings=(*result.findings, released))


def migrate(root: Path, *, apply: bool = False, backup: bool = False) -> Migration:
    """Migrate the record of the project at `root` to record version 3: a dry run unless `apply`. With
    `backup`, apply first copies hw/ to .benchhand/backups/; without it, hw/ must be clean in git."""
    root = root.resolve()
    found, product, refusals = source_version(root)
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
    if apply:
        return _apply(root, found, product, backup)
    return _checked(root, found, product).migration
