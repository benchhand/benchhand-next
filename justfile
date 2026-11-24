# benchhand-next developer tasks.

default: check

# Lint, type-check and test everything.
check: lint test

lint:
    uv run ruff check .
    uv run ruff format --check .

test:
    uv run pytest

# Regenerate code from contracts/ (ADR-0017). Arrives in Phase 1.
contracts:
    @echo "codegen lands in Phase 1"

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
