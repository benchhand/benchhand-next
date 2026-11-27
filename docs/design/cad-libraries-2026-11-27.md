<!--
SPDX-FileCopyrightText: 2026 Sjors Robroek

SPDX-License-Identifier: MPL-2.0
-->

# CAD libraries: the owner's decisions of 2026-11-27

Status: decided. The owner answered D-1 to D-47 on 2026-11-27, and D-21 after the viewer lane. D-37 is still open. Written against `main` at `5adfd920`. This record changes the plan ([design plan](../design-plan.md)), ADR-0001 and the provider protocol, and adds [ADR-0022](../adr/0022-hazards-risk-assessment.md), the design rules RULE-40 to RULE-46 and catalogue entries. Each row below says where its decision lands.

## Context

The CAD-libraries study surveyed what benchhand-next and the prototype could adopt:

- thread and fastener libraries, purchased-part geometry and supplier terms;
- standards data, FDM checks and slicers;
- analysis and drawing tools, and FreeCAD addons;
- the 3D viewer and product documents.

Its lane reports aren't in this repository. This record keeps only what a decision needs. Two kinds of finding are cited by number:

- **B-n** is a defect the study found in the prototype;
- **U-n** is a defect it found upstream, in a library.

"Lands in" names the plan section or phase, the contract, the ADR, the design rule, the catalogue capability or the provider. "Deferred" means no contract changes now, and the catalogue lists the change as `planned`.

## Decisions

| D | Question | Decision | Consequence | Lands in |
|---|---|---|---|---|
| D-1 | Which prototype changes count as fixes under "fixes only"? | Fix now: B1 to B3 (opt-in Boolean guards that keep the generic `safe_cut` and `safe_fuse` contract, and kernel warnings surfaced for diagnosis), B8 (FEA mesh provenance), B9 to B12 (build guide), B17a (diff time budget), B19 (bed footprint) and prototype bead `benchhand-03vn` (procurement source order). Features wait for benchhand-next: B5 to B7, B15, B17b and B24. B13, B14, B16, B18 and B23 are decided one by one. | Each fix lands in the prototype, then reaches benchhand-next through its own reviewed port step (ADR-0015). | The prototype's ledger; `release.toml` `reference_commit` ports |
| D-2 | Default kernel for new parts | build123d, once a build123d example part and a contract test exist. A record may mix kernels. | CadQuery stays supported for existing parts. | Plan section 12; Phase 4 `kernel-build123d` |
| D-3 | Included angle of a printed FDM thread | At least 92 degrees at a 45-degree overhang limit, taken from the process profile, not a fixed 90. | A 90-degree thread breaks the profile's own flank rule. | Phase 4 SDK thread helper; IR-024 |
| D-4 | Radial allowance of a printed fit | A per-printer calibration with a value and its basis. The starting value is 0.15 to 0.25 mm. | No vendor publishes a figure, and ISO 965 classes don't hold for printed threads. | Phase 4 SDK thread helper; the capability profile's calibration |
| D-5 | Which geometry provenance clears the F3 fidelity level for a bought part? | An envelope clears F3 as `F3-envelope`: the record states the dimension source (datasheet, measurement or customer), and the gate shows a warning. Nothing blocks. A supplier STEP, or a generated STEP the maker verified, gives `F3-as-bought`. At release, the BOM and the release notes list every part that is envelope only. A standard ISO or DIN part takes its geometry in the library order of RULE-36. | A design without a supplier model can still pass its gates. The release says which parts are approximations. | RULE-40; Phase 2 record contract and fidelity rule list (deferred), catalogue `purchased-part-fidelity`; IR-031 |
| D-6 | Supplier STEP bytes in a repository | Always record the file's sha256. Commit the bytes only where the supplier's terms allow it. `run` fails only when a STEP frozen as required evidence is missing or changed. | Restricted vendor files stay out of public repositories. | RULE-41; Phase 4 supplier STEP import |
| D-7 | Supplier sites whose terms are unread or restrictive | The user approves each download, and the agent downloads it on the user's behalf. benchhand doesn't contact suppliers for permission; that is the user's call. | The user accepts each supplier's terms. | RULE-42 |
| D-8 | Generators on FreeCAD addon internal APIs (Fasteners, SheetMetal, FCGear) | A trial, pinned by addon commit, with a geometry comparison test rather than byte equality. | Internal APIs drift; the pin and the test catch it. | Phase 4 `freecad` provider; the `part-source` kind (D-20, D-44); the addon pins (D-45) |
| D-9 | Must threaded parts use build123d? | Yes. Threads are modelled only in build123d. | The thread helper lives only in the build123d environment. | Plan section 12; Phase 4 SDK |
| D-10 | bd_warehouse pin | 0.4.0, with a row-audit test that overrides the known-bad M3 and M14 hex-nut rows until a release fixes them. | A test checks each pinned row that a part uses. | Phase 4 `kernel-build123d` |
| D-11 | File the upstream defects? | Yes: bd_warehouse's ruthex rows shadowed by CNC Kitchen rows, its thread fade and length, its M3 and M14 nut rows, the Fasteners heat-set `KeyError`, and the SheetMetal K-factor interpolation. | An action, not a design change. | Upstream reports; none in this repository |
| D-12 | GPI bottle threads | Only when a project needs them. | Not scheduled. | None |
| D-13 | FreeCAD material cards for analysis | A trial. They are read at run time, never redistributed, and reviewed one by one before use. | The cards' licences are mixed, and one shipped card is inconsistent. | Phase 4 `freecad` and `solver-calculix` |
| D-14 | Analysis-only slicing | Allowed. OrcaSlicer first, opt in, run in a container, with hashed profiles. An unknown statistics version gives UNKNOWN. G-code and sliced files are discarded after their statistics are read. | Print time, mass and support volume can become evidence. | Plan section 6 (an opt-in slicer provider, no phase yet) |
| D-15 | Mesh dependencies in the orchestrator | Add `rtree` (MIT); `embreex` is optional. | The mesh cross-checks get spatial queries. | Phase 4 `checks-process` |
| D-16 | Thread wrapper guard | Always on: the result is one valid solid, and its net volume gain or removal is within tolerance of the expected value. The same checks are offered to other callers as an opt-in guard. | A bare minimum-gain check misses a result with two solids. | RULE-43; Phase 4 SDK |
| D-17 | GPL and AGPL tools | Slicers, gmsh, CalculiX and FCGear run only as separate processes or containers, never imported. benchhand downloads the pinned upstream file and checks its sha256, and never rehosts it. The owner signs off before a Dockerfile that fetches AGPL code ships. | The process boundary keeps benchhand's own code under its licence. | RULE-44; plan section 6 |
| D-18 | Remove FreeCAD from analysis and drawings? | Analysis runs gmsh and CalculiX directly in the Phase 4 `solver-calculix` provider, with its own deck writer and result parser, as subprocesses. Drawings stay on FreeCAD. Assembly solve and motion stay on FreeCAD. build123d `project_to_viewport` stays on the watch list. | FEM preparation leaves the `cad-app` provider. | Plan section 6, Phase 4; catalogue `fea-analysis` |
| D-19 | PMI in the STEP | Trial both paths behind a pin: OCCT XCAF dimensions and datums at export, and a semantic `THREAD` from specify-core after the final write. | AP242 stays the primary deliverable. | Phase 4 kernel export |
| D-20 | Home of the standards-parts data | A new `part-source` provider kind. CC-BY-SA electronics data ships as a separate package beside the MPL core. | A minor protocol change, once its hooks are designed. | Plan section 6; catalogue `part-source-provider` (deferred) |
| D-21 | The 3D viewer | benchhand builds its own three.js viewer from the start. STEP is parsed on the server only. The viewer meets WCAG 2.2 AA, with every control in benchhand's React UI. Interactive measurements are mesh based and labelled as such; a value the agent records or a gate cites is exact, from the kernel. The `ViewerPick` and payload contracts are drafted in Phase 5. PMI in the viewer waits for the D-19 trial. The viewer has no provider of its own: it reads the kernel's per-face GLB (one glTF primitive per B-rep face) plus an edge layer, and exact measurement is a kernel call. | `viewer-ocp` leaves the plan, and the prototype's separate viewer server processes are retired. | Plan D6, sections 1, 2, 6 and 12, Phase 5; catalogue `viewer`, `viewer-ocp` (dropped) |
| D-22 | ISO 286 tables beyond 120 mm | Only from the controlled standard, cited. | No values from secondary sources. | Phase 4 fits data |
| D-23 | Citing a standard | Freeze-on-cite: a copy of the cited rows goes into the record. No contract change. | A dataset source kind can come later as a minor change. | Phase 4 standards data |
| D-24 | A non-ISO thread callout on a release | A release that carries one waits for a wording check against ISO 6410-1 and ASME Y14.6. | A release refusal check. | Phase 4 release packaging |
| D-25 | Supplier specifications as calibration | A supplier's published specification counts as calibration, as `source.kind: supplier`. It can turn UNKNOWN into pass or fail, and the record shows that the figure is supplier data. | Supplier data is evidence, and it is labelled as supplier data. | RULE-45; Phase 2 record contract (deferred), catalogue `supplier-calibration` |
| D-26 | Typst distribution | The Typst PyPI wheel everywhere: for users, development, CI and the golden files, pinned in `uv.lock`. No separate binary, and users need no mise. A wheel upgrade regenerates the golden files. | One distribution gives one set of bytes. | Plan section 12a, Phase 4 |
| D-27 | A `quote` provider | A contract sketch only, off by default. | Every quote uploads design data, so it stays opt-in. | Not scheduled |
| D-28 | Read-only CLI subcommands | ADR-0001 is amended: the CLI gets read-only subcommands such as `docset` and `inspect`. Writes stay on MCP or `debug call`. | Hosts whose model can't see MCP tools can still read. | ADR-0001 amendment; plan D1 and section 7; catalogue `read-only-cli` |
| D-29 | Approving a gate from the preview page | Approvals stay in chat and in the MCP App gate card. Approving from the preview page may come later, and no phase builds it. | Approvals keep their two channels. | Plan section 11 |
| D-30 | Spatial review comments | Each comment becomes either a "request changes" item on the gate or an open question in the record, chosen per comment. | Scope for the Phase 5 viewer work. | Phase 5 or later |
| D-31 | A self-verifying approval reference | A decision gets an optional `manifest_sha256` beside its ADR-0019 approval scope. | An approval names the exact sealed manifest it saw. | Phase 2 scoped approvals; decision contract (deferred), catalogue `decision-manifest-hash` |
| D-32 | agentcad's `solid_compare.py` and `edit_risk.py` | benchhand adopts their designs and rewrites them by default. A file is ported only when the owner approves that file, with its Apache-2.0 notice. | The plan's "rewrite, don't port" rule holds. | RULE-46; Phase 4 `model.diff` and `model.inspect` |
| D-33 | A self-contained `viewer.html` in a release | Optional, chosen per release. It uses the D-21 viewer. | The release package layout allows it. | Phase 5 viewer export; Phase 7 |
| D-34 | PDF profile for product documents and drawing sets | PDF/A-3a plus PDF/UA-1, with the input JSON attached. Drawings are SVG sheets with a vendored Osifont, after the font file itself is checked. Release gates: the set compiles, and veraPDF validates the golden files. | PDF/A refuses embedded PDFs, so drawings go in as SVG. | Plan section 12a, Phase 4 |
| D-35 | Hazards and risk assessment | A hazards and risk-assessment contract with its own ADR. A release blocks on a safety UNKNOWN only where the service class is `safety_critical`. | The safety sections of the manual stop being UNKNOWN once the contract exists. | ADR-0022; after Phase 4, catalogue `hazards-risk-assessment` |
| D-36 | Product identity | Add product identity fields: title, manufacturer or author, contact, and licensor. | The manual and datasheet can fill their identity cells. | Phase 2 product contract (deferred), catalogue `product-identity` |
| D-37 | Where generated documents live, and the project storage layout | **Open.** The owner asked to reconsider the whole project storage layout: authored data against machine data, and SQLite or a key-value store where that is better. The storage-layout study, bead `bhn-7pg`, is running. | D-38's path may move with it. | Pending, bead `bhn-7pg` |
| D-38 | Project template overrides | A project may override the document templates in `hw/templates/`, and the overrides are hashed into the recipe. The path may move with D-37. | A larger recipe, for flexibility. | Phase 4 product documents |
| D-39 | Diagram annotations in product documents | Drawn as SVG upstream. No fletcher and no cetz. | No LGPL files in the document toolchain. | Phase 4 product documents |
| D-40 | Safety symbols | No ISO 7010 or ISO 7000 symbols by default: a signal-word panel with text. Users may supply their own symbols. | No symbol licences to track by default. | ADR-0022; after Phase 4 |
| D-41 | Fonts | Atkinson Hyperlegible for text and Noto Sans Symbols 2 as the fallback, both OFL and vendored. The build fails on a missing glyph. | No silent missing glyphs. | Plan section 12a, Phase 4 |
| D-42 | The 3MF writer | Rewritten in the kernel provider, with the prototype's writer and tests as the behavioural oracle. | No code port. | Phase 4 `model.export` |
| D-43 | manifold3d | Parked until a part needs it. | A mesh result would leave the B-rep path. | None |
| D-44 | New FreeCAD jobs | Add the `cad-app/unfold` job. Part generators go through the `part-source` kind (D-20). | Unfold is a FreeCAD job like the others. | Provider protocol 1.1.0 (`cad-app/unfold`, made); plan section 6 |
| D-45 | Addons in the FreeCAD environment | `environment.freecad` gains `addons: [{url, commit}]` and a hashed Python lock. | SheetMetal's unfolder needs networkx, which FreeCAD doesn't bundle. | Plan section 6; manifest contract (deferred), catalogue `freecad-environment-pins` |
| D-46 | Sheet metal | In scope as a trial behind `process.sheet_forming.*`, using `cad-app/unfold` and supplier K-factors per thickness (D-25). | `cad-app/unfold` has a consumer. | Plan section 6, Phase 4 `freecad` and `checks-process`; catalogue `sheet-metal-unfold` |
| D-47 | The strict OCCT Boolean argument check | A report from Phase 4. A gate is decided after the investigation of the open thread-mesh edges (B4). | The warehouse threads of bd_warehouse 0.4.0 fail the strict check, so a gate would block them. | Phase 4 `model.inspect` |

## Contract changes

Made:

- **`cad-app/unfold`** (D-44). The provider protocol gains the method, with `CadAppUnfoldParams` and `CadAppUnfoldResult`, as protocol 1.1.0. Like the other hooks, its params and result are the shared base shapes until Phase 4 designs them.

Deferred, each listed in the capability catalogue as `planned`, with the plan's [CAD-libraries decisions](../design-plan.md#cad-libraries-decisions-2026-11-27) as its source:

- **The `part-source` kind** (D-20, D-44). The kind needs its hooks, and no source names them yet. A kind without hooks can't pass the manifest agreement rule.
- **`environment.freecad` addons and the Python lock** (D-45). The `addons` shape is decided, but the lock's shape (a path, a file list or a hash domain) isn't. The change lands as one minor version once it is.
- **`F3-envelope` and `F3-as-bought`** (D-5), with the dimension source, are part of the Phase 2 record additions and the fidelity rule list. No published contract has a fidelity level yet.
- **`source.kind: supplier`** (D-25). No published contract has calibration source kinds yet.
- **Product identity fields** (D-36). The field names still need choosing, for example whether "manufacturer or author" is one field or two.
- **`manifest_sha256` on a decision** (D-31). It sits beside the approval scope, which Phase 2 adds to the decision contract (ADR-0019).

## Left for later contract decisions

- **The `viewer` hook kind** (D-21). The protocol keeps it. With no viewer provider, the preview host serves the viewer and the kernel provider answers exact measurements. Whether the kind leaves the protocol is a later contract decision.
- **`cad-app/fem`** (D-18). Analysis runs gmsh and CalculiX directly, so no provider in the plan calls the hook. It stays in the protocol until a contract decision removes it.
