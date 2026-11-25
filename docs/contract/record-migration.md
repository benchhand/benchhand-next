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

The rules are a table, `RULES` in `packages/benchhand-core/src/benchhand_core/record/migrate/rules.py`. Each row is one prototype change. Each row runs on the files its glob names, in table order. Its fixture is `packages/benchhand-core/tests/record/migrate_fixtures/<id>/`: a `before/` tree, an `after/` tree, and `findings.txt` when the rule reports. A prototype change that lands after `release.toml` `reference_commit` is ported by adding one row and one fixture (ADR-0015).

The prototype at `reference_commit` 412b5d9 reads `record_version: 2` only and has no migrate script: `skills/cad-record/scripts/migrate.py` was removed in a41f2955 (#65). The source column names the prototype commit that introduced the form each row rewrites.

| Id | Document | Changes | Source |
|---|---|---|---|
| `record-version` | `hw/product.yaml` | `record_version` 2 or 1 becomes 3 | b0bce410 |
| `human-approval` | `hw/product.yaml` | removes `flow.profile.human_approval` and its `asked` entry | 1903d0a0 (#307) |
| `heat-set-keys` | `hw/interfaces.yaml` | `hole_d`, `hole_tol`, `depth_min` in `interfaces[].limits.heat_set[]` | 164ab11c, b0bce410 |
| `bom-columns` | `hw/bom.csv` | `specification_ref`, `specification_rev` header cells | 164ab11c |
| `verification-column` | `hw/verification.csv` | `requirement_id` header cell | 164ab11c |
| `evidence-configuration-rev` | `hw/manufacturing/evidence.yaml` | `entries[].configuration.part_rev` | b0bce410 |
| `waiver-valid-until` | `evidence.yaml`, `findings.yaml` | a waiver's `expires` | b0bce410 |
| `decision-gate` | `hw/decisions/DR-*.md` | removes `gate: {from, to}` and reports it | 6575b883 (#318) |
| `decision-deprecated` | `hw/decisions/DR-*.md` | `status: deprecated` without `superseded-by` | 1a7efb7e (#110) |
| `decision-front-matter` | `hw/decisions/DR-*.md` | adds `id`, `kind: design`, `title`; renames `decision-makers`, `superseded-by`; status `superseded` | 1a7efb7e (#110) |

How the service edits and writes:

- **YAML** is edited in place at the character positions that PyYAML's composer reports. It is not dumped again, so comments, key order, quoting, flow or block style and line endings stay as written. ruamel.yaml round-trip was not used: it adds a dependency, and it re-flows the long flow mappings the prototype writes.
- **CSV** edits rename the header cells only. Every other byte stays, the line endings included.
- **Decision files** have their front matter edited in place the same way. The Markdown body is not touched.
- A file that no rule changes keeps its bytes.
- OS and tool junk is never read, rewritten or counted: `.DS_Store`, `._*`, `Thumbs.db`, `desktop.ini`, `__pycache__`, editor swap and backup files. This rule is the reader's (`record/ignore.py`). The project ignore file of bead `benchhand-3fc` will replace it.
- **Dry run** is the default. It writes nothing under the project. It returns each file change (the rules applied, and a unified diff), the rules' findings, and the validation findings of the migrated record. It validates a temporary stage of links.
- **Apply** builds the migrated `hw/` beside the original. Unchanged files are hard-linked, and each changed file is written to a temp file and renamed into place. The service validates the new tree, swaps it in with two renames, and reads it again. If any step fails or the migrated record has an error, the original `hw/` goes back and the tree stays byte-identical. A file that changed after the plan read it refuses the apply (`migrate.changed_meanwhile`).
- A `record_version: 3` record is a no-op (`migrate.current`). Any version other than 1, 2 or 3 is refused with `record.version_unsupported`, and nothing changes.

The CLI is `benchhand record migrate [--apply] HW`.

## Decided defaults

The supervisor settled the three open items as conservative, reversible defaults (2026-11-25).

1. **`flow.profile.human_approval`.** Migration writes no `hw/policy.yaml`, so every gate asks, which is the v3 default. It removes the key and its `flow.profile.asked` entry. A value other than `all` let a passing full check approve the middle gates without the user. For such a value, the info finding `migrate.gates_now_ask` says those gates now ask, and its action says how to set `hw/policy.yaml`.
2. **A MADR decision with `gate: {from, to}`** stays `kind: design` with its mapped status, and the `gate` key is removed. It does not become `kind: gate`, because a migrated record has no approval channel, approver or quote to give it. Each such file gets the info finding `migrate.gate_decision`.
3. **`status: deprecated`.** With `superseded-by`, it becomes `superseded` with `superseded_by`. Without it, it becomes `rejected` only if the body says the decision was never adopted (`migrate.deprecated_rejected`, info). Otherwise the migration refuses that file with `migrate.deprecated_status`. The finding asks the user to pick `accepted`, `rejected` or `superseded`, and the dry run lists it. No real record has one: 0 in `benchhand-test-project`, `benchhand-test-src`, the reference examples and the prototype at 412b5d9.
