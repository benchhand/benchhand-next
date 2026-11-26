"""Check the map against a reference copy of the prototype."""

from __future__ import annotations

from pathlib import Path

from .entries import Entry, MapError, ReferenceMap, pattern_regex

REQUIRED_PATTERNS = (
    "skills/*/scripts/**/*.py",
    "skills/*/SKILL.md",
    "agents/*.md",
    "harness/*.py",
    "harness/*/agents/*",
    "harness/*/commands/*",
)
"""What needs an entry: each skill's scripts and SKILL.md, each agent, and the harness modules and outputs."""
IGNORED_NAMES = ("__pycache__",)


def reference_files(roots: list[Path]) -> set[str]:
    """Every file below the reference roots, as ``/``-separated paths relative to their root."""
    found: set[str] = set()
    for root in roots:
        for path in root.rglob("*"):
            relative = path.relative_to(root)
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
    """Fail when a required prototype file has no entry, or an entry names a path that doesn't exist."""
    files = reference_files(roots)
    matchers = [(entry, pattern_regex(entry.path)) for entry in reference.entries]
    problems = [
        f"{entry.path}: names a path that doesn't exist in the reference copy"
        for entry, matcher in matchers
        if not any(matcher.match(path) for path in files)
    ]
    for path in required_files(files):
        hits = [entry.path for entry, matcher in matchers if matcher.match(path)]
        if not hits:
            problems.append(f"{path}: a prototype file with no entry")
        elif len(hits) > 1:
            problems.append(f"{path}: matched by {len(hits)} entries ({', '.join(hits)})")
    problems += _skills_without_entries(files, reference.entries)
    if problems:
        raise MapError(problems)


def _skills_without_entries(files: set[str], entries: tuple[Entry, ...]) -> list[str]:
    inside_skills = [path for path in files if path.startswith("skills/") and path.count("/") > 1]
    skills = sorted({path.split("/")[1] for path in inside_skills})
    return [
        f"skills/{skill}/: a prototype skill with no entry"
        for skill in skills
        if not any(entry.path.startswith(f"skills/{skill}/") for entry in entries)
    ]


def check_homes(reference: ReferenceMap, repo_root: Path) -> None:
    """A ported entry's home must exist in this repository."""
    problems = [
        f"{entry.path}: ported, but {home} doesn't exist"
        for entry in reference.entries
        if entry.status == "ported"
        for home in entry.homes
        if not (repo_root / home).exists()
    ]
    if problems:
        raise MapError(problems)
