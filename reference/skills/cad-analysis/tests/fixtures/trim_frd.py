#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

"""Trim a large ccx .frd file to the nodes a stress-study test needs, and gzip it.

The truss_member pair of the fast-bias campaign is 4.69 MB gzipped, over the size a fixture should
have. Only three kinds of node matter to `fea_stress.compare_levels`:

* the nodes on the fixed and load planes, because every kept node's distance is measured to them;
* the nodes with the highest von Mises stress, because the kept peak is among them;
* the node with the largest displacement, because the displacement change uses it.

The script keeps those nodes' original NODE, DISP and STRESS records, character for character, and drops
every other node and block. The node count and kept share therefore differ from the full mesh: the
trimmed fixture holds the `--top` stressed nodes plus the face nodes. The expected results in
`test_fea_stress.py` are the ones the trimmed files give.

Regenerate the truss_member fixtures from the campaign files on dev, under
~/cad-bench/pkgA/fast-bias/ (fixed plane x=0, load plane x=320 in both cases):

    python3 trim_frd.py --out truss_r1_6mm.frd.gz --plane x=0 --plane x=320 --top 3000 \
        fb-2f0b457-r1/cases/truss_member/curved-6mm/.cad-work/jobs/fea_static/f8fedd44daee4efd86b0c3bea6672660/GmshMesh.frd
    python3 trim_frd.py --out truss_r2_4.5mm.frd.gz --plane x=0 --plane x=320 --top 3000 \
        fb-2f0b457-r2-finer/cases/truss_member/curved-4.5mm/.cad-work/jobs/fea_static/dc47b2b8d1014fcaa244a465c1015a59/GmshMesh.frd

Needs only the standard library and `fea_stress` from the sibling scripts directory.
"""

from __future__ import annotations

import argparse
import gzip
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import fea_stress  # noqa: E402


def keep_ids(text: str, planes: list[tuple[str, float]], top: int) -> set[int]:
    result = fea_stress.read_frd(text)
    keep: set[int] = set()
    for axis, value in planes:
        keep |= fea_stress.plane_node_ids(result, axis, value)
    keep |= set(sorted(result.von_mises, key=lambda n: (-result.von_mises[n], n))[:top])
    keep.add(max(result.displacement, key=lambda n: (result.displacement[n], -n)))
    return keep


def trim(text: str, keep: set[int]) -> str:
    """Keep the header, the node block, the last DISP block and the last STRESS block, filtered by id."""
    lines = text.splitlines()
    last = {name: max(i for i, line in enumerate(lines) if line.startswith(f" -4  {name}"))
            for name in ("DISP", "STRESS")}
    out: list[str] = []
    emit = True  # the header precedes the first block
    for i, line in enumerate(lines):
        if line.startswith("    2C"):
            emit = True
        elif line.startswith("    3C"):
            emit = False  # the element block
        elif line.startswith("  100C"):
            # A result block opens with this line, then its " -4" line.
            emit = i + 1 in last.values()
        elif line.startswith(" -4  ") and i not in last.values():
            emit = False
        if not emit:
            continue
        if line.startswith(" -1") and int(line[3:13]) not in keep:
            continue
        out.append(line)
        if line.startswith(" -3"):
            emit = False
    return "\n".join(out) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("frd", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--plane", action="append", default=[], metavar="AXIS=VALUE")
    parser.add_argument("--top", type=int, default=3000)
    args = parser.parse_args()
    planes = [(a, float(v)) for a, v in (p.split("=") for p in args.plane)]
    text = args.frd.read_text()
    trimmed = trim(text, keep_ids(text, planes, args.top))
    # mtime=0 keeps the gzip bytes reproducible.
    with open(args.out, "wb") as raw, gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as gz:
        gz.write(trimmed.encode())


if __name__ == "__main__":
    main()
