# benchhand-next developer tasks.

default: check

# Lint, type-check and test everything, and check the generated contract code.
check: lint test contracts-check

lint:
    uv run ruff check .
    uv run ruff format --check .

test:
    uv run pytest

# Regenerate models, types, validators, fixtures and reference docs from contracts/ (ADR-0017).
contracts:
    PYTHONPATH=tools/gen uv run python -m contracts_gen generate

# Fail on generated files that differ from a fresh run, and on a breaking change without a major bump.
contracts-check:
    PYTHONPATH=tools/gen uv run python -m contracts_gen check
    PYTHONPATH=tools/gen uv run python -m contracts_gen breaking

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
