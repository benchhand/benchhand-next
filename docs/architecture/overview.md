# Architecture overview

Start here. This page draws benchhand's software in layers. The other pages go further into each part:

- [context.md](context.md): the system context, with the user, the agent hosts and the systems benchhand works with.
- [containers.md](containers.md): the containers, the components of `benchhand-core`, and the contracts pipeline.
- [layers.md](layers.md): the layered architecture of plan section 1, the repository layout, and the package dependencies.
- [data-flow.md](data-flow.md): sequences for one MCP call, a long job, evidence and freeze, release, and migrate.
- [flow.md](flow.md) and the generated [domain model](../contract/generated/domain-model.md).

The diagrams are D2, the format of the domain model. Each has its source and its rendered SVG in [`overview/`](overview/).

## The diagram rule

- A solid box or arrow is on `main`, checked against the code at `518c2ae`.
- A dashed box or arrow is in a later phase, on a branch, or open. Its label gives its phase from the [Steps](../design-plan.md#steps-phased) of the design plan, or says why it has none.
- A count comes from generated output only. The record count is from the generated [domain model](../contract/generated/domain-model.md#overview-the-record-documents).
- Each box names a package path or a doc. The tables below cite why each box has its style.
- The colours follow the [legend](README.md#legend) of the other pages. Green is on `main`, orange is on a branch, white is a later phase, red is open and grey is outside benchhand.

## The software in layers

![The software architecture in layers](overview/layers.svg)

Six layers stack from the clients down to storage. The contracts sit beside them, because every layer reads its shapes from them (ADR-0017).

| Box | Style | Evidence |
|---|---|---|
| Claude Code CLI, Claude Desktop, Codex CLI, OpenCode, Pi | Outside benchhand | Probe runs in `docs/client-support.md`; run records for Claude Code, Codex, OpenCode and Pi in `tools/probe/runs/` |
| Codex / ChatGPT desktop | Open | `docs/client-support.md`: "manual run needed" |
| Kiro CLI | Open | `docs/client-support.md`: Kiro connects and lists the probe tools, and the model's tools lack them, under the default and a custom agent |
| benchhand CLI | On `main` | `packages/benchhand/src/benchhand/cli.py` has `version` and `record migrate`. The other subcommands are in Phase 3 |
| Browser UI | Phase 5 | `ui/` holds only `shared/` on `main`. Phase 5 builds the viewer, concept, gallery, gate card and flow view |
| benchhand server and its MCP surface, interaction layer and tools | Phase 3, Apps and tasks Phase 5 | No `benchhand mcp` on `main`. Phase 3 lists the tools; Phase 4 the output, drawing and release tools |
| Flow engine | Phase 2 | No `flow/` directory and no flow code on `main` |
| Preview host | Phase 5 | Not on `main` |
| Record: store, validate, migrate, evidence | On `main` | `packages/benchhand-core/src/benchhand_core/record/`: `store.py`, `validate.py` with `rules/`, `migrate/`, `evidence/` |
| Versions | Phase 2 | Not on `main`; the Phase 1 step moves snapshot, seal and verify to Phase 2 |
| Jobs | On `main` | `packages/benchhand-core/src/benchhand_core/jobs/`: `service.py`, `supervisor.py`, `store.py` |
| Policy service | Phase 2 | Phase 2 lists policy (`hw/policy.yaml`) with the interpreter. On `main` the record already reads `hw/policy.yaml` (`record/documents.py`), and `rules/decisions.py` checks an approved gate against its mode |
| Provider protocol | On `main` | `contracts/provider/protocol.tsp`, `contracts/provider/manifest.tsp` and [provider-protocol.md](../contract/provider-protocol.md) |
| Provider runtime and conformance kit | Phase 4, on a branch | `packages/benchhand-provider/src/benchhand_provider/__init__.py` is a one-line stub on `main`. The runtime and kit are on `pi-subagents/task-4-a307ae9-5a16-s0-t0` |
| Provider host, the arrow from core | Open | No phase in the Steps ([containers.md](containers.md#legend)) |
| Kernels, solvers, render, checks, store | Phase 4 | No `providers/` directory on `main` |
| FreeCAD: managed install and probe | Phase 4, on a branch | On `pi-subagents/task-5-e1402fe-4bd3-s0-t0`, in `benchhand_core/freecad/` and `contracts/env/` |
| Project `hw/` | On `main` | The record service reads and writes it |
| Project `.benchhand/` | On `main` | `jobs/store.py` `RecordStore` writes `.benchhand/runs/<jobId>.json` |
| User cache with managed FreeCAD | Phase 4, on a branch | `<data>/freecad/<version>` on `pi-subagents/task-5-e1402fe-4bd3-s0-t0` (design plan D5) |
| TypeSpec, JSON Schema, Pydantic, TypeScript | On `main` | `contracts/*.tsp`, `benchhand_contracts/schemas/`, `benchhand_contracts/models/`, `ui/shared/contracts/`. `benchhand-core` imports the models and `validate` |
| Envelope, flow, flow rules and policy contribution contracts | Phase 1 list, on a branch | On `pi-subagents/task-1-3d530ac-2da9-s0-t0`, provisional. `main` has no `contracts/envelope/`, `contracts/flow/` or `contracts/policy/` |
| CEL environment | Phase 2 | Not on `main` ([containers.md](containers.md#contracts-and-codegen)) |

## Rendering

The SVGs are rendered with d2 0.9.0 and the ELK layout:

```sh
cd docs/architecture/overview
d2 --layout elk --pad 40 layers.d2 layers.svg
```

## Sources

- `docs/design-plan.md`: [1. Layered architecture](../design-plan.md#1-layered-architecture), [3. Transport](../design-plan.md#3-transport-stdio-vs-localhost-http-d10), [5. Flow engine and rules](../design-plan.md#5-flow-engine-and-rules-d14), [6a. Contracts](../design-plan.md#6a-contracts-generated-and-enforced-d17), [8. Prerequisites, FreeCAD and the container](../design-plan.md#8-prerequisites-freecad-and-the-container) and [Steps (phased)](../design-plan.md#steps-phased).
- `docs/adr/`: [0002](../adr/0002-install-uvx-and-container.md) (install and container), [0010](../adr/0010-stdio-transport.md) (stdio), [0013](../adr/0013-provider-protocol.md) (provider protocol), [0014](../adr/0014-flow-rules-cel.md) (CEL), [0016](../adr/0016-dev-only-probe.md) (probe) and [0017](../adr/0017-contracts.md) (contracts).
- [docs/client-support.md](../client-support.md) and [docs/contract/provider-protocol.md](../contract/provider-protocol.md).
- Code on `main` at `518c2ae`: `packages/*/src/`, `contracts/`, `ui/shared/contracts/` and `tools/probe/`.
- Branches, for the orange boxes: `pi-subagents/task-1-3d530ac-2da9-s0-t0` (envelope, flow and policy contracts), `pi-subagents/task-4-a307ae9-5a16-s0-t0` (provider runtime and kit) and `pi-subagents/task-5-e1402fe-4bd3-s0-t0` (FreeCAD install and probe).
