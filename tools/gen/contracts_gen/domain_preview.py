"""A browsable preview of the D2 domain diagrams, next to the current Mermaid ones: ``index.html`` and SVGs.

    PYTHONPATH=tools/gen uv run python -m contracts_gen.domain_preview OUT_DIR

writes, below ``OUT_DIR``: ``classes.d2``, ``overview.d2`` and ``.svg``, one folder per contract with its
``NN-name.d2`` and ``.svg`` files and the ``mermaid.svg`` of the diagram the Markdown page has for it, and an
``index.html`` that shows them all. Every D2 diagram is rendered twice; ``determinism.txt`` says whether the
two SVGs are the same bytes. Mermaid needs ``pnpm --dir contracts install`` and a Chrome.
"""

from __future__ import annotations

import argparse
import html
import os
import posixpath
import re
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from .domain import DomainModel, build_model, ref_counts
from .domain_d2 import (
    CLASSES_D2,
    CLASSES_FILE,
    D2_COMMAND,
    D2_LAYOUT,
    D2_PAD,
    OVERVIEW_FILE,
    DiagramPlan,
    check_d2_version,
    plan_diagrams,
    render_diagram,
    render_overview,
    stubs_of,
)
from .domain_render import render_domain_model
from .sources import CONTRACTS_DIR, REPO_ROOT, SCHEMAS_OUT, Contract, load_contracts

RENDER_TIMEOUT_SECONDS = 300
MMDC = REPO_ROOT / CONTRACTS_DIR / "node_modules" / ".bin" / "mmdc"
CHROME_APP = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
OVERVIEW_HEADING = "Overview"
_HEADING = re.compile(r"^#{2,3} `?([^`]+?)`?$")


@dataclass(frozen=True)
class Determinism:
    """Whether two renders of one D2 source gave the same SVG bytes."""

    name: str
    same: bool
    first: bytes
    second: bytes


def render_d2(source: Path, target: Path) -> bytes:
    """Lay ``source`` out with ELK into ``target``; return the SVG."""
    command = [D2_COMMAND, "--layout", D2_LAYOUT, "--pad", str(D2_PAD), str(source), str(target)]
    result = subprocess.run(
        command, capture_output=True, text=True, timeout=RENDER_TIMEOUT_SECONDS, check=False
    )
    if result.returncode:
        raise RuntimeError(f"d2 failed on {source}:\n{result.stderr}")
    return target.read_bytes()


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def write_d2(out: Path, model: DomainModel, plan: DiagramPlan, refs: Counter[tuple[str, str]]) -> list[Path]:
    """Write ``classes.d2``, the overview and every diagram's source; return the sources to render."""
    _write(out / CLASSES_FILE, CLASSES_D2)
    sources = [_write(out / f"{OVERVIEW_FILE}.d2", render_overview(model, plan, refs))]
    for diagrams in plan.diagrams.values():
        sources += [_write(out / f"{d.path}.d2", render_diagram(model, plan, d)) for d in diagrams]
    return sources


def render_all(out: Path, sources: list[Path]) -> list[Determinism]:
    """Render every source twice, the second time into a scratch directory, and compare the bytes."""
    results = []
    with tempfile.TemporaryDirectory() as scratch:
        for source in sources:
            relative = source.relative_to(out).with_suffix(".svg")
            first = render_d2(source, out / relative)
            second = render_d2(source, Path(scratch) / "second.svg")
            results.append(Determinism(relative.as_posix(), first == second, first, second))
    return results


def determinism_report(results: list[Determinism]) -> str:
    differing = [result for result in results if not result.same]
    lines = [f"{len(results) - len(differing)} of {len(results)} diagrams rendered twice to the same bytes."]
    for result in differing:
        lines.append(f"differs: {result.name}: {_first_difference(result.first, result.second)}")
    return "\n".join(lines) + "\n"


def _first_difference(first: bytes, second: bytes) -> str:
    one, two = first.decode().splitlines(), second.decode().splitlines()
    for number, (left, right) in enumerate(zip(one, two, strict=False), start=1):
        if left != right:
            return f"line {number}: {left[:160]!r} != {right[:160]!r}"
    return f"lengths {len(first)} and {len(second)}"


# --- the current Mermaid diagrams


def mermaid_blocks(markdown: str) -> dict[str, list[str]]:
    """The Mermaid blocks of the Markdown page by the heading above them: a contract, a directory, or the overview."""
    found: dict[str, list[str]] = {}
    heading, block = "", None
    for line in markdown.splitlines():
        match = _HEADING.match(line)
        if match:
            heading = match.group(1)
            heading = OVERVIEW_HEADING if heading.startswith(OVERVIEW_HEADING) else heading
        elif line.strip() == "```mermaid":
            block = []
        elif line.strip() == "```" and block is not None:
            found.setdefault(heading, []).append("\n".join(block) + "\n")
            block = None
        elif block is not None:
            block.append(line)
    return found


def _chrome() -> str:
    configured = os.environ.get("PUPPETEER_EXECUTABLE_PATH")
    if configured:
        return configured
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
        if shutil.which(name):
            return shutil.which(name) or name
    return str(CHROME_APP)


def render_mermaid(blocks: dict[str, list[str]], plan: DiagramPlan, out: Path) -> dict[str, Path]:
    """Render the Mermaid page's diagrams to ``out``; return the SVG of each contract, and ``OVERVIEW_HEADING``."""
    if not MMDC.is_file():
        raise RuntimeError(f"no mermaid-cli at {MMDC}: run `pnpm --dir contracts install --frozen-lockfile`")
    headings = list(blocks)
    page = "\n".join(f"```mermaid\n{blocks[heading][0]}```\n" for heading in headings)
    written: dict[str, Path] = {}
    with tempfile.TemporaryDirectory() as scratch:
        work = Path(scratch)
        config = f'{{"executablePath": "{_chrome()}", "args": ["--no-sandbox"]}}'
        command = [str(MMDC), "--quiet", "-p", str(_write(work / "puppeteer.json", config))]
        command += ["-i", str(_write(work / "page.md", page)), "-o", str(work / "out.md"), "-e", "svg"]
        result = subprocess.run(
            command, capture_output=True, text=True, timeout=RENDER_TIMEOUT_SECONDS, check=False
        )
        rendered = {heading: work / f"out-{number}.svg" for number, heading in enumerate(headings, start=1)}
        if result.returncode or not all(path.is_file() for path in rendered.values()):
            raise RuntimeError(f"mmdc failed:\n{result.stdout}{result.stderr}")
        written[OVERVIEW_HEADING] = _copy(rendered[OVERVIEW_HEADING], out / "mermaid-overview.svg")
        for stem in plan.diagrams:
            source = rendered.get(stem) or rendered.get(stem.split("/")[0])
            if source:
                written[stem] = _copy(source, out / stem / "mermaid.svg")
    return written


def _copy(source: Path, target: Path) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    return target


# --- index.html


def _anchor(path: str) -> str:
    return "d2-" + path.replace("/", "-")


def _inline_svg(svg: bytes, page: str, known: set[str]) -> str:
    """The SVG as markup, with the links between diagrams turned into links within the page."""
    text = re.sub(r"^<\?xml[^>]*\?>\s*", "", svg.decode())

    def link(match: re.Match[str]) -> str:
        target = posixpath.normpath(posixpath.join(posixpath.dirname(page), match.group(1)))
        path = target.removesuffix(".svg")
        return f'href="#{_anchor(path)}"' if path in known else match.group(0)

    return re.sub(r'href="([^"#]+\.svg)"', link, text)


def _figure(path: str, caption: str, svg: str) -> str:
    return f'<figure id="{_anchor(path)}"><figcaption>{html.escape(caption)}</figcaption><div class="svg">{svg}</div></figure>'


def _contract_section(model: DomainModel, plan: DiagramPlan, stem: str, out: Path, known: set[str]) -> str:
    diagrams = plan.diagrams[stem]
    classes = sum(len(d.owned) for d in diagrams)
    parts = [f'<section id="{_anchor(stem)}"><h3>{html.escape(stem)}</h3>']
    parts.append(f"<p>{classes} classes in {len(diagrams)} D2 diagram(s).</p>")
    for diagram in diagrams:
        caption = f"{diagram.path}: {len(diagram.owned)} classes, {len(stubs_of(model, diagram))} stubs"
        svg = _inline_svg((out / f"{diagram.path}.svg").read_bytes(), diagram.path, known)
        parts.append(_figure(diagram.path, caption, svg))
    if (out / stem / "mermaid.svg").is_file():
        image = f"{stem}/mermaid.svg"
        parts.append(
            f"<details><summary>The current Mermaid diagram of {html.escape(stem)}</summary>"
            f'<div class="svg"><img src="{html.escape(image)}" alt="Mermaid diagram of {html.escape(stem)}"></div></details>'
        )
    return "".join(parts) + "</section>"


def write_index(out: Path, model: DomainModel, plan: DiagramPlan) -> Path:
    """``index.html``: the overview, then the contracts grouped by directory, each with its diagrams."""
    known = {diagram.path for diagrams in plan.diagrams.values() for diagram in diagrams} | {OVERVIEW_FILE}
    groups: dict[str, list[str]] = {}
    for stem in plan.diagrams:
        groups.setdefault(stem.split("/")[0], []).append(stem)
    nav = "".join(
        f"<h4>{html.escape(group)}</h4>"
        + "".join(f'<a href="#{_anchor(stem)}">{html.escape(stem.split("/", 1)[-1])}</a>' for stem in stems)
        for group, stems in groups.items()
    )
    body = [
        f'<section id="{_anchor(OVERVIEW_FILE)}"><h2>Overview</h2>',
        _figure(
            OVERVIEW_FILE,
            "Documents and libraries of the record, edges labelled by $ref count",
            _inline_svg((out / f"{OVERVIEW_FILE}.svg").read_bytes(), f"{OVERVIEW_FILE}.svg", known),
        ),
    ]
    if (out / "mermaid-overview.svg").is_file():
        body.append(
            '<details><summary>The current Mermaid overview</summary><div class="svg">'
            '<img src="mermaid-overview.svg" alt="Mermaid overview"></div></details>'
        )
    body.append("</section>")
    for group, stems in groups.items():
        body.append(f"<h2>{html.escape(group)}</h2>")
        body += [_contract_section(model, plan, stem, out, known) for stem in stems]
    page = _PAGE.format(nav=nav, body="\n".join(body))
    return _write(out / "index.html", page)


_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>benchhand domain model: D2 preview</title>
<style>
body {{ font: 15px/1.4 system-ui, sans-serif; margin: 0; display: flex; }}
nav {{ position: sticky; top: 0; align-self: flex-start; height: 100vh; overflow: auto; width: 230px; flex: none;
  padding: 12px; background: #f1f5f9; box-sizing: border-box; }}
nav h4 {{ margin: 14px 0 4px; }} nav a {{ display: block; color: #1d4ed8; text-decoration: none; padding: 1px 0; }}
main {{ padding: 12px 24px; min-width: 0; flex: 1; }}
figure {{ margin: 12px 0 28px; }} figcaption {{ font-weight: 600; color: #334155; margin-bottom: 4px; }}
.svg {{ overflow: auto; border: 1px solid #e2e8f0; background: #fff; padding: 8px; }}
.svg svg {{ max-width: none; }} .svg img {{ max-width: none; }}
details {{ margin: 8px 0 24px; }}
</style></head><body><nav><a href="#d2-overview"><b>Overview</b></a>{nav}</nav>
<main><h1>Domain model: D2 preview</h1>
<p>Each contract is split into aggregates; a grey box is a type of another aggregate and links to it.
A table row is a field: <code>req</code> marks a required one.</p>
{body}
</main></body></html>
"""


# --- the whole preview


def write_preview(out: Path, contracts: list[Contract], *, mermaid: bool = True) -> str:
    """Write the preview below ``out``; return the summary."""
    check_d2_version()
    model = build_model(contracts)
    plan = plan_diagrams(model)
    sources = write_d2(out, model, plan, ref_counts(contracts))
    results = render_all(out, sources)
    report = determinism_report(results)
    _write(out / "determinism.txt", report)
    if mermaid:
        render_mermaid(mermaid_blocks(render_domain_model(contracts)), plan, out)
    write_index(out, model, plan)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write the D2 domain-model preview.")
    parser.add_argument("out", type=Path)
    parser.add_argument("--no-mermaid", action="store_true", help="skip the Mermaid comparison SVGs")
    args = parser.parse_args(argv)
    contracts = load_contracts(REPO_ROOT / SCHEMAS_OUT)
    print(write_preview(args.out, contracts, mermaid=not args.no_mermaid), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
