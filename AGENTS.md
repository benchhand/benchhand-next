# Working in benchhand-next

- Read `docs/design-plan.md` and the ADR an area cites before changing it.
- `contracts/` is the only source of message and record shapes (ADR-0017). Never hand-write a copy of a shape in Python or TypeScript. Generate it.
- `reference/` holds the prototype's tests and fixtures as a behavioural oracle. Don't edit it. Port its cases into new tests instead.
- Keep functions under the ruff complexity limits. They are enforced, not ratcheted.
- Run `just check` before committing.
