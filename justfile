# benchhand-next developer tasks.

default: check

# Lint, type-check and test everything, and check the generated contract code.
check: lint typecheck test test-wheel contracts-check

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
