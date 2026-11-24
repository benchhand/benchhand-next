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
