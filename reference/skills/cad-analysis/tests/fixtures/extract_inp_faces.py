#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

"""Cut the boundary-condition sections out of a FreeCAD-written CalculiX input, for a test fixture.

The stress study reads the fixed-face and load-face nodes of a solve from its `GmshMesh.inp`: the
`*NSET,NSET=FixedFaces` block and the `*CLOAD` blocks. A whole input holds the mesh as well (85 kB for the
cantilever at 4.5 mm), so the fixture keeps only those two sections, character for character, under a header
that names the source.

The cantilever fixtures come from the fast-bias campaign `fb-2f0b457-r1` on dev (~/cad-bench/pkgA/fast-bias/):

    python3 extract_inp_faces.py --out cantilever_r1_4.5mm.faces.inp \
        fb-2f0b457-r1/cases/cantilever/curved-4.5mm/runs/377fe34862d04364aaef7b15ba601ea6/GmshMesh.inp
    python3 extract_inp_faces.py --out cantilever_r1_3mm.faces.inp \
        fb-2f0b457-r1/cases/cantilever/curved-3mm/runs/d22c0dbb7ed147a0ab35f1bf6a9cd4c9/GmshMesh.inp

Standard library only.
"""

from __future__ import annotations

import argparse
from pathlib import Path


def faces_sections(text: str) -> list[str]:
    """The lines of the FixedFaces node set and of every *CLOAD block, up to the next keyword."""
    lines = text.splitlines()
    out: list[str] = []
    keep = False
    for line in lines:
        keyword = line.strip().upper()
        if keyword.startswith("*NSET,NSET=FIXEDFACES") or keyword.startswith("*CLOAD"):
            keep = True
        elif keyword.startswith("*") and not keyword.startswith("**"):
            keep = False
        if keep:
            out.append(line)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("inp", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    body = faces_sections(args.inp.read_text())
    header = [f"** excerpt of {args.inp.name} from the fast-bias campaign: the FixedFaces node set and the *CLOAD blocks",
              "** (extract_inp_faces.py); the mesh, the material and the step are left out"]
    args.out.write_text("\n".join(header + body) + "\n")


if __name__ == "__main__":
    main()
