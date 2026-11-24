"""Regenerate every output from contracts/, and compare a fresh generation with the tree (drift check)."""

from __future__ import annotations

import filecmp
import shutil
import tempfile
from pathlib import Path

from .docs import write_docs
from .examples import write_examples
from .python_models import write_python, write_schemas
from .sources import (
    CONTRACTS_DIR,
    DOCS_OUT,
    EXAMPLES_OUT,
    MODELS_OUT,
    OUTPUT_DIRS,
    REPO_ROOT,
    SCHEMAS_OUT,
    TYPESCRIPT_OUT,
    load_contracts,
)
from .typescript import write_typescript


def generate(out_root: Path, contracts_dir: Path = REPO_ROOT / CONTRACTS_DIR) -> None:
    """Write every file generated from ``contracts_dir`` below ``out_root``.

    Everything is generated into a scratch tree first; the output directories under ``out_root`` are
    replaced as a whole only when every generator succeeded, so the outputs of a deleted schema disappear
    and a failed run leaves the previous outputs in place.
    """
    with tempfile.TemporaryDirectory(prefix="contracts-gen-") as scratch:
        fresh_root = Path(scratch)
        _generate_into(fresh_root, contracts_dir)
        for rel_dir in OUTPUT_DIRS:
            shutil.rmtree(out_root / rel_dir, ignore_errors=True)
            if (fresh_root / rel_dir).is_dir():
                shutil.copytree(fresh_root / rel_dir, out_root / rel_dir)


def _generate_into(out_root: Path, contracts_dir: Path) -> None:
    contracts = load_contracts(contracts_dir)
    write_python(contracts, contracts_dir, out_root / MODELS_OUT)
    write_schemas(contracts, contracts_dir, out_root / SCHEMAS_OUT)
    write_examples(contracts, out_root / EXAMPLES_OUT)
    write_typescript(contracts, contracts_dir, out_root / TYPESCRIPT_OUT)
    write_docs(contracts, out_root / DOCS_OUT)


def drift(tree_root: Path = REPO_ROOT, contracts_dir: Path = REPO_ROOT / CONTRACTS_DIR) -> list[str]:
    """Files under ``tree_root`` that differ from a fresh generation, as ``<status> <path>`` lines."""
    with tempfile.TemporaryDirectory(prefix="contracts-check-") as scratch:
        fresh_root = Path(scratch)
        _generate_into(fresh_root, contracts_dir)
        return [line for rel_dir in OUTPUT_DIRS for line in _compare(tree_root, fresh_root, rel_dir)]


def _compare(repo_root: Path, fresh_root: Path, rel_dir: str) -> list[str]:
    committed = _files(repo_root / rel_dir)
    fresh = _files(fresh_root / rel_dir)
    lines = [f"missing  {rel_dir}/{rel}" for rel in sorted(fresh - committed)]
    lines += [f"extra    {rel_dir}/{rel}" for rel in sorted(committed - fresh)]
    for rel in sorted(committed & fresh):
        if not filecmp.cmp(repo_root / rel_dir / rel, fresh_root / rel_dir / rel, shallow=False):
            lines.append(f"changed  {rel_dir}/{rel}")
    return lines


def _files(root: Path) -> set[str]:
    if not root.is_dir():
        return set()
    ignored = {"__pycache__"}
    return {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and not ignored.intersection(path.relative_to(root).parts)
    }
