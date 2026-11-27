---
title: What providers are
description: The provider interface that kernels, FreeCAD, solvers, renderers, checks and storage plug into.
sidebar:
  order: 1
---

The [provider protocol](/reference/contracts/provider-protocol/) is the contract between benchhand and a provider.

## The provider kinds

Every integration in benchhand sits behind a provider: the CAD kernels, FreeCAD, the solvers, the renderer and viewers, the process checks, artifact storage and policy.
A provider can be swapped or added without a change to benchhand itself.

| Kind | Hooks | What it does |
|---|---|---|
| `kernel` | `build`, `export`, `inspect` | Runs `model.py` part scripts to STEP, exports other formats, and queries geometry. |
| `cad-app` | `drawing`, `assembly`, `fem` | Runs FreeCAD jobs: TechDraw drawings, assembly solves and FEM preparation. |
| `solver` | `solve` | Solves an analysis case, such as a CalculiX static FEA. |
| `collision` | `check`, `sweep` | Checks interference and clearance, and runs motion sweeps. |
| `renderer` | `render`, `snapshot` | Makes renders and quick snapshots. |
| `viewer` | `show`, `compare`, `capture` | Shows geometry interactively, and captures views. |
| `process-check` | `check` | Checks a part and its route against a manufacturing process. |
| `store` | `put`, `get`, `list` | Stores artifacts. |
| `policy` | `evaluate` | Adds policy rules. |

A provider can also declare subcommands of the `benchhand` CLI, which run as `benchhand <provider> <command>`.

The kernel, process-check and policy kinds come with full documentation and a conformance kit.
The other kinds are documented as experimental.

## How a provider runs

Each provider is a separate program.
The server starts it as a subprocess, in its own environment, and speaks JSON-RPC 2.0 to it over the provider's standard input and output, with the `Content-Length` framing of the Language Server Protocol.
Because each provider has its own process, CadQuery and build123d, which need different versions of OpenCASCADE, never share one.

A provider ships a manifest, `benchhand-provider.toml`, which declares:

- its name, version and the protocol versions it speaks;
- its kinds and hooks;
- its environment: a uv environment built from its Python version and pinned dependencies, FreeCAD's own Python, or the system;
- what it needs from outside: FreeCAD, Chromium or the network;
- whether it stays resident for the session;
- any CLI subcommands.

`benchhand doctor` reads every manifest without starting a provider.
The server builds each uv environment from its manifest, and providers with the same dependency set share one environment.

When the server starts a provider, the two negotiate a protocol version, the hooks the provider implements and the features each side supports.
During a job, the provider sends `$/progress` and `$/log` notifications.
Its results carry files as paths, never as bytes: each artifact has an absolute path, a media type, a role, a size and a SHA-256, and the server checks all of them.

A hook is honest about its coverage.
When it can't assess something, it returns `unknown` with a reason, and a check that no provider covers is UNKNOWN, never a pass.

## What the server does with them

The server is the provider host:

- **It starts providers when they are needed.** A resident provider, such as a renderer that keeps Chromium warm, stays up for the session. Any other provider may run for one job and stop.
- **It owns every timeout.** A hook has a deadline from its manifest, or a default: 300 s for a hook, and 3600 s for a solve, a sweep or a FreeCAD job. On expiry it cancels the request, and kills the provider's process group after a 5 s grace period.
- **It contains crashes.** A provider that crashes fails its requests in flight. A resident provider is restarted once per session; after a second crash it is unavailable, and its hooks report UNKNOWN coverage.
- **It is the only writer of `hw/`.** A provider writes only into the output directory of its request, and the server moves the accepted artifacts into the record.
- **It turns long work into jobs.** A tool whose provider work can run past about 30 s returns a job handle to the agent, which follows it with `jobs.status` and `jobs.result`.

No provider outlives the server.
When the session ends, the server shuts every provider down, and kills any that don't exit, with all their child processes.

Built-in providers ship with benchhand.
Third-party providers are listed in `benchhand.toml`, or are found through Python entry points.
[The built-in providers](/concepts/providers/built-in/) lists the ones that ship.
