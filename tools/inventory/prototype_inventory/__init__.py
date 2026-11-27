# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

"""Writes the function-level inventory of the prototype: every public function, class and command line.

``python -m prototype_inventory`` reads the prototype's scripts with ``ast`` (it never imports them),
joins each file to its entry in ``docs/architecture/reference-map.yaml`` and writes
``docs/architecture/prototype-inventory.md`` and ``docs/architecture/prototype-inventory.json``. Without
``--write`` it checks that the committed files match. The inventory covers the Python files that
``reference_map`` requires an entry for: each skill's ``scripts/`` and the harness modules, tests left out.
Names that start with an underscore are private and left out, methods included; nested definitions too.
"""
