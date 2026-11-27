# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

"""The evidence service: the status of every obligation of one built version, and its acceptance digest.

The acceptance digest (evidence_sha256) covers every source artifact the record names, as well as the
files the prototype's digest covers. It is not byte-compatible with a prototype digest: the prototype
collects only the artifacts its `source()` call sites read (manufacturing_intent.py:1345), so for example
a bought part's procurement specification artifact falls outside it.
"""
