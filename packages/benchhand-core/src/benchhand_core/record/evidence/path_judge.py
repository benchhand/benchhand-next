"""Judge each path a ledger cites against the project's filesystem and git: the observation half of the path
rules (prototype evidence_paths.py `ProjectPaths`, lines 112-163, at release.toml reference_commit 412b5d9).

Only the reader calls this; the assessment reads the verdicts it returns
(benchhand_core.record.evidence.paths).
"""

from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from benchhand_core.record.evidence.paths import BUNDLE_KINDS, PathQuery, Verdict

_MANAGED_VERSION = re.compile(r"^hw/versions/v[1-9][0-9]*/.+")
_VERSION = re.compile(r"v[1-9][0-9]*")


@dataclass(frozen=True)
class GitView:
    """What git says about the project root. `tracked` lists the files a work tree tracks (empty for a work
    tree with no tracked files, which then refuses every unmanaged citation, as the prototype does);
    `not_worktree` is set when git confirmed the root is no work tree, so only the layout and scratch rules
    apply; `unavailable` says why git could not be read (no git, an unreadable index), which refuses every
    unmanaged citation rather than letting it through."""

    tracked: frozenset[str] = frozenset()
    not_worktree: bool = False
    unavailable: str | None = None


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    env = {**os.environ, "LC_ALL": "C"}  # the not-a-repository message is matched in English
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, check=False, env=env)


def git_view(root: Path) -> GitView:
    """Observe git at `root` (evidence_paths.py:119-128). The prototype reads any `git ls-files` failure as
    "no work tree"; here only a rev-parse that says so is, and any other failure leaves git unavailable."""
    try:
        inside = _git(root, "rev-parse", "--is-inside-work-tree")
    except OSError as error:
        return GitView(unavailable=f"git cannot run: {error}")
    stderr = inside.stderr.decode("utf-8", "replace").strip()
    if inside.returncode != 0 and "not a git repository" in stderr:
        return GitView(not_worktree=True)
    if inside.returncode != 0 or inside.stdout.strip() != b"true":
        return GitView(unavailable=f"git rev-parse failed: {stderr or inside.stdout.decode().strip()}")
    listed = _git(root, "ls-files", "-z")
    if listed.returncode != 0:
        return GitView(unavailable=f"git ls-files failed: {listed.stderr.decode('utf-8', 'replace').strip()}")
    return GitView(frozenset(name for name in listed.stdout.decode("utf-8", "replace").split("\0") if name))


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

    def __init__(self, root: Path, git: GitView) -> None:
        self.root = Path(root).resolve()
        self.git = git

    def _is_tracked(self, rel: str) -> bool:
        tracked = self.git.tracked
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
        if is_managed or self.git.not_worktree:
            return Verdict(rel, None, is_managed)
        if self.git.unavailable is not None:
            return Verdict(
                rel, f"cannot be checked against git ({self.git.unavailable}) and is not a record result"
            )
        if not self._is_tracked(rel):
            return Verdict(rel, "is not tracked by git and not a record result")
        return Verdict(rel, None, is_managed)


def judge_all(root: Path, queries: Iterable[PathQuery]) -> dict[PathQuery, Verdict]:
    judge = PathJudge(root, git_view(root))
    return {query: judge.judge(query) for query in sorted(queries, key=lambda q: (q.cited, q.structured))}
