"""Rules for hw/product.yaml: the record version and the removed flow.profile.human_approval."""

from __future__ import annotations

from yaml.nodes import ScalarNode

from benchhand_core.record.errors import RECORD_VERSION
from benchhand_core.record.finding import Finding, info, pointer
from benchhand_core.record.migrate.rule import Rewrite
from benchhand_core.record.migrate.yaml_edit import Document, Steps, value_of

HUMAN_APPROVAL = "human_approval"
POLICY_ACTION = (
    "To let a gate go ahead without asking, add hw/policy.yaml with policy_version: 1 and "
    "gates: {<gate id>: {mode: auto, decision: DR-###}}, citing the decision that records it."
)


def record_version(path: str, text: str) -> Rewrite:
    """record_version 2 (or the PR #319 record version 1) becomes 3; the service has checked which it is."""
    document = Document.parse(text)
    target = document.root_target()
    if target is not None:
        document.replace_value(target, "record_version", str(RECORD_VERSION))
    return Rewrite(document.result())


def _policy_note(path: str, steps: Steps, value: object) -> Finding:
    return info(
        "migrate.gates_now_ask",
        path,
        f"flow.profile.human_approval was {value!r}: the stage gates other than intent, variant, freeze and "
        "release went ahead on a passing full check without the user. Record version 3 has no such "
        "setting, and without hw/policy.yaml every gate now asks.",
        pointer=pointer(*steps, HUMAN_APPROVAL),
        action=POLICY_ACTION,
    )


def human_approval(path: str, text: str) -> Rewrite:
    """Remove flow.profile.human_approval and its flow.profile.asked entry. The migration writes no
    hw/policy.yaml, so every gate asks; a value other than all, which let some gates pass without the user,
    is reported."""
    document = Document.parse(text)
    findings: list[Finding] = []
    for profile in document.mappings_at(("flow", "profile")):
        if not document.has(profile, HUMAN_APPROVAL):
            continue
        document.remove_entries(profile, (HUMAN_APPROVAL,))
        value = value_of(profile.mapping, HUMAN_APPROVAL)
        shown = value.value if isinstance(value, ScalarNode) else "a collection"
        if shown != "all":
            findings.append(_policy_note(path, profile.steps, shown))
    for asked in document.mappings_at(("flow", "profile", "asked")):
        document.remove_entries(asked, (HUMAN_APPROVAL,))
    return Rewrite(document.result(), tuple(findings))
