# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

"""Each package carries the repository's licence text as a regular file, and a wheel built from its sdist
alone, with no checkout around it, contains that text."""

from __future__ import annotations

import os
import shutil
import subprocess
import tarfile
import zipfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
ROOT_LICENCE = REPO_ROOT / "LICENSE"
PACKAGES = sorted(path.parent for path in (REPO_ROOT / "packages").glob("*/pyproject.toml"))
UV = shutil.which("uv")


def test_there_are_packages_to_check() -> None:
    assert len(PACKAGES) == 5


@pytest.mark.parametrize("package", PACKAGES, ids=lambda package: package.name)
def test_the_package_licence_is_a_regular_file_equal_to_the_root_licence(package: Path) -> None:
    licence = package / "LICENSE"
    # A symlink becomes a text file holding its target path where core.symlinks is false (Windows, some
    # archives), and hatchling's license-files glob would still match it.
    assert not licence.is_symlink(), f"{licence} is a symlink; copy the root LICENSE instead"
    assert licence.read_bytes() == ROOT_LICENCE.read_bytes()


@pytest.mark.wheel
@pytest.mark.skipif(UV is None, reason="needs uv")
@pytest.mark.parametrize("package", PACKAGES, ids=lambda package: package.name)
def test_a_wheel_built_from_the_sdist_holds_the_licence(package: Path, tmp_path: Path) -> None:
    assert UV is not None
    env = {key: value for key, value in os.environ.items() if key not in ("PYTHONPATH", "VIRTUAL_ENV")}

    def run(*command: str | Path) -> None:
        result = subprocess.run(command, cwd=tmp_path, env=env, capture_output=True, text=True, check=False)
        assert result.returncode == 0, f"{command}:\n{result.stdout}{result.stderr}"

    sdist_dir, unpacked, wheel_dir = tmp_path / "sdist", tmp_path / "unpacked", tmp_path / "wheel"
    run(UV, "build", "--sdist", "--quiet", "--out-dir", sdist_dir, package)
    (sdist,) = sdist_dir.glob("*.tar.gz")
    with tarfile.open(sdist) as archive:
        archive.extractall(unpacked, filter="data")
    (source,) = unpacked.iterdir()
    # Built from the unpacked sdist, which has no workspace root above it.
    run(UV, "build", "--wheel", "--quiet", "--out-dir", wheel_dir, source)
    (wheel,) = wheel_dir.glob("*.whl")
    with zipfile.ZipFile(wheel) as archive:
        licences = [name for name in archive.namelist() if name.endswith(".dist-info/licenses/LICENSE")]
        assert len(licences) == 1, archive.namelist()
        assert archive.read(licences[0]) == ROOT_LICENCE.read_bytes()
