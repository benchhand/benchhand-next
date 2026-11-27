# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

"""OS and tool junk under hw/ that no record service reads, rewrites or counts.

TODO(benchhand-3fc): replace this fixed rule with the project ignore file mechanism once that bead lands.
"""

from __future__ import annotations

from fnmatch import fnmatchcase
from pathlib import PurePath

# Matched against every path component, so a junk directory hides everything below it.
JUNK_PATTERNS = (
    ".DS_Store",  # macOS Finder
    "._*",  # macOS AppleDouble resource forks
    "Thumbs.db",  # Windows Explorer
    "desktop.ini",  # Windows Explorer
    "__pycache__",  # Python bytecode
    "*.swp",  # vim swap files
    "*.swo",
    "*.swx",
    "*~",  # editor backups
    ".#*",  # emacs lock files
    "#*#",  # emacs auto-save files
)


def is_junk(relative: PurePath) -> bool:
    """Whether any component of `relative`, a path below the project root, is OS or tool junk."""
    return any(fnmatchcase(part, pattern) for part in relative.parts for pattern in JUNK_PATTERNS)
