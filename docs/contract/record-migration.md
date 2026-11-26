# Record migration: prototype record version 2 to record version 3

Status: the list of changes the migrate service applies. Schemas: [`contracts/record/`](../../contracts/record/). Decisions: [ADR-0012](../adr/0012-python-host-rewrite.md), [ADR-0017](../adr/0017-contracts.md).

The record service reads `record_version: 3` only. It refuses any other value, or a missing one, with the finding `record.version_unsupported`, and it changes nothing. The migrate service, `benchhand_core.record.migrate`, accepts two sources: prototype record version 2, and the record version 1 of prototype PR #319, which is the same format. This page lists every difference between those sources and record version 3, and the rule that applies each one ([Migrate rules](#migrate-rules)).

## Renames

| Document | Prototype (v2) | Record v3 |
|---|---|---|
| `hw/product.yaml` | `record_version: 2` | `record_version: 3` |
| `hw/interfaces.yaml`, each `limits.heat_set[]` entry | `hole_d` | `hole_diameter_mm` |
| | `hole_tol` | `hole_deviation_mm` |
| | `depth_min` | `min_depth_mm` |
| `hw/bom.csv` columns | `specification_ref` | `specification_reference` |
| | `specification_rev` | `specification_revision` |
| `hw/verification.csv` columns | `requirement_id` | `requirement` |
| `hw/manufacturing/evidence.yaml`, `entries[].configuration` | `part_rev` | `rev` |
| Every waiver (`evidence.yaml` entries, `findings.yaml` dispositions) | `expires` | `valid_until` |

## Removals

| Document | Removed | Notes |
|---|---|---|
| `hw/product.yaml` | `flow.profile.human_approval`, and its key in `flow.profile.asked` | `hw/policy.yaml` now sets how each gate asks. A migrated record has no policy file, so every gate asks ([Decided defaults](#decided-defaults)). |

## New documents

- **`hw/policy.yaml`** (`policy.schema.json`): `{policy_version: 1, default, gates}`. `default` is `ask`, `chat` or `auto`, and is `ask` when left out. `gates` maps a gate id (`^[a-z][a-z0-9_]*$`) to `{mode, decision}`. Any mode other than `ask` cites the decision that records it, and so does a `default` other than `ask`. A record without the file asks at every gate. The prototype has no counterpart, so migration writes no file.

## Decision record format

Prototype decisions are MADR 4.0.0 files. The front matter holds `status` (`proposed`, `accepted`, `rejected` or `deprecated`), `date`, `superseded-by`, an optional `gate: {from, to}`, `decision-makers`, `consulted` and `informed`. The body has required MADR sections. Record v3 keeps the file name `hw/decisions/DR-###-<slug>.md` and changes the rest (`decision.schema.json`):

- The front matter carries `id` (matching the file name), `title` (taken from the body's `# ` heading, which the body keeps), `date` and a discriminated `kind`.
- `kind: gate` records a flow gate: `status` is `approved`, `provisional` or `void`, plus `gate`, `stage` and optionally `version`, `evidence[]`, `supersedes[]` and `approval{channel, by, quote}`. `channel` is `app`, `form`, `chat` or `auto`. An approved gate carries `approval` unless the policy mode of its gate is `auto`. Validation checks this against `hw/policy.yaml`.
- `kind: design` records a design decision: `status` is `proposed`, `accepted`, `rejected` or `superseded`. `superseded` is now stored, and it names its replacements in `superseded_by` (renamed from `superseded-by`). `decision-makers` becomes `decision_makers`. `consulted` and `informed` keep their names.
- The Markdown body stays as written. No section is required.
- A decision cited as the approval of a freeze (`flow.frozen.decision`), an engineering change (`flow.change.decision`) or the flow profile (`flow.profile.decision`) must be a gate with status `approved` or a design decision with status `accepted`.

Mapping: a MADR record with `superseded-by` becomes `kind: design, status: superseded`. Any other record becomes `kind: design` with the same status. A record with `gate: {from, to}` and a record with `status: deprecated` follow the [decided defaults](#decided-defaults). Name lists left empty (`consulted: []`) are removed, because record v3 states each list with at least one name.

## Schema files

- The prototype's `manufacturing.schema.json` (the shared definitions) is now `common.schema.json`. The definitions that the product, drawing and assembly schemas each declared for themselves (`stage`, `decision`, `sha256`, `version`, `process` (now `primary_process`), `pn`, `semantic_id`, `occurrence_ref` and `vector`) live there once. `common.schema.json` adds `revision`, `project_path` and `gate_id`. These schema changes don't change any record document.
- Every schema's `$id` is `https://benchhand.github.io/benchhand/contracts/record/<name>.schema.json`, and each carries an `x-version`.
- Findings share one contract, `contracts/common/finding.schema.json`: `code`, `severity` (`error`, `warning` or `info`), `path`, `message`, and optionally `pointer`, `action` and `subject`.

## Migrate rules

The rules are a table, `RULES` in `packages/benchhand-core/src/benchhand_core/record/migrate/rules.py`. Each row is one prototype change. Each row runs on the files its glob names, in table order. Its fixture is `packages/benchhand-core/tests/record/migrate_fixtures/<id>/`: a `before/` tree, an `after/` tree, and `findings.txt` when the rule reports. A prototype change that lands after `release.toml` `reference_commit` is ported by adding one row and one fixture (ADR-0015). A rule changes nothing on its own output, and a test checks this for every row.

The prototype at `reference_commit` 412b5d9 reads `record_version: 2` only and has no migrate script: `skills/cad-record/scripts/migrate.py` was removed in a41f2955 (#65). The source column names the prototype commit that introduced the form each row rewrites.

| Id | Document | Changes | Source |
|---|---|---|---|
| `record-version` | `hw/product.yaml` | `record_version` 2 or 1 becomes 3 | b0bce410 |
| `human-approval` | `hw/product.yaml` | removes `flow.profile.human_approval` and its `asked` entry | 1903d0a0 (#307) |
| `heat-set-keys` | `hw/interfaces.yaml` | `hole_d`, `hole_tol`, `depth_min` in `interfaces[].limits.heat_set[]` | 164ab11c, b0bce410 |
| `bom-columns` | `hw/bom.csv` | `specification_ref`, `specification_rev` header cells | 164ab11c |
| `bom-number-spacing` | `hw/bom.csv` | strips the white space around a number in `level`, `qty` or `mass` | 164ab11c (`validate.py`) |
| `verification-column` | `hw/verification.csv` | `requirement_id` header cell | 164ab11c |
| `evidence-configuration-rev` | `hw/manufacturing/evidence.yaml` | `entries[].configuration.part_rev` | b0bce410 |
| `waiver-valid-until` | `evidence.yaml`, `findings.yaml` | a waiver's `expires` | b0bce410 |
| `decision-gate` | `hw/decisions/DR-*.md` | removes `gate: {from, to}` and reports it | 6575b883 (#318) |
| `decision-deprecated` | `hw/decisions/DR-*.md` | refuses `status: deprecated` without `superseded-by` | 1a7efb7e (#110) |
| `decision-front-matter` | `hw/decisions/DR-*.md` | adds `id`, `kind: design`, `title`; renames `decision-makers`, `superseded-by`; status `superseded` | 1a7efb7e (#110) |

The prototype read BOM numbers with `int()` and `float()`, which accept surrounding white space. The record v3 reader stays strict, so `bom-number-spacing` strips the ASCII white space (space, tab, CR, LF, form feed, vertical tab) around a number in those cells, and nothing else. It reports one info finding per file, `migrate.csv_number_spacing`. `int()` and `float()` also read spellings record v3 doesn't, such as non-ASCII digits (`０`), digit grouping (`1_000`), `inf`, and padding with a no-break space. The migration doesn't rewrite these. It refuses the file with `migrate.csv_number_unreadable`, one finding per cell, naming the file, the row, the column and the value.

## How the service edits

- **YAML** is edited in place at the character positions that PyYAML's composer reports. It is not dumped again, so comments, key order, quoting, flow or block style and line endings stay as written. ruamel.yaml round-trip was not used: it adds a dependency, and it re-flows the long flow mappings the prototype writes.
  - Flow mappings are edited too: flow-style decision front matter, a trailing comma, and several entries removed side by side. A removed entry takes its own separator with it. The comment after a kept entry stays.
  - The editor changes only a node it can locate by its own delimiter tokens: a plain or quoted scalar, or a flow mapping whose marks are its braces. It refuses anything else with `migrate.unsupported_layout`, naming the file, the pointer and the hand fix.
  - The refused layouts include a tagged flow mapping (`!!map {…}`), a tagged or anchored key, an anchor inside a removed value, and a key the mapping holds only through a merge key (`<<`).
  - An edit that would change an anchored node, a node reached through an alias, or a mapping with a merge key is refused the same way. Its fix is to write the node out in full. Each case has a fixture in `packages/benchhand-core/tests/record/migrate_layout_fixtures/`.
- **CSV** edits rename the header cells, or strip the ASCII white space around a number. Every other byte stays, the line endings included.
- **Decision files** have their front matter edited in place the same way. The Markdown body is not touched.
- A file that no rule changes keeps its bytes.
- **Sealed history** is never rewritten. `hw/versions/**`, `hw/checks/**` and `hw/releases/**` stay byte-identical, even where they hold v2 forms, because a digest or a seal states their bytes.
- **Sealed history is read through an in-memory upgrade.** The evidence reader (`benchhand_core.record.evidence.reader`) checks the seal on the bytes on disk first. It then upgrades what it reads of a built version that is still at record version 2 (or 1), and writes nothing back:
  - a snapshot document under `hw/versions/<V>/record/` runs through `RULES` (`migrate/sealed.py`, `rules.rewrite`), as `hw/<document>`, when its `product.yaml` is at a source version;
  - a packet, `hw/checks/<V>/<S>/result.json`, differs from its v3 form in `record_version` only, so it takes that one change, and then has to meet the v3 `manufacturing-check-result` contract;
  - a packet that still breaks the contract is the finding `packet.unupgradable`, and it counts as nothing, like a `packet.invalid` one. A snapshot that can't be upgraded leaves the build's staleness not computed;
  - the seals and the acceptance inventory keep covering the bytes on disk: the seal check, the packet's `manifest.json` and so the `evidence_sha256` of the inventory. A digest recorded for a v2 built version stays valid. `expected_sha256` hashes the expected obligations, not files, so it is the same for a v2 built version and its v3 twin.
- OS and tool junk is never read, rewritten or backed up. The junk set is `.DS_Store`, `._*`, `Thumbs.db`, `desktop.ini`, `__pycache__`, and editor swap and backup files. This rule is the reader's (`record/ignore.py`). The project ignore file of bead `benchhand-3fc` will replace it.
- **The scan** of `hw/` stops at the first directory it cannot list (`migrate.scan_failed`), so no subtree is silently left out. The scan lists names and link targets only. It records which files exist, not a snapshot of their contents. These are refused, in the dry run and in apply, before any file is read:
  - `hw/` itself being a symbolic link (`migrate.symlink_hw`), checked before anything is read or locked;
  - `hw/product.yaml` being a symbolic link (`migrate.unsupported_layout`), checked with `lstat` before its record version is read;
  - a symbolic link under `hw/` whose target resolves outside the project (`migrate.symlink_outside`);
  - a symbolic link to a directory (`migrate.unsupported_layout`), so that no link nested under one goes unchecked.

  A link to a file inside the project is read, but a rule never changes a link (`migrate.unsupported_layout`).

## Dry run and apply

**Dry run** is the default. It writes nothing under the project. It returns each file change (the rules applied, and a unified diff), the rules' findings, and the validation findings of the migrated record. It validates a real copy of the migrated record, made in a new temporary directory without sealed history, and checks that the copy holds every file it read (`migrate.scan_incomplete`).

**Apply** writes in place. Git plays no part: the state of a work tree, its index or its ignore rules don't matter.

1. **Two files keep migrations apart.** Apply, `--resume` and `--undo` each first check the lock, then take ownership of the record by creating `hw/.benchhand-migrate.owner` with `O_CREAT|O_EXCL`. That file names the process: its pid, its host and its start time. It is synced, with `hw/`. A second process is refused with `migrate.locked`, naming the owner; if that process was killed, delete the owner file by hand. Under ownership, the service reads the lock again. The lock, `hw/.benchhand-migrate.lock`, is the recovery state: it names the backup the apply belongs to, and it is written atomically (a synced temp file, renamed, then `hw/` synced). If the lock exists, a fresh apply is refused with `migrate.locked`, whose action names `--resume` and `--undo <backup>`. At the end the service removes the lock (when it is done with it) and then the owner file, and syncs `hw/` after each.
2. Under the lock, the service plans again and validates the migrated copy.
3. **A preimage backup.** Before writing anything, apply copies the exact current bytes of every file it will change to `<project>/.benchhand/migrate-backups/<UTC time>/hw/<path>`. It backs up those target files only, not the whole of `hw/`. Beside them, `manifest.json` lists each `hw/`-relative path with the sha256 of its preimage and of its migrated bytes. Each file, the manifest and their directories are synced. Each file is read back and compared with the manifest. Then a `COMPLETE` marker is published last and atomically: a temp file that holds the manifest's sha256 is synced, renamed to `COMPLETE`, and the backup directory is synced. A backup counts as `COMPLETE` only when its marker holds that hash. A symbolic link at `.benchhand/`, at `.benchhand/migrate-backups/` or at the backup directory is refused before the service creates or reads anything there. A backup that cannot be written is refused with `migrate.backup_failed`, and nothing in `hw/` changes. The result reports the path (`migrate.backup_written`).
4. The service checks that no file under `hw/` was added or removed since the plan (`migrate.changed_meanwhile`).
5. **It writes only the changed files**, with `hw/product.yaml` last. Each file goes to a temp file in the same directory, which is synced. Then the target is hashed again, and the write is refused if its bytes differ from the ones the plan read (`migrate.changed_meanwhile`). Only then is the temp file renamed over the target and the directory synced. If the directory sync fails after the rename, the file is listed in `written`, and `migrate.not_durable` says the change may not survive a power loss. Any other write error stops apply (`migrate.write_failed`).
6. It syncs the directory of every target, including the files already in their migrated state, so that a rename a stopped run made before its directory sync is durable. It validates the record again (`migrate.invalid_result` if that fails), and removes the lock.

**Undo** is `benchhand record migrate --undo <backup>`, and every failure finding after step 3 names it.
- It refuses a backup without a valid `COMPLETE` (`migrate.backup_incomplete`: that apply wrote nothing). It also refuses a backup whose files don't match the manifest (`migrate.backup_unusable`), and a lock that names another backup (`migrate.locked`).
- Before it writes, it refuses a symbolic link at `hw/` (`migrate.symlink_hw`), at any target, at any directory between `hw/` and a target, or on the way to the backup (`migrate.unsupported_layout`). It syncs the `COMPLETE` marker and the backup directory again. If no lock is held, it points the lock at the backup, so that a stopped undo keeps a fresh apply from backing up a half-restored record.
- It puts each preimage back with the same synced temp file and rename, `hw/product.yaml` first. It restores only the files the manifest lists, and only when a file still holds the bytes the migration wrote. Then it syncs the directory of every target and removes the lock.
- A file that holds neither those bytes nor its original ones was changed by something else. Undo leaves it as it is and reports it with `migrate.undo_skipped`, naming its preimage in the backup.
- Because apply changes only the files it backs up, undo gives back the record as it was, junk included. A second undo has nothing left to restore. A stopped undo is finished by running the same `--undo` again.

**A stopped apply.** If apply stops after its backup is `COMPLETE`, through a write error, a changed file or a crash, the lock stays. The next run is refused with `migrate.locked` until it chooses one of two ways:
- `--apply --resume` reuses that backup. Before it writes, it syncs the `COMPLETE` marker and the backup directory again. Its preimages are the originals, so no second backup of a partly migrated tree is made. Each file still to migrate must hold its preimage, and each file already written must hold its migrated bytes; otherwise the resume is refused (`migrate.changed_meanwhile`). Every rule changes nothing on its own output, so the resumed apply writes the bytes a clean run writes.
- `--undo <backup>` puts the files back.

If apply stops before its backup is `COMPLETE`, it wrote nothing. A lock left by a killed process then says so. `--resume` leaves the unfinished backup where it is, marks it with an atomic, synced `ABANDONED` file (`migrate.backup_abandoned`), and makes a new backup beside it. Every backup stays until you delete it by hand under `.benchhand/migrate-backups/`. Tests stop an apply after several numbers of files, while it publishes `COMPLETE`, after a rename but before its directory sync, and after the last write, and they stop an undo. After each stop they check that `--resume` gives the bytes of a clean run and that `--undo` gives back the original. Another test runs two resumes at once, and only one of them proceeds.

A `record_version: 3` record is a no-op (`migrate.current`), but only once no migration lock is held and the record validates. A lock that a stopped apply left after writing `hw/product.yaml` refuses the record with `migrate.locked`, so `current` is never reported for a run that didn't finish. Any version other than 1, 2 or 3 is refused with `record.version_unsupported`, and nothing changes. The service and the CLI make the project root absolute.

The owner file and the lock keep out a second migration only. **Stop every other process that writes under `hw/` before applying or undoing.** The re-hash in step 5 covers the time up to the hash; a write between the hash and the rename is still possible.

**Frozen records.** Any prototype record with `flow.frozen` is refused with `migrate.frozen_anchor`, whatever the rules would change. Its acceptance digest, `flow.frozen.evidence_sha256`, covers the bytes of the ledgers and of the artifacts they cite (prototype `evidence.py`). The digest is never recomputed. The freeze can't be re-anchored until the Phase 2 flow engine can record an engineering change for it. No real project was frozen on 2026-11-25.

The CLI is `benchhand record migrate [--apply [--resume]] HW`, and `benchhand record migrate --undo BACKUP`. It exits 1 on a refusal or a failure, and 2 on bad arguments.

## Decided defaults

The supervisor settled the three open items as conservative, reversible defaults (2026-11-25).

1. **`flow.profile.human_approval`.** Migration writes no `hw/policy.yaml`, so every gate asks, which is the v3 default. It removes the key and its `flow.profile.asked` entry. A value other than `all` let a passing full check approve the middle gates without the user. For such a value, the info finding `migrate.gates_now_ask` says those gates now ask, and its action says how to set `hw/policy.yaml`.
2. **A MADR decision with `gate: {from, to}`** stays `kind: design` with its mapped status, and the `gate` key is removed. It does not become `kind: gate`, because a migrated record has no approval channel, approver or quote to give it. Each such file gets the info finding `migrate.gate_decision`.
3. **`status: deprecated`.** With `superseded-by`, it becomes `superseded` with `superseded_by`. Without it, the migration always refuses that file with `migrate.deprecated_status`. The finding asks the user to pick `accepted`, `rejected` or `superseded`, and the dry run lists it. The body is not searched for words such as "never adopted", because such a phrase can describe another option. No real record has a deprecated decision: 0 in `benchhand-test-project`, `benchhand-test-src`, the reference examples and the prototype at 412b5d9.
