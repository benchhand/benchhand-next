# Record migration: prototype record version 2 to record version 3

Status: the list of changes the migrate service applies. Schemas: [`contracts/record/`](../../contracts/record/). Decisions: [ADR-0012](../adr/0012-python-host-rewrite.md), [ADR-0017](../adr/0017-contracts.md).

The record service reads `record_version: 3` only. It refuses any other value, or a missing one, with the finding `record.version_unsupported`, and it changes nothing. The migrate service (a later lane) accepts two sources: prototype record version 2, and the record version 1 of prototype PR #319, which is the same format. This page lists every difference between those sources and record version 3. The migrate service applies them, and the test fixture converter in `packages/benchhand-core/tests/record/prototype_v2.py` applies the ones the reference examples need.

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
| `hw/product.yaml` | `flow.profile.human_approval`, and its key in `flow.profile.asked` | `hw/policy.yaml` now sets how each gate asks. How `all` and `key` map to gate modes is an open item for the migrate lane. |

## New documents

- **`hw/policy.yaml`** (`policy.schema.json`): `{policy_version: 1, default, gates}`. `default` is `ask`, `chat` or `auto`, and is `ask` when left out. `gates` maps a gate id (`^[a-z][a-z0-9_]*$`) to `{mode, decision}`. Any mode other than `ask` cites the decision that records it, and so does a `default` other than `ask`. A record without the file asks at every gate. The prototype has no counterpart, so migration writes no file.

## Decision record format

Prototype decisions are MADR 4.0.0 files. The front matter holds `status` (`proposed`, `accepted`, `rejected` or `deprecated`), `date`, `superseded-by`, an optional `gate: {from, to}`, `decision-makers`, `consulted` and `informed`. The body has required MADR sections. Record v3 keeps the file name `hw/decisions/DR-###-<slug>.md` and changes the rest (`decision.schema.json`):

- The front matter carries `id` (matching the file name), `title` (taken from the body's `# ` heading, which the body keeps), `date` and a discriminated `kind`.
- `kind: gate` records a flow gate: `status` is `approved`, `provisional` or `void`, plus `gate`, `stage` and optionally `version`, `evidence[]`, `supersedes[]` and `approval{channel, by, quote}`. `channel` is `app`, `form`, `chat` or `auto`. An approved gate carries `approval` unless the policy mode of its gate is `auto`. Validation checks this against `hw/policy.yaml`.
- `kind: design` records a design decision: `status` is `proposed`, `accepted`, `rejected` or `superseded`. `superseded` is now stored, and it names its replacements in `superseded_by` (renamed from `superseded-by`). `decision-makers` becomes `decision_makers`. `consulted` and `informed` keep their names.
- The Markdown body stays as written. No section is required.
- A decision cited as the approval of a freeze (`flow.frozen.decision`), an engineering change (`flow.change.decision`) or the flow profile (`flow.profile.decision`) must be a gate with status `approved` or a design decision with status `accepted`.

Mapping, for the migrate lane: a MADR record with `superseded-by` becomes `kind: design, status: superseded`. Any other record becomes `kind: design` with the same status. Two cases are open items: a MADR record with `gate: {from, to}`, which may become `kind: gate`, and `status: deprecated`, which has no v3 status.

## Schema files

- The prototype's `manufacturing.schema.json` (the shared definitions) is now `common.schema.json`. The definitions that the product, drawing and assembly schemas each declared for themselves (`stage`, `decision`, `sha256`, `version`, `process` (now `primary_process`), `pn`, `semantic_id`, `occurrence_ref` and `vector`) live there once. `common.schema.json` adds `revision`, `project_path` and `gate_id`. These schema changes don't change any record document.
- Every schema's `$id` is `https://benchhand.github.io/benchhand/contracts/record/<name>.schema.json`, and each carries an `x-version`.
- Findings share one contract, `contracts/common/finding.schema.json`: `code`, `severity` (`error`, `warning` or `info`), `path`, `message`, and optionally `pointer`, `action` and `subject`.
