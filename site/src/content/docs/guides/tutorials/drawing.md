---
title: "Tutorial: a drawing"
description: A worked example of a part drawing and an assembly drawing.
sidebar:
  order: 2
---

This tutorial makes the drawings for the design of [Tutorial: a bracket](/guides/tutorials/bracket/): a part drawing of the bracket, and an assembly drawing of the bracket and its screws.
The drawings come in DETAIL, after the PARTS gate has approved the bracket's model.

## What you build

The documentation set of one built version:

| Output | What it holds | Files |
|---|---|---|
| Part drawing | Views, dimensions, tolerances, sections with material hatch, detail views, centre marks, the title block, surface finish and weld symbols, and notes | PDF and SVG sheets, and a text list of the views, dimensions and symbols |
| Assembly drawing | An exploded view, balloons, the parts list grouped by make, buy and existing, and one sheet per assembly step | PDF and SVG, the parts list as CSV, and the steps as text |
| Labelled views | A render with numbered callouts and a legend | PNG, and the legend as text |
| Keynoted section details | A section through the assembly, each region hatched by its material and labelled with a leader | PNG and SVG, and the keynote list as text |
| FreeCAD document | A structured `.FCStd` with the TechDraw pages inside | The file, and its object tree as text |

STEP AP242 stays the primary deliverable.
Every output is built from the same version as the STEP file, so the drawings, the FreeCAD document and the viewer show the same names, groups and materials.

## State the drawing intent

A drawing starts from what the record says about the part, not from lines drawn by hand.
The part record carries its drawing intent in the shape of the [drawing contract](/reference/contracts/record/drawing/):

- **Datum features and a coordinate frame**, which the dimensions and tolerances refer to.
- **Views**, each `orthographic`, `auxiliary`, `section` or `detail`, with the sheet it goes on and its scale. The principal view is on sheet 1.
- **Dimension requests**, the dimensions the drawing must show. A request has no value field: every value comes from the model.
- **Geometric tolerances** to ISO 1101 or ASME Y14.5. The tolerance zone is design intent, never a measured value.
- **Tolerance policies**, and the general tolerance for every dimension without its own.
- **Surface texture** to ISO 21920-1: the upper limit of the parameter in micrometres, and whether material must be removed.
- **Edges** to ISO 13715: the size limits of edges whose shape isn't drawn. A detail drawing needs the general indication.
- **Threads** to ISO 6410-1 and **fits** to ISO 286.

Two rules keep the drawing honest:

- A wall or web thickness that follows from other dimensions isn't a drawing dimension. The model check controls it.
- A model feature is kept or dropped for its function, never to suit the drawing tools.

For the bracket, the datums are the faces that locate it on the rail, and the hole positions are dimensioned from them.

## The annotation set

Beside the drawing intent, each part and assembly has one annotation set.
benchhand derives it from the record, and you can edit it.
It holds:

- **Groups**: the assembly tree, and a sourcing group for every part, make, buy or existing. Fasteners and bought hardware go in buy. Reference and construction geometry get a group of their own.
- **Callout targets**: each part, and each feature it recognises, such as a hole, thread, slot, fit or sealing face. Each has a label with the part number, name, material and finish.
- **Materials**: one for each body, from the record. It sets the section hatch, the look of the render, the mass and the label.
- **Surface finish**, for each part and for each face where it matters. It is a roughness such as Ra, or a process such as anodising, powder coating or polishing, and comes from the requirements and the manufacturing review.
- **Notes**: general notes, notes for each group, and weld callouts for welded joints.
- **The assembly order**: numbered steps, each naming the parts it adds and the fasteners, with their torque.

Every output reads the same annotation set, so a label on the drawing matches the label in the viewer.

## Make the part drawing

The drawing tools make the part drawing with FreeCAD's TechDraw, through the FreeCAD provider.
For the bracket, the sheet can hold:

- the principal views;
- a section through a counterbore, with the material's hatch;
- the hole positions, dimensioned from the datums;
- the general tolerance, in the title block;
- the finish of the shelf seat.

You get PDF and SVG sheets.
You and the agent also get a text list of every view, dimension and symbol, so the agent can check the drawing against its intent without reading an image.

## Make the assembly drawing

The assembly drawing shows the bracket and its screws:

- an exploded view, with a balloon on each part;
- a parts list, grouped by make, buy and existing: the bracket under make, and the screws under buy;
- one sheet for each assembly step, with the parts and fasteners that step adds.

The parts list comes as CSV, and the steps as text.
In the viewer you can step through the assembly order.

The parts list holds the product only.
If you record the wall rail as an existing part, its occurrence has the role `context`.
The drawings show it in phantom lines.
The BOM and the build guide list it under "Customer-furnished equipment (not supplied)", with its required ranges.
[Tutorial: an assembly with a mechanism](/guides/tutorials/assembly-mechanism/) covers existing parts.

## Labelled views and section details

A labelled view is a render with numbered callouts and a legend.
The agent uses it to review its own work, and you get the PNG and the legend as text.
In the viewer, you can hover or click a part, switch the sourcing, subassembly and material groups on and off, and step through the assembly.
Context parts are ghosted, with a toggle.

A keynoted section detail cuts through the assembly, hatches each region by its material, and labels it with a leader: part number, material, finish and sourcing group.

## The FreeCAD document

The `.FCStd` file is structured for you to open in FreeCAD:

- an Assembly with its joints;
- one group for each subassembly and each sourcing group, and a Construction group;
- named bodies, each with its material;
- sketches that keep their construction geometry;
- the TechDraw pages.

Its object tree also comes as text.

## Approve the drawings

The drawings are part of the DETAIL version, and the DETAIL gate approves them with the rest of the stage's work, in three steps.
A later change that alters what a drawing shows makes its drawing evidence stale, and the drawing checks run again on the version built from that change.
