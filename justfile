# benchhand-next developer tasks.

default: check

# Lint, type-check and test everything, and check the generated contract code.
check: lint typecheck test test-wheel contracts-check reference-map

lint:
    uv run ruff check .
    uv run ruff format --check .

# Type-check the TypeScript in ui/, the generated contract types included.
typecheck:
    pnpm --dir ui typecheck

test:
    uv run pytest

# The tests that build a wheel and install it in a fresh venv (docs/testing.md).
test-wheel:
    uv run pytest -m wheel

# The published contract schemas, generated from contracts/*.tsp.
schemas := "packages/benchhand-contracts/src/benchhand_contracts/schemas"
# Every directory `just contracts` writes.
generated := schemas + " packages/benchhand-contracts/src/benchhand_contracts/models packages/benchhand-contracts/src/benchhand_contracts/examples ui/shared/contracts docs/contract/generated"
# contracts/package.json pins the TypeSpec compiler and emitter and the Sourcemeta JSON Schema CLI.
bin := "contracts/node_modules/.bin"

# Regenerate the published schemas from contracts/*.tsp, then the models, types, validators, fixtures and
# reference docs from those (ADR-0017). A TypeSpec warning fails the compile.
contracts:
    PYTHONPATH=tools/gen uv run python -m contracts_gen generate

# Fail on unformatted TypeSpec, a schema that fails meta-validation or lint, generated files that differ
# from a fresh run, and a breaking change without a major bump.
contracts-check: contracts-format contracts-lint
    PYTHONPATH=tools/gen uv run python -m contracts_gen check
    PYTHONPATH=tools/gen uv run python -m contracts_gen breaking

contracts-format:
    cd contracts && ../{{bin}}/tsp format --check "**/*.tsp"

# Meta-validate the emitted bundle (an unpublished intermediate, in contracts/tsp-output/) and the published
# schemas, and lint the published schemas, which are what consumers and generators read. The bundle isn't
# linted: the normaliser rewrites its emitter idioms, and the $refs written in @extension values resolve only
# once it is split into files. Rules left out, and why:
# - description_trailing_period: descriptions are sentences, and the docs render them as prose.
# - enum_with_type, enum_to_const, oneof_to_anyof_disjoint_types, unnecessary_allof_wrapper,
#   unnecessary_allof_ref_wrapper_modern: each rewrite keeps what validates but changes the generated
#   models (datamodel-code-generator makes a class of a one-value enum and a subclass of an allOf $ref), or
#   what the breaking check compares; the emitter writes `type` beside every enum.
# - orphan_definitions: record/common and record/drawing are libraries; their $defs are published API that
#   other contracts refer to, and each has a validator of its own.
# - simple_properties_identifiers: property names such as requires-python are part of the published shape.
# required_properties_in_properties runs on its own: the findings it keeps are listed by location and by the
# property name required there, each with its reason, in tools/gen/contracts_gen/lint.py; any other fails.
contracts-lint:
    #!/usr/bin/env bash
    set -euo pipefail
    (cd contracts && ../{{bin}}/tsp compile . --warn-as-error --output-dir tsp-output > /dev/null)
    {{bin}}/jsonschema metaschema contracts/tsp-output {{schemas}}
    {{bin}}/jsonschema lint --resolve {{schemas}} \
        --exclude description_trailing_period --exclude enum_with_type --exclude enum_to_const \
        --exclude oneof_to_anyof_disjoint_types --exclude unnecessary_allof_wrapper \
        --exclude unnecessary_allof_ref_wrapper_modern --exclude orphan_definitions \
        --exclude required_properties_in_properties --exclude simple_properties_identifiers {{schemas}}
    # The lint exits 2 when it reports a finding; lint-allowed decides whether that one is kept.
    report=$({{bin}}/jsonschema lint --json --resolve {{schemas}} --only required_properties_in_properties {{schemas}} || [ $? -eq 2 ])
    PYTHONPATH=tools/gen uv run python -m contracts_gen lint-allowed <<< "$report"

# CI: regenerate in place and fail if any generated file changed. Locally `contracts-check` compares a fresh
# run in a scratch directory instead, so it passes before the regenerated files are committed.
contracts-drift: contracts
    #!/usr/bin/env bash
    set -euo pipefail
    changed=$(git status --porcelain -- {{generated}})
    if [ -n "$changed" ]; then
        echo "contracts: generated files are out of date; run \`just contracts\` and commit:" >&2
        echo "$changed" >&2
        exit 1
    fi
    echo "contracts: no drift"

# Migration evidence (ADR-0017), on demand and not a CI gate: it compares the published schemas with the
# hand-written ones at the migration base 41598c2, which a later contract change will rightly differ from.
# It compares them decoded, then judges the instances the tests validate, the fixtures, the examples and
# mutations of each accepted one, in Python (the whole list of violations) and in Ajv (the first error),
# against the hand-written schemas, the published ones, and the published ones without the Timestamp
# pattern. Takes about half an hour; writes tools/equiv/results/.
contracts-equivalence:
    #!/usr/bin/env bash
    set -euo pipefail
    work=$(mktemp -d)
    trap 'rm -rf "$work"' EXIT
    EQUIV_LOG="$work/calls.jsonl" PYTHONPATH=tools/equiv uv run pytest -q -p record_plugin packages > /dev/null
    PYTHONPATH=tools/equiv uv run python tools/equiv/cases.py "$work"
    uv run python tools/equiv/decoded.py | tee tools/equiv/results/decoded.txt
    PYTHONPATH=tools/equiv uv run python tools/equiv/replay.py "$work" | tee tools/equiv/results/python.txt
    node tools/equiv/replay.mjs "$work" | tee tools/equiv/results/ajv.txt

# List prototype PRs merged and commits landed since release.toml's reference_commit.
reference-changes:
    #!/usr/bin/env bash
    set -euo pipefail
    repo=$(sed -n 's/^reference_repo = "\(.*\)"/\1/p' release.toml)
    ref=$(sed -n 's/^reference_commit = "\(.*\)"/\1/p' release.toml)
    since=$(gh api "repos/$repo/commits/$ref" --jq .commit.committer.date)
    echo "Since $ref ($since):"
    gh pr list -R "$repo" --state merged --search "merged:>$since" --json number,title,mergedAt --jq '.[] | "  merged #\(.number) \(.title)"'
    gh pr list -R "$repo" --state open --json number,title,updatedAt --jq '.[] | "  open   #\(.number) \(.title)"'

# Check docs/architecture/reference-map.yaml, and with `--write` regenerate docs/architecture/function-map.md from it.
# Offline and fast. Set BENCHHAND_REFERENCE_DIR to a read-only copy of the prototype at release.toml's
# reference_commit to also check that every prototype script, skill, agent and harness module has an entry and
# that no entry names a path that is gone. A copy with a .git or a .reference-commit stamp must hold that commit.
# With CI=true the copy is required; CI fetches it.
reference-map *args:
    PYTHONPATH=tools/map uv run python -m reference_map {{args}}
