# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

# benchhand-next developer tasks.

default: check

# The tools pinned in mise.toml are not on PATH until mise is activated. Without this guard the recipe fails
# with a bare "command not found" (exit 127).
[private]
_need tool:
    @command -v {{tool}} >/dev/null || { echo "{{tool}} not found: run \`mise install\`, then \`mise activate\` (or prefix with \`mise x --\`)" >&2; exit 1; }

# Lint, type-check and test everything, and check the generated contract code. The git hooks
# (.pre-commit-config.yaml) call the same recipes. `audit`, `secrets-history` and `lint-workflows-online`
# need the network and run in CI.
check: lint reuse spell lint-toml lint-workflows dead-code typecheck test test-wheel contracts-check reference-map inventory issues capabilities specs

lint:
    uv run ruff check .
    uv run ruff format --check .

# Licence and copyright data on every file (SPDX headers, REUSE.toml, LICENSES/).
reuse: (_need "reuse")
    reuse lint

# Spelling in source, docs and config (_typos.toml lists what is left out and why).
spell: (_need "typos")
    typos --force-exclude

# TOML formatting (.taplo.toml).
lint-toml: (_need "taplo")
    taplo fmt --check

# Workflow syntax, security and action pins, offline: the hook's check. A pin is checked for being a full
# SHA; `lint-workflows-online` also checks that it matches its version comment and runs zizmor's online audits.
lint-workflows: (_need "actionlint") (_need "zizmor") (_need "pinact")
    actionlint
    zizmor --offline --min-severity medium .github
    pinact run --fix=false --no-api

# CI only: needs GITHUB_TOKEN (the rate limit without one is too low for the pin check).
lint-workflows-online: (_need "zizmor") (_need "pinact")
    zizmor --min-severity medium .github
    pinact run --check --verify-comment

# Code that nothing uses, at the confidence and with the whitelist set in pyproject.toml ([tool.vulture]).
dead-code:
    uv run vulture

# Secrets in the staged changes: the pre-commit hook's check. Offline.
secrets: (_need "gitleaks")
    gitleaks git --pre-commit --staged --redact --no-banner

# Secrets anywhere in the history: CI, and on demand. Offline.
secrets-history: (_need "gitleaks")
    gitleaks git --redact --no-banner

# Known vulnerabilities in the locked dependencies. Queries osv.dev, so it fails on a new advisory against a
# dependency that did not change: CI runs it on a schedule as well as on lockfile changes. It audits the three
# product and workspace lockfiles only, not the tools pinned in mise.toml or the reuse install.
audit: (_need "osv-scanner")
    osv-scanner scan source --lockfile uv.lock --lockfile ui/pnpm-lock.yaml --lockfile contracts/pnpm-lock.yaml

# Type-check the Python (pyright, [tool.pyright]) and the TypeScript in ui/, the generated contract types included.
typecheck: typecheck-python typecheck-ui

typecheck-python:
    uv run pyright

typecheck-ui:
    pnpm --dir ui typecheck

test:
    uv run pytest

# The unit and API tests under packages/, in parallel: the pre-push hook's subset. `test` also runs tests/, the
# contract, diagram and function-map tests, which regenerate and render and take several minutes.
test-fast:
    uv run pytest packages -n auto

# The tests, with line coverage of packages/ and tools/ ([tool.coverage]). A report, not a gate: there is no
# threshold. CI puts the table in the job summary.
test-coverage:
    uv run pytest --cov --cov-report=term-missing:skip-covered --cov-report=xml

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
contracts: contracts-toolchain contracts-d2
    PYTHONPATH=tools/gen uv run python -m contracts_gen generate

# Fail on unformatted TypeSpec, a schema that fails meta-validation or lint, generated files that differ
# from a fresh run, and a breaking change without a major bump.
contracts-check: contracts-validate contracts-d2
    PYTHONPATH=tools/gen uv run python -m contracts_gen check
    PYTHONPATH=tools/gen uv run python -m contracts_gen breaking

# The contract errors that need no regeneration: unformatted TypeSpec, a TypeSpec warning, a schema that fails
# meta-validation or lint. The pre-commit hook runs this; drift (a full regeneration) is `contracts-drift`.
contracts-validate: contracts-toolchain contracts-format contracts-lint

# Fail with the install command when the TypeSpec toolchain isn't installed; a skipped check passes silently.
contracts-toolchain:
    #!/usr/bin/env bash
    set -euo pipefail
    for tool in tsp jsonschema; do
        if [ ! -x "{{bin}}/$tool" ]; then
            echo "contracts: {{bin}}/$tool is missing; run \`pnpm --dir contracts install --frozen-lockfile\`" >&2
            exit 1
        fi
    done

# Fail with the install command when D2 (pinned in mise.toml) isn't on PATH; the generators lay out diagrams with it.
contracts-d2:
    #!/usr/bin/env bash
    set -euo pipefail
    if ! command -v d2 > /dev/null; then
        echo "contracts: d2 is not on PATH; run \`mise install\` (mise.toml pins it)" >&2
        exit 1
    fi

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

# The function-level inventory of the prototype: every public function, class and command line, joined to its
# reference-map entry. Writes docs/architecture/prototype-inventory.md and .json with `--write`; without it,
# checks that the committed files match. Writing needs BENCHHAND_REFERENCE_DIR (a read-only copy of the
# prototype at release.toml's reference_commit); without a copy the check covers the committed JSON against
# reference-map.yaml and the Markdown against the JSON. With CI=true the copy is required.
inventory *args:
    PYTHONPATH=tools/inventory:tools/map uv run python -m prototype_inventory {{args}}

# Check docs/migration/issue-register.yaml against tools/issues/issue-register.schema.json and the reference map, and
# with `--write` regenerate docs/migration/issue-register.md from it. Offline and fast. It refuses home-directory
# paths, and the private tokens listed one regular expression per line in tools/issues/private-patterns.txt (git
# ignores it) or in the file BENCHHAND_PRIVATE_PATTERNS names; CI has neither file.
issues *args:
    PYTHONPATH=tools/issues:tools/map uv run python -m issue_register check {{args}}

# Local only (CI has no ledger): compare the register with the prototype's ledger (`--ledger` or
# BENCHHAND_PROTOTYPE_LEDGER) and the test project's tool-issues log (`--lead` or BENCHHAND_TEST_PROJECT_LEAD); both
# are required. Exits 1 when something needs triage. `--update-snapshot --acknowledge` records bead statuses, a date
# and per-issue hashes once the report is triaged; the new file must pass `just issues` before it is written.
issues-sync *args:
    PYTHONPATH=tools/issues:tools/map uv run python -m issue_register sync {{args}}

# Check docs/architecture/capabilities.yaml against its JSON Schema and its cross references, and with `--write`
# regenerate docs/architecture/capabilities.md from it. Offline and fast. Its prototype commands are checked against
# the committed prototype-inventory.json, which `inventory` keeps current, so no copy of the prototype is needed.
capabilities *args:
    PYTHONPATH=tools/catalogue:tools/inventory:tools/map uv run python -m capability_catalogue {{args}}

# Check the capability specs (docs/specs/*.md) against their front-matter schema, the catalogue and the issue
# register, and with `--write` regenerate docs/specs/phase-2.md from them. Offline and fast.
specs *args:
    PYTHONPATH=tools/specs uv run python -m capability_specs {{args}}

# Install the git hooks (.pre-commit-config.yaml) for pre-commit and pre-push. Run `mise install` first: the
# hooks call the tools pinned in mise.toml. Git keeps hooks per clone, so every worktree of it shares them.
hooks-install:
    prek install --install-hooks --hook-type pre-commit --hook-type pre-push

# Run every hook on every file, as CI does, except three: `reuse` has its own CI step (fsfe/reuse-action), `gitleaks` scans the staged changes, which a CI
# checkout has none of (`secrets-history` covers it there), and `tests` is the `check` job's `test-coverage`.
hooks:
    SKIP=gitleaks,reuse prek run --all-files --stage pre-commit
    SKIP=tests prek run --all-files --stage pre-push
