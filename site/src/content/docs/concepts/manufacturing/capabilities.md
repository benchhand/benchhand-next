---
title: Capabilities
description: How a manufacturer's capabilities are described in the record.
sidebar:
  order: 1
---

The [capabilities contract](/reference/contracts/record/manufacturing-capabilities/) lists its fields.

## What a capability is

A capability profile states what one of your actual machines, operators or suppliers can do.
The profiles live in `hw/manufacturing/capabilities.yaml`, apart from the design's requirements.

A profile has:

- an id, a revision and a title;
- the process it runs, as a route kind such as `fdm`;
- whether it is `local` or `outsourced`, with the supplier or operator;
- the machine's identity and its working envelope in X, Y and Z;
- the exact materials and stock it is approved or forbidden for;
- its parameters, and its tools with their own parameters;
- its workholding and other constraints;
- its calibrations;
- the guideline sets that apply to its machine.

## Parameters and calibrations

A machine's parameters, such as its nozzle diameter, layer height or travel, describe the machine.
They are never its achieved accuracy.

What the machine actually achieves comes only from calibrations.
Each calibration is scoped to a material, a feature, an orientation, a setup and a tool, and it carries its evidence.
A check whose calibration is turned off is `not_assessed`, with the reason `calibration_off`, and a check with no capability profile at all is `not_assessed` with `no_capability_profile`.

Capability templates carry `template: true`.
A template holds no machine numbers and is never a capability itself: copy it, record your own values, then remove the flag.

A process that benchhand has no check contract for is still accepted, and its coverage is reported as unknown, never as a pass.

## Materials

The material profiles live in [`hw/manufacturing/materials.yaml`](/reference/contracts/record/manufacturing-materials/).
A part names the material profile it is made from, and a capability profile names the materials it is approved for.

A material profile states the material's identity and its properties, each with its conditions:

- **Family or grade.** A family profile, such as PLA+, nylon, PETG or aluminium, is guidance and never a grade specification. A grade profile names the manufacturer's grade.
- **Form.** Printed, moulded, bulk, cast and wrought material are different profiles.
- **Conditions.** Every property states its test standard, temperature and conditioning, and for a printed form its orientation.
- **Typical values.** A profile marked `typical_not_allowable` holds only typical or estimated values, never design allowables.

Density is never strength.
