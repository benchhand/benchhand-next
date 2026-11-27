---
title: Install
description: Run benchhand through uvx, register it with your agent host, and set up FreeCAD or the container.
sidebar:
  order: 1
---

benchhand is an MCP server.
Your agent host starts it from its MCP configuration, so registering benchhand with the host is the whole install.

## Requirements

- [uv](https://docs.astral.sh/uv/), which fetches and runs benchhand.
- An agent host. benchhand is tested and supported on seven: Claude Code CLI, Claude Desktop, Codex CLI, the Codex and ChatGPT desktop app, OpenCode, Kiro CLI and Pi.
  Other MCP hosts work through the fallbacks, without a guarantee ([Agent hosts](/concepts/clients/hosts/)).
- A supported FreeCAD, which benchhand can download for you, or a container runtime if you use the container instead.

## Run benchhand with uvx

Each host's MCP configuration runs one command:

```sh
uvx benchhand@<version> mcp
```

On the first start, uv fetches the package and caches it.
The server answers the host straight away and prepares its provider environments in the background.
The `env.doctor` tool shows the progress to the agent.

The server talks to the host over stdio, so the host owns its lifetime and no authentication is involved.
`benchhand mcp --http` serves MCP on loopback instead, for a shared server or a remote container.
That mode needs a bearer token.

For pinned or offline use, install the package as a uv tool:

```sh
uv tool install benchhand
```

The host's configuration can then run `benchhand mcp`, which starts the same server.

## Register benchhand with your agent host

`benchhand install` writes the registration for one host:

```sh
uvx benchhand@<version> install --harness <host>
```

`--user` registers benchhand for your user, and `--project DIR` for one project.

For each host, the command writes the MCP registration, a short bootstrap skill, the agent profiles and the settings that the host needs:

| Host | MCP registration | Bootstrap skill | Agent profiles | Also |
|---|---|---|---|---|
| Claude Code | the plugin's `.mcp.json`, or the project's `.mcp.json` | plugin skill | plugin agents | also installs from the Claude Code plugin marketplace |
| Claude Desktop | a `.mcpb` bundle that runs `uvx benchhand mcp` | none | none | the bundle asks for the FreeCAD path and whether to use the container |
| Codex CLI and app | the Codex plugin, or `[mcp_servers.benchhand]` in `config.toml` | plugin skill | `.codex/agents/*.toml` | sets the startup and tool timeouts |
| OpenCode | `mcp.servers.benchhand` in `opencode.json` | `.opencode/skills` | `.opencode/agents` | checks the startup timeout |
| Kiro CLI | `mcp.json`, and `mcpServers` in the agent profile | `.kiro/skills` | `.kiro/agents` | none |
| Pi | the benchhand Pi package, or `.pi/mcp.json` | package skill | none | the package's extension adds a gate dialog and opens preview URLs |

The first start can take longer than a host's default startup timeout.
Codex waits 10 s by default, so `install` sets 120 s.
OpenCode waits 30 s, and `install` checks that setting.

Claude Desktop starts servers without a project directory.
The project comes from the bundle's settings, or the agent opens it with the `project.open` tool.

[Agent hosts](/concepts/clients/hosts/) has the notes for each host.

## Set up FreeCAD

benchhand runs FreeCAD for drawings, assemblies and analysis, and accepts only the versions on its supported list.
Each release ships that list in `freecad-versions.toml`, with the platforms, download URLs and SHA-256 of each version.
The first release supports FreeCAD 1.1.4.

```sh
benchhand setup
```

benchhand looks for FreeCAD in:

- the `FREECADCMD` environment variable;
- `PATH`;
- the macOS application bundle;
- an AppImage;
- benchhand's own download directory.

If it finds no supported version, `setup` offers to download one into `~/.local/share/benchhand/freecad/<version>`, and it downloads only after you agree.
`setup --yes` agrees for you.

A FreeCAD that isn't on the list is refused, with a fix that names the supported versions and offers the download.
The `--allow-unsupported` option exists for developing benchhand itself: results from an unsupported FreeCAD are UNKNOWN, never a pass.

## Check the installation

```sh
benchhand doctor
```

`doctor` checks uv, the provider environments, Chromium, the viewer's three.js cache, FreeCAD, the provider manifests, and the MCP registration and startup timeouts of each host you registered.
Each failed check comes with the fix.
`--json` prints the report as JSON, and the agent gets the same report from `env.doctor`.

## Use the container instead

The benchhand image carries FreeCAD, both modelling kernels (CadQuery and build123d) and Chromium, so nothing else needs installing on your machine.
Register it with:

```sh
uvx benchhand@<version> install --harness <host> --container
```

The host still starts an ordinary command, `uvx benchhand@<version> mcp --container`.
That launcher:

- finds the project from the working directory, the host's MCP roots or `--project`;
- pulls the image for this benchhand version if it's missing;
- mounts the project at the same path inside the container, so every path in a result is a real path on your machine;
- forwards stdio, and removes the container when the session ends, however it ends.

The launcher takes the first container runtime it finds in:

1. the `--runtime` option;
2. the `BENCHHAND_CONTAINER_RUNTIME` environment variable;
3. `[container] runtime` in `benchhand.toml`;
4. `podman`, `docker` or `nerdctl` on `PATH`.

Docker Desktop, Docker Engine, Colima, OrbStack, Rancher Desktop, Podman and containerd all work.
A custom command names the profile it behaves like:

```toml
[container]
runtime = "colima nerdctl --"
profile = "nerdctl"
```

If the launcher can't reach the runtime, it serves only `env.doctor`, which tells the agent the fix, so the host doesn't just report a failed server.
On macOS the runtime's VM has to be running, and the fix names `colima start` or `podman machine start`.
`benchhand doctor` reports the runtime it picked and why.
It also checks that the image matches this benchhand version and that the project can be written through the mount.
`benchhand doctor --clean` removes containers left behind by a launcher that was killed.

Next: [A first project](/getting-started/first-project/).
