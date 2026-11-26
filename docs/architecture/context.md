# System context

The C4 system context of benchhand: who uses it, which agent hosts start it, and which systems and files it works with.
Read it first; [containers.md](containers.md) opens the benchhand box.

```mermaid
flowchart TB
  user["Designer<br/>person: briefs the agent, answers gates in chat, opens preview pages"]:::person

  subgraph hosts["Agent hosts: each starts one benchhand MCP server per session"]
    claudeCode["Claude Code CLI"]:::ext
    claudeDesktop["Claude Desktop<br/>.mcpb bundle, stdio only"]:::ext
    codexCli["Codex CLI"]:::ext
    codexApp["Codex / ChatGPT desktop<br/>open: manual probe run needed"]:::open
    openCode["OpenCode"]:::ext
    kiro["Kiro CLI<br/>open: probe tools never reach the model"]:::open
    pi["Pi"]:::ext
    otherHosts["Other MCP hosts<br/>through the fallbacks, no guarantee"]:::ext
  end

  browser["Web browser"]:::ext
  benchhand["benchhand<br/>MCP server, runner and preview host<br/>core services on main; MCP server Phase 3"]:::planned
  hw[("Project files<br/>hw/ design record, hw/policy.yaml, benchhand.toml")]:::ext

  uv["uv / uvx<br/>fetches, caches and starts benchhand; builds provider environments"]:::ext
  freecad["FreeCAD<br/>supported versions only, host or managed install"]:::ext
  chromium["Chromium, headless"]:::ext
  runtime["Container runtime<br/>Docker, Podman, nerdctl, Colima"]:::ext
  container["benchhand OCI image<br/>benchhand mcp with FreeCAD, both kernels, Chromium and the cache<br/>Phase 7"]:::planned

  pypi["PyPI<br/>benchhand and provider dependencies"]:::ext
  ghcr["GHCR<br/>pinned benchhand image"]:::ext
  freecadDownloads["FreeCAD downloads<br/>URLs and sha256 in freecad-versions.toml"]:::ext

  user -->|"chat"| hosts
  user -.->|"opens loopback preview URLs from tool results, Phase 5"| browser
  hosts -->|"MCP config runs uvx benchhand@ver mcp"| uv
  uv -->|"fetches the package on first start"| pypi
  uv -.->|"starts"| benchhand
  hosts -.->|"MCP over stdio by default, or loopback HTTP with --http"| benchhand
  browser -.->|"loopback HTTP, Host-header check, path token"| benchhand
  benchhand -->|"reads and writes; the host is the only writer of hw/"| hw
  hosts -.->|"agent may edit hw/ directly; validate reports it"| hw
  benchhand -.->|"freecadcmd jobs through the freecad provider, Phase 4"| freecad
  benchhand -.->|"managed download with consent, sha256 checked"| freecadDownloads
  benchhand -.->|"renders through render-chromium, Phase 4"| chromium
  benchhand -.->|"mcp --container launcher: run -i, forwards stdio, supervises; open: phase"| runtime
  runtime -.->|"pulls the pinned image"| ghcr
  runtime -.->|"runs; project mounted at the same path"| container

  style hosts fill:#fafafa,stroke:#9e9e9e,color:#1b1b1b

  classDef impl fill:#e8f5e9,stroke:#2e7d32,stroke-width:2px,color:#1b1b1b
  classDef review fill:#fff3e0,stroke:#e65100,stroke-width:2px,stroke-dasharray:6 4,color:#1b1b1b
  classDef planned fill:#ffffff,stroke:#616161,stroke-width:1px,stroke-dasharray:6 4,color:#1b1b1b
  classDef open fill:#ffebee,stroke:#c62828,stroke-width:2px,stroke-dasharray:2 3,color:#1b1b1b
  classDef ext fill:#eceff1,stroke:#37474f,stroke-width:1px,color:#1b1b1b
  classDef person fill:#e3f2fd,stroke:#1565c0,stroke-width:2px,color:#1b1b1b
```

## Legend

- Styles as in the [legend](README.md#legend). Solid arrows exist on `main`, and dashed arrows are planned.
- `benchhand` is dashed because its MCP server, the part every host talks to, arrives in Phase 3. The record and job services inside it are on `main` ([containers.md](containers.md)).
- **Open: Codex / ChatGPT desktop.** The probe hasn't run there. **Open: Kiro CLI.** Kiro connects and lists the tools, but they never reach the model, under the default or a custom agent. Both settle the "?" cells of the [Open questions](../design-plan.md#open-questions).
- **Open: container launcher phase.** Phase 6 delivers `install --container` and Phase 7 the image. No step names the phase of the `mcp --container` launcher itself.
- The arrow from the hosts to `hw/` is not a planned interface. The server doesn't stop direct edits, because gates guide and are no security control; `validate` reports them as findings.

## Sources

- `docs/design-plan.md`:
  - [Decisions](../design-plan.md#decisions), D2 (uvx and the container), D4 (server is the runner), D5 (FreeCAD versions), D9 (hosts tested at release), D10 (transport).
  - [1. Layered architecture](../design-plan.md#1-layered-architecture): the harness list and the transports.
  - [3. Transport: stdio vs localhost HTTP (D10)](../design-plan.md#3-transport-stdio-vs-localhost-http-d10): the preview listener, the Host-header check and the path token; Claude Desktop is stdio only.
  - [5. Flow engine and rules (D14)](../design-plan.md#5-flow-engine-and-rules-d14), "Scope": direct edits to `hw/` aren't stopped, and `validate` reports them.
  - [8. Prerequisites, FreeCAD and the container](../design-plan.md#8-prerequisites-freecad-and-the-container): the FreeCAD lookup and managed install, the container runtimes, the launcher steps, GHCR and the same-path mount.
  - [10. Harness integration and distribution](../design-plan.md#10-harness-integration-and-distribution): the `.mcpb` bundle.
  - [Steps (phased)](../design-plan.md#steps-phased): Phases 3, 4, 5, 6 and 7.
- `docs/adr/`: [0002](../adr/0002-install-uvx-and-container.md) (install and container), [0003](../adr/0003-gates-guide.md) (gates guide), [0004](../adr/0004-server-is-runner.md) (server is the runner), [0005](../adr/0005-freecad-supported-versions.md) (FreeCAD list and download), [0009](../adr/0009-first-class-hosts.md) (hosts), [0010](../adr/0010-stdio-transport.md) (stdio). Each under its "Decision" heading.
- `docs/contract/provider-protocol.md`: [6. Artifacts and paths](../contract/provider-protocol.md#6-artifacts-and-paths): the host is the only writer of `hw/`.
- `docs/client-support.md`: [Client support](../client-support.md#client-support), the Kiro CLI and Codex / ChatGPT desktop rows.
