"""migrate(): convert a prototype hw/ record (record_version 2, or PR #319's record version 1) to record
version 3; undo(): put back the files an apply changed.

A dry run, the default, writes nothing under the project. It returns every file change (the rules applied
and a unified diff) and every finding, and it validates a real copy of the migrated record in a temporary
directory, so `remaining` lists what the migration cannot fix.

Apply, resume and undo each run as the record's one owner (hw/.benchhand-migrate.owner, created with O_EXCL).
Apply points hw/.benchhand-migrate.lock at a new backup, plans again, validates the migrated copy, and
writes a backup of the preimages of the files it will change (recovery.py). Only once that backup is COMPLETE
does it write: only the changed files, each re-hashed after its temp file is synced and just before the
rename, with hw/product.yaml last. Before it removes the lock, it syncs the directory of every target, so a
rename a stopped run made is durable. If apply stops after the backup is COMPLETE, the lock stays: a rerun
finishes the migration with --resume, reusing that backup's preimages, or `--undo <backup>` puts the files
back. Every rule changes nothing on its own output, so a resumed apply writes the bytes a clean run writes.
Another process writing under hw/ must be stopped first: the owner file keeps out only a second migration.
"""

from __future__ import annotations

import difflib
import re
import shutil
import tempfile
from dataclasses import dataclass, field, replace
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Any

from benchhand_core.record import documents
from benchhand_core.record.errors import RECORD_VERSION, RecordMissingError
from benchhand_core.record.finding import Finding, Severity, error, info
from benchhand_core.record.formats import FormatError, parse_yaml
from benchhand_core.record.migrate import inventory as scanning
from benchhand_core.record.migrate import recovery
from benchhand_core.record.migrate.inventory import Inventory, ScanError
from benchhand_core.record.migrate.recovery import Entry, Preimage
from benchhand_core.record.migrate.rule import Rule
from benchhand_core.record.migrate.rules import RULES
from benchhand_core.record.validate import validate

SOURCE_VERSIONS = (1, 2)  # the prototype's record_version 2, and PR #319's record version 1 (the same format)


class MigrationStatus(StrEnum):
    current = "current"  # already record_version 3; nothing to do
    ready = "ready"  # a dry run whose changes apply cleanly
    refused = "refused"  # a refusal, or the migrated record does not validate; nothing was written
    applied = "applied"
    failed = "failed"  # apply stopped after its backup was COMPLETE; --resume finishes it, --undo reverts it
    undone = "undone"  # undo() put the files back


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
    """What migrate() or undo() found, and what it did."""

    status: MigrationStatus
    from_version: int | None
    changes: tuple[FileChange, ...] = ()
    findings: tuple[Finding, ...] = ()  # what the checks and the rules report: notes and refusals
    remaining: tuple[Finding, ...] = ()  # validation findings of the migrated record
    written: tuple[str, ...] = ()  # the files this run wrote (or replaced), in the order it wrote them
    recovery: str | None = None  # the undo command, once a COMPLETE backup exists
    backup: Path | None = None

    @property
    def refusals(self) -> tuple[Finding, ...]:
        found = (*self.findings, *self.remaining)
        return tuple(finding for finding in found if finding.severity == Severity.error)


def _blocking(findings: tuple[Finding, ...] | list[Finding]) -> bool:
    return any(finding.severity == Severity.error for finding in findings)


def _refused(from_version: int | None, *findings: Finding) -> Migration:
    return Migration(MigrationStatus.refused, from_version, findings=findings)


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


def _hw_link(root: Path) -> Finding | None:
    hw = root / documents.HW
    if not hw.is_symlink():
        return None
    return error(
        "migrate.symlink_hw",
        documents.HW,
        f"hw/ is a symbolic link to {hw.resolve()}; the migration changes the record of this project only",
        action="Run the migration in the project that holds the record, or replace the link with the "
        "directory; nothing was read or changed.",
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


def _frozen_anchor(product: Any) -> Finding | None:
    """A frozen prototype record is refused whatever the rules would change: the freeze's acceptance digest
    states the bytes of the ledgers and the artifacts they cite."""
    flow = product.get("flow") if isinstance(product, dict) else None
    if not isinstance(flow, dict) or "frozen" not in flow:
        return None
    return error(
        "migrate.frozen_anchor",
        documents.PRODUCT.path,
        "the record is frozen (flow.frozen): its acceptance digest (flow.frozen.evidence_sha256) states the "
        "bytes of the record it froze, and a migrated record cannot keep that anchor",
        pointer="/flow/frozen",
        action="A frozen record cannot be migrated: its freeze cannot be re-anchored until the Phase 2 "
        "flow engine records an engineering change for it; nothing was changed.",
    )


@dataclass(frozen=True)
class _Plan:
    migration: Migration
    inventory: Inventory


def _plan(root: Path, from_version: int, product: Any) -> _Plan:
    empty = Inventory((), frozenset())
    frozen = _frozen_anchor(product)
    if frozen is not None:
        return _Plan(_refused(from_version, frozen), empty)
    try:
        inventory, findings = scanning.scan(root)
    except ScanError as failure:
        return _Plan(_refused(from_version, failure.finding()), empty)
    if _blocking(findings):  # a link out of the project, or to a directory: read nothing
        return _Plan(_refused(from_version, *findings), inventory)
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


@dataclass
class _Run:
    """One apply or resume, run by the owner: its backup, whether that backup is COMPLETE (from here on the
    lock stays when apply stops, since files may have been written), and every file it migrates."""

    root: Path
    backup: Path
    complete: bool = False
    written: list[str] = field(default_factory=list)
    targets: list[str] = field(default_factory=list)  # project-relative

    def recover(self) -> str:
        """How to finish or revert this run, for a failure finding."""
        if not self.complete:
            return "Nothing was written"
        return (
            f"To finish the migration, run: {recovery.resume_command(self.root)}; to put the files it "
            f"changed back, run: {recovery.undo_command(self.backup)}"
        )


def _hw_relative(path: str) -> str:
    return PurePosixPath(path).relative_to(documents.HW).as_posix()


def _changed_meanwhile(run: _Run, path: str, why: str) -> Finding:
    return error(
        "migrate.changed_meanwhile",
        path,
        why,
        action=f"Stop every other process that writes under hw/. {run.recover()}.",
    )


def _same_files(run: _Run, plan: _Plan) -> Finding | None:
    """A refusal when a file was added under hw/ or removed since the plan read it."""
    try:
        now, _ = scanning.scan(run.root)
    except ScanError as failure:
        return failure.finding()
    if now.files == plan.inventory.files and now.links == plan.inventory.links:
        return None
    added = sorted(set(now.files) - set(plan.inventory.files))
    removed = sorted(set(plan.inventory.files) - set(now.files))
    shown = (added or removed or [documents.HW])[0]
    why = f"files changed under hw/ while the migration ran: {len(added)} added, {len(removed)} removed"
    return _changed_meanwhile(run, shown, why)


def _write_order(changes: tuple[FileChange, ...]) -> list[FileChange]:
    """hw/product.yaml last: until it says record_version 3, a resumed apply migrates the rest."""
    return sorted(changes, key=lambda change: change.path == documents.PRODUCT.path)


def _write_failed(run: _Run, path: str, failure: OSError) -> Finding:
    return error(
        "migrate.write_failed",
        path,
        f"cannot write it: {failure.strerror or failure}; the files before it in `written` are migrated",
        action=f"Fix the cause. {run.recover()}.",
    )


def _not_durable(path: str, failure: OSError, recover: str) -> Finding:
    return error(
        "migrate.not_durable",
        path,
        f"the file was replaced, but syncing its directory failed ({failure.strerror or failure}), so the "
        "change may not survive a power loss",
        action=f"Fix the disk or file system. {recover}.",
    )


def _write_one(run: _Run, change: FileChange) -> Finding | None:
    """Write one planned change; the refusal that stops apply, if any."""
    expected = recovery.sha256(change.before.encode("utf-8"))
    try:
        recovery.write_durably(run.root / change.path, change.after.encode("utf-8"), expected)
    except recovery.ChangedMeanwhile:
        return _changed_meanwhile(run, change.path, "the file changed after the migration read it")
    except recovery.NotDurable as failure:
        run.written.append(change.path)
        return _not_durable(change.path, failure.failure, run.recover())
    except OSError as failure:
        return _write_failed(run, change.path, failure)
    run.written.append(change.path)
    return None


def _write_all(run: _Run, migration: Migration) -> Migration:
    for change in _write_order(migration.changes):
        refusal = _write_one(run, change)
        if refusal is not None:
            return _stopped(run, migration, refusal)
    try:  # a stopped run may have renamed a file it never synced the directory of
        recovery.sync_parents(run.root, run.targets)
    except OSError as failure:
        return _stopped(run, migration, _not_durable(documents.HW, failure, run.recover()))
    remaining = tuple(validate(run.root))
    if _blocking(remaining):
        note = error(
            "migrate.invalid_result",
            documents.HW,
            "the migrated record does not validate, though its copy did",
            action=f"Put the files back with: {recovery.undo_command(run.backup)}",
        )
        failed = replace(migration, remaining=remaining)
        return _stopped(run, failed, note)
    return replace(migration, status=MigrationStatus.applied, remaining=remaining, written=tuple(run.written))


def _stopped(run: _Run, migration: Migration, refusal: Finding) -> Migration:
    status = MigrationStatus.failed if run.complete else MigrationStatus.refused
    return replace(
        migration, status=status, written=tuple(run.written), findings=(*migration.findings, refusal)
    )


def _write_backup(run: _Run, changes: tuple[FileChange, ...]) -> Finding | None:
    preimages = [
        Preimage(
            _hw_relative(change.path),
            change.before.encode("utf-8"),
            recovery.sha256(change.after.encode("utf-8")),
        )
        for change in changes
    ]
    try:
        recovery.write_backup(run.root, run.backup, preimages)
    except OSError as failure:
        return error(
            "migrate.backup_failed",
            recovery.BACKUPS,
            f"cannot write the backup {run.backup}: {failure.strerror or failure}",
            action="Free space, fix permissions, or replace a symbolic link under .benchhand/ with a "
            "directory, then migrate again; nothing was written.",
        )
    run.complete = True
    return None


def _backup_note(run: _Run) -> Finding:
    return info(
        "migrate.backup_written",
        documents.HW,
        f"the files the migration changes are kept as they were in {run.backup}",
        action=f"To put them back, run: {recovery.undo_command(run.backup)}",
    )


def _fresh(run: _Run, from_version: int, product: Any) -> Migration:
    """Plan, back up the preimages, then write."""
    plan = _checked(run.root, from_version, product)
    if plan.migration.status == MigrationStatus.refused:
        return plan.migration
    run.targets = [change.path for change in plan.migration.changes]
    failed = _write_backup(run, plan.migration.changes)
    if failed is not None:
        findings = (*plan.migration.findings, failed)
        return replace(plan.migration, status=MigrationStatus.refused, findings=findings)
    migration = replace(
        plan.migration,
        recovery=recovery.undo_command(run.backup),
        backup=run.backup,
        findings=(*plan.migration.findings, _backup_note(run)),
    )
    meanwhile = _same_files(run, plan)
    if meanwhile is not None:
        return _stopped(run, migration, meanwhile)
    return _write_all(run, migration)


def _resume_check(run: _Run, changes: tuple[FileChange, ...], entries: list[Entry]) -> Finding | None:
    """Each planned change must be a preimage the backup holds, and each other backed-up file must hold its
    migrated bytes; otherwise something else changed the record since the stopped apply."""
    by_path = {f"{documents.HW}/{entry.path}": entry for entry in entries}
    for change in changes:
        entry = by_path.get(change.path)
        before, after = (recovery.sha256(text.encode("utf-8")) for text in (change.before, change.after))
        if entry is None or (entry.sha256, entry.migrated_sha256) != (before, after):
            return _changed_meanwhile(run, change.path, "the file is not as the stopped migration left it")
    planned = {change.path for change in changes}
    for path, entry in by_path.items():
        if path in planned:
            continue
        try:
            found = recovery.sha256((run.root / path).read_bytes())
        except OSError:
            found = ""
        if found != entry.migrated_sha256:
            return _changed_meanwhile(run, path, "the file is not as the stopped migration left it")
    return None


def _resumed(run: _Run, from_version: int, product: Any) -> Migration:
    """Finish the apply that left the lock, from its COMPLETE backup."""
    entries = recovery.read_manifest(run.backup)
    if isinstance(entries, str):
        unusable = _backup_unusable(run.backup, entries)
        return _stopped(run, Migration(MigrationStatus.failed, from_version), unusable)
    run.targets = [f"{documents.HW}/{entry.path}" for entry in entries]
    resumed = Migration(MigrationStatus.failed, from_version, recovery=recovery.undo_command(run.backup))
    try:
        recovery.sync_complete(run.backup)
    except OSError as failure:
        return _stopped(run, resumed, _not_durable(_backup_path(run.backup), failure, run.recover()))
    if from_version == RECORD_VERSION:  # hw/product.yaml was written last: every file was
        found = _resume_check(run, (), entries)
        if found is not None:
            return _stopped(run, resumed, found)
        return _write_all(run, replace(resumed, backup=run.backup))
    plan = _checked(run.root, from_version, product)
    migration = replace(plan.migration, recovery=resumed.recovery, backup=run.backup)
    if plan.migration.status == MigrationStatus.refused:
        return replace(migration, status=MigrationStatus.failed)
    found = _resume_check(run, plan.migration.changes, entries) or _same_files(run, plan)
    if found is not None:
        return _stopped(run, migration, found)
    return _write_all(run, migration)


def _backup_path(backup: Path) -> str:
    """A backup as a finding path: relative to its project, or the backups directory when it has none."""
    root = recovery.project_of(backup)
    return backup.relative_to(root).as_posix() if root is not None else recovery.BACKUPS


def _backup_unusable(backup: Path, reason: str) -> Finding:
    return error(
        "migrate.backup_unusable",
        _backup_path(backup),
        f"the backup {backup} cannot be used: {reason}",
        action=f"Restore the files listed in {backup / recovery.MANIFEST} by hand from "
        f"{backup / documents.HW}, then delete {recovery.LOCK_PATH}.",
    )


def _linked(root: Path, relative: str, what: str) -> Finding:
    return error(
        "migrate.unsupported_layout",
        relative,
        f"{relative} is a symbolic link; the service does not {what} through one",
        action="Replace the link with the directory or file it points to, then run the command again; "
        "nothing was changed.",
    )


def _own_backup(root: Path, held: Path) -> Path | Finding:
    """The backup a lock names, as a path under this project, with no symbolic link on the way. The lock
    stores the backup under the resolved project root, so its spelling is compared, not resolved."""
    if recovery.project_of(held) != root:
        return recovery.locked(root, held)
    backup = root / recovery.BACKUPS / held.name
    link = recovery.backup_link(root, backup)
    return backup if link is None else _linked(root, link, "recover a backup")


def _abandon(backup: Path, why: str) -> Finding:
    """Leave an unfinished backup where it is, marked ABANDONED: the note, or the refusal when the marker
    cannot be written."""
    try:
        recovery.abandon(backup, f"left unfinished by a stopped apply; {why}")
    except OSError as failure:
        return error(
            "migrate.backup_failed",
            _backup_path(backup),
            f"cannot mark the unfinished backup {backup} {recovery.ABANDONED}: {failure.strerror or failure}",
            action="Fix permissions or free space, then run the command again; nothing was written.",
        )
    return info(
        "migrate.backup_abandoned",
        _backup_path(backup),
        f"the unfinished backup {backup} of the stopped apply is marked {recovery.ABANDONED}, left in place",
        action="That apply wrote nothing. Delete the directory by hand when you no longer want it.",
    )


def _abandon_and_start(root: Path, backup: Path) -> tuple[_Run, Finding] | Finding:
    """Mark an unfinished backup ABANDONED and point the lock at a new one beside it."""
    fresh = recovery.new_backup(root)
    note = _abandon(backup, f"--resume continued in {fresh.name}")
    if note.severity == Severity.error:
        return note
    try:
        recovery.write_lock(root, fresh)
    except OSError as failure:
        return _lock_failed(failure)
    return _Run(root, fresh), note


def _lock_failed(failure: OSError) -> Finding:
    return error(
        "migrate.lock_failed",
        recovery.LOCK_PATH,
        f"cannot write the migration lock: {failure.strerror or failure}",
        action="Fix permissions or free space, then run the command again; nothing was written.",
    )


def _not_interrupted() -> Finding:
    return error(
        "migrate.not_interrupted",
        recovery.LOCK_PATH,
        "there is no stopped migration to resume: the record has no migration lock",
        action="Run the migration without --resume.",
    )


def _lock_state(root: Path, resume: bool) -> Path | Finding | None:
    """What the lock says to an apply: None (no lock) for a fresh apply, the backup a resume reuses or
    replaces, or the refusal. Read before the run takes ownership, and again once it owns the record."""
    held = recovery.read_lock(root)
    if held is None:
        return _not_interrupted() if resume else None
    if not resume or isinstance(held, str):
        return recovery.locked(root, held)
    return _own_backup(root, held)


def _run_for(root: Path, from_version: int, resume: bool) -> tuple[_Run | None, Finding | None] | Finding:
    """The run the owner starts: a fresh apply, a resume of a COMPLETE backup, or a fresh apply beside an
    abandoned backup, each with an optional note; a refusal; or no run when a stale lock sits on a record
    nothing migrated."""
    held = _lock_state(root, resume)
    if isinstance(held, Finding):
        return held
    if held is None:
        backup = recovery.new_backup(root)
        try:
            recovery.write_lock(root, backup)
        except OSError as failure:
            return _lock_failed(failure)
        return _Run(root, backup), None
    if recovery.is_complete(held):
        return _Run(root, held, complete=True), None
    if from_version == RECORD_VERSION:
        note = _abandon(held, f"the record was already record_version {RECORD_VERSION}")
        return note if note.severity == Severity.error else (None, note)
    return _abandon_and_start(root, held)


def _owned_apply(root: Path, from_version: int, product: Any, resume: bool) -> Migration:
    started = _run_for(root, from_version, resume)
    if isinstance(started, Finding):
        return _refused(from_version, started)
    run, note = started
    if run is None:  # nothing was written before the backup was COMPLETE; the record was already v3
        cleared = recovery.clear_lock(root)
        current = _current(root)
        found = (note, *current.findings, cleared)
        return replace(current, findings=tuple(finding for finding in found if finding is not None))
    try:
        result = _resumed(run, from_version, product) if run.complete else _fresh(run, from_version, product)
    except BaseException:
        if not run.complete:
            recovery.clear_lock(root)
        raise
    if note is not None:
        result = replace(result, findings=(note, *result.findings))
    if result.status != MigrationStatus.applied and run.complete:
        return result  # the lock stays: the next run must --resume or --undo
    cleared = recovery.clear_lock(root)
    return result if cleared is None else replace(result, findings=(*result.findings, cleared))


def _owned(root: Path, work: Any) -> Migration:
    """Run `work()` as the owner of the record's migration; a refusal when another process owns it."""
    try:
        owner = recovery.acquire_owner(root)
    except OSError as failure:
        return _refused(None, _lock_failed(failure))
    if isinstance(owner, Finding):
        return _refused(None, owner)
    try:
        result: Migration = work()
    finally:
        released = recovery.release_owner(owner)
    return result if released is None else replace(result, findings=(*result.findings, released))


def _held(root: Path) -> Finding | None:
    """The refusal when a migration owns the record now or a stopped one holds its lock."""
    held = recovery.read_lock(root)
    return recovery.owner_refusal(root) or (None if held is None else recovery.locked(root, held))


def _current(root: Path) -> Migration:
    """A record_version 3 record: nothing to migrate, once no stopped migration holds it and it validates."""
    held = recovery.read_lock(root)
    if held is not None:
        return _refused(RECORD_VERSION, recovery.locked(root, held))
    note = info(
        "migrate.current",
        documents.PRODUCT.path,
        f"the record is already record_version {RECORD_VERSION}; nothing to migrate",
        pointer="/record_version",
    )
    remaining = tuple(validate(root))
    return Migration(MigrationStatus.current, RECORD_VERSION, findings=(note,), remaining=remaining)


def migrate(root: Path, *, apply: bool = False, resume: bool = False) -> Migration:
    """Migrate the record of the project at `root` to record version 3: a dry run unless `apply`. With
    `resume`, apply finishes the stopped apply whose lock it finds."""
    root = root.absolute()
    link = _hw_link(root)
    if link is not None:
        return _refused(None, link)
    root = root.resolve()
    if recovery.is_link(root / documents.PRODUCT.path):
        return _refused(None, _linked(root, documents.PRODUCT.path, "read the record version"))
    found, product, refusals = source_version(root)
    if refusals or found is None:
        return _refused(found, *refusals)
    if apply and (found != RECORD_VERSION or resume):
        stale = _lock_state(root, resume)  # checked again once the run owns the record
        if isinstance(stale, Finding):
            return _refused(found, stale)
        return _owned(root, lambda: _owned_apply(root, found, product, resume))
    held = _held(root)
    if held is not None:
        return _refused(found, held)
    if found == RECORD_VERSION:
        return _current(root)
    return _checked(root, found, product).migration


# --- undoing --------------------------------------------------------------------------------------------


def _restore_plan(root: Path, entries: list[Entry], backup: Path) -> tuple[list[Entry], list[Finding]]:
    """The entries to restore (the file holds its migrated bytes), and a warning per file left as it is
    because it holds neither its migrated bytes nor its original ones."""
    restore: list[Entry] = []
    skipped: list[Finding] = []
    for entry in entries:
        path = f"{documents.HW}/{entry.path}"
        try:
            found = recovery.sha256((root / path).read_bytes())
        except OSError:
            found = ""
        if found == entry.migrated_sha256:
            restore.append(entry)
        elif found != entry.sha256:
            skipped.append(
                Finding(
                    code="migrate.undo_skipped",
                    severity=Severity.warning,
                    path=path,
                    message="the file holds neither the bytes the migration wrote nor the ones it replaced, "
                    "so something else changed it; it is left as it is",
                    action=f"Its original is {backup / documents.HW / entry.path}; copy it back by hand if "
                    "that is what you want.",
                )
            )
    restore.sort(key=lambda entry: entry.path != PurePosixPath(documents.PRODUCT.path).name)
    return restore, skipped


def _undo_failed(path: str, failure: BaseException, command: str) -> Finding:
    return error(
        "migrate.undo_failed",
        path,
        f"cannot restore it: {failure}",
        action=f"Stop every other process that writes under hw/, fix the cause, then run: {command}",
    )


def _restore(root: Path, backup: Path, entries: list[Entry]) -> Migration:
    restore, skipped = _restore_plan(root, entries, backup)
    written: list[str] = []
    command = recovery.undo_command(backup)
    stopped = Migration(MigrationStatus.failed, None, recovery=command, backup=backup)
    for entry in restore:  # hw/product.yaml first, so a stopped undo leaves a record a rerun of undo finishes
        path = f"{documents.HW}/{entry.path}"
        data = (backup / documents.HW / entry.path).read_bytes()
        try:
            recovery.write_durably(root / path, data, entry.migrated_sha256)
        except (recovery.ChangedMeanwhile, recovery.NotDurable, OSError) as failure:
            if isinstance(failure, recovery.NotDurable):
                written.append(path)
            refusal = _undo_failed(path, failure, command)
            return replace(stopped, findings=(*skipped, refusal), written=tuple(written))
        written.append(path)
    try:  # a stopped undo may have renamed a file it never synced the directory of
        recovery.sync_parents(root, [f"{documents.HW}/{entry.path}" for entry in entries])
    except OSError as failure:
        refusal = _not_durable(documents.HW, failure, f"Run: {command}")
        return replace(stopped, findings=(*skipped, refusal), written=tuple(written))
    return replace(stopped, status=MigrationStatus.undone, findings=tuple(skipped), written=tuple(written))


def _undo_links(root: Path, backup: Path, entries: list[Entry]) -> Finding | None:
    """A refusal for a symbolic link at hw/, a target, or a target's parent directory, or on the way to the
    backup."""
    link = recovery.backup_link(root, backup)
    if link is not None:
        return _linked(root, link, "recover a backup")
    for entry in entries:
        link = recovery.linked_part(root, f"{documents.HW}/{entry.path}")
        if link is not None:
            return _linked(root, link, "restore a file")
    return None


def _undo_lock_refusal(root: Path, backup: Path) -> Finding | None:
    """The refusal when the lock names another backup, or cannot be read. Checked before undo takes
    ownership, and again once it owns the record."""
    held = recovery.read_lock(root)
    if held is not None and (isinstance(held, str) or _own_backup(root, held) != backup):
        return recovery.locked(root, held)
    return None


def _owned_undo(root: Path, backup: Path) -> Migration:
    if not recovery.is_complete(backup):
        return _refused(
            None,
            error(
                "migrate.backup_incomplete",
                _backup_path(backup),
                f"the backup {backup} has no valid {recovery.COMPLETE} marker: the apply stopped before it "
                "wrote any file",
                action=f"Nothing needs undoing. If {recovery.LOCK_PATH} names this backup, run "
                f"{recovery.resume_command(root)} to migrate again; you may delete the backup by hand.",
            ),
        )
    entries = recovery.read_manifest(backup)
    if isinstance(entries, str):
        return _refused(None, _backup_unusable(backup, entries))
    links = _undo_links(root, backup, entries)
    if links is not None:
        return _refused(None, links)
    held = _undo_lock_refusal(root, backup)
    if held is not None:
        return _refused(None, held)
    try:
        if recovery.read_lock(root) is None:  # a stopped undo must keep a fresh apply from backing up a
            recovery.write_lock(root, backup)  # half-restored record
        recovery.sync_complete(backup)
    except OSError as failure:
        return _refused(None, _lock_failed(failure))
    result = _restore(root, backup, entries)
    if result.status != MigrationStatus.undone:
        return result
    cleared = recovery.clear_lock(root)
    return result if cleared is None else replace(result, findings=(*result.findings, cleared))


def undo(backup: Path) -> Migration:
    """Put back the files an apply changed, from its COMPLETE backup: each file that holds the bytes the
    migration wrote gets its preimage back. The lock goes once undo has finished."""
    spelled = backup.absolute()
    project = recovery.project_of(spelled)
    if project is None:
        return _refused(None, _backup_unusable(spelled, f"it is not under {recovery.BACKUPS}/"))
    root = project.resolve()
    backup = root / recovery.BACKUPS / spelled.name
    link = _hw_link(root)
    if link is not None:
        return _refused(None, link)
    link_on_way = recovery.backup_link(root, backup)
    if link_on_way is not None:
        return _refused(None, _linked(root, link_on_way, "recover a backup"))
    if not backup.is_dir():
        return _refused(None, _backup_unusable(backup, "it is not a directory"))
    stale = _undo_lock_refusal(root, backup)
    if stale is not None:
        return _refused(None, stale)
    return _owned(root, lambda: _owned_undo(root, backup))
