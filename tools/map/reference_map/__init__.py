"""Checks the prototype-to-benchhand-next function map and writes its diagrams.

``docs/architecture/reference-map.yaml`` says where each prototype script, skill, agent and harness module
ends up. ``python -m reference_map`` checks that file. Given a reference copy of the prototype, it also
checks the file against that copy. ``--write`` regenerates ``docs/architecture/function-map.md`` from it.
"""
