"""Judge each path a ledger cites against the project's filesystem and git: the observation half of the path
rules (prototype evidence_paths.py `ProjectPaths`, lines 112-163, at release.toml reference_commit 412b5d9).

Only the reader calls this; the assessment reads the verdicts it returns
(benchhand_core.record.evidence.paths).
"""

from __future__ import annotations

import re
import subprocess
from collections.abc import Iterable
from pathlib import Path, PurePosixPath

from benchhand_core.record.evidence.paths import BUNDLE_KINDS, PathQuery, Verdict

_MANAGED_VERSION = re.compile(r"^hw/versions/v[1-9][0-9]*/.+")
_VERSION = re.compile(r"v[1-9][0-9]*")


def tracked_files(root: Path) -> frozenset[str] | None:
    """The files git tracks below `root`, relative to it; None when `root` is no git work tree, so only the
    layout and scratch rules apply."""
    try:
        done = subprocess.run(["git", "-C", str(root), "ls-files", "-z"], capture_output=True, check=False)
    except OSError:
        return None
    if done.returncode != 0:
        return None
    return frozenset(name for name in done.stdout.decode("utf-8", "replace").split("\0") if name)


def managed(rel: str) -> bool:
    """A record-managed result location: a sealed hw/versions/<V>/ or a bundle hw/<kind>/<V>/<S>/."""
    parts = PurePosixPath(rel).parts
    if any(part.startswith(".") for part in parts):
        return False
    if _MANAGED_VERSION.match(rel):
        return True
    if len(parts) < 4 or parts[0] != "hw" or parts[1] not in BUNDLE_KINDS:
        return False
    return _VERSION.fullmatch(parts[2]) is not None


class PathJudge:
    """The inside rule for one project root (evidence_paths.py:112)."""

    def __init__(self, root: Path, tracked: frozenset[str] | None) -> None:
        self.root = Path(root).resolve()
        self.tracked = tracked

    def _is_tracked(self, rel: str) -> bool:
        tracked = self.tracked or frozenset()
        return rel in tracked or any(name.startswith(f"{rel}/") for name in tracked)

    def judge(self, query: PathQuery) -> Verdict:
        """evidence_paths.py:135 `judge`. A structured path that does not exist is not refused here: the
        inventory reports it missing."""
        cited = query.cited
        if cited.startswith("~"):
            return Verdict(None, "is in the home directory")
        candidates = [cited]
        if not query.structured and not cited.startswith(("/", "..", ".cad-work", "hw/")):
            candidates.append(f"hw/{cited}")
        resolved = [(self.root / c).resolve() for c in candidates]
        full = next((found for found in resolved if found.exists()), (self.root / cited).resolve())
        if not full.is_relative_to(self.root):
            return Verdict(None, "is outside the project root")
        rel = full.relative_to(self.root).as_posix()
        if ".cad-work" in PurePosixPath(rel).parts or rel == "hw/.cad" or rel.startswith("hw/.cad/"):
            return Verdict(rel, "is scratch space, not the record")
        is_managed = managed(rel)
        if not full.exists():
            return Verdict(rel, None if query.structured else "does not exist", is_managed)
        if not is_managed and self.tracked is not None and not self._is_tracked(rel):
            return Verdict(rel, "is not tracked by git and not a record result")
        return Verdict(rel, None, is_managed)


def judge_all(root: Path, queries: Iterable[PathQuery]) -> dict[PathQuery, Verdict]:
    judge = PathJudge(root, tracked_files(root))
    return {query: judge.judge(query) for query in sorted(queries, key=lambda q: (q.cited, q.structured))}
