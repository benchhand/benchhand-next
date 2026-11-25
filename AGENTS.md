# Working in benchhand-next

- Read `docs/design-plan.md` and the ADR an area cites before changing it.
- `contracts/` is the only source of message and record shapes (ADR-0017). Never hand-write a copy of a shape in Python or TypeScript. Generate it.
- `reference/` holds the prototype's tests and fixtures as a behavioural oracle. Don't edit it. Port its cases into new tests instead.
- Keep functions under the ruff complexity limits. They are enforced, not ratcheted.
- Tests follow `docs/testing.md`: test real behaviour, not for the sake of testing.
- Run `just check` before committing.
- Every phase ends at a review gate (`docs/design-plan.md`, Steps). Write `docs/phases/phase-N.md`, verify by running the built code against a copy of a real record, then stop and wait for the owner's approval. Don't merge the next phase's work or tick its box before that.
- Subagents: set the model explicitly on every launch, and never let a child inherit one. Use the strongest model for contracts and core boundaries, a cheaper model for work a contract or test bounds, and a different model family for review.
- The prototype in `benchhand/benchhand` keeps changing. `release.toml` `reference_commit` records the last commit whose behaviour is reflected here. Run `just reference-changes` to list what landed since, and port the relevant behaviour (ADR-0015).
