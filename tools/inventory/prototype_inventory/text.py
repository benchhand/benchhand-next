# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

"""Docstring text."""

from __future__ import annotations


def first_line(docstring: str | None) -> str:
    """The first non-empty line of an already cleaned docstring, or an empty string."""
    for line in (docstring or "").splitlines():
        if line.strip():
            return line.strip()
    return ""
