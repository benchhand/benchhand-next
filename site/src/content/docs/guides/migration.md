---
title: Migrate a prototype record
description: Bring a project record from the prototype, record version 2, to record version 3.
sidebar:
  order: 1
---

benchhand reads a record at `record_version: 3` only.
A record from the prototype is at record version 2, and `benchhand record migrate` brings it to version 3.
The [record migration contract](/reference/contracts/record-migration/) lists every change it makes, and the rule that makes it.

## When to migrate

Migrate when benchhand refuses a record with the finding `record.version_unsupported`.
benchhand gives that finding for any `record_version` in `hw/product.yaml` other than 3, or for none, and changes nothing.

The migration accepts two sources:

- prototype record version 2;
- record version 1, from an early prototype release, which has the same format.

A record already at version 3 needs nothing, and the migration reports it as `current`.
Any other version is refused, and nothing changes.

## Before you start

The migration edits files under `hw/` in place.
It keeps a second migration out, but no other writer.
**Stop every other process that writes under `hw/`**, such as an agent session or an editor, before you apply or undo a migration.

The migration doesn't use git.
It takes its own backup, and the state of a work tree, its index or its ignore rules doesn't matter.

Some records are refused whatever the rules would change:

- **A frozen record.** A record with `flow.frozen` is refused with `migrate.frozen_anchor`. The freeze's acceptance digest covers the bytes of the ledgers and the artifacts they cite, and the migration never recomputes it.
- **A `deprecated` decision without a replacement.** A decision with `status: deprecated` and no `superseded-by` is refused with `migrate.deprecated_status`. Set its status to `accepted`, `rejected` or `superseded` by hand, and run the migration again.
- **A layout the editor can't change in place.** The migration edits YAML at the positions of the values it changes, so it keeps comments, key order, quoting and line endings as written. It refuses a node it can't locate that way with `migrate.unsupported_layout`, such as a tagged mapping, an anchored node or a merge key (`<<`). The finding names the file, the place in it and the hand fix, which is usually to write the node out in full.
- **Symbolic links that leave the record.** `hw/` itself as a link, `hw/product.yaml` as a link, a link whose target is outside the project and a link to a directory are all refused before any file is read.

## Dry run

The migration is a dry run unless you pass `--apply`.
Give it the project's `hw/` directory:

```sh
benchhand record migrate hw
```

A dry run writes nothing under the project.
For each file it would change, it prints a header line with the path and the rules that apply, then a unified diff:

```text
# hw/product.yaml: record-version, human-approval
```

It then validates a copy of the migrated record in a temporary directory, and prints every finding, from the rules and from that validation.
Each finding gives its severity, its code, the path and its message, and a fix when there is one:

```text
error migrate.deprecated_status hw/decisions/DR-007-motor.md#/status: status deprecated has no record version 3 counterpart, and the file names no superseded-by
  fix: Set status to accepted, rejected, or superseded with superseded-by: [DR-###] naming its replacement, then migrate again.
```

The last line is the status and the count of files, such as `ready: 12 files`.
`ready` means the changes apply cleanly.
`refused` means a refusal, or a migrated record that doesn't validate, and the dry run lists every finding to fix.

The command exits 1 on a refusal or a failure, and 2 on bad arguments.

## Apply it

When the dry run is `ready`, apply it:

```sh
benchhand record migrate --apply hw
```

Apply plans the migration again, under a lock, and validates the result before it writes anything:

1. **It takes the record.** It creates `hw/.benchhand-migrate.owner`, which names the process, and the lock `hw/.benchhand-migrate.lock`. A second migration is refused with `migrate.locked`, naming the owner.
2. **It backs up the files it will change.** Their exact bytes go to `.benchhand/migrate-backups/<UTC time>/hw/`, beside a `manifest.json` of their hashes and a `COMPLETE` marker that is written last. Nothing in `hw/` changes until the backup is complete.
3. **It writes the changed files**, with `hw/product.yaml` last. Before each write, it checks that the file still holds the bytes the plan read. A file that changed in the meantime stops the apply with `migrate.changed_meanwhile`.
4. **It validates the record again**, and removes the lock and the owner file.

The output lists each file it changed and the findings, then the backup to undo from, and a count such as `applied: 12 of 12 files`:

```text
to undo: benchhand record migrate --undo <project>/.benchhand/migrate-backups/<UTC time>
```

## If an apply stops

An apply can stop after its backup is complete: through a write error, a file that changed under it, or a crash.
The status is then `failed`, and the lock stays.
A fresh apply is refused with `migrate.locked`, and its fix names the two ways on:

- **Finish it** with `benchhand record migrate --apply --resume hw`. The resume reuses the same backup, so its preimages are the original files. It checks that each file still to migrate holds its original bytes, and each file already written holds its migrated bytes, and refuses otherwise. The result is the same bytes a clean run writes.
- **Put it back** with `benchhand record migrate --undo <backup>`, using the backup the failure finding names.

If an apply stops before its backup is complete, it wrote nothing.
`--apply --resume` then marks the unfinished backup `ABANDONED`, makes a new backup beside it, and applies.

If the process that holds the record was killed, `migrate.locked` names it in the owner file.
Delete `hw/.benchhand-migrate.owner` by hand, then resume or undo.

## Undo a migration

```sh
benchhand record migrate --undo .benchhand/migrate-backups/<UTC time>
```

`--undo` takes the backup directory, and no `hw/` argument.
It puts back each file the backup lists, `hw/product.yaml` first, but only when the file still holds the bytes the migration wrote.
A file that holds neither those bytes nor its original ones was changed by something else: undo leaves it as it is and reports it with `migrate.undo_skipped`, naming its original in the backup.

Because apply changes only the files it backs up, undo gives back the record as it was.
A stopped undo is finished by running the same `--undo` again.
The status is `undone`.

Undo refuses a backup without a valid `COMPLETE` marker, which means that apply wrote nothing, and a backup whose files don't match its manifest.

## After the migration

Check what changed in how the project runs:

- **Every gate asks.** The migration writes no `hw/policy.yaml`, so every gate asks you for approval. A prototype setting that let some gates pass without you gives the finding `migrate.gates_now_ask`, and its fix says how to set [`policy.yaml`](/concepts/policy/policy-yaml/).
- **Gate decisions become design decisions.** A prototype decision that recorded a gate keeps its status as a design decision, with the finding `migrate.gate_decision`. It doesn't become a gate decision, because it has no approval channel, approver or quote to give.
- **Migrated approvals are confirmed at the next human gate.** A prototype approval doesn't list the items it covers, so a migrated decision has no [approval scope](/concepts/process/approvals/). It doesn't count as covering the whole stage, and the next human gate confirms it.
- **Sealed history keeps its bytes.** `hw/versions/`, `hw/checks/` and `hw/releases/` are never rewritten, because a seal or a digest states their bytes. benchhand reads a built version still at version 2 by upgrading it in memory, and writes nothing back. A digest recorded for that version stays valid.

Every backup stays under `.benchhand/migrate-backups/` until you delete it by hand.
Commit the migrated record when you are satisfied with it.
