# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

"""Checks the migration issue register and writes its summary page.

``docs/migration/issue-register.yaml`` records every issue found in the prototype, by the test project and by
the prototype's lead sessions, and every bead in the prototype's ledger, with how benchhand-next addresses
it. ``python -m issue_register check`` validates it against ``tools/issues/issue-register.schema.json`` and
the reference map; ``--write`` regenerates ``docs/migration/issue-register.md``. ``python -m issue_register
sync`` compares it with the live ledger and the private files listed in ``tools/issues/tracked-sources.yaml``;
it runs locally only.
"""
