# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

"""Kernel validity on cad-design's deliberate defect models (reused in place, parameter-edited for the twin) and one
corpus fixture, as a release sees it: the cad.readback obligation of the packet cad-model check publishes for the built
version.

TST-0101: equal-radius bores meeting in a T leave an unorientable face. Both brep_validity and step_readback catch it.
TST-0102: fillets rolled across 2-5 degree outline kinks come out out of tolerance. Only step_readback catches it.
fixtures/form_check_kernel_validity/vertex_off_its_edges: a cube corner vertex off its edges. The STEP read-back heals it
inside the read-back tolerance, so only the in-memory validity of brep_validity catches it. The twin of each is the model
with one edit: an entry bore 0.8 of the run's radius, the fillets left off, or the vertex left in place. Each model
becomes the sole part of a one-part project, which cad_model builds and checks.

The part is made in a different state (part.yaml `manufacture.relationship: different`): build() is the installed
definition under test, the defect in the mutant, and build_manufacture() is the twin's geometry in both. cad_model run
judges the manufacturing state alone, so it seals the mutant's version. Made as installed, the same run would refuse
it, and the case would never reach cad_model check (issue #192). The check's brep_validity and step_readback then
judge the installed definition.

The state's volume tolerance is the tightest round value that lets the mutant seal: the run's identity check compares
the two states' kernel volumes. TST-0101: 700 mm^3 (volume_abs_tolerance_mm3). The kernel volume of the invalid solid
reads about 697 mm^3 (13.5 %) above the twin's, beyond the schema's 0.1 relative cap. TST-0102: 0.006 relative. The
fillets take about 0.53 % off the volume. The cube: 1e-9 relative, the same-state default of the layout. Moving the
vertex leaves the kernel volume as it was. The twin has no gap: its states are one geometry.
"""

import ast
from pathlib import Path

from corpus import Family, Outcome, Pair
from support import SKILLS, readback_verdict

DEFECTS = SKILLS / "cad-design" / "tests" / "fixtures" / "defects" / "cadquery"
FIXTURES = SKILLS / "cad-design" / "tests" / "mfg_corpus" / "fixtures" / "form_check_kernel_validity"


def made_as_twin(source: Path, edit: tuple[str, str], mutant: bool, tolerance: dict[str, float]) -> Outcome:
    """The verdict on the model at `source` as installed (the defect, or with `edit` for the twin), made in the twin's
    geometry."""
    text = source.read_text(encoding="utf-8")
    if edit[0] not in text:
        raise RuntimeError(f"{source.name} has no {edit[0]!r} to edit")
    repaired = text.replace(*edit)
    build = next(node for node in ast.parse(repaired).body if isinstance(node, ast.FunctionDef) and node.name == "build")
    manufactured = (ast.get_source_segment(repaired, build) or "").replace("def build(", "def build_manufacture(", 1)
    state = {"relationship": "different", "state": "twin", "reason": "corpus_twin_geometry", "decision": "DR-001",
             **tolerance}
    return readback_verdict(f"{text if mutant else repaired}\n\n{manufactured}\n", manufacture=state)


def t_bore(mutant: bool) -> Outcome:
    return made_as_twin(DEFECTS / "TST-0101.py",
                        ('center(p["entry_x"], 0).circle(r)', 'center(p["entry_x"], 0).circle(0.8 * r)'),
                        mutant, {"volume_abs_tolerance_mm3": 700.0})


def kinked_fillets(mutant: bool) -> Outcome:
    return made_as_twin(DEFECTS / "TST-0102.py", ('return body.fillet(p["edge_fillet"], silhouette)', "return body"),
                        mutant, {"volume_rel_tolerance": 0.006})


def vertex_off_its_edges(mutant: bool) -> Outcome:
    return made_as_twin(FIXTURES / "vertex_off_its_edges" / "mutant.py",
                        ("moved = gp_Pnt(point.X() + d, point.Y() + d, point.Z() + d)", "moved = point"),
                        mutant, {"volume_rel_tolerance": 1e-9})


FAMILY = Family(
    id="form_check_kernel_validity", check="cad-model check cad.readback packet (brep_validity, step_readback)",
    owner="cad-design",
    pairs=(
        Pair("t_bore_unorientable_face", "equal-radius bores meeting in a T", t_bore),
        Pair("kinked_outline_fillets", "1.5 mm fillets rolled across 2-5 degree kinks", kinked_fillets),
        Pair("vertex_off_its_edges", "a cube corner vertex 1e-5 mm off its edges at a 1e-7 mm tolerance",
             vertex_off_its_edges),
    ))
