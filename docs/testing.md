# Testing

A test or CI step exists to catch a real failure that someone would otherwise ship. If a check can't fail for a reason that matters, delete it.

## Kinds of test

| Kind | Covers | Where | Runs |
|---|---|---|---|
| Unit | One module's logic: flow transitions, CEL rules, record validation, fit maths, framing | `packages/*/tests/` | Every push and PR |
| Contract | Schemas are valid, their examples validate, generated code matches `contracts/` | `tests/` | Every push and PR |
| API | One public surface end to end in-process: an MCP tool call through the server, or a provider through the protocol host with a fake provider | `packages/*/tests/api/` | Every push and PR |
| Wheel | A built wheel installs in a fresh venv and runs outside the checkout | `packages/*/tests/`, marked `wheel` | Every push and PR, as its own step (`just test-wheel`); the default `pytest` run skips them |
| End to end | The lamp-arm project from GROUND to RELEASE through MCP, with real kernels and FreeCAD | `tests/e2e/` | On `main`, nightly, and on PRs labelled `e2e` |

## Rules

- Port a prototype test case only if it guards behaviour benchhand still has. Don't port tests of prototype internals.
- Don't test generated code, third-party libraries, or a mock against itself.
- Prefer one API test that drives a real path over several unit tests that each mock a neighbour.
- A test that needs FreeCAD, a CAD kernel or Chromium belongs with the end-to-end tests, unless it's a provider's own conformance test.
- Keep the PR job fast: one runner, one environment sync, and no matrix unless a check really needs another OS.
