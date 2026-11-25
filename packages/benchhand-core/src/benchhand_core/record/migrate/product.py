"""Rules for hw/product.yaml: the record version and the removed flow.profile.human_approval."""

from __future__ import annotations

from yaml.nodes import MappingNode, ScalarNode

from benchhand_core.record.errors import RECORD_VERSION
from benchhand_core.record.finding import Finding, info, pointer
from benchhand_core.record.migrate import yaml_edit
from benchhand_core.record.migrate.rule import Rewrite

HUMAN_APPROVAL = "human_approval"
POLICY_ACTION = (
    "To let a gate go ahead without asking, add hw/policy.yaml with policy_version: 1 and "
    "gates: {<gate id>: {mode: auto, decision: DR-###}}, citing the decision that records it."
)


def record_version(path: str, text: str) -> Rewrite:
    """record_version 2 (or the PR #319 record version 1) becomes 3; the service has checked which it is."""
    root = yaml_edit.compose(text)
    value = yaml_edit.value_of(root, "record_version") if isinstance(root, MappingNode) else None
    if not isinstance(value, ScalarNode) or value.value == str(RECORD_VERSION):
        return Rewrite(text)
    return Rewrite(yaml_edit.apply(text, [yaml_edit.replace_scalar(value, str(RECORD_VERSION))]))


def _policy_note(path: str, steps: tuple[str | int, ...], value: object) -> Finding:
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
    root = yaml_edit.compose(text)
    splices: list[yaml_edit.Splice | None] = []
    findings: list[Finding] = []
    for steps, profile in yaml_edit.mappings_at(root, ("flow", "profile")):
        value = yaml_edit.value_of(profile, HUMAN_APPROVAL)
        if value is not None:
            splices.append(yaml_edit.remove_entry(text, profile, HUMAN_APPROVAL))
            shown = value.value if isinstance(value, ScalarNode) else "a collection"
            if shown != "all":
                findings.append(_policy_note(path, steps, shown))
        for _, asked in yaml_edit.mappings_at(profile, ("asked",)):
            splices.append(yaml_edit.remove_entry(text, asked, HUMAN_APPROVAL))
    return Rewrite(yaml_edit.apply(text, splices), tuple(findings))
