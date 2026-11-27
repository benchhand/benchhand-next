---
title: The built-in providers
description: The providers that ship with benchhand.
sidebar:
  order: 2
---

benchhand ships with these providers.
Each runs in its own process and environment, as [What providers are](/concepts/providers/overview/) describes.

| Provider | Kind | Hooks |
|---|---|---|
| `kernel-cadquery` | `kernel` | `build`, `export`, `inspect` |
| `kernel-build123d` | `kernel` | `build`, `export`, `inspect` |
| `freecad` | `cad-app` | `drawing`, `assembly`, `fem` |
| `solver-calculix` | `solver` | `solve` |
| `collision-fcl` | `collision` | `check`, `sweep` |
| `render-chromium` | `renderer` | `render`, `snapshot` |
| `checks-process` | `process-check` | `check` |
| `store-fs` | `store` | `put`, `get`, `list` |

## Kernels

A part's `model.py` is a CadQuery or a build123d script, and the matching kernel provider runs it.
`kernel-cadquery` and `kernel-build123d` each run in their own uv environment, because CadQuery uses OpenCASCADE 7.9 and build123d uses 8.0.

A kernel's hooks are behind the output and inspect tools:

- `build` runs the script and writes STEP AP242, a GLB and a manifest, for `model.build`;
- `export` writes other formats, STL and 3MF, for `model.export`;
- `inspect` answers geometry queries, for `model.measure`, `model.section`, `model.mass_props` and `model.interference`.

## FreeCAD

The `freecad` provider runs FreeCAD jobs under FreeCAD's own Python, through `freecadcmd`: TechDraw drawings, assembly solves, FEM preparation and the export of a structured FreeCAD document.

It owns benchhand's FreeCAD install:

- **Lookup.** It finds FreeCAD through the `FREECADCMD` environment variable, `PATH`, the macOS application bundle, an AppImage, or benchhand's own download directory.
- **The supported list.** Each benchhand release ships `freecad-versions.toml`, which lists every supported version with its platforms, download URLs, SHA-256 and a status: `supported`, `deprecated` or `removed`. A FreeCAD that isn't on the list is refused, with a fix that names the supported versions, and a `deprecated` version gives a warning. The download offers only `supported` versions.
- **The managed install.** With your consent, `benchhand setup` downloads a supported version into `~/.local/share/benchhand/freecad/<version>`.

A provider can add its own CLI subcommands, and `freecad` adds its compatibility probe as `benchhand freecad probe`.
[Install](/getting-started/install/) shows the setup steps.

## Solvers, collision and rendering

- `solver-calculix` solves analysis cases with CalculiX, such as a static FEA.
- `collision-fcl` checks interference and clearance between parts, and runs the motion sweeps of moving joints.
- `render-chromium` renders images and snapshots in Chromium. It stays resident for the session, so Chromium stays warm between renders.

`benchhand doctor` checks that Chromium and the three.js vendor cache are in place.

## Checks and storage

`checks-process` runs the manufacturing process checks.
For each obligation it owns, the dispatch [rule list](/concepts/policy/rule-lists/) picks a handler from the process, the operation and the material.
A case with no handler is UNKNOWN coverage, never a pass.
[Guidelines and checks](/concepts/manufacturing/guidelines-and-checks/) explains the checks and their findings.

`store-fs` stores artifacts on the file system.
