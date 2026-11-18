# Manufacturability mutation corpus

Each defect is a **mutant** that a check must FAIL, paired with a **clean twin** it must PASS. The twin
differs from the mutant only by the defect. The harness reports, per family:

- detection rate: share of mutants judged FAIL
- abstention rate: share of mutants judged UNKNOWN
- false-positive rate: share of twins judged FAIL

The rates are a baseline for ratcheting, not a gate. A low rate for a defect no check catches yet is recorded as is.

## Rate command

    uv run --script skills/cad-design/tests/mfg_corpus/rates.py [--family ID ...] [--out PATH]

It prints a table, writes the JSON report (default `<tempdir>/mfg-corpus-rates.json`) and prints
`report: <path>`. The JSON is `{"format": 1, "families": [{family, check, owner, pairs, ran, skipped, errors, rejected, known_gaps,
detected, abstained, missed, false_positives, detection_rate, abstention_rate, false_positive_rate, results}]}`.
Rates are `null` when no pair ran. Pairs that raise `Skip` are excluded from the rates and counted in `skipped`.

## Layout

    mfg_corpus/
      corpus.py              Pair, Family, loader, rate arithmetic (stdlib only)
      rates.py               the command above
      capability_profile.py  materials() / capabilities(): the TEST profile as record documents (needs pyyaml)
      families/<id>.py       one module per family; exposes FAMILY (or FAMILIES)
      doc_support.py         helpers of the doc_* families: the lamp-arm record copy, edits, the pipeline, process_checks cases
      fixtures/
        test_capabilities.yaml     the TEST capability profile: printer test_printer (fdm), material test_polymer,
                                   synthetic calibrations; the shipped templates stay empty
        <family_id>/<pair_id>/     optional per-pair files (STEP, YAML), named mutant.* and twin.*
    ../test_mfg_corpus.py    tests of the harness itself

Existing defect sources are reused in place, never copied: `../fixtures/defects/` and
`../../../cad-motion/tests/fixtures/access_fixture.py`.

## Register a family

Add `families/<family_id>.py`; nothing else needs editing, so stacked PRs do not conflict. Files starting with
`_` are ignored (`_example.py` is a template).

    from corpus import Family, Pair, Skip

    def run(mutant: bool) -> str:        # "fail" | "pass" | "unknown"
        ...build the case, the defect applied only when mutant is True, run the check...

    FAMILY = Family(id="<check>_<defect>", check="module.or.script", owner="package",
                    pairs=(Pair("<pair_id>", "what the mutant gets wrong", run),))

`run(True)` builds the mutant and `run(False)` its twin from the same code, so the pair cannot drift. Map the
verdict onto `fail`, `pass` or `unknown`. Import heavy tools (OCP, yaml) inside `run`, and
`raise Skip("why")` when they are absent. A crash counts as a miss. Family and pair ids are unique.

## Verdicts are taken at the packet

A verdict is what the packet a user or release gate sees, and cad-record evidence's assessment of it, conclude for the
obligations the family is about. Never call an inner check function (`check_order`, `pc.assess`, `probe`, a script's own
report) from a family: take the verdict through a helper in `support.py`, which runs the real path with the arguments a
real build passes.

| helper | path | obligations |
| --- | --- | --- |
| `printed_verdict(shape, prefix)` | `form_check.probe` (with the bed build axis) -> `process_checks.assess(...).packet()` -> packet schema -> `evidence.assess` | `process.fdm.*@` |
| `assembly_verdict(items, *prefixes)` | the `access.py` command's packet (order check over the chain's inventory, then path planning) -> schema -> `evidence.assess` | `assembly.order@`, `intent.assembly_operations@`, `assembly.access@` |
| `readback_verdict(model_source)` | `cad_model run`, `cad_model check` -> the sealed `hw/checks/<V>/cad` bundle -> `evidence.collect_packets` -> `evidence.assess` | `cad.readback@` |
| `purchase_verdict(record, *prefixes)` | `process_checks.assess(record, {})` (no geometry) -> packet -> schema -> `evidence.assess` | `purchase.`, `route.`, `process.*` |

An evidence state maps to a verdict: `fail` is fail, `pass` and `not_applicable` are pass, anything else (unknown, stale,
planned, waived, or no packet at all) is unknown. A stage that refuses before it produces a packet (the build of a
part, a guide) has no obligation of its own: evidence shows the obligation unevidenced, so the verdict is unknown. A record
that expects no such obligation at all raises `Rejected` (the release asks nothing of the check). Say so in the family's
notes and open a gap for it.

One departure from a sealed release, stated so nobody reads it as the real thing: the `access.py` and additive packets go
to evidence in memory (assessed for a version label no repository uses, `v9000`) instead of from a sealed `hw/checks/`
bundle, and the `access.py` packet drops its `detail` key. The packet and evidence logic are the real ones.
`tests/test_mfg_corpus.py` fails when a family imports or calls an inner check.

A packet the schema or evidence refuses is not a verdict: `support` raises `corpus.Rejected(reason)`, the pair is a miss
and the reason is in the report (`rejected`).

`Pair(..., known_gap="why")` marks a mutant whose verdict is not trusted, for example one that FAILs for a wrong reason.
The pair counts in `ran` and as a miss whatever the mutant returned, its twin's false positive still counts, and the
rate command prints `known gap: <family>/<pair>: <why>`. Remove the field when the check is fixed.

## Families not at the packet

Five families judge the `cad_model check` report instead of the packet, because the `cad.readback` packet has no
obligation for `glb_step_agreement` or `declared_dimensions` yet: `semantic_changed_only_scope`,
`semantic_equal_volume_substitution`, `semantic_misplaced_feature`, `semantic_step_glb_disagreement` and
`semantic_wrong_placement`. They run through `families/_oracles.py`. The rates command marks them `not at the packet (#174)`
and leaves them out of its packet-level total. Their rates measure whether the oracle tells the mutant from its twin,
not whether a release blocks the mutant. Quote them apart from the packet-level rates.

`ORACLES_EXEMPTION_174` in `corpus.py` names them. The guard in `../test_mfg_corpus.py` lets exactly these families import
`_oracles`, and it fails when any other family imports it, directly or through a helper module. It also pins that
`_oracles` runs one command, the check driver, and that the driver calls only `check.check`. Issue #174 moves the
families to the packet and deletes `ORACLES_EXEMPTION_174` with its guard lines.

## Baseline and ratchet

`baseline/<family_id>.json` holds the rates recorded when a family was seeded (`detection_rate`, `abstention_rate`,
`false_positive_rate`, `ran`). `../test_mfg_corpus.py` fails when a family's detection rate falls or its
false-positive rate rises past its baseline. After a check improves, raise the rates in that family's baseline file
in the same PR. A new family adds its own file; one file per family keeps stacked PRs from conflicting.

## fdm_horizontal_hole

Horizontal holes (axis parallel to the bed) against the FDM support obligation, five pairs built in code, no fixture files.
The TEST profile has no self-supporting-hole calibration, so no round roof counts as support-free. Each pair changes one
thing: a round roof against a 45 deg teardrop or diamond roof of the same width, at a fixed height. The square pair uses
the 5 mm bridge calibration.

The `square_roof_bridge` pair is a known gap. Its 4 mm twin and 12 mm mutant both FAIL on the same wrong span, because
the probe measures the roof length (30 mm) instead of the width (`form_check.py:862-867`). It counts as a miss until item 9
fixes the span. The twin's FAIL is a false positive.
