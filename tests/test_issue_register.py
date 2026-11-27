# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

"""The migration issue register: its checks, its summary page, and the local sync against the ledger."""

from __future__ import annotations

import shutil
import textwrap
from pathlib import Path

import pytest
import yaml
from issue_register import cli
from issue_register.cli import REPO_ROOT, run_check, run_sync
from issue_register.register import (
    MAP_FILE,
    OUTPUT_FILE,
    PRIVATE_PATTERNS_ENV,
    PRIVATE_PATTERNS_FILE,
    REGISTER_FILE,
    SCHEMA_FILE,
    RegisterError,
    load_register,
)
from issue_register.render import render_register
from issue_register.sync import LEAD_ENV, LEDGER_ENV, ledger_statuses, tool_issue_hashes, triage

MAP = """\
reference_commit: abc1234
entries:
  - path: skills/cad-x/SKILL.md
    home: flow/guides/
    phase: 2
    status: planned
  - path: skills/cad-x/scripts/build.py
    home: providers/kernel-cadquery/
    phase: 4
    status: planned
"""

REGISTER = """\
reference_commit: abc1234
design_rules:
  - id: RULE-01
    rule: Unknown is never pass.
    sources: [handoff §2]
    benchhand_next: Kept.
issues:
  - id: IR-001
    title: A check passes with no stated limit.
    kind: false-pass
    sources: ['test-project tool-issues #1']
    beads: [benchhand-aaa]
    prototype_status: open
    area: cad-x
    prototype_paths: [skills/cad-x/scripts/build.py]
    disposition: already-covered
    pointer: docs/x.md §One
    benchhand_next: {action: Covered by the evidence service., phase: 2}
    acceptance: A test where the check is unknown.
  - id: IR-002
    title: The owner must choose a default.
    kind: decision
    sources: [findings 1.2]
    prototype_status: open
    area: cad-x
    disposition: decide
    recommendation: Take the stricter default.
    benchhand_next: {action: Waiting on the owner; see IR-001., phase: null}
    acceptance: An owner decision.
    needs_recheck: true
bead_dispositions:
  - {bead_id: benchhand-bbb, area: cad-x, disposition: not-applicable, reason: Prototype process.}
ledger_snapshot:
  date: '2026-11-27'
  statuses: {benchhand-aaa: open, benchhand-bbb: closed}
  tool_issue_hashes: {'1': 0123456789abcdef}
"""

LOG = """\
# Tool issues

## 1 (open, 2026-11-26): a check passes with no limit
Private text that must never reach the register.

## 2 (open, 2026-11-27): a second issue
More private text.
"""


def _repo(tmp_path: Path, register: str = REGISTER) -> Path:
    files = {
        "release.toml": 'reference_commit = "abc1234"\n',
        MAP_FILE: MAP,
        REGISTER_FILE: register,
        "docs/x.md": "# One\n",
    }
    for name, text in files.items():
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text(text, encoding="utf-8")
    (tmp_path / SCHEMA_FILE).parent.mkdir(parents=True)
    shutil.copy(REPO_ROOT / SCHEMA_FILE, tmp_path / SCHEMA_FILE)
    return tmp_path


def _problems(tmp_path: Path, register: str) -> str:
    with pytest.raises(RegisterError) as raised:
        load_register(_repo(tmp_path, register))
    return "\n".join(raised.value.problems)


def test_the_committed_register_is_valid_and_its_summary_is_current() -> None:
    assert "beads referenced once each" in run_check(REPO_ROOT, write=False)


def test_a_valid_register_loads_and_counts_every_bead_once(tmp_path: Path) -> None:
    register = load_register(_repo(tmp_path))
    assert register.bead_references() == ["benchhand-aaa", "benchhand-bbb"]
    assert register.cited_tool_issues() == {"1"}


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ("id: IR-002", "id: IR-001", "id IR-001 is used more than once"),
        ("bead_id: benchhand-bbb", "bead_id: benchhand-aaa", "benchhand-aaa is referenced more than once"),
        ("[skills/cad-x/scripts/build.py]", "[skills/cad-x/scripts/gone.py]", "gone.py is not in"),
        ("pointer: docs/x.md §One", "pointer: docs/missing.md", "pointer docs/missing.md does not exist"),
        ("see IR-001.", "see IR-009.", "IR-009 is mentioned but is not an issue"),
        ("area: cad-x\n    disposition: decide", "area: cad-y\n    disposition: decide", "area cad-y is not"),
        ("reference_commit: abc1234", "reference_commit: abc1235", "is not release.toml's abc1234"),
        ("benchhand-aaa: open, ", "", "benchhand-aaa has no ledger_snapshot status"),
        (
            "{'1': 0123456789abcdef}",
            "{'1': 0123456789abcdef, '7': 0123456789abcdef}",
            "tool-issues #7: no issue",
        ),
    ],
)
def test_a_broken_cross_reference_is_reported(tmp_path: Path, old: str, new: str, message: str) -> None:
    assert old in REGISTER
    assert message in _problems(tmp_path, REGISTER.replace(old, new, 1))


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ("    pointer: docs/x.md §One\n", "", "'pointer' is a required property"),
        ("    recommendation: Take the stricter default.\n", "", "'recommendation' is a required property"),
        ("reason: Prototype process.", "pointer: docs/x.md", "'reason' is a required property"),
        ("kind: decision", "kind: wish", "'wish' is not one of"),
        ("sources: [findings 1.2]", "sources: [hw/parts/x/part.yaml]", "does not match"),
        (
            "sources: [findings 1.2]",
            "sources: ['agentcad product test 2026-11-27, REPORT']",
            "does not match",
        ),
    ],
)
def test_a_schema_violation_is_reported(tmp_path: Path, old: str, new: str, message: str) -> None:
    assert old in REGISTER
    assert message in _problems(tmp_path, REGISTER.replace(old, new, 1))


def test_an_agentcad_product_test_report_section_is_a_source(tmp_path: Path) -> None:
    source = "'agentcad product test 2026-11-27, REPORT \u00a7bugs item 4'"
    register = REGISTER.replace("sources: [findings 1.2]", f"sources: [{source}]", 1)
    assert load_register(_repo(tmp_path, register)).issues[1]["sources"] == [source.strip("'")]


def test_a_cad_libraries_decision_is_a_source(tmp_path: Path) -> None:
    register = REGISTER.replace("sources: [findings 1.2]", "sources: [cad-libraries decision D-17]", 1)
    assert load_register(_repo(tmp_path, register)).issues[1]["sources"] == ["cad-libraries decision D-17"]


@pytest.fixture(autouse=True)
def _no_local_private_patterns(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(PRIVATE_PATTERNS_ENV, raising=False)


def _with_patterns(root: Path, patterns: str) -> Path:
    (root / PRIVATE_PATTERNS_FILE).write_text(patterns, encoding="utf-8")
    return root


# Built from parts so that the repository holds no literal home-directory path.
@pytest.mark.parametrize("token", ["/".join(["", home, "someone", "project"]) for home in ("Users", "home")])
def test_a_home_directory_path_is_refused_with_no_local_patterns(tmp_path: Path, token: str) -> None:
    register = REGISTER.replace("Prototype process.", f"Prototype process near {token}.")
    assert "line 32: matches the private pattern" in _problems(tmp_path, register)


@pytest.mark.parametrize("token", ["ACME-0042", "Widgetron"])
def test_a_token_of_the_local_patterns_file_is_refused(tmp_path: Path, token: str) -> None:
    root = _with_patterns(_repo(tmp_path), "# synthetic tokens\n\nACME-[0-9]{4}\n(?i)widgetron\n")
    register = REGISTER.replace("Prototype process.", f"Prototype process near {token}.")
    (root / REGISTER_FILE).write_text(register, encoding="utf-8")
    with pytest.raises(RegisterError, match="line 32: matches the private pattern"):
        load_register(root)


def test_the_patterns_file_named_by_the_environment_replaces_the_local_one(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = _with_patterns(_repo(tmp_path / "repo"), "never-matches-anything\n")
    elsewhere = tmp_path / "patterns.txt"
    elsewhere.write_text("Prototype process\n", encoding="utf-8")
    load_register(root)
    monkeypatch.setenv(PRIVATE_PATTERNS_ENV, str(elsewhere))
    with pytest.raises(RegisterError, match="'Prototype process'"):
        load_register(root)


def test_a_bad_pattern_is_reported_with_its_line(tmp_path: Path) -> None:
    root = _with_patterns(_repo(tmp_path), "# a comment\n(unclosed\n")
    with pytest.raises(RegisterError, match="line 2: not a regular expression"):
        load_register(root)


def test_the_snapshot_must_stay_the_last_key(tmp_path: Path) -> None:
    snapshot = REGISTER[REGISTER.index("ledger_snapshot:") :]
    reordered = snapshot + REGISTER.replace(snapshot, "")
    assert "must be the last top-level key" in _problems(tmp_path, reordered)


def test_the_summary_lists_counts_rules_decisions_and_rechecks(tmp_path: Path) -> None:
    page = render_register(load_register(_repo(tmp_path)))
    assert "| decide | 1 |" in page
    assert "| Phase 2 | 1 |" in page
    assert "| no phase | 1 |" in page
    assert "| RULE-01 | Unknown is never pass. |" in page
    assert "| IR-002 | The owner must choose a default. | Take the stricter default. |" in page
    assert "- IR-002: The owner must choose a default. (findings 1.2)" in page
    assert "2 beads from the prototype's ledger" in page


def test_a_stale_summary_fails_until_it_is_written(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    with pytest.raises(RegisterError, match="out of date"):
        run_check(root, write=False)
    run_check(root, write=True)
    assert run_check(root, write=False).startswith("issues: 2 issues, 1 design rules, 2 beads")
    assert (root / OUTPUT_FILE).is_file()


def test_each_issue_hash_covers_its_headings_and_bodies_and_carries_no_text() -> None:
    hashes = tool_issue_hashes(LOG)
    assert list(hashes) == ["1", "2"]
    assert all(len(value) == 16 and value not in LOG for value in hashes.values())
    heading = tool_issue_hashes(LOG.replace("## 2 (open, 2026-11-27)", "## 2 (fixed, 2026-11-28)"))
    assert (heading["1"], heading["2"] != hashes["2"]) == (hashes["1"], True)
    body = tool_issue_hashes(LOG.replace("must never reach", "must still never reach"))
    assert (body["1"] != hashes["1"], body["2"]) == (True, hashes["2"])
    follow_up = tool_issue_hashes(LOG + "\n## 1 (fixed, 2026-11-29): a follow-up\nFixed.\n")
    assert (follow_up["1"] != hashes["1"], follow_up["2"]) == (True, hashes["2"])


def test_triage_reports_new_changed_and_vanished_beads_and_issues(tmp_path: Path) -> None:
    register = load_register(_repo(tmp_path))
    ledger = ledger_statuses(
        [{"id": "benchhand-aaa", "status": "closed"}, {"id": "benchhand-ccc", "status": "open"}]
    )
    hashes = {"1": "fedcba9876543210", "2": "0123456789abcdef"}
    found = triage(register, ledger, hashes)
    assert found.lines() == [
        "benchhand-ccc (open): not in the register",
        "benchhand-aaa: open -> closed since the snapshot",
        "benchhand-bbb: in the register, not in the ledger",
        "test-project tool-issues #2: new",
        "test-project tool-issues #1: its text changed",
    ]


FIRST_ISSUE = LOG.split("## 2")[0]
LEDGER = {"benchhand-aaa": "open", "benchhand-bbb": "closed"}


def _in_sync(tmp_path: Path) -> tuple[Path, Path]:
    """A repository whose snapshot matches LEDGER and a lead folder whose log holds issue 1 only."""
    snapshot_hash = tool_issue_hashes(FIRST_ISSUE)["1"]
    root = _repo(tmp_path / "repo", REGISTER.replace("0123456789abcdef", snapshot_hash))
    lead = tmp_path / "lead"
    lead.mkdir()
    (lead / "tool-issues.md").write_text(FIRST_ISSUE, encoding="utf-8")
    return root, lead


def _sync(
    monkeypatch: pytest.MonkeyPatch,
    where: tuple[Path, Path],
    ledger: dict[str, str],
    *,
    update: bool = False,
    acknowledge: bool = False,
) -> int:
    monkeypatch.setattr(cli, "read_ledger", lambda _directory: ledger)
    root, lead = where
    return run_sync(root, Path("/nonexistent-ledger"), lead, update, acknowledge)


@pytest.mark.parametrize(
    ("argv", "env", "message"),
    [
        (["sync"], {}, f"no the prototype checkout: pass --ledger or set {LEDGER_ENV}"),
        (["sync", "--ledger", "x"], {}, f"pass --lead or set {LEAD_ENV}"),
        (["sync"], {LEDGER_ENV: "x"}, f"pass --lead or set {LEAD_ENV}"),
        (["sync", "--lead", "y"], {LEAD_ENV: ""}, f"pass --ledger or set {LEDGER_ENV}"),
    ],
)
def test_sync_needs_the_ledger_and_the_log_and_has_no_default(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    argv: list[str],
    env: dict[str, str],
    message: str,
) -> None:
    monkeypatch.delenv(LEDGER_ENV, raising=False)
    monkeypatch.delenv(LEAD_ENV, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    assert cli.main(argv) == 2
    assert message in capsys.readouterr().err


def test_sync_exits_non_zero_while_anything_needs_triage(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root, lead = _in_sync(tmp_path)
    before = (root / REGISTER_FILE).read_text(encoding="utf-8")
    assert _sync(monkeypatch, (root, lead), {**LEDGER, "benchhand-ccc": "open"}) == 1
    assert (root / REGISTER_FILE).read_text(encoding="utf-8") == before
    assert _sync(monkeypatch, (root, lead), LEDGER) == 0


def test_an_update_clears_a_change_only_when_acknowledged_and_reports_it_either_way(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    root, lead = _in_sync(tmp_path)
    (lead / "tool-issues.md").write_text(
        FIRST_ISSUE.replace("must never", "must still never"), encoding="utf-8"
    )
    before = (root / REGISTER_FILE).read_text(encoding="utf-8")
    changed = {**LEDGER, "benchhand-aaa": "closed"}
    reported = ["benchhand-aaa: open -> closed since the snapshot", "tool-issues #1: its text changed"]
    assert _sync(monkeypatch, (root, lead), changed, update=True) == 1
    out = capsys.readouterr().out
    assert all(line in out for line in reported)
    assert "snapshot not updated" in out
    assert (root / REGISTER_FILE).read_text(encoding="utf-8") == before
    assert _sync(monkeypatch, (root, lead), changed, update=True, acknowledge=True) == 0
    out = capsys.readouterr().out
    assert all(line in out for line in reported)
    assert "snapshot updated; 0 still to triage" in out
    assert _sync(monkeypatch, (root, lead), changed) == 0


def test_updating_the_snapshot_writes_statuses_and_hashes_only(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root, lead = _in_sync(tmp_path)
    before = (root / REGISTER_FILE).read_text(encoding="utf-8")
    ledger = {"benchhand-aaa": "closed", "benchhand-bbb": "closed"}
    assert _sync(monkeypatch, (root, lead), ledger, update=True, acknowledge=True) == 0
    after = (root / REGISTER_FILE).read_text(encoding="utf-8")
    assert after.startswith(before[: before.index("ledger_snapshot:")])
    snapshot = yaml.safe_load(after)["ledger_snapshot"]
    assert snapshot["statuses"] == {"benchhand-aaa": "closed", "benchhand-bbb": "closed"}
    assert snapshot["tool_issue_hashes"] == tool_issue_hashes(FIRST_ISSUE)
    assert "Private text" not in after
    assert "passes with no limit" not in textwrap.dedent(after[after.index("ledger_snapshot:") :])


def test_a_snapshot_that_fails_the_checks_is_never_written(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root, lead = _in_sync(tmp_path)
    before = (root / REGISTER_FILE).read_text(encoding="utf-8")
    with pytest.raises(RegisterError, match="'not a status' is not one of"):
        _sync(
            monkeypatch,
            (root, lead),
            {**LEDGER, "benchhand-aaa": "not a status"},
            update=True,
            acknowledge=True,
        )
    assert (root / REGISTER_FILE).read_text(encoding="utf-8") == before


def test_the_register_and_its_page_are_where_the_justfile_expects() -> None:
    justfile = (REPO_ROOT / "justfile").read_text(encoding="utf-8")
    assert "issue_register check" in justfile
    assert "issue_register sync" in justfile
    assert (REPO_ROOT / REGISTER_FILE).is_file()
    assert (REPO_ROOT / OUTPUT_FILE).is_file()
