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

The prototype read BOM numbers with `int()` and `float()`, which accept surrounding white space. The record v3 reader stays strict, so `bom-number-spacing` strips that white space from those cells only. It reports one info finding per file, `migrate.csv_number_spacing`.

## How the service edits

- **YAML** is edited in place at the character positions that PyYAML's composer reports. It is not dumped again, so comments, key order, quoting, flow or block style and line endings stay as written. ruamel.yaml round-trip was not used: it adds a dependency, and it re-flows the long flow mappings the prototype writes.
  - Flow mappings are edited too: flow-style decision front matter, a trailing comma, and several entries removed side by side. A removed entry takes its own separator with it. The comment after a kept entry stays.
  - An edit that would change an anchored node, a node reached through an alias, or a mapping with a merge key (`<<`) is refused with `migrate.unsupported_layout`. The finding names the file, the pointer and the hand fix: write the node out in full.
- **CSV** edits rename the header cells, or strip the white space around a number. Every other byte stays, the line endings included.
- **Decision files** have their front matter edited in place the same way. The Markdown body is not touched.
- A file that no rule changes keeps its bytes.
- **Sealed history** is never rewritten. `hw/versions/**`, `hw/checks/**` and `hw/releases/**` stay byte-identical, even where they hold v2 forms, because a digest or a seal states their bytes.
- OS and tool junk is never read or rewritten, and it doesn't count as an uncommitted change. The junk set is `.DS_Store`, `._*`, `Thumbs.db`, `desktop.ini`, `__pycache__`, and editor swap and backup files. It stays in place, and a backup leaves it out. This rule is the reader's (`record/ignore.py`). The project ignore file of bead `benchhand-3fc` will replace it.
- **The scan** of `hw/` stops at the first directory it cannot list (`migrate.scan_failed`), so no subtree is silently left out. A symbolic link under `hw/` whose target resolves outside the project refuses the record (`migrate.symlink_outside`), in the dry run and in apply. A link inside the project is read, but a rule never changes a link (`migrate.unsupported_layout`).

## Dry run and apply

**Dry run** is the default. It writes nothing under the project. It returns each file change (the rules applied, and a unified diff), the rules' findings, and the validation findings of the migrated record. It validates a real copy of the migrated record, made in a new temporary directory without sealed history, and checks that the copy holds every file it read (`migrate.scan_incomplete`).

**Apply** writes in place:

1. **A recovery point comes first.** One of these must hold:
   - `hw/` is inside a git work tree, with no tracked changes and no untracked files (`git status --porcelain -- hw`), and git tracks every file the migration changes. The recovery command is then `git -C <project> restore -- hw`.
   - The user passes `--backup`. The service first writes a complete copy of `hw/` to `<project>/.benchhand/backups/<UTC time>/hw`, syncs it to disk, reads each file back and reports the path (`migrate.backup_written`). The recovery command is then `cp -Rp <backup>/. <project>/hw/`.

   With neither, apply is refused with `migrate.no_recovery_point`, which names both fixes.
2. **An exclusive lock**, `hw/.benchhand-migrate.lock`, is created with `O_CREAT|O_EXCL` and removed when apply ends. If the lock exists, apply is refused with `migrate.locked`, which says to delete a lock that a crash left behind. A lock that cannot be removed is reported (`migrate.cleanup_failed`).
3. Under the lock, the service plans again and validates the migrated copy. It also checks that no file under `hw/` was added or removed since the plan (`migrate.changed_meanwhile`).
4. **It writes only the changed files**, with `hw/product.yaml` last. Before writing each file, it hashes it again and refuses if the bytes differ from the ones the plan read (`migrate.changed_meanwhile`). Each file goes to a temp file in the same directory, which is synced and renamed over the original, and then the directory is synced. A write error stops apply (`migrate.write_failed`).
5. It reads and validates the record again (`migrate.invalid_result` if that fails).

Every failure finding names the recovery command. Until `hw/product.yaml` says `record_version: 3`, a rerun migrates the files that are left. Every rule changes nothing on its own output, so a rerun after a crash finishes a partly migrated tree with the bytes a clean run writes. A test covers this by stopping after several numbers of files. A partly migrated tree has tracked changes, so the rerun needs `--backup`, or `git restore hw` first.

The lock keeps out a second migration only. **Stop every other process that writes under `hw/` before applying.** The checks in steps 3 and 4 catch a change made before a file is written, not one made during the rename.

**Frozen records.** In the prototype, `flow.frozen.evidence_sha256` is a digest of the bytes of `hw/verification.csv`, the evidence ledger and the finding dispositions (prototype `evidence.py` `LEDGER_FILES`). If `flow.frozen` is present and a rule would change one of those files, the migration is refused with `migrate.frozen_anchor`. The digest is never recomputed. The freeze can't be re-anchored until the Phase 2 flow engine can record an engineering change for it. No real project was frozen on 2026-11-25.

A `record_version: 3` record is a no-op (`migrate.current`). Any version other than 1, 2 or 3 is refused with `record.version_unsupported`, and nothing changes. The service and the CLI make the project root absolute.

The CLI is `benchhand record migrate [--apply [--backup]] HW`. It exits 1 when the result is refused or failed.

## Decided defaults

The supervisor settled the three open items as conservative, reversible defaults (2026-11-25).

1. **`flow.profile.human_approval`.** Migration writes no `hw/policy.yaml`, so every gate asks, which is the v3 default. It removes the key and its `flow.profile.asked` entry. A value other than `all` let a passing full check approve the middle gates without the user. For such a value, the info finding `migrate.gates_now_ask` says those gates now ask, and its action says how to set `hw/policy.yaml`.
2. **A MADR decision with `gate: {from, to}`** stays `kind: design` with its mapped status, and the `gate` key is removed. It does not become `kind: gate`, because a migrated record has no approval channel, approver or quote to give it. Each such file gets the info finding `migrate.gate_decision`.
3. **`status: deprecated`.** With `superseded-by`, it becomes `superseded` with `superseded_by`. Without it, the migration always refuses that file with `migrate.deprecated_status`. The finding asks the user to pick `accepted`, `rejected` or `superseded`, and the dry run lists it. The body is not searched for words such as "never adopted", because such a phrase can describe another option. No real record has a deprecated decision: 0 in `benchhand-test-project`, `benchhand-test-src`, the reference examples and the prototype at 412b5d9.
