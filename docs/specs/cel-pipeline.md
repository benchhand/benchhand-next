---
spec: cel-pipeline
title: The CEL pipeline and the flow's rule lists
status: draft
capabilities:
  - cel-rule-pipeline
  - rule-lists
questions:
  - user-bundle-location
rules:
  - RULE-05
issues:
  closes: []
  defers:
    - id: IR-043
      to: check-orchestration
      reason: >-
        It joins through fail_fast.py, but its fix is in the gate run that starts the producers, which is
        check orchestration in Phase 4. The checks_by_iteration list here only gives the check ids in run order.
blocks:
  - id: CP-1
    title: Rule scopes and the structural-scope check
    size: M
    requirements: [REQ-1, REQ-2, REQ-3]
    depends_on: [question:user-bundle-location]
  - id: CP-2
    title: The profile-manifest and rules-bundle contracts, and where a bundle lives
    size: S
    requirements: [REQ-7]
    depends_on: [question:user-bundle-location]
  - id: CP-3
    title: The descriptor set for each scope
    size: M
    requirements: [REQ-4]
    depends_on: [CP-1]
  - id: CP-4
    title: The JCS digest and its test vector
    size: S
    requirements: [REQ-5, REQ-6]
    depends_on: [CP-2]
  - id: CP-5
    title: The profile manifest and the env YAML for each scope
    size: M
    requirements: [REQ-4, REQ-17]
    depends_on: [CP-3, CP-4]
  - id: CP-6
    title: The pinned cel-go tool and its environment checks
    size: M
    requirements: [REQ-6, REQ-8, REQ-13]
    depends_on: [CP-5]
  - id: CP-7
    title: Compiling a rule list in the restricted profile
    size: M
    requirements: [REQ-9]
    depends_on: [CP-6]
  - id: CP-8
    title: Writing the rules bundle
    size: S
    requirements: [REQ-7]
    depends_on: [CP-7]
  - id: CP-9
    title: The host adapter and bundle verification
    size: M
    requirements: [REQ-11, REQ-12, REQ-13, REQ-19]
    depends_on: [CP-5, CP-8]
  - id: CP-10
    title: The presence lint
    size: M
    requirements: [REQ-14]
    depends_on: [CP-9]
  - id: CP-11
    title: The flow's four rule lists and the stale-entry step in CI
    size: M
    requirements: [REQ-10, REQ-15, REQ-16]
    depends_on: [CP-8, CP-9]
  - id: CP-12
    title: Both checkers of record on every shipped expression in CI
    size: M
    requirements: [REQ-18]
    depends_on: [CP-11, FE-2]
  - id: CP-13
    title: The supported-profile conformance gate in CI
    size: L
    requirements: [REQ-18]
    depends_on: [CP-9, CP-10]
---

# The CEL pipeline and the flow's rule lists

Baseline: pointers checked against `main` at `58dea29e`.

## Capabilities

- [`cel-rule-pipeline`](../architecture/capabilities.md#cel-rule-pipeline): the CEL environment as data, the pinned cel-go tool and the host's adapter. The catalogue gives it no MCP tool. Its user surface is `benchhand rules compile` (Phase 3). Contracts: `common/cel`, `flow/rules`, and the planned profile manifest and rules bundle.
- [`rule-lists`](../architecture/capabilities.md#rule-lists): the ordered first-match rule lists that replace the prototype's decision tables. No MCP tool: the flow engine and the check tools evaluate them. Contract: `flow/rules`.

## Problem and users

The prototype keeps its decision tables in Python (`fail_fast.py`, `process_checks/dispatch.py`). Reading or extending a table takes a code change, and a condition is first checked when it runs. benchhand moves every decision to CEL (ADR-0014), so a wrong field name or operand type must fail at load, never mid-flow.

- **Maintainers** write `flow/*.celpolicy` and the flow's expressions, and need CI to refuse a list that doesn't type-check against the contracts.
- **Policy-provider authors** ship rule lists that the host must verify before it runs them.
- **The agent** gets a load-time refusal that names the file and the command to run, never a wrong pass.

## Requirements

- **REQ-1.** Each rule scope names the variables a rule sees, each pointing at one node of a published schema, and may omit fields; a rule that reads an omitted field fails the check. Source: `docs/adr/0020-cel-rule-pipeline.md:55`. How a scope is declared, a TypeSpec marker or a scope file, is open (`user-bundle-location`, `docs/adr/0020-cel-rule-pipeline.md:236`).
- **REQ-2.** The generator refuses a scope that reaches a node with more than one shape, and reports the path and the reason. That covers a shaped `oneOf` or `anyOf`, a shape-merging `allOf`, an untyped node, an unsealed object, a map of lists, a nullable message and a field named with a CEL reserved word. No reachable path is typed `dyn`. Source: `docs/adr/0020-cel-rule-pipeline.md:57-67`.
- **REQ-3.** The generator maps JSON Schema to proto3 and CEL by the table of `docs/adr/0020-cel-rule-pipeline.md:69-77`.
- **REQ-4.** For each scope, `contracts_gen` generates a FileDescriptorSet and an environment profile manifest, under the drift check, and nobody writes them by hand. The manifest holds the fields of `docs/adr/0020-cel-rule-pipeline.md:34-39`, with `cross_type_numeric_comparisons` and `homogeneous_aggregate_literals` both `false`. Source: `docs/design-plan.md:554`.
- **REQ-5.** The profile digest is the SHA-256 of the manifest's RFC 8785 canonical JSON. The generator refuses a manifest with a float, a non-ASCII string or an integer beyond 2^53 in either sign. Source: `docs/adr/0020-cel-rule-pipeline.md:47-49`.
- **REQ-6.** A committed JCS test vector holds a manifest, its canonical bytes and its digest. The cel-go tool and the host each reproduce it byte for byte in CI. Source: `docs/design-plan.md:555`, `docs/adr/0020-cel-rule-pipeline.md:51`.
- **REQ-7.** `contracts/` holds the profile-manifest and rules-bundle contracts. A bundle's identity is the profile digest, the checker, and the SHA-256 of each entry's payload. Each entry also carries the rule list's path, its output type and its source SHA-256. Source: `docs/design-plan.md:556`, `docs/adr/0020-cel-rule-pipeline.md:130-136`. The bundle contract names the path and file name of a project's bundle and of a provider package's bundle, next to the sources each covers. Phase 2 picks them with the bundle contract (`docs/adr/0020-cel-rule-pipeline.md:235`).
- **REQ-8.** `tools/celcheck/` is a Go module pinned to one `cel.dev/cel-go` version and its matching `policy` module. It verifies the descriptor-set bytes against the manifest before it builds an environment, and refuses a mismatch. Source: `docs/adr/0020-cel-rule-pipeline.md:128`, `docs/design-plan.md:559`.
- **REQ-9.** The tool compiles a rule list only in the restricted profile. It refuses `variables`, `aggregate`, a nested `rule`, `imports` and every other excluded field before the policy compiler runs. It refuses an output type other than the kind's slot type, and a list in which only some choices have an `explanation`. It compiles explanations as a second checked expression and refuses one whose type isn't `string`. Source: `docs/adr/0020-cel-rule-pipeline.md:104-124`, `docs/contract/flow.md:21-29`, `docs/phases/phase-0-1.md:126`.
- **REQ-10.** CI compiles `flow/*.celpolicy` into the rules bundle and fails when a shipped entry is stale. Source: `docs/design-plan.md:557`, `docs/adr/0020-cel-rule-pipeline.md:140`.
- **REQ-11.** The host checks standalone expressions and evaluates every rule with `cel-expr-python`, behind one adapter with the operations `load`, `check`, `program`, `eval` and `identity`. A rule whose evaluation fails gives a finding with UNKNOWN coverage, never a pass. Source: `docs/design-plan.md:164`, `docs/adr/0020-cel-rule-pipeline.md:168`.
- **REQ-12.** At load the host runs the six checks of `docs/adr/0020-cel-rule-pipeline.md:145-150`. A refusal stops the load and names the file and `benchhand rules compile`. After the checks, the host evaluates each checked expression without checking it again. Source: `docs/adr/0020-cel-rule-pipeline.md:152`, `docs/design-plan.md:558`.
- **REQ-13.** Each adapter refuses, at load, an extension version outside its own inventory and a manifest option it can't set, and each refuses descriptor-set bytes whose SHA-256 differs from the manifest's. A profile enables an extension only at a version that both engines implement. Source: `docs/adr/0020-cel-rule-pipeline.md:41`, `docs/adr/0020-cel-rule-pipeline.md:43`, `docs/adr/0020-cel-rule-pipeline.md:188`.
- **REQ-14.** The loader's presence lint flags a bare read of an optional or nullable field outside a `has()` guard, and a `has()` on a required scalar. Source: `docs/adr/0020-cel-rule-pipeline.md:100`, `docs/adr/0020-cel-rule-pipeline.md:239`.
- **REQ-15.** `flow/` holds one list of each kind: `checks_by_iteration`, `dispatch`, `fidelity` and `rigor`, each with the output type and the last choice of `docs/contract/flow.md:33-38`. Every list but dispatch ends with an explicit default of its output type. The lists carry the prototype's tables, as the fixture at `tests/fixtures/flow/prototype-412b5d9/` writes them. Source: `docs/design-plan.md:154-160`, `docs/contract/flow.md:74-77`.
- **REQ-16.** The dispatch list's last choice gives `"unknown"`, which the host records as UNKNOWN coverage and never as a pass (RULE-05). Source: `docs/design-plan.md:156`.
- **REQ-17.** The first profile enables the `strings` extension only, as the research's gate-guard profile did. **Proposal** for the owner: `docs/adr/0020-cel-rule-pipeline.md:237` leaves the list to the first rule lists.
- **REQ-18.** In CI, each engine passes the supported-profile cases of its role, for every profile. Both checkers of record check every standalone expression that benchhand ships. CI fails when they disagree on whether an expression checks, or on its output type. Source: `docs/design-plan.md:560`, `docs/adr/0020-cel-rule-pipeline.md:173-191`.
- **REQ-19.** When the matching choice of a list has an explanation, the host evaluates the explanation's checked expression on the same activation as the output's, and the finding's text is the explanation's result. Source: `docs/adr/0020-cel-rule-pipeline.md:120`.

## Interfaces

- **MCP tools:** none. The catalogue records the capability as load-time machinery.
- **CLI:** none here. `benchhand rules compile` and the `benchhand-celcheck` platform wheel are Phase 3 (`docs/adr/0020-cel-rule-pipeline.md:203`).
- **Contracts:**
  - new: the environment profile manifest and the rules bundle (CP-2), each at `0.1.0` and provisional. Their names in `contracts/` follow the scope decision of CP-1, and the bundle contract names where a project's and a provider's bundle live;
  - read: `common/cel` and `flow/rules`, unchanged.
- **Provider methods:** none. A policy provider ships rule lists as data (`docs/contract/policy.md:23-26`). The flow engine spec merges them.
- **Code:** `tools/gen/contracts_gen` (the scope check, the descriptor set, the manifest and the env YAML), `tools/celcheck/` (Go), and the adapter in `packages/benchhand-core`.

## Issue register

No Phase 2 register entry is closed here. The one joined entry is deferred:

| Entry | Deferred to | Why |
|---|---|---|
| IR-043 | `check-orchestration` | The fix is in the gate run that starts the producers. |

## Prototype behaviour replaced

| Prototype | Inventory | Replaced by | Oracle tests |
|---|---|---|---|
| `fail_fast.py` `plan`, the scope matrix | `docs/architecture/prototype-inventory.md:2313` | `flow/checks-by-iteration.celpolicy` | `reference/skills/cad-record/tests/test_fail_fast.py:93`, `reference/skills/cad-record/tests/test_fail_fast.py:103` |
| `process_checks/dispatch.py` `handler_for` | `docs/architecture/prototype-inventory.md:437` | `flow/dispatch.celpolicy` | `reference/skills/cad-design/tests/test_process_checks.py:862` |
| `process_checks/dispatch.py` `coverage_gap` | `docs/architecture/prototype-inventory.md:438` | the dispatch list's `"unknown"` | `reference/skills/cad-design/tests/test_process_checks.py:862` |

`fail_fast.py`'s run itself, `status_of` and the producers it starts and stops (`docs/architecture/prototype-inventory.md:2314`), stays with check orchestration.

## Non-goals

- `benchhand rules compile` and the platform wheel: Phase 3. Publishing the wheel: Phase 7 (`docs/adr/0020-cel-rule-pipeline.md:203`).
- The enum lint, which isn't decided (`docs/adr/0020-cel-rule-pipeline.md:238`), and a fallback evaluator (`docs/adr/0020-cel-rule-pipeline.md:240`).
- Cost budgets, collection bounds and a runtime limit, which the plan defers (`docs/design-plan.md:171`).
- Merging providers' lists and evaluating lists in the flow: the [flow engine spec](flow-engine.md).

## Open questions

| Question | Blocking | Blocks that wait |
|---|---|---|
| [`user-bundle-location`](../architecture/capabilities.md#user-bundle-location) | no: Phase 2 picks | CP-1 picks how a scope is declared. CP-2 picks where a project's and a provider's bundle live. `benchhand rules compile` and the wheel stay in Phase 3. |

## Blocks

### CP-1: Rule scopes and the structural-scope check

Size M. Depends on `user-bundle-location`, which this block answers for the scope declaration.

**Scope.** Pick how a scope is declared and record the choice in ADR-0020's open items. Add the scope definitions for the flow's expressions and the four rule kinds. Add the `contracts_gen` structural-scope check with the refusals of REQ-2, and the type mapping of REQ-3.

**Acceptance.** Generator tests: one refusal fixture for each shape of REQ-2, each naming the path and the reason, and a sealed scope that passes. A mapping test for each row of the type table.

### CP-2: The profile-manifest and rules-bundle contracts, and where a bundle lives

Size S. Depends on `user-bundle-location`, which this block answers for the bundle's place.

**Scope.** Write the two contracts in TypeSpec with their examples. Regenerate the schemas, models, types and reference pages. Pick the path and file name of a project's bundle and of a provider package's bundle, next to the sources each covers, and record the choice in the bundle contract's page and in ADR-0020's open items.

**Acceptance.** `just contracts-check` is clean. Contract tests validate each example and refuse a manifest without `descriptor_set` and a bundle entry without its source SHA-256. The bundle contract's page names both locations, and ADR-0020's open item on them is marked decided.

### CP-3: The descriptor set for each scope

Size M. After CP-1.

**Scope.** Generate the `.proto` files and the FileDescriptorSet for each scope from its definition, under the drift check.

**Acceptance.** Generator tests: each scope's descriptor set holds one message per schema node it reaches, typed by the table of REQ-3. The drift check fails on a hand-edited `.proto` file.

### CP-4: The JCS digest and its test vector

Size S. After CP-2.

**Scope.** Compute the profile digest in Python as RFC 8785 canonical JSON, with the refusals of REQ-5. Commit the JCS test vector: a manifest, its canonical bytes and its digest.

**Acceptance.** The Python digest reproduces the vector's bytes and digest. Refusal tests for a float, a non-ASCII string, and an integer of 2^53 + 1 and its negative.

### CP-5: The profile manifest and the env YAML for each scope

Size M. After CP-3 and CP-4.

**Scope.** Generate each scope's manifest, with its descriptor set's SHA-256 and its profile digest, and the cel-go env YAML, under the drift check. The manifest enables the extensions of REQ-17 once the owner approves them.

**Acceptance.** The drift check fails on a hand-edited manifest. Each manifest validates against the CP-2 contract, and its digest is the CP-4 digest of its bytes. Both cross-type options are `false`.

### CP-6: The pinned cel-go tool and its environment checks

Size M. After CP-5.

**Scope.** Add `tools/celcheck/`, pinned as REQ-8 says. It builds an environment from a manifest after it checks the descriptor-set bytes, its extension inventory and the manifest's options, and it reproduces the JCS vector.

**Acceptance.** Go tests:

- a descriptor set whose bytes differ from the manifest is refused;
- an extension version outside the tool's inventory is refused;
- a manifest option the tool can't set is refused;
- the JCS vector, byte for byte.

### CP-7: Compiling a rule list in the restricted profile

Size M. After CP-6.

**Scope.** The tool compiles a rule list in the restricted profile of REQ-9 into its checked expressions, with a second checked expression for the explanations when the list has them.

**Acceptance.** Go tests:

- a refusal fixture for each excluded cel-policy feature, and one for a wrong slot type;
- a list with explanations on some choices only, and an explanation that isn't a `string`;
- a list that compiles gives its output and explanation expressions, with their types.

### CP-8: Writing the rules bundle

Size S. After CP-7.

**Scope.** The tool writes the compiled lists into a bundle of the CP-2 contract, with the identity and the per-entry fields of REQ-7.

**Acceptance.** A Go test compiles two lists and validates the bundle against the contract. Its identity changes when one list's source changes, and when the profile digest changes.

### CP-9: The host adapter and bundle verification

Size M. After CP-5 and CP-8.

**Scope.** The `cel-expr-python` adapter with its five operations, its environment checks of REQ-13, and the load-time bundle verification of REQ-12. Each refusal names the file and `benchhand rules compile`. Evaluation follows REQ-11 and REQ-19. The host reads a project's and a provider's bundle from the places CP-2 names.

**Acceptance.** Host tests:

- the four tampered-bundle cases (another profile's digest, an edited source, a substituted payload, a checker not of record), a rule list with no entry, a descriptor set whose bytes differ, an unknown extension version and an option the adapter can't set. Each refusal names the file and the command;
- a rule whose evaluation fails, such as a division by zero, gives a finding with UNKNOWN coverage;
- a matching choice with an explanation gives a finding whose text is the explanation's result;
- a project bundle and a provider bundle at the CP-2 places load.

The block replaces the dyn stand-in in `tests/rule_lists.py` with the typed environment.

### CP-10: The presence lint

Size M. After CP-9.

**Scope.** The loader's presence lint of REQ-14, run on standalone expressions and on rule-list sources.

**Acceptance.** Lint tests: a bare read of a nullable and of an optional field outside `has()` is flagged, a guarded read is not, and a `has()` on a required scalar is flagged.

### CP-11: The flow's four rule lists and the stale-entry step in CI

Size M. After CP-8 and CP-9.

**Scope.** Write `flow/checks-by-iteration.celpolicy`, `flow/dispatch.celpolicy`, `flow/fidelity.celpolicy` and `flow/rigor.celpolicy` from the fixture's lists, and compile them into the shipped bundle. Add the CI step that recompiles and fails on a stale entry.

**Acceptance.** Ported cases of `reference/skills/cad-record/tests/test_fail_fast.py:93-103` evaluate through the bundle: a commit iteration at `parts` gives the form check and the changed-only check, in order. A dispatch case with no handler gives `"unknown"`. A CI test edits one list without recompiling and expects the stale-entry failure.

### CP-12: Both checkers of record on every shipped expression in CI

Size M. After CP-11 and FE-2, whose `flow/flow.yaml` holds the standalone expressions that benchhand ships.

**Scope.** A CI job checks every standalone expression that benchhand ships with both checkers of record, and evaluates every shipped checked expression on the host.

**Acceptance.** The job fails on a fixture expression that one checker accepts and the other refuses, and on one whose output type the two checkers give differently. It passes on the shipped flow and rule lists.

### CP-13: The supported-profile conformance gate in CI

Size L. After CP-9 and CP-10.

**Scope.** The rest of the CI gate of REQ-18:

- each engine's accept, reject, profile and presence cases;
- the refusal and tampered-bundle cases;
- the cel-spec simple tests, against a committed failure baseline.

**Acceptance.** The CI job fails when an engine regresses on a case of its role, or on a cel-spec test outside the baseline. The explanation cases of `docs/adr/0020-cel-rule-pipeline.md:191` run on both engines.
