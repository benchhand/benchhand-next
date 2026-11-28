<!--
SPDX-FileCopyrightText: 2026 Sjors Robroek

SPDX-License-Identifier: MPL-2.0
-->

# Assembly and part structure: the owner's decisions of 2026-11-28

Status: owner decisions, recorded on 2026-11-28 for the assembly-structure spec (spec 21, "Assembly structure and steps") and the export specs. This note changes no contract, ADR or code. The catalogue records it as the proposed capability `product-scene-structure`, and the register's IR-227 carries the lesson that asked for it: the only assembly a build wrote was the check scene, with context, tooling and every variant in it. The example product is the lamp-arm fixture.

## Decisions

### Every exported model

The structure below applies to every exported model, an assembly and a single part alike. The owner: "This should also apply to the individual parts as well as the assembly (all of the above)."

### The product tree (`product.step`)

1. **Grouping.** Built subassemblies are at the top. Inside each subassembly, and in every nested one, there are always two groups, `[Made]` then `[Purchased]`, even when one is empty.
2. **Purchased subgroups.** `[Fasteners]`, `[Inserts]`, `[Bearings and shafts]`, `[Retaining]`, `[Springs]`, `[Electrical]` and `[Other]` come from the part's purchased-part class. A group is for display only: a bracketed name, with no part number and no BOM line.
3. **`[Final assembly]`** holds the parts that join subassemblies, with the same split.
4. **The kit** holds the items that ship loose, with the same split.
5. **Names** are the part number, the name and the revision. A standard part appears once and is placed many times.

### The scene tree (`scene.step`, never released)

- The product, as one placement.
- `[Context]`, split into `[Mounting]`, `[Existing]`, `[Neighbours]` and `[Reference]`.
- `[Tooling]`.
- `[Joints]`: one marker per joint, named with its type and limits.
- `[Poses]`: the moving subassembly only, at each limit.
- `[Envelopes]`: `[Motion]`, `[Access]` and `[Keep-out]`.
- `[Findings]`: the overlap solids and the blocked access points.
- `[Construction]`.

### Views, not bodies

Sections, cut-throughs and slices are named saved views with clipping planes (AP242 saved views), plus rendered images in the review documents. No cut bodies are exported. The exploded view and the kit view are saved views too. PMI stays attached to the faces it annotates.

### Hidden by default

- **Visible:** the product's `[Made]` and `[Purchased]`, `[Mounting]`, `[Existing]`, and parts nested inside other parts.
- **Hidden:** the kit, `[Tooling]`, `[Envelopes]`, `[Reference]`, `[Neighbours]`, `[Joints]`, `[Poses]`, `[Findings]` and `[Construction]`.
- **The hidden flag.** The STEP files use AP242 invisibility. Import tests check how FreeCAD and the owner's CAD tools honour it. The benchhand viewer applies the defaults itself.
- **A failing check shows its envelope.** Opening a failing check in the viewer turns on its `[Findings]` item, the envelope that caused it, and the joint or pose involved.

### A single part

The same structure applies, scaled down:

- the part body, with `[Made]` for the printed or machined inserts it owns;
- `[Purchased]` for its installed hardware, such as heat-set inserts, when it is exported with them;
- a scene with `[Context]`, `[Tooling]` (for example the insert tool), `[Envelopes]` (the print-bed or tool-access volumes), `[Findings]` and `[Construction]`;
- saved section views;
- the same hidden-by-default rules.

## What this settles

- The product export and the check scene are two files. The checks keep reading the full scene, and a release ships only the product tree.
- Customer-furnished equipment is `[Existing]` or `[Reference]` context, and a loose item is in the kit. Neither is a product BOM line of a part to buy (RULE-01, IR-003, IR-025).
- A variant or size class is its own project (RULE-06), so one product tree never holds two of them.
