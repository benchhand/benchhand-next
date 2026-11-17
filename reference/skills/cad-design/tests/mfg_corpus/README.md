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
`report: <path>`. The JSON is `{"format": 1, "families": [{family, check, owner, pairs, ran, skipped, errors,
detected, abstained, missed, false_positives, detection_rate, abstention_rate, false_positive_rate, results}]}`.
Rates are `null` when no pair ran. Pairs that raise `Skip` are excluded from the rates and counted in `skipped`.

## Layout

    mfg_corpus/
      corpus.py              Pair, Family, loader, rate arithmetic (stdlib only)
      rates.py               the command above
      capability_profile.py  materials() / capabilities(): the TEST profile as record documents (needs pyyaml)
      families/<id>.py       one module per family; exposes FAMILY (or FAMILIES)
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
check's own verdict onto `fail`, `pass` or `unknown`. Import heavy tools (OCP, yaml) inside `run`, and
`raise Skip("why")` when they are absent. A crash counts as a miss. Family and pair ids are unique.

## Baseline and ratchet

`baseline/<family_id>.json` holds the rates recorded when a family was seeded (`detection_rate`, `abstention_rate`,
`false_positive_rate`, `ran`). `../test_mfg_corpus.py` fails when a family's detection rate falls or its
false-positive rate rises past its baseline. After a check improves, raise the rates in that family's baseline file
in the same PR. A new family adds its own file; one file per family keeps stacked PRs from conflicting.
