---
title: A first part through to STEP
description: Take one part from its requirements through a concept, a model and its checks to a STEP file.
sidebar:
  order: 3
---

This page follows one part through the flow, from what it must do to a STEP AP242 file.
The agent does the work through benchhand's tools, and you answer at the gates.
[Tutorial: a bracket](/guides/tutorials/bracket/) goes through a whole design in more detail.

## Write the requirements

In SPECIFY, the agent turns what you told it into requirements, and records each one with `record.add_requirement`.
The record keeps requirements, preferences, assumptions and open questions apart in [`hw/requirements.yaml`](/reference/contracts/record/requirements/).
A value you haven't given stays unknown until you give it.

Every `record.*` write is checked against the record's contract, so a malformed entry is refused when the agent writes it.

The INTENT gate, before SPECIFY, asked you to approve what the product is for.
Each gate decision lands in `hw/decisions/` as a [decision record](/reference/contracts/record/decision/), with who approved, through which channel, and your words quoted.

## Pick a concept

In CONCEPT, the agent builds rough options with the concept scene tools: `concept.add_variant`, `concept.set_primitive` and `concept.snapshot`.

`preview.serve` hosts the concept page on a loopback URL, so you can compare the options in your browser.
The VARIANT gate then asks you to choose one, and records the choice.

## Lay it out

In LAYOUT, `layout.from_concept` drafts a layout skeleton from the chosen concept.
Each value it infers is recorded as a bounded assumption.
You accept or change each one at the LAYOUT freeze, so the skeleton is never frozen unreviewed.

## Design the part

In PARTS, the agent writes the part's `model.py` in CadQuery or build123d, and registers the part with `record.add_part`.
The part's record is [`hw/parts/<PN>/part.yaml`](/reference/contracts/record/part/): its material, process and finish, whether it is made or bought, and its design intent.

The agent writes geometry, and benchhand's tools do the routine work:

- The part SDK, `benchhand-sdk`, gives `model.py` safe booleans, holes, fillets and fonts. `sdk://describe` lists their signatures.
- Generators write reviewable `model.py` fragments for ISO and ASME holes and counterbores, purchased fasteners and bearings, bosses, ribs and sheet flanges.
- `preview.part` builds the part without making a version, returns snapshots, and updates the live viewer.
- `model.measure`, `model.section`, `model.mass_props` and `model.interference` inspect the geometry.

## Verify it

`model.build` builds the part as a new version, under `hw/versions/<V>/`.
The PARTS gate then approves that version in three steps:

1. **PROVISIONAL.** Every fast check on the version has to pass. The next stage can start.
2. **The full check.** It runs on the same version. If it fails, the gate is VOID and the agent builds a fixed version.
3. **The human gate.** The agent presents the gate packet with its renders and asks you. Your explicit approval records the gate APPROVED.

Which checks run at each stage, and how the process checks are picked for a material and process, come from [rule lists](/concepts/policy/rule-lists/).
Check results are sealed in bundles under `hw/checks/<V>/<S>/`, and a manufacturing check writes its [`result.json`](/reference/contracts/record/manufacturing-check-result/) there.
When no provider covers a check, its result is UNKNOWN, never a pass.

The [evidence](/concepts/record/evidence/) of a version is assessed from three sources only: the record itself, the sealed check bundles of that version, and the accepted ledger in `hw/manufacturing/evidence.yaml`.
`unknown` and `planned` evidence and untested obligations never count as a pass, and `stale` evidence counts as nothing.

## Export STEP

Each `model.build` writes the version's STEP AP242 file, which is the primary deliverable, with a GLB for the viewer and a manifest.
No agent script is involved: the tool takes the version and returns the artifacts, each with its absolute path and SHA-256.
`model.export` writes STL and 3MF from the same version.

A release packages a frozen version.
After the DESIGN freeze approves the configuration, the RELEASE gate releases it into `hw/releases/<REV>/`.
The release checks the version's evidence against the acceptance digest that the freeze recorded, and refuses to release when they differ.
[Versions and the freeze](/concepts/record/versions-and-freeze/) explains both.
