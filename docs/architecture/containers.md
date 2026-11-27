# Containers and components

The C4 containers of benchhand and the components of its core, each with the phase that delivers it.
The third diagram is the contracts pipeline that generates every message and record shape.

## Containers

```mermaid
flowchart LR
  host["Agent host"]:::ext
  person["Designer, in a web browser"]:::person

  subgraph process["benchhand mcp: the runner, one process<br/>stdio: the host starts one per session; --http: one shared server"]
    surface["MCP surface<br/>tools, resources, prompts<br/>MCP over stdio by default, or a loopback MCP HTTP listener with --http<br/>Phase 3"]:::planned
    interaction["Interaction layer<br/>chat fallbacks Phase 3<br/>App shells, image results, tasks adapter behind a flag Phase 5"]:::planned
    preview["Preview host<br/>a separate loopback HTTP listener: viewer, concept, gallery, gate card, flow view, prototype pages<br/>Phase 5"]:::planned
    core["benchhand-core<br/>record and job services on main<br/>see Components"]:::impl
    contractsPkg["benchhand-contracts<br/>generated pydantic models and validators"]:::impl
  end

  cli["benchhand CLI, Typer<br/>on main: version, record migrate<br/>Phase 3: mcp, doctor, setup, policy, rules compile, debug call<br/>Phase 4: provider subcommands<br/>Phase 5: serve, Phase 6: install"]:::impl

  subgraph providers["Providers: one subprocess each, in its own environment"]
    providerRuntime["benchhand-provider runtime and conformance kit<br/>stub on main, Phase 4"]:::planned
    kernels["kernel-cadquery, kernel-build123d<br/>kernel: build, export, inspect<br/>Phase 4"]:::planned
    sdk["benchhand-sdk, imported by model.py<br/>stub on main, Phase 4"]:::planned
    freecadProvider["freecad<br/>cad-app: drawing, assembly, fem<br/>Phase 4"]:::planned
    solver["solver-calculix<br/>solver: solve<br/>Phase 4"]:::planned
    collision["collision-fcl<br/>collision: check, sweep<br/>Phase 4"]:::planned
    renderer["render-chromium<br/>renderer: render, snapshot<br/>Phase 4"]:::planned
    checks["checks-process<br/>process-check: check, CEL dispatch<br/>Phase 4"]:::planned
    store["store-fs<br/>store: put, get, list<br/>Phase 4"]:::planned
    viewer["viewer-ocp<br/>viewer: show, compare, capture<br/>open: no phase in Steps"]:::open
    policy["policy-default<br/>policy: evaluate<br/>open: no phase in Steps"]:::open
  end

  ui["ui/ pnpm workspace, TypeScript and React<br/>viewer, concept, gallery, gate card, flow view<br/>Phase 5"]:::planned
  uiShared["ui/shared/contracts<br/>generated TypeScript types and Ajv validators"]:::impl
  hw[("hw/ design record")]:::ext

  host -.->|"MCP"| surface
  surface -.-> interaction
  surface -.-> core
  person -.->|"loopback URL"| preview
  preview -.->|"serves built assets"| ui
  ui -.-> uiShared
  cli -.->|"mcp starts the server"| surface
  cli -.->|"debug call: same code path as an MCP call"| surface
  cli -->|"record migrate"| core
  core --> contractsPkg
  core -->|"record service"| hw
  core -.->|"provider host: JSON-RPC 2.0 over stdio, Content-Length framing"| providerRuntime
  providerRuntime -.- kernels & freecadProvider & solver & collision & renderer & checks & store & viewer & policy
  kernels -.->|"runs model.py"| sdk

  style process fill:#fafafa,stroke:#9e9e9e,color:#1b1b1b
  style providers fill:#fafafa,stroke:#9e9e9e,color:#1b1b1b

  classDef impl fill:#e8f5e9,stroke:#2e7d32,stroke-width:2px,color:#1b1b1b
  classDef review fill:#fff3e0,stroke:#e65100,stroke-width:2px,stroke-dasharray:6 4,color:#1b1b1b
  classDef planned fill:#ffffff,stroke:#616161,stroke-width:1px,stroke-dasharray:6 4,color:#1b1b1b
  classDef open fill:#ffebee,stroke:#c62828,stroke-width:2px,stroke-dasharray:2 3,color:#1b1b1b
  classDef ext fill:#eceff1,stroke:#37474f,stroke-width:1px,color:#1b1b1b
  classDef person fill:#e3f2fd,stroke:#1565c0,stroke-width:2px,color:#1b1b1b
```

## Components of benchhand-core

```mermaid
flowchart TB
  surface["MCP surface, Phase 3"]:::planned

  subgraph core["benchhand-core, no CAD dependencies"]
    flowEngine["Flow engine<br/>flow.yaml graph and state machine; CEL guards on the edges<br/>and CEL requires on the gates, at transitions only;<br/>standalone CEL checked at load, rule lists from the rules bundle,<br/>all evaluated with cel-expr-python (ADR-0020);<br/>decision records, VOID cascade, policy<br/>Phase 2"]:::planned
    guide["Guide service<br/>flow/guides per stage and role: Phase 2<br/>flow.guide tool: Phase 3"]:::planned
    middleware["Middleware chain<br/>validation, policy, audit, provenance, cache, telemetry<br/>open: no phase in Steps"]:::open
    providerHost["Provider host<br/>lifecycle, timeouts, cancel, artifact checks<br/>open: no phase in Steps; Phase 4 builds the runtime it speaks to"]:::open

    subgraph record["Record service: benchhand_core.record"]
      store["store: read_record, load_record, read_document,<br/>save_document, save_decision, save_record<br/>typed YAML, CSV and decision documents"]:::impl
      validate["validate(root)<br/>rules: bom, interfaces, assembly, drawing, decisions, verification"]:::impl
      migrate["migrate: migrate(root, apply, resume), undo(backup), RULES"]:::impl
      evidence["evidence: read_built_version, assess, acceptance_digest"]:::impl
      versions["versions: snapshot, seal, verify<br/>Phase 2"]:::planned
      release["release packaging: hw/releases/REV<br/>Phase 4"]:::planned
      recordOps["typed record ops: record.add_requirement, add_part, add_evidence and more<br/>record.* tools Phase 3"]:::planned
    end

    subgraph jobs["Job service: benchhand_core.jobs"]
      jobService["JobService: start, status, list_jobs,<br/>result, report_progress, cancel, reap"]:::impl
      supervisor["supervisor.py and SupervisedProcess<br/>own session, anchored process group"]:::impl
      runStore["RecordStore<br/>run records under .benchhand/runs/"]:::impl
    end

    domain["fits, bom, motion: Phase 4 tools<br/>recheck, work: open, no phase in Steps"]:::open
  end

  contracts["benchhand-contracts<br/>validate, violations, models"]:::impl
  hwArtifacts["Artifact placement in hw/<br/>open: the host verifies and moves artifacts; no source names the writer"]:::open

  surface -.-> middleware
  middleware -.-> flowEngine
  middleware -.-> providerHost
  surface -.-> guide
  guide -.->|"current stage"| flowEngine
  flowEngine -.->|"writes flow.stage and hw/decisions/"| store
  recordOps -.-> store
  validate -->|"reads the record"| store
  store -->|"checks every document against its contract"| contracts
  migrate -->|"validates a migrated copy"| validate
  evidence -->|"read_document: the built version's snapshot documents<br/>the caller supplies the current record"| store
  versions -.-|"open: how versions and evidence connect"| evidence
  release -.->|"acceptance digest against the freeze"| evidence
  providerHost -.->|"$/progress to report_progress"| jobService
  providerHost -.-|"open: where accepted artifacts land in hw/"| hwArtifacts
  providerHost -.->|"validates every message"| contracts
  jobService --> supervisor
  jobService --> runStore
  jobService -->|"builds JobHandle from a JobRecord"| contracts
  runStore -->|"JobRecord; validates JobId"| contracts

  style core fill:#fafafa,stroke:#9e9e9e,color:#1b1b1b
  style record fill:#f5f5f5,stroke:#9e9e9e,color:#1b1b1b
  style jobs fill:#f5f5f5,stroke:#9e9e9e,color:#1b1b1b

  classDef impl fill:#e8f5e9,stroke:#2e7d32,stroke-width:2px,color:#1b1b1b
  classDef review fill:#fff3e0,stroke:#e65100,stroke-width:2px,stroke-dasharray:6 4,color:#1b1b1b
  classDef planned fill:#ffffff,stroke:#616161,stroke-width:1px,stroke-dasharray:6 4,color:#1b1b1b
  classDef open fill:#ffebee,stroke:#c62828,stroke-width:2px,stroke-dasharray:2 3,color:#1b1b1b
  classDef ext fill:#eceff1,stroke:#37474f,stroke-width:1px,color:#1b1b1b
  classDef person fill:#e3f2fd,stroke:#1565c0,stroke-width:2px,color:#1b1b1b
```

## Contracts and codegen

```mermaid
flowchart LR
  tsp["contracts/*.tsp<br/>TypeSpec, the only source of shapes<br/>record: 18 documents and 2 libraries; jobs, provider protocol and manifest, common finding"]:::impl
  missing["Result envelope and flow contracts<br/>listed for Phase 1, not on main; Phase 2 uses them"]:::planned
  later["MCP tool inputs and outputs, benchhand.toml, rule lists,<br/>CEL profile manifest and rules bundle,<br/>preview-host HTTP API, App postMessage<br/>with their users, Phases 2 to 5"]:::planned
  bundle["tsp compile --warn-as-error<br/>one JSON Schema bundle, unpublished"]:::impl
  normalise["tools/gen contracts_gen normalise<br/>one published schema per contract"]:::impl
  published["Published JSON Schema 2020-12<br/>benchhand_contracts/schemas"]:::impl
  pydantic["pydantic v2 models<br/>datamodel-code-generator"]:::impl
  validator["Runtime validator<br/>benchhand_contracts.validate"]:::impl
  tsTypes["ui/shared/contracts<br/>json-schema-to-typescript types, Ajv standalone validators"]:::impl
  fixtures["Conformance fixtures<br/>benchhand_contracts/examples"]:::impl
  docs["Reference pages<br/>docs/contract/generated"]:::impl
  toolSchemas["MCP tool schemas<br/>Phase 3"]:::planned
  celTypes["CEL FileDescriptorSet, profile manifest and env YAML<br/>per structural rule scope<br/>Phase 2"]:::planned
  celcheck["tools/celcheck: pinned cel-go tool<br/>compiles flow/*.celpolicy into the rules bundle in CI: Phase 2<br/>benchhand-celcheck wheel for rules compile: Phase 3"]:::planned
  openapi["OpenAPI 3.2, hey-api TypeScript and Zod<br/>open: arrive with the first HTTP or Zod consumer"]:::open
  ci["just contracts-check<br/>format, metaschema and lint, drift, breaking change"]:::impl

  tsp --> bundle --> normalise --> published
  missing -.-> tsp
  later -.-> tsp
  published --> pydantic
  published --> validator
  published --> tsTypes
  published --> fixtures
  published --> docs
  published -.-> toolSchemas
  published -.-> celTypes
  celTypes -.->|"builds its environment from the manifest"| celcheck
  published -.-> openapi
  ci --> tsp
  ci --> published

  classDef impl fill:#e8f5e9,stroke:#2e7d32,stroke-width:2px,color:#1b1b1b
  classDef review fill:#fff3e0,stroke:#e65100,stroke-width:2px,stroke-dasharray:6 4,color:#1b1b1b
  classDef planned fill:#ffffff,stroke:#616161,stroke-width:1px,stroke-dasharray:6 4,color:#1b1b1b
  classDef open fill:#ffebee,stroke:#c62828,stroke-width:2px,stroke-dasharray:2 3,color:#1b1b1b
  classDef ext fill:#eceff1,stroke:#37474f,stroke-width:1px,color:#1b1b1b
  classDef person fill:#e3f2fd,stroke:#1565c0,stroke-width:2px,color:#1b1b1b
```

## Legend

- Styles as in the [legend](README.md#legend). Solid arrows exist on `main`, and dashed arrows are planned.
- **Open: no phase in Steps.** The plan names the middleware chain, the provider host, `viewer-ocp`, `policy-default`, and the `recheck` and `work` modules, but no phase of its Steps delivers them. The plan's [Open questions](../design-plan.md#open-questions) don't list them.
- **Open: OpenAPI and Zod.** ADR-0017 adds them with the first HTTP or Zod consumer, which no phase names yet.
- **Open: the integration points.** Plan section 5 puts CEL on transitions only: guards on the edges, `requires` on the gates. No source says a guard runs on every tool call. The provider host verifies artifacts and moves them into `hw/`, but no source routes them through the typed record store, which reads and writes YAML, CSV and decision documents only. No source names a call between record versions and the evidence service.
- The record counts come from the generated [domain model](../contract/generated/domain-model/README.md): the documents (blue) and the libraries (amber) of its overview.
- The `benchhand` CLI node is solid because the CLI exists; on `main` it has `version` and `record migrate`. The provider and SDK packages exist on `main` as empty stubs, so their nodes stay dashed until Phase 4.

## Sources

- `docs/design-plan.md`:
  - [Decisions](../design-plan.md#decisions), D1 (CLI), D4 (runner), D6 (providers), D10 (transport), D13 (provider protocol), D17 (contracts).
  - [1. Layered architecture](../design-plan.md#1-layered-architecture): the MCP surface, interaction layer, preview host, the core services and the provider list.
  - [2. Repository and package layout](../design-plan.md#2-repository-and-package-layout-temporary-repo-benchhandbenchhand-next): the packages, `ui/` and `providers/`.
  - [3. Transport: stdio vs localhost HTTP (D10)](../design-plan.md#3-transport-stdio-vs-localhost-http-d10): the lifecycle of each transport, and the preview host as a separate loopback listener.
  - [5. Flow engine and rules (D14)](../design-plan.md#5-flow-engine-and-rules-d14): the edges with CEL guards and the gates with CEL `requires`; the interpreter writes `flow.stage` and `hw/decisions/`; the CEL pipeline, with the generated profile, the cel-go tool and the rules bundle.
  - [6. Provider protocol (D13)](../design-plan.md#6-provider-protocol-d13): the hook families.
  - [6a. Contracts: generated and enforced (D17)](../design-plan.md#6a-contracts-generated-and-enforced-d17): the contract list, the generated outputs and runtime validation.
  - [7. CLI (D1)](../design-plan.md#7-cli-d1), [11. Adaptive interaction layer (D8)](../design-plan.md#11-adaptive-interaction-layer-d8) and [12. Build API (D7)](../design-plan.md#12-build-api-d7): typed record ops.
  - [Behavioural reference map](../design-plan.md#behavioural-reference-map-from-benchhandbenchhand-into-benchhandbenchhand-next): `benchhand-core/{fits,bom,recheck,motion,work}`.
  - [Steps (phased)](../design-plan.md#steps-phased): the phase of every node.
- `docs/adr/`: [0001](../adr/0001-mcp-only-interface.md), [0004](../adr/0004-server-is-runner.md), [0006](../adr/0006-providers-everywhere.md), [0010](../adr/0010-stdio-transport.md), [0011](../adr/0011-guidance-from-server.md), [0013](../adr/0013-provider-protocol.md), [0014](../adr/0014-flow-rules-cel.md), [0017](../adr/0017-contracts.md) ("Decision": TypeSpec source, the generator table, OpenAPI with the first consumer) and [0018](../adr/0018-baseline-and-no-forms.md) (no form elicitation) and [0020](../adr/0020-cel-rule-pipeline.md) (the CEL rule pipeline). Each under its "Decision" heading.
- `docs/contract/provider-protocol.md`: [1. Transport](../contract/provider-protocol.md#1-transport), [4. Hooks](../contract/provider-protocol.md#4-hooks), [5. Notifications from the provider](../contract/provider-protocol.md#5-notifications-from-the-provider) and [6. Artifacts and paths](../contract/provider-protocol.md#6-artifacts-and-paths).
- `docs/contract/versioning.md`: [Generated outputs](../contract/versioning.md#generated-outputs) and [Drift check](../contract/versioning.md#drift-check).
- `docs/phases/phase-0-1.md`: [What was built](../phases/phase-0-1.md#what-was-built) and [Not built, which the plan puts in Phase 1](../phases/phase-0-1.md#not-built-which-the-plan-puts-in-phase-1).
- Code on `main`: `packages/benchhand-core/src/benchhand_core/record/` (`store.py`, `validate.py`, `rules/`, `migrate/`, `evidence/`; `evidence/reader.py` reads snapshot documents with `read_document`), `packages/benchhand-core/src/benchhand_core/jobs/` (`service.py` `handle_of`, `supervisor.py`, `process.py`, `store.py` `RecordStore`), `packages/benchhand/src/benchhand/cli.py`, `contracts/`, `tools/gen/contracts_gen/`, `ui/shared/contracts/`.
- `docs/contract/record-migration.md`: [Dry run and apply](../contract/record-migration.md#dry-run-and-apply).
