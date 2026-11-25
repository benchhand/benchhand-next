"""The migration rule table: one row per prototype change, applied in this order to each file it names.

Porting a later prototype change (ADR-0015, `just reference-changes`) is one new row here plus its fixture
under packages/benchhand-core/tests/record/migrate_fixtures/<id>/ (before/ and after/ trees). The prototype at
`release.toml` reference_commit 412b5d9 reads record_version 2 only; each row's source names the prototype
commit or PR that introduced the form the row rewrites. docs/contract/record-migration.md lists every row.
"""

from __future__ import annotations

from benchhand_core.record.migrate import decisions, product
from benchhand_core.record.migrate.renames import csv_columns, yaml_keys
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
        changes="status deprecated without superseded-by becomes rejected when the body says it was never "
        "adopted; otherwise the file is refused until the user picks a status",
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
