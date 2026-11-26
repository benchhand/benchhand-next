"""The migration rule table: one row per prototype change, applied in this order to each file it names.

Porting a later prototype change (ADR-0015, `just reference-changes`) is one new row here plus its fixture
under packages/benchhand-core/tests/record/migrate_fixtures/<id>/ (before/ and after/ trees). The prototype at
`release.toml` reference_commit 412b5d9 reads record_version 2 only; each row's source names the prototype
commit or PR that introduced the form the row rewrites. docs/contract/record-migration.md lists every row.
"""

from __future__ import annotations

from dataclasses import dataclass

from benchhand_core.record.finding import Finding
from benchhand_core.record.formats import FormatError
from benchhand_core.record.migrate import decisions, product
from benchhand_core.record.migrate.inventory import matches
from benchhand_core.record.migrate.renames import csv_columns, csv_numbers, yaml_keys
from benchhand_core.record.migrate.rule import Rule
from benchhand_core.record.migrate.yaml_edit import ANY

DECISIONS = ("hw/decisions/DR-*.md",)


def _fixture(rule_id: str) -> str:
    return f"migrate_fixtures/{rule_id}"


RULES: tuple[Rule, ...] = (
    Rule(
        id="record-version",
        documents=("hw/product.yaml",),
        changes="record_version 2, or the record version 1 of prototype PR #319, becomes 3",
        source="b0bce410 (record_version 2, the manufacturing-intent work)",
        fixture=_fixture("record-version"),
        transform=product.record_version,
    ),
    Rule(
        id="human-approval",
        documents=("hw/product.yaml",),
        changes="flow.profile.human_approval and its flow.profile.asked entry are removed; no hw/policy.yaml "
        "is written, so every gate asks, and a value other than all is reported",
        source="1903d0a0 (#307, the project-start profile)",
        fixture=_fixture("human-approval"),
        transform=product.human_approval,
    ),
    Rule(
        id="heat-set-keys",
        documents=("hw/interfaces.yaml",),
        changes="interfaces[].limits.heat_set[]: hole_d, hole_tol and depth_min become hole_diameter_mm, "
        "hole_deviation_mm and min_depth_mm",
        source="164ab11c (the plugin import; hole_d reworded in b0bce410)",
        fixture=_fixture("heat-set-keys"),
        transform=yaml_keys(
            (("interfaces", ANY, "limits", "heat_set", ANY),),
            {"hole_d": "hole_diameter_mm", "hole_tol": "hole_deviation_mm", "depth_min": "min_depth_mm"},
        ),
    ),
    Rule(
        id="bom-columns",
        documents=("hw/bom.csv",),
        changes="the columns specification_ref and specification_rev become specification_reference and "
        "specification_revision",
        source="164ab11c (the plugin import)",
        fixture=_fixture("bom-columns"),
        transform=csv_columns(
            {"specification_ref": "specification_reference", "specification_rev": "specification_revision"}
        ),
    ),
    Rule(
        id="verification-column",
        documents=("hw/verification.csv",),
        changes="the column requirement_id becomes requirement",
        source="164ab11c (the plugin import)",
        fixture=_fixture("verification-column"),
        transform=csv_columns({"requirement_id": "requirement"}),
    ),
    Rule(
        id="bom-number-spacing",
        documents=("hw/bom.csv",),
        changes="white space around a number in a numeric column (level, qty, mass) is removed; the "
        "prototype's int() and float() accepted it",
        source="164ab11c (the plugin import, validate.py)",
        fixture=_fixture("bom-number-spacing"),
        transform=csv_numbers("bom-row"),
    ),
    Rule(
        id="evidence-configuration-rev",
        documents=("hw/manufacturing/evidence.yaml",),
        changes="entries[].configuration.part_rev becomes rev",
        source="b0bce410 (the manufacturing-intent work)",
        fixture=_fixture("evidence-configuration-rev"),
        transform=yaml_keys((("entries", ANY, "configuration"),), {"part_rev": "rev"}),
    ),
    Rule(
        id="waiver-valid-until",
        documents=("hw/manufacturing/evidence.yaml", "hw/manufacturing/findings.yaml"),
        changes="a waiver's expires becomes valid_until, in evidence entries[] and findings dispositions[]",
        source="b0bce410 (the manufacturing-intent work)",
        fixture=_fixture("waiver-valid-until"),
        transform=yaml_keys(
            (("entries", ANY, "waiver"), ("dispositions", ANY, "waiver")), {"expires": "valid_until"}
        ),
    ),
    Rule(
        id="decision-gate",
        documents=DECISIONS,
        changes="a MADR gate: {from, to} key is removed; the decision stays kind: design with its status, "
        "and the result notes it",
        source="6575b883 (#318, a stage advance approved only on its gate decision)",
        fixture=_fixture("decision-gate"),
        transform=decisions.gate,
    ),
    Rule(
        id="decision-deprecated",
        documents=DECISIONS,
        changes="status deprecated without superseded-by is refused until the user picks accepted, rejected "
        "or superseded",
        source="1a7efb7e (#110, MADR 4.0.0 decision records)",
        fixture=_fixture("decision-deprecated"),
        transform=decisions.deprecated,
    ),
    Rule(
        id="decision-front-matter",
        documents=DECISIONS,
        changes="MADR front matter becomes kind: design: id, kind and title are added, decision-makers and "
        "superseded-by become decision_makers and superseded_by, superseded-by makes status superseded, "
        "and empty name lists are removed",
        source="1a7efb7e (#110, MADR 4.0.0 decision records)",
        fixture=_fixture("decision-front-matter"),
        transform=decisions.front_matter,
    ),
)


def rules_for(path: str) -> list[Rule]:
    """The rules whose documents match the project-relative `path`, in table order."""
    return [rule for rule in RULES if any(matches(pattern, path) for pattern in rule.documents)]


@dataclass(frozen=True)
class Rewritten:
    """What the matching rules make of one file's text: the text, the ids of the rules that changed it, what
    they report, and why a rule could not read it (the text and ids are then those before that rule)."""

    text: str
    applied: tuple[str, ...]
    findings: tuple[Finding, ...]
    unreadable: str | None = None


def rewrite(path: str, text: str) -> Rewritten:
    """Run each rule that matches `path` on `text`, in table order. The migrate service plans every file
    with it, and the evidence reader upgrades a sealed snapshot's documents with it."""
    applied: list[str] = []
    findings: list[Finding] = []
    for rule in rules_for(path):
        try:
            rewrite_of_rule = rule.run(path, text)
        except FormatError as failure:
            return Rewritten(text, tuple(applied), tuple(findings), f"{rule.id}: {failure}")
        findings.extend(rewrite_of_rule.findings)
        if rewrite_of_rule.text != text:
            text = rewrite_of_rule.text
            applied.append(rule.id)
    return Rewritten(text, tuple(applied), tuple(findings))
