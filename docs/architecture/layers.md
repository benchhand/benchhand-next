# Layers and packages

The layered architecture of plan section 1, the repository layout of section 2, and the package dependencies as the `pyproject.toml` files on `main` declare them.
The last section lists where the plan and the code differ.

## Layered architecture

```mermaid
flowchart TB
  harness["Harness: Claude Code, Claude Desktop, Codex CLI and app, OpenCode, Kiro, Pi, any MCP client<br/>bootstrap skill and server instructions: call flow.guide"]:::ext

  subgraph server["benchhand MCP server: one process per harness session, started from the MCP config"]
    surface["MCP surface: tools, resources, prompts, skills-over-MCP, Apps, tasks and jobs<br/>Phase 3, Apps and tasks Phase 5, skills-over-MCP Phase 6"]:::planned
    interaction["Interaction layer: picks App, chat, image or URL per client capability<br/>Phase 3 and Phase 5"]:::planned
    preview["Preview host, loopback HTTP<br/>viewer, concept, gate page, flow view, prototype pages<br/>Phase 5"]:::planned
    subgraph core["core"]
      flowEngine["Flow engine<br/>flow.yaml graph and state machine, CEL guards, decision records, policy<br/>Phase 2"]:::planned
      guide["Guide service<br/>per-stage and per-role instructions served by flow.guide<br/>Phase 2 and Phase 3"]:::planned
      record["Record service<br/>schemas, typed record ops, validate, migrate, evidence, release<br/>validate on main, the rest later"]:::impl
      jobs["Job service<br/>long jobs, process groups, progress, cancellation<br/>on main"]:::impl
      middleware["Middleware chain<br/>validation, policy, audit, provenance, cache, telemetry<br/>open: no phase"]:::open
      providerHost["Provider host<br/>JSON-RPC 2.0 plugin protocol, lifecycle, timeouts<br/>open: no phase"]:::open
    end
  end

  providers["Providers<br/>kernel-cadquery, kernel-build123d, freecad, solver-calculix, collision-fcl,<br/>render-chromium, checks-process, store-fs: Phase 4<br/>viewer-ocp, policy-default: open, no phase"]:::planned

  harness -.->|"stdio by default, streamable HTTP on loopback with --http"| surface
  surface -.-> interaction
  surface -.-> preview
  surface -.-> core
  providerHost -.->|"JSON-RPC over stdio, one subprocess per provider, each in its own uv env"| providers

  style server fill:#fafafa,stroke:#9e9e9e,color:#1b1b1b
  style core fill:#f5f5f5,stroke:#9e9e9e,color:#1b1b1b

  classDef impl fill:#e8f5e9,stroke:#2e7d32,stroke-width:2px,color:#1b1b1b
  classDef review fill:#fff3e0,stroke:#e65100,stroke-width:2px,stroke-dasharray:6 4,color:#1b1b1b
  classDef planned fill:#ffffff,stroke:#616161,stroke-width:1px,stroke-dasharray:6 4,color:#1b1b1b
  classDef open fill:#ffebee,stroke:#c62828,stroke-width:2px,stroke-dasharray:2 3,color:#1b1b1b
  classDef ext fill:#eceff1,stroke:#37474f,stroke-width:1px,color:#1b1b1b
  classDef person fill:#e3f2fd,stroke:#1565c0,stroke-width:2px,color:#1b1b1b
```

## Package dependencies

Solid arrows are the `dependencies` of each `pyproject.toml` on `main`, and nothing else. Each arrow between workspace packages says whether the source code imports the target yet.

```mermaid
flowchart LR
  subgraph workspace["uv workspace: packages/*"]
    benchhand["benchhand<br/>CLI: version only on main<br/>requires-python >=3.12"]:::impl
    core["benchhand-core<br/>record and job services<br/>requires-python >=3.12"]:::impl
    contracts["benchhand-contracts<br/>generated models and validators<br/>requires-python >=3.12"]:::impl
    provider["benchhand-provider<br/>empty stub<br/>requires-python >=3.11"]:::impl
    sdk["benchhand-sdk<br/>empty stub, no dependencies<br/>requires-python >=3.11"]:::impl
  end

  typer["typer >=0.15"]:::ext
  pyyaml["pyyaml >=6.0"]:::ext
  pydantic["pydantic >=2.9"]:::ext
  validation["jsonschema >=4.23<br/>referencing >=0.35<br/>regress >=2026.9"]:::ext

  benchhand -->|"declared, not imported yet"| core
  benchhand --> typer
  core -->|"imported"| contracts
  core -->|"declared, not imported yet"| provider
  core --> pyyaml
  core --> pydantic
  provider -->|"declared, not imported yet"| contracts
  contracts --> pydantic
  contracts --> validation

  providersDir["providers/*<br/>each its own pyproject and pinned env<br/>Phase 4"]:::planned
  benchhand -.->|"built-ins ship in the wheel extras"| providersDir
  providersDir -.->|"the manifest example lists benchhand-provider"| provider
  providersDir -.->|"open: which env gives model.py benchhand-sdk"| sdk

  style workspace fill:#fafafa,stroke:#9e9e9e,color:#1b1b1b

  classDef impl fill:#e8f5e9,stroke:#2e7d32,stroke-width:2px,color:#1b1b1b
  classDef review fill:#fff3e0,stroke:#e65100,stroke-width:2px,stroke-dasharray:6 4,color:#1b1b1b
  classDef planned fill:#ffffff,stroke:#616161,stroke-width:1px,stroke-dasharray:6 4,color:#1b1b1b
  classDef open fill:#ffebee,stroke:#c62828,stroke-width:2px,stroke-dasharray:2 3,color:#1b1b1b
  classDef ext fill:#eceff1,stroke:#37474f,stroke-width:1px,color:#1b1b1b
  classDef person fill:#e3f2fd,stroke:#1565c0,stroke-width:2px,color:#1b1b1b
```

## Repository layout

```mermaid
flowchart TB
  repo["benchhand-next/"]:::ext
  subgraph code["Code and contracts"]
    direction TB
    packagesDir["packages/<br/>benchhand, benchhand-contracts, benchhand-core,<br/>benchhand-provider, benchhand-sdk"]:::impl
    contractsDir["contracts/<br/>TypeSpec sources"]:::impl
    uiShared["ui/shared/<br/>generated contract types"]:::impl
    uiApps["ui/ viewer, concept, gate-card, flow-view<br/>Phase 5"]:::planned
    providersDir["providers/<br/>Phase 4"]:::planned
  end
  subgraph product["Process and distribution"]
    direction TB
    flowDir["flow/<br/>flow.yaml, guides, CEL rule lists<br/>Phase 2"]:::planned
    harnessDir["harness/<br/>install templates<br/>Phase 6"]:::planned
    containerDir["container/<br/>OCI image<br/>Phase 7"]:::planned
    releaseToml["release.toml<br/>repo name, image, reference_commit"]:::impl
  end
  subgraph support["Tools, docs and reference"]
    direction TB
    probe["tools/probe/<br/>dev-only capability probe"]:::impl
    toolsGen["tools/gen/, tools/equiv/<br/>contracts generator, TypeSpec equivalence evidence"]:::impl
    docsDir["docs/<br/>adr/, contract/, phases/, architecture/, client-support.md"]:::impl
    reference["reference/<br/>prototype tests, examples, agents, harness"]:::impl
    examples["examples/lamp-arm/<br/>golden fixture, on main only under reference/"]:::planned
  end

  repo --> code & product & support

  style code fill:#fafafa,stroke:#9e9e9e,color:#1b1b1b
  style product fill:#fafafa,stroke:#9e9e9e,color:#1b1b1b
  style support fill:#fafafa,stroke:#9e9e9e,color:#1b1b1b

  classDef impl fill:#e8f5e9,stroke:#2e7d32,stroke-width:2px,color:#1b1b1b
  classDef review fill:#fff3e0,stroke:#e65100,stroke-width:2px,stroke-dasharray:6 4,color:#1b1b1b
  classDef planned fill:#ffffff,stroke:#616161,stroke-width:1px,stroke-dasharray:6 4,color:#1b1b1b
  classDef open fill:#ffebee,stroke:#c62828,stroke-width:2px,stroke-dasharray:2 3,color:#1b1b1b
  classDef ext fill:#eceff1,stroke:#37474f,stroke-width:1px,color:#1b1b1b
  classDef person fill:#e3f2fd,stroke:#1565c0,stroke-width:2px,color:#1b1b1b
```

## Legend

- Styles as in the [legend](README.md#legend). Solid arrows exist on `main`, and dashed arrows are planned.
- The record service is solid because `store` and `validate` are on `main`. Migrate and evidence are in review, and versions and release come in Phases 2 and 4 ([containers.md](containers.md#components-of-benchhand-core)).
- Plan section 1 also lists elicitation on the MCP surface, and forms in the interaction layer. ADR-0018 drops form elicitation from v1, so neither is drawn.
- **Open: no phase.** The middleware chain, the provider host, `viewer-ocp` and `policy-default` have no phase in the plan's Steps. **Open: the SDK's environment.** The plan says `model.py` imports `benchhand-sdk`, but the kernel manifest example doesn't list it among its dependencies. The plan's [Open questions](../design-plan.md#open-questions) list neither item.

## Where the plan and the code differ

| Topic | Plan | ADRs and `main` |
|---|---|---|
| Contract source | Section 2, section 6a and D17: hand-written JSON Schema 2020-12 under `contracts/` | ADR-0017, revised: TypeSpec under `contracts/`, compiled to the published JSON Schema |
| Repo name | Section 2 and Phase 0: one `BENCHHAND_REPO` variable in CI and the templates | ADR-0015: `release.toml` is the only place that names the repo; `main` has `release.toml` `repo` |
| Core to provider runtime | Section 2 lists the packages and states no edges between them | `benchhand-core` declares `benchhand-provider`, and doesn't import it |
| Declared, unused | Not stated | `benchhand` declares `benchhand-core`, and `benchhand-provider` declares `benchhand-contracts`; neither imports it yet |
| Phase 1 contracts | Phase 1: record, envelope, provider protocol, flow, policy | No envelope or flow contract on `main`; `docs/phases/phase-0-1.md` doesn't list them as not built |
| Phase 1 services | Phase 1: migrate and evidence | Both on unmerged branches; `docs/phases/phase-0-1.md` lists them as not built |
| TypeSpec timing | Phase 2: the record additions are "made with the move to TypeSpec" | ADR-0017: the move to TypeSpec happened in Phase 1 |
| Forms | Section 1 lists elicitation and forms | ADR-0018: no form elicitation in v1; section 11 was updated, section 1 wasn't |
| Long calls | Section 11 and provider-protocol section 8: about 50 s | ADR-0018: about 30 s |
| CLI | D1 and section 7: `mcp`, `serve`, `install`, `doctor`, `setup`, `policy`, `debug call` | `main` has only `version`, which D1 doesn't list; the migrate lane adds `record migrate` |
| Golden fixture | Section 2: `examples/lamp-arm/` | Only `reference/examples/lamp-arm/` |
| Tools | Section 2 lists `tools/probe/` | `main` also has `tools/gen/` and `tools/equiv/` |

## Sources

- `docs/design-plan.md`:
  - [1. Layered architecture](../design-plan.md#1-layered-architecture): every node of the first diagram.
  - [2. Repository and package layout](../design-plan.md#2-repository-and-package-layout-temporary-repo-benchhandbenchhand-next): the packages, `providers/`, `ui/`, `contracts/`, `flow/`, `harness/`, `container/`, `tools/probe/`, `examples/lamp-arm/`, and `BENCHHAND_REPO`.
  - [6. Provider protocol (D13)](../design-plan.md#6-provider-protocol-d13): one uv environment per provider.
  - [6a. Contracts: generated and enforced (D17)](../design-plan.md#6a-contracts-generated-and-enforced-d17), [7. CLI (D1)](../design-plan.md#7-cli-d1), [11. Adaptive interaction layer (D8)](../design-plan.md#11-adaptive-interaction-layer-d8) and [12. Build API (D7)](../design-plan.md#12-build-api-d7) (the part SDK).
  - [Steps (phased)](../design-plan.md#steps-phased): the phase of every node, and the Phase 1 and Phase 2 lists.
- `docs/adr/`: [0006](../adr/0006-providers-everywhere.md), [0010](../adr/0010-stdio-transport.md), [0013](../adr/0013-provider-protocol.md), [0015](../adr/0015-temporary-repo.md), [0016](../adr/0016-dev-only-probe.md), [0017](../adr/0017-contracts.md) and [0018](../adr/0018-baseline-and-no-forms.md), each under "Decision".
- `docs/contract/provider-protocol.md`: [7. Provider manifest](../contract/provider-protocol.md#7-provider-manifest): the example's `dependencies`.
- `docs/phases/phase-0-1.md`: [What was built](../phases/phase-0-1.md#what-was-built) and [Not built, which the plan puts in Phase 1](../phases/phase-0-1.md#not-built-which-the-plan-puts-in-phase-1).
- Code on `main`: `packages/*/pyproject.toml` (`dependencies`, `requires-python`, `[tool.uv.sources]`), the root `pyproject.toml` (`[tool.uv.workspace] members`), the imports under `packages/*/src/`, `release.toml`, and the top-level directories.
