"""Read what the evidence rules need about a built version, from hw/versions/<V>/ and hw/checks/<V>/.

This is the only module of the evidence service with I/O, and it only reads. It ports the prototype's
evidence.py `build_assessment` (skills/cad-record/scripts/evidence.py at release.toml reference_commit
412b5d9, lines 1686-1715), `collect_packets` (1207-1228), `_bundle_problems` (1185-1204) and the seal check
of layout.py `verify` (837-861) and `built_version` (942-957). Phase 2's snapshot, seal and verify service
owns version directories; it can replace this reader without touching the rules.
"""

from __future__ import annotations

import hashlib
import json
import os
import posixpath
from pathlib import Path
from typing import Any

from benchhand_contracts.base import ContractModel

from benchhand_core.record import contracts, documents
from benchhand_core.record.errors import RecordError
from benchhand_core.record.evidence import fingerprints as fp
from benchhand_core.record.evidence.built import (
    BuiltVersion,
    ChangedSinceBuild,
    FileState,
    NotComputed,
    Packet,
)
from benchhand_core.record.evidence.digest import LEDGER_FILES, MANIFEST, SOURCES_DIR, cited_paths
from benchhand_core.record.evidence.view import view
from benchhand_core.record.finding import Finding
from benchhand_core.record.model import MANUFACTURING_MODELS, Record
from benchhand_core.record.rules.assembly import inventory
from benchhand_core.record.store import check_version, read_document

SNAPSHOT_MANUFACTURING = ("capabilities", "materials", "selection")


class BuiltVersionError(RecordError):
    """The version is not built, or its directory fails its seal: build it again."""

    code = "evidence.version_unbuilt"


def _sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _safe_name(name: str) -> bool:
    return bool(name) and name not in (".", "..") and not any(char in name for char in "/\\\0")


def _tree(directory: Path) -> tuple[set[str], list[str], list[str]]:
    """(regular files, links or special files or unsafe names, empty directories) below `directory`."""
    files: set[str] = set()
    odd: list[str] = []
    empty: list[str] = []
    for root, folders, names in os.walk(directory, followlinks=False):
        rel = Path(root).relative_to(directory).as_posix()
        prefix = "" if rel == "." else f"{rel}/"
        for name in list(folders):
            if (Path(root) / name).is_symlink() or not _safe_name(name):
                odd.append(prefix + name)
                folders.remove(name)
        for name in names:
            path = Path(root) / name
            if path.is_symlink() or not path.is_file() or not _safe_name(name):
                odd.append(prefix + name)
            else:
                files.add(prefix + name)
        if prefix and not folders and not names:
            empty.append(rel)
    return files, sorted(odd), sorted(empty)


def _manifest(directory: Path) -> tuple[dict[str, Any] | None, str | None]:
    """A sealed directory's manifest.json, checked against record/bundle-manifest, or why it is none."""
    try:
        data = json.loads((directory / MANIFEST).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        return None, f"cannot read {MANIFEST}: {error}"
    found = contracts.violations("bundle-manifest", data)
    if found:
        return None, f"{MANIFEST} breaks its contract at {found[0].pointer or '/'}: {found[0].message}"
    return data, None


def seal_problems(directory: Path) -> list[str]:
    """Problems of a sealed directory against its manifest `files`: an unreadable manifest, a link, an
    empty directory, a missing, changed or unlisted file (layout.py:837). Empty when it verifies."""
    manifest, problem = _manifest(directory)
    if manifest is None:
        return [str(problem)]
    files, odd, empty = _tree(directory)
    problems = [f"{name} is a link, a special file or an unsafe name" for name in odd]
    problems += [f"{name}/ is an empty directory" for name in empty]
    for name, expected in sorted(manifest["files"].items()):
        if name == MANIFEST or posixpath.normpath(name) != name or name.startswith(("/", "../")):
            problems.append(f"the manifest lists an unsafe path {name!r}")
        elif name not in files:
            problems.append(f"{name} is listed but missing")
        elif _sha256(directory / name) != expected:
            problems.append(f"{name} changed after it was sealed")
    unlisted = sorted(files - set(manifest["files"]) - {MANIFEST})
    problems += [f"{name} is not in the manifest" for name in unlisted]
    return problems


def _stale(problems: list[str]) -> str:
    return f"stale: {problems[0]}" + (f" (+{len(problems) - 1} more)" if len(problems) > 1 else "")


def _packet_problem(directory: Path, version: str, version_sha: str) -> tuple[Any, str | None]:
    """The parsed result.json of a check bundle and why it is no valid packet (evidence.py:1185)."""
    try:
        data = json.loads((directory / "result.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        return None, f"cannot read result.json: {error}"
    found = contracts.violations("manufacturing-check-result", data)
    if found:
        where = found[0].pointer or "/"
        return None, f"result.json breaks manufacturing-check-result at {where}: {found[0].message}"
    if not (directory / MANIFEST).is_file():
        return None, f"it has no {MANIFEST}"
    problems = seal_problems(directory)
    if problems:
        return None, _stale(problems)
    manifest, _ = _manifest(directory)
    if manifest is None or manifest.get("version_manifest_sha256") != version_sha:
        return None, f"stale: it is bound to another build of {version}"
    return data, None


def collect_packets(
    hw: Path, version: str, version_sha: str
) -> tuple[tuple[Packet, ...], tuple[Finding, ...]]:
    """The packets sealed for `version` under hw/checks/<V>/<S>/result.json, and a packet.invalid finding for
    each bundle that is unreadable, no packet, unsealed, stale or bound to another build
    (evidence.py:1207)."""
    root = hw / "checks" / version
    packets, findings = [], []
    for directory in sorted(root.iterdir()) if root.is_dir() and not root.is_symlink() else []:
        if not (directory / "result.json").is_file():
            continue
        bundle = f"hw/checks/{version}/{directory.name}"
        data, problem = _packet_problem(directory, version, version_sha)
        if problem is not None:
            message = f"{bundle}: {problem}"
            data = {"code": "packet.invalid", "severity": "error", "path": f"{bundle}/result.json"}
            findings.append(Finding.model_validate({**data, "message": message}))
            continue
        packets.append(Packet(bundle, _sha256(directory / MANIFEST), data))
    return tuple(packets), tuple(findings)


def _snapshot_document(snapshot: Path, rel: str, contract: str, model: type[ContractModel]) -> Any:
    return read_document(snapshot, documents.DocumentSpec(rel, contract, "yaml", model))


def read_snapshot(snapshot: Path, current: Record) -> Record:
    """The record a version was built from (hw/versions/<V>/record/), with the current ledgers and
    decisions, which a snapshot does not hold. RecordError when a document does not read."""
    product_spec = documents.PRODUCT
    product_data = _snapshot_document(snapshot, "product.yaml", product_spec.contract, product_spec.model)
    check_version(f"{snapshot}/product.yaml", product_data.model_dump(mode="json", by_alias=True))
    parts = {}
    for path in sorted((snapshot / "parts").glob("*/part.yaml")):
        rel = f"parts/{path.parent.name}/part.yaml"
        parts[path.parent.name] = _snapshot_document(snapshot, rel, "part", documents.part("X").model)
    ledgers = [name for name in ("evidence", "findings") if name in current.manufacturing]
    manufacturing = {name: current.manufacturing[name] for name in ledgers}
    for name in SNAPSHOT_MANUFACTURING:
        if (snapshot / "manufacturing" / f"{name}.yaml").is_file():
            manufacturing[name] = _snapshot_document(
                snapshot, f"manufacturing/{name}.yaml", f"manufacturing-{name}", MANUFACTURING_MODELS[name]
            )
    return Record(
        product=product_data,
        requirements=_snapshot_document(
            snapshot, "requirements.yaml", "requirements", documents.REQUIREMENTS.model
        ),
        interfaces=_snapshot_document(snapshot, "interfaces.yaml", "interfaces", documents.INTERFACES.model),
        assembly=_snapshot_document(snapshot, "assembly.yaml", "assembly", documents.ASSEMBLY.model),
        bom=[],
        verification=[],
        parts=parts,
        decisions=current.decisions,
        manufacturing=manufacturing,
    )


def current_geometry(hw: Path) -> dict[str, str | None]:
    """PN -> sha256 of each current hw/parts/<PN>/model.py (impact.py:698)."""
    return {
        path.parent.name: _sha256(path)
        for path in sorted((hw / "parts").glob("*/model.py"))
        if path.is_file() and not path.is_symlink()
    }


def version_geometry(manifest: dict[str, Any]) -> dict[str, str | None]:
    """PN -> sha256 of the model source a version built, from its manifest `parts` (impact.py:690)."""
    return {pn: entry.get("source_sha256") for pn, entry in (manifest.get("parts") or {}).items()}


def _staleness(
    snapshot: Path, current: Record, built_geometry: dict[str, str | None], geometry: dict[str, str | None]
) -> ChangedSinceBuild | NotComputed:
    """What changed between the built record and the current one (evidence.py:1695-1698)."""
    if not snapshot.is_dir():
        return NotComputed(f"the version has no record snapshot at {snapshot}")
    try:
        built = read_snapshot(snapshot, current)
    except RecordError as error:
        return NotComputed(f"the record snapshot does not read: {error.path}: {error.message}")
    before = fp.subject_fingerprints(view(built), inventory(built.assembly, built.parts)[0], built_geometry)
    after = fp.subject_fingerprints(view(current), inventory(current.assembly, current.parts)[0], geometry)
    return ChangedSinceBuild(fp.changed_domains(before, after))


def file_state(root: Path, path: str) -> FileState:
    """The sha256 of the regular file at the project path `path`, or why it cannot be read: an unnormalized
    or escaping path, a link anywhere on the way, or a missing file (evidence.py:1261)."""
    if not path.startswith("hw/") or "\\" in path or posixpath.normpath(path) != path:
        return FileState(problem="is not a normalized path inside hw/")
    current = root
    for part in path.split("/"):
        current = current / part
        if current.is_symlink():
            return FileState(problem="lies behind or is a symbolic link")
    if not current.is_file():
        return FileState(problem="is missing")
    return FileState(sha256=_sha256(current))


def _sources(root: Path) -> list[str]:
    found = []
    for directory, folders, names in os.walk(root / SOURCES_DIR, followlinks=False):
        rel = Path(directory).relative_to(root).as_posix()
        found += [f"{rel}/{name}" for name in folders + names if (Path(directory) / name).is_symlink()]
        found += [f"{rel}/{name}" for name in names]
    return found


def read_built_version(root: Path, record: Record, version: str) -> BuiltVersion:
    """What the evidence of `record` (the current record of the project at `root`) reads about built
    `version`. BuiltVersionError when it is not built or its directory fails its seal."""
    hw = root / documents.HW
    folder = hw / "versions" / version
    if not (folder / MANIFEST).is_file():
        raise BuiltVersionError(f"hw/versions/{version}/{MANIFEST}", f"{version} is not a built version")
    problems = seal_problems(folder)
    if problems:
        raise BuiltVersionError(
            f"hw/versions/{version}/{MANIFEST}", f"{version}: {_stale(problems)}; build a new version"
        )
    manifest, _ = _manifest(folder)
    assert manifest is not None
    manifest_sha = _sha256(folder / MANIFEST)
    geometry = current_geometry(hw)
    packets, packet_findings = collect_packets(hw, version, manifest_sha)
    wanted = cited_paths(view(record), packets) | set(LEDGER_FILES) | set(_sources(root))
    files = {path: file_state(root, path) for path in sorted(wanted)}
    files = {path: state for path, state in files.items() if path not in LEDGER_FILES or state.sha256}
    return BuiltVersion(
        label=version,
        manifest_sha256=manifest_sha,
        staleness=_staleness(folder / "record", record, version_geometry(manifest), geometry),
        packets=packets,
        packet_findings=packet_findings,
        current_geometry=geometry,
        files=files,
    )
