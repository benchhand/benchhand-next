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
from collections.abc import Sequence
from dataclasses import dataclass
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
from benchhand_core.record.evidence.digest import (
    LEDGER_FILES,
    MANIFEST,
    SOURCES_DIR,
    cited_bundles,
    cited_paths,
)
from benchhand_core.record.evidence.guideline_files import Layer, holds_shipped_copies
from benchhand_core.record.evidence.guideline_files import discover as discover_guidelines
from benchhand_core.record.evidence.guidelines import GuidelineCatalog, with_guideline_digests
from benchhand_core.record.evidence.path_judge import judge_all
from benchhand_core.record.evidence.paths import PathQuery, disposition_queries, entry_queries
from benchhand_core.record.evidence.view import RecordView, view
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


def linked_on_the_way(root: Path, path: Path) -> str | None:
    """The first symbolic link on the way from the project `root` to `path`, `path` itself included, as a
    project path; None when there is none. A seal is only as good as the directory it is read from."""
    current = root
    for part in path.relative_to(root).parts:
        current = current / part
        if current.is_symlink():
            return current.relative_to(root).as_posix()
    return None


def bundle_problems(root: Path, bundle: str) -> tuple[str, ...]:
    """Why the sealed bundle at project path `bundle` does not verify: a link on the way to it, or a payload
    file that is missing, changed or unlisted against its manifest. Empty when it verifies."""
    if not bundle.startswith("hw/") or posixpath.normpath(bundle) != bundle or "\\" in bundle:
        return (f"{bundle} is not a normalized path inside hw/",)
    directory = root / bundle
    link = linked_on_the_way(root, directory)
    if link is not None:
        return (f"{link} is a symbolic link",)
    if not (directory / MANIFEST).is_file():
        return (f"{bundle} has no {MANIFEST}",)
    return tuple(seal_problems(directory))


def _stale(problems: Sequence[str]) -> str:
    return f"stale: {problems[0]}" + (f" (+{len(problems) - 1} more)" if len(problems) > 1 else "")


def _bound_problem(root: Path, directory: Path, version: str, version_sha: str) -> str | None:
    """Why a check bundle is not sealed and bound to this build: a link, no result.json or manifest, a
    failed seal or another build (evidence.py:1185-1204, the seal verified before the packet is read)."""
    link = linked_on_the_way(root, directory)
    if link is not None:
        return f"{link} is a symbolic link"
    if not (directory / "result.json").is_file():
        return "it has no result.json"
    if not (directory / MANIFEST).is_file():
        return f"it has no {MANIFEST}"
    problems = seal_problems(directory)
    if problems:
        return _stale(problems)
    manifest, _ = _manifest(directory)
    if manifest is None or manifest.get("version_manifest_sha256") != version_sha:
        return f"stale: it is bound to another build of {version}"
    return None


def _packet_problem(directory: Path) -> tuple[Any, str | None]:
    """The parsed result.json of a sealed, bound check bundle and why it is no valid packet."""
    try:
        data = json.loads((directory / "result.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        return None, f"cannot read result.json: {error}"
    # TODO(migrate): packets and snapshots stay at record_version 3 (orchestrator decision). When the migrate
    # service merges, verify the seal on the raw bytes first, then upgrade a record_version 2 packet in
    # memory by migrate's rules; until then a v2 packet breaks this contract and counts as nothing.
    found = contracts.violations("manufacturing-check-result", data)
    if found:
        where = found[0].pointer or "/"
        return None, f"result.json breaks manufacturing-check-result at {where}: {found[0].message}"
    return data, None


def _packet_invalid(bundle: str, message: str) -> Finding:
    data = {"code": "packet.invalid", "severity": "error", "path": f"{bundle}/result.json"}
    return Finding.model_validate({**data, "message": f"{bundle}: {message}"})


def collect_packets(
    root: Path, version: str, version_sha: str
) -> tuple[tuple[Packet, ...], tuple[Finding, ...], tuple[str, ...]]:
    """The packets sealed for `version` under hw/checks/<V>/<S>/result.json, and a packet.invalid finding for
    each bundle that is behind a link, has no result.json, is unreadable, no packet, unsealed, stale or bound
    to another build (evidence.py:1207). The prototype skips a bundle without result.json; here a damaged
    packet cannot disappear that way. Also returns every sealed, bound bundle, its packet valid or not."""
    checks = f"hw/checks/{version}"
    folder = root / checks
    link = linked_on_the_way(root, folder) if folder.exists() or folder.is_symlink() else None
    if link is not None:
        return (), (_packet_invalid(checks, f"{link} is a symbolic link"),), ()
    packets, findings, bound = [], [], []
    for directory in sorted(folder.iterdir()) if folder.is_dir() else []:
        bundle = f"{checks}/{directory.name}"
        data: Any = None
        problem = _bound_problem(root, directory, version, version_sha)
        if problem is None:
            bound.append(bundle)
            data, problem = _packet_problem(directory)
        if problem is not None:
            findings.append(_packet_invalid(bundle, problem))
            continue
        packets.append(Packet(bundle, _sha256(directory / MANIFEST), data))
    return tuple(packets), tuple(findings), tuple(bound)


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


@dataclass(frozen=True)
class _Sides:
    """The built and the current record's geometry and guideline catalogs, which staleness compares."""

    built_geometry: dict[str, str | None]
    geometry: dict[str, str | None]
    built_guidelines: GuidelineCatalog
    guidelines: GuidelineCatalog


def _staleness(
    snapshot: Path, current: Record, sides: _Sides, catalog_missing: bool
) -> tuple[ChangedSinceBuild | NotComputed, frozenset[str]]:
    """What changed between the built record and the current one (evidence.py:1695-1698), guideline sets
    included (manufacturing_intent.py:1235 reads a snapshot's own copies only), and the subjects a missing
    shipped catalog affects. Those count as changed in `source` even when every hash matches: without the
    catalog the current record cannot show it resolves the sets the build did."""
    current_view = with_guideline_digests(view(current), sides.guidelines)
    placed_now = inventory(current.assembly, current.parts)[0]
    affected = (
        fp.guideline_subjects(current_view, placed_now, sides.geometry) if catalog_missing else frozenset()
    )
    if not snapshot.is_dir():
        return NotComputed(f"the version has no record snapshot at {snapshot}"), affected
    try:
        built = read_snapshot(snapshot, current)
    except RecordError as error:
        return NotComputed(f"the record snapshot does not read: {error.path}: {error.message}"), affected
    built_view = with_guideline_digests(view(built), sides.built_guidelines)
    placed_before = inventory(built.assembly, built.parts)[0]
    if catalog_missing:
        affected |= fp.guideline_subjects(built_view, placed_before, sides.built_geometry)
    before = fp.subject_fingerprints(built_view, placed_before, sides.built_geometry)
    after = fp.subject_fingerprints(current_view, placed_now, sides.geometry)
    changed = fp.changed_domains(before, after)
    for key in affected:
        shown = {*changed.get(key, ()), "source"}
        changed[key] = tuple(domain for domain in fp.DOMAINS if domain in shown)
    return ChangedSinceBuild(changed), affected


MISSING = "is missing"


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
        return FileState(problem=MISSING)
    return FileState(sha256=_sha256(current))


def _sources(root: Path) -> list[str]:
    """Every file below the sources directory, and each link there, which the inventory refuses; the
    directory itself when it is a link, even an empty one (evidence.py:1306-1313)."""
    if linked_on_the_way(root, root / SOURCES_DIR) is not None:
        return [SOURCES_DIR]
    found = []
    for directory, folders, names in os.walk(root / SOURCES_DIR, followlinks=False):
        rel = Path(directory).relative_to(root).as_posix()
        found += [f"{rel}/{name}" for name in folders + names if (Path(directory) / name).is_symlink()]
        found += [f"{rel}/{name}" for name in names]
    return found


def ledger_queries(record: RecordView) -> set[PathQuery]:
    """Every path the evidence and findings ledgers cite, structured or in prose."""
    found: set[PathQuery] = set()
    for entry in record.evidence:
        found |= entry_queries(entry)
    for disposition in record.dispositions:
        found |= disposition_queries(disposition)
    return found


def read_built_version(
    root: Path, record: Record, version: str, *, shipped_guidelines: Path | None
) -> BuiltVersion:
    """What the evidence of `record` (the current record of the project at `root`) reads about built
    `version`. BuiltVersionError when it is not built or its directory fails its seal.

    `shipped_guidelines` is the directory of the shipped guideline sets the project's own sets override;
    None reads the project's sets only, so a build that resolved shipped sets reads as changed (stale, with
    guideline.catalog_missing), never as unchanged. TODO: the shipped sets become a benchhand package asset
    when the guideline catalog is ported (docs/design-plan.md, open items); until then the caller names
    the directory."""
    hw = root / documents.HW
    folder = hw / "versions" / version
    link = linked_on_the_way(root, folder) if folder.exists() or folder.is_symlink() else None
    if link is not None:
        message = f"{link} is a symbolic link; a seal read through it proves nothing"
        raise BuiltVersionError(f"hw/versions/{version}", message)
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
    packets, packet_findings, bound = collect_packets(root, version, manifest_sha)
    wanted = cited_paths(view(record), bound) | set(LEDGER_FILES) | set(_sources(root))
    files = {path: file_state(root, path) for path in sorted(wanted)}
    files = {
        path: state
        for path, state in files.items()
        if path not in LEDGER_FILES or state.problem != MISSING  # a linked ledger file stays, to be refused
    }
    bundles = {path: bundle_problems(root, path) for path in cited_bundles(view(record))}
    verdicts = judge_all(root, ledger_queries(view(record)))
    layers = [Layer(root / documents.GUIDELINES_DIR, documents.GUIDELINES_DIR)]
    shipped = [Layer(shipped_guidelines, "shipped", shipped=True)] if shipped_guidelines is not None else []
    layers += shipped
    guidelines = discover_guidelines(layers)
    snapshot_guidelines = folder / "record" / documents.GUIDELINES_DIR.removeprefix(f"{documents.HW}/")
    sides = _Sides(
        version_geometry(manifest),
        geometry,
        discover_guidelines([Layer(snapshot_guidelines, copies=True)]),
        guidelines,
    )
    catalog_missing = holds_shipped_copies(snapshot_guidelines) and not guidelines.has_shipped
    staleness, affected = _staleness(folder / "record", record, sides, catalog_missing)
    return BuiltVersion(
        label=version,
        manifest_sha256=manifest_sha,
        staleness=staleness,
        packets=packets,
        packet_findings=packet_findings,
        bound_bundles=bound,
        current_geometry=geometry,
        files=files,
        bundle_seals=bundles,
        path_verdicts=verdicts,
        guidelines=guidelines,
        guideline_catalog_missing=catalog_missing,
        catalog_missing_subjects=affected,
    )
