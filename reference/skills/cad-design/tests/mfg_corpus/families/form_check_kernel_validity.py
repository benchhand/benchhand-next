"""Kernel validity on cad-design's deliberate defect models (reused in place, parameter-edited for the twin), as a release
sees it: the cad.readback obligation of the packet cad-model check publishes for the built version.

TST-0101: equal-radius bores meeting in a T leave an unorientable face (brep_invalid). TST-0102: fillets rolled across
2-5 degree outline kinks come out out of tolerance (step_readback). The twin of each is the model with one edit: an entry
bore 0.8 of the run's radius, or the fillets left off. Each model becomes the sole part of a one-part project, which
cad_model builds and checks.
"""

from corpus import Family, Outcome, Pair
from support import SKILLS, readback_verdict

DEFECTS = SKILLS / "cad-design" / "tests" / "fixtures" / "defects" / "cadquery"


def kernel_verdict(pn: str, edit: tuple[str, str] | None) -> Outcome:
    text = (DEFECTS / f"{pn}.py").read_text(encoding="utf-8")
    if edit:
        if edit[0] not in text:
            raise RuntimeError(f"{pn}.py has no {edit[0]!r} to edit")
        text = text.replace(*edit)
    return readback_verdict(text)


def t_bore(mutant: bool) -> Outcome:
    return kernel_verdict("TST-0101", None if mutant else ('center(p["entry_x"], 0).circle(r)', 'center(p["entry_x"], 0).circle(0.8 * r)'))


def kinked_fillets(mutant: bool) -> Outcome:
    return kernel_verdict("TST-0102", None if mutant else ('return body.fillet(p["edge_fillet"], silhouette)', "return body"))


FAMILY = Family(
    id="form_check_kernel_validity", check="cad-model check cad.readback packet (brep_validity, step_readback)",
    owner="cad-design",
    pairs=(
        Pair("t_bore_unorientable_face", "equal-radius bores meeting in a T", t_bore),
        Pair("kinked_outline_fillets", "1.5 mm fillets rolled across 2-5 degree kinks", kinked_fillets),
    ))
