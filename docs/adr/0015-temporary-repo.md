# ADR-0015: Temporary repo `benchhand/benchhand-next`, swapped later

Status: accepted. Source: [the approved plan](../design-plan.md).

## Context

The name `benchhand/benchhand` is taken by the current repo.

## Decision

Development happens in `benchhand/benchhand-next`. `release.toml` is the only place that names the repo. Once golden parity is reached, the old repo is renamed `benchhand-legacy` and archived, and `-next` takes the name.

## Consequences

The swap is one change to `release.toml`, plus the GitHub renames.
