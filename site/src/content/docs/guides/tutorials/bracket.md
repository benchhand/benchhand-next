---
title: "Tutorial: a bracket"
description: A worked example that takes a bracket from requirements to release.
sidebar:
  order: 1
---

This tutorial takes one printed bracket through every stage of the flow, to a released STEP file.
It goes further than [A first part](/getting-started/first-part/): it adds bought screws, manufacturing checks, an analysis and the release.
You need benchhand [installed](/getting-started/install/) and registered with your agent host.

## What you build

A shelf bracket: one printed part that screws to a wall rail and carries a shelf, and the screws that hold it.
At the end, the record holds:

- the requirements, and how each one is verified;
- the bracket's `model.py` and its part record;
- the screws, as bought standard parts;
- the manufacturing checks, the analysis and the reviews of one built version;
- a release with the STEP AP242 file, a GLB and the documentation set.

The agent does the work through benchhand's tools.
You answer its questions and decide at the gates.

## Say what it is for

Open a project in an empty directory and ask the agent to design the bracket.
The agent calls `flow.guide` first, and follows its next action from then on.
[A first project](/getting-started/first-project/) describes how the project starts.

In GROUND the agent asks about the product and its use: what the shelf holds, where the bracket mounts, and how you make parts.
In INTENT it records what the bracket is for, and the INTENT gate asks you to approve that.

## Write the requirements

In SPECIFY, tell the agent what the bracket must do, such as:

- carry the shelf and its load at the front edge;
- fix to the rail with two screws;
- fit a shelf of a given thickness;
- print on your printer, in one material.

The agent records them with `record.add_requirement` in [`hw/requirements.yaml`](/reference/contracts/record/requirements/).
That file keeps four things apart:

- **Requirements**, which the design must meet. A requirement is never turned into a preference or an assumption to make the design pass.
- **Preferences**, such as as few screws as possible.
- **Assumptions**, each with its origin, its bounds, how it will be checked, and an owner. An assumption stays `open` until it is validated or shown wrong.
- **Open questions**, each with an owner, and whether it changes a design choice or is safety-relevant.

A value you haven't given stays unknown until you give it.

Each requirement also gets a row in [`hw/verification.csv`](/reference/contracts/record/verification-row/), which says how it will be verified: by inspection (`I`), analysis (`A`), demonstration (`D`) or test (`T`).
The load requirement is verified by analysis, and the hole positions by inspection.
Each row starts as `planned`, and holds its criteria and, later, its evidence.

## Pick a concept

In CONCEPT the agent builds rough variants, such as a plain L with a gusset and an open truss.
It uses `concept.add_variant` and `concept.set_primitive`, and `concept.snapshot` captures each one.
`preview.serve` hosts the concept page on a loopback URL, so you can compare them in your browser.

The VARIANT gate asks you to pick one, and records your choice and your words in a decision under `hw/decisions/`.

## Lay it out

In LAYOUT, `layout.from_concept` drafts a layout skeleton from the chosen variant: the envelope, and the interfaces where the bracket meets the rail and the shelf.
The agent records each interface with `record.add_interface` in [`hw/interfaces.yaml`](/reference/contracts/record/interfaces/).

Every value the skeleton infers is a bounded assumption.
You accept or change each one at the LAYOUT freeze, so no inferred value is frozen unreviewed.
The LAYOUT freeze is a [three-step gate](/concepts/process/gates/): PROVISIONAL after the fast checks, then the full check, then your approval.

## Model the bracket

In PARTS, the agent writes the bracket's `model.py` in CadQuery or build123d, and registers it with `record.add_part`.
Its [part record](/reference/contracts/record/part/), `hw/parts/<PN>/part.yaml`, gives the material, the process and the finish, and says that the part is made (`make_buy: make`).
Which process and material suit it come from your [capabilities](/concepts/manufacturing/capabilities/), and the agent records how it chose them as a [selection](/concepts/manufacturing/selection/).

The part SDK, `benchhand-sdk`, gives `model.py` its holes, fillets and safe booleans.
A generator writes the counterbores for the screws as a `model.py` fragment the agent can review.

The screws are bought, standard parts (`make_buy: buy`).
Each is identified by a designation: the standard, the size, the length and the property class, such as an ISO 4762 screw.
The agent takes their dimensions from a standard library, and records which one and which row, as [Standard parts](/concepts/manufacturing/selection/#standard-parts) describes.
No paywalled standard is needed.

While it models, the agent checks its work:

- `preview.part` builds the bracket without making a version, and shows it in the live viewer;
- `model.measure`, `model.section` and `model.mass_props` inspect the geometry.

`model.build` then builds the design as a version under `hw/versions/<V>/`, and the PARTS gate approves that version in three steps.
At PARTS, the full check runs beside a light mechanical review and a light manufacturing review, and a major finding from either voids the version.

## Check that it can be made

In DETAIL, the bracket gets its fits, its drawing and its assembly steps.
[Tutorial: a drawing](/guides/tutorials/drawing/) covers the drawing.

The process checks judge each operation of the bracket's route against your capabilities and the shipped [guidelines](/concepts/manufacturing/guidelines-and-checks/).
For a printed part, the dispatch list picks a handler for each check, such as `process.fdm.orientation`.
A check that no handler covers is UNKNOWN, never a pass.
A finding you accept is waived, with a reason and a date it stays valid until.

In BOM, the agent writes a row for the bracket and for the screws with `record.add_bom_row`, in [`hw/bom.csv`](/reference/contracts/record/bom-row/).

## Analyse it

In ANALYSIS, `fea.case_from_requirement` turns the load requirement into an analysis case.
The CalculiX solver provider solves it as a static FEA, and the result is the evidence for the load requirement's verification row.
The ANALYSIS gate approves the analysed version in three steps.

In CRITIQUE, the mechanical and manufacturing reviewers review that version.
RECONCILE is the last stage of work before the freeze.

## Freeze and release

The DESIGN freeze asks you to approve one built version as the configuration to release.
It opens only when every three-step gate has passed, the bracket has its manufacturing outputs, and the version's [evidence](/concepts/record/evidence/) forms an acceptance.
Approving it records the frozen version and its acceptance digest in `hw/product.yaml`.

The RELEASE gate shows the frozen version, the revision to issue, the contents and their verification.
When you approve it, the release tool packages the version into `hw/releases/<REV>/`: the STEP AP242 file, the GLB and the documentation set.
It refuses to package when the version's evidence differs from the digest the freeze recorded.
[Versions and the freeze](/concepts/record/versions-and-freeze/) lists every check the release makes.
