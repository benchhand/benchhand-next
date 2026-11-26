"""Check the map against a reference copy of the prototype."""

from __future__ import annotations

import subprocess
from pathlib import Path

from .entries import BUILT, Entry, MapError, ReferenceMap, pattern_regex

STAMP_FILE = ".reference-commit"
"""A file in a copy without ``.git`` that holds the commit the copy was taken at."""

REQUIRED_PATTERNS = (
    "skills/*/scripts/**/*.py",
    "skills/*/SKILL.md",
    "agents/*.md",
    "harness/*.py",
    "harness/*/agents/*",
    "harness/*/commands/*",
)
"""What needs an entry: each skill's scripts and SKILL.md, each agent, and the harness modules and outputs."""
IGNORED_NAMES = ("__pycache__", ".git")


def reference_files(roots: list[Path]) -> set[str]:
    """Every file below the reference roots, as ``/``-separated paths relative to their root."""
    found: set[str] = set()
    for root in roots:
        for path in root.rglob("*"):
            relative = path.relative_to(root)
            if relative.as_posix() == STAMP_FILE:
                continue
            if path.is_file() and not set(IGNORED_NAMES) & set(relative.parts):
                found.add(relative.as_posix())
    return found


def required_files(files: set[str]) -> list[str]:
    """The files that need an entry: the prototype's scripts, skills, agents and harness modules, no tests."""
    patterns = [pattern_regex(pattern) for pattern in REQUIRED_PATTERNS]
    return sorted(
        path for path in files if any(pattern.match(path) for pattern in patterns) and not _is_test(path)
    )


def _is_test(path: str) -> bool:
    return path.rsplit("/", 1)[-1].startswith("test_")


def check_coverage(reference: ReferenceMap, roots: list[Path]) -> None:
    """Fail when a required prototype file has no entry, any file has two, or an entry names a path that
    doesn't exist."""
    files = reference_files(roots)
    matchers = [(entry, pattern_regex(entry.path)) for entry in reference.entries]
    problems = [
        f"{entry.path}: names a path that doesn't exist in the reference copy"
        for entry, matcher in matchers
        if not any(matcher.match(path) for path in files)
    ]
    required = set(required_files(files))
    for path in sorted(files):
        hits = [entry.path for entry, matcher in matchers if matcher.match(path)]
        if not hits and path in required:
            problems.append(f"{path}: a prototype file with no entry")
        elif len(hits) > 1:
            problems.append(f"{path}: matched by {len(hits)} entries ({', '.join(hits)})")
    problems += _skills_without_entries(files, reference.entries)
    if problems:
        raise MapError(problems)


def copy_commit(reference_dir: Path) -> str | None:
    """The commit a reference copy holds: its git ``HEAD``, else the SHA in its ``STAMP_FILE``, else None."""
    if (reference_dir / ".git").exists():
        result = subprocess.run(
            ["git", "-C", str(reference_dir), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise MapError([f"{reference_dir}: its git HEAD doesn't read: {result.stderr.strip()}"])
        return result.stdout.strip()
    stamp = reference_dir / STAMP_FILE
    return stamp.read_text(encoding="utf-8").strip() if stamp.is_file() else None


def check_copy_commit(reference_dir: Path, pinned: str) -> bool:
    """Fail when the copy says which commit it holds and that isn't ``pinned``; False when it doesn't say."""
    found = copy_commit(reference_dir)
    if found is None:
        return False
    if found != pinned:
        raise MapError([f"{reference_dir} holds {found}, not release.toml's reference_commit {pinned}"])
    return True


def _skills_without_entries(files: set[str], entries: tuple[Entry, ...]) -> list[str]:
    inside_skills = [path for path in files if path.startswith("skills/") and path.count("/") > 1]
    skills = sorted({path.split("/")[1] for path in inside_skills})
    return [
        f"skills/{skill}/: a prototype skill with no entry"
        for skill in skills
        if not any(entry.path.startswith(f"skills/{skill}/") for entry in entries)
    ]


def check_homes(reference: ReferenceMap, repo_root: Path) -> None:
    """A ported or partial entry's home must exist in this repository."""
    problems = [
        f"{entry.path}: {entry.status}, but {home} doesn't exist"
        for entry in reference.entries
        if entry.status in BUILT
        for home in entry.homes
        if not (repo_root / home).exists()
    ]
    if problems:
        raise MapError(problems)
