"""form_check F0 kernel validity on cad-design's deliberate defect models (reused in place, parameter-edited for the twin).

TST-0101: equal-radius bores meeting in a T leave an unorientable face (brep_invalid). TST-0102: fillets rolled across
2-5 degree outline kinks come out out of tolerance (step_readback). The twin of each is a temporary copy with one edit: an entry bore 0.8 of the run's radius, or the fillets left off. The verdict is fail when form_check reports a blocking finding on that part.
"""

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from corpus import Family, Outcome, Pair, Skip
from support import SKILLS

DESIGN = SKILLS / "cad-design"
DEFECTS = DESIGN / "tests" / "fixtures" / "defects" / "cadquery"
HW = SKILLS.parent / "examples" / "lamp-arm" / "hw"


def _run(command: list[str]) -> dict[str, Any]:
    done = subprocess.run(command, capture_output=True, text=True, check=False, timeout=1800)
    try:
        report: dict[str, Any] = json.loads(done.stdout)
    except json.JSONDecodeError as error:
        raise RuntimeError(f"{command[3]} printed no JSON (exit {done.returncode}): {done.stderr[-800:]}") from error
    return report


def kernel_verdict(pn: str, edit: tuple[str, str] | None) -> Outcome:
    if shutil.which("uv") is None:
        raise Skip("uv is required to build the kernel environment")
    with tempfile.TemporaryDirectory() as tmp:
        models = Path(tmp) / "models"
        models.mkdir()
        text = (DEFECTS / f"{pn}.py").read_text(encoding="utf-8")
        if edit:
            if edit[0] not in text:
                raise RuntimeError(f"{pn}.py has no {edit[0]!r} to edit")
            text = text.replace(*edit)
        (models / f"{pn}.py").write_text(text, encoding="utf-8")
        out = Path(tmp) / "parts"
        built = _run([sys.executable, str(DESIGN / "scripts" / "build_reference.py"), "--kernel", "cadquery",
                      "--models", str(models), "--out", str(out)])
        if built.get("errors"):
            raise RuntimeError(f"build failed: {built['errors']}")
        report = _run(["uv", "run", "--script", str(DESIGN / "scripts" / "form_check.py"), "--hw", str(HW),
                       "--parts-dir", str(out), "--fidelity", "F0"])
    return "fail" if any(f["part"] == pn and f["blocking"] for f in report["findings"]) else "pass"


def t_bore(mutant: bool) -> Outcome:
    return kernel_verdict("TST-0101", None if mutant else ('center(p["entry_x"], 0).circle(r)', 'center(p["entry_x"], 0).circle(0.8 * r)'))


def kinked_fillets(mutant: bool) -> Outcome:
    return kernel_verdict("TST-0102", None if mutant else ('return body.fillet(p["edge_fillet"], silhouette)', "return body"))


FAMILY = Family(
    id="form_check_kernel_validity", check="cad-design/scripts/form_check.py F0 (brep_invalid, step_readback)",
    owner="cad-design",
    pairs=(
        Pair("t_bore_unorientable_face", "equal-radius bores meeting in a T", t_bore),
        Pair("kinked_outline_fillets", "1.5 mm fillets rolled across 2-5 degree kinks", kinked_fillets),
    ))
