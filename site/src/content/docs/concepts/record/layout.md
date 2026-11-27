---
title: The record layout
description: The files under hw/ and what each one holds.
sidebar:
  order: 1
---

A project's design record is the directory `hw/`.
It is plain YAML, CSV and Markdown, kept beside the project's other files, and every document in it has a contract.
Each file below links to the reference page that lists its fields.

## The hw/ directory

### The product and its requirements

| File | What it holds |
|---|---|
| [`hw/product.yaml`](/reference/contracts/record/product/) | The product's identity, units, drawing regime and general tolerance, its use case, and its design, manufacturing, storage and drawing defaults. Its `flow` block holds the current stage, the frozen configuration, an open engineering change, and your project-start answers. |
| [`hw/requirements.yaml`](/reference/contracts/record/requirements/) | The requirements, preferences, assumptions and open questions, each in its own list. |
| [`hw/policy.yaml`](/reference/contracts/record/policy/) | How each gate asks for approval, and the rigor level. |
| [`hw/decisions/DR-###-<slug>.md`](/reference/contracts/record/decision/) | One decision record per file: a gate decision or a design decision. |

### The design

| File | What it holds |
|---|---|
| [`hw/parts/<PN>/part.yaml`](/reference/contracts/record/part/) | One part: its identity and revision, material, process and finish, whether it is made or bought, its drawing, how it is made, and its design intent. |
| `hw/parts/<PN>/model.py` | The part's geometry, a CadQuery or build123d script. |
| `hw/parts/<PN>/sources/` | Frozen supporting files for the part, such as a supplier datasheet. |
| [`hw/interfaces.yaml`](/reference/contracts/record/interfaces/) | Each interface between two parts, with its type and description. |
| [`hw/assembly.yaml`](/reference/contracts/record/assembly/) | The subassemblies, the occurrences of each part, the joints and assembly operations, and the assembly drawing. |
| [`hw/bom.csv`](/reference/contracts/record/bom-row/) | The engineering bill of materials, with optional procurement columns. |
| [`hw/verification.csv`](/reference/contracts/record/verification-row/) | The verification matrix. |
| `hw/analysis/cases/<ID>` | An analysis case, such as a tolerance stack that an interface names. |
| `hw/motion/cases/<ID>` | A motion scenario that an interface's play refers to. |

The part, product and interface records state their drawing intent in one shared form: sheets, views, tolerances, dimension requests, fits and threads.
Its fields are on the [drawing definitions](/reference/contracts/record/drawing/) page.

### Manufacturing

| File | What it holds |
|---|---|
| [`hw/manufacturing/capabilities.yaml`](/reference/contracts/record/manufacturing-capabilities/) | What your machines, operators and suppliers can do, with their calibrations. |
| [`hw/manufacturing/materials.yaml`](/reference/contracts/record/manufacturing-materials/) | The material profiles that parts and capabilities refer to. |
| [`hw/manufacturing/guidelines/*.yaml`](/reference/contracts/record/manufacturing-guideline/) | Published design-for-manufacturing guidance, one set per file. |
| [`hw/manufacturing/selection.yaml`](/reference/contracts/record/manufacturing-selection/) | The candidate materials, processes and architectures, compared together, and the recommendation. |
| [`hw/manufacturing/evidence.yaml`](/reference/contracts/record/manufacturing-evidence/) | The accepted evidence ledger. |
| [`hw/manufacturing/findings.yaml`](/reference/contracts/record/manufacturing-findings/) | Your dispositions of the findings that checks reported. |
| `hw/manufacturing/sources/` | Frozen source files that the manufacturing records cite. |

[Manufacturing](/concepts/manufacturing/capabilities/) explains how these files work together.

### Versions, checks and releases

| Path | What it holds |
|---|---|
| `hw/versions/<V>/` | A built version: a snapshot of the record documents under `record/`, sealed by its [`manifest.json`](/reference/contracts/record/bundle-manifest/). |
| `hw/checks/<V>/<S>/` | A sealed check bundle for version `<V>`, with its own `manifest.json`. A manufacturing check writes its [`result.json`](/reference/contracts/record/manufacturing-check-result/) here. |
| `hw/releases/<REV>/` | A release: the product STEP AP242 and GLB and the documentation set, packaged from the frozen version. |

These three directories are sealed history.
Nothing rewrites them, not even a record migration, because a seal or a digest states their exact bytes.
[Versions and the freeze](/concepts/record/versions-and-freeze/) explains how they are made and checked.

## Documents

Every record document has a JSON Schema, generated from benchhand's contracts, and the record format has one version, `record_version: 3`.
A document at any other record version is refused, never guessed; a prototype record is brought to version 3 by migration.

benchhand validates a document before it writes it to disk.
A violation is an error that names the field and the rule it breaks, and nothing is written.
The agent changes the record through typed tools, such as `record.add_requirement`, `record.add_part` and `record.add_bom_row`, which validate on write.

A fact in the record is in one of three states:

- **known**, with its sources and its basis;
- **unknown**, with the reason it is unknown;
- **not applicable**, with the reason it doesn't apply.

Missing information is never a default, a zero or a pass.

Nothing stops you or the agent from editing a file under `hw/` directly.
Validation reports such an edit, or anything else that breaks a contract, as a finding.

The [contract reference](/reference/contracts/) has the fields of every document, and its domain model shows how the documents refer to each other.

## Decisions

Each decision record is one Markdown file, `hw/decisions/DR-###-<slug>.md`.
YAML front matter at the top holds the fields benchhand reads, and the Markdown body after it is kept as written.

A decision record is one of two kinds:

- **Gate decisions**, `kind: gate`, record a gate's state: `provisional`, `approved` or `void`. The flow engine writes them, and neither you nor the agent edits them by hand.
- **Design decisions**, `kind: design`, record a design choice: `proposed`, `accepted`, `rejected` or `superseded`. A superseded decision names the decisions that replace it.

Other records cite decisions by id.
A relaxed gate mode in `hw/policy.yaml` cites the decision that records it, and the frozen configuration cites the decision that approved the freeze.
A decision cited as the approval of a freeze, an engineering change or the project-start answers must be an approved gate decision or an accepted design decision.
