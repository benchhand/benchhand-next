---
title: Installing other providers
description: Add a provider that doesn't ship with benchhand.
sidebar:
  order: 4
---

Every integration in benchhand is a provider: a kernel, FreeCAD, a solver, a renderer, a process check, storage or policy.
benchhand ships its [built-in providers](/concepts/providers/built-in/), and you can add others beside them.
[What providers are](/concepts/providers/overview/) explains how a provider runs.

## Where providers come from

benchhand finds providers in three places:

- **The package.** The built-in providers ship with benchhand.
- **`benchhand.toml`.** A project lists the other providers it uses in its `benchhand.toml`.
- **Python entry points.** An installed package can register a provider through an entry point.

Each provider ships a manifest, `benchhand-provider.toml`, checked against the [manifest contract](/reference/contracts/provider/manifest/).
The kernel, process-check and policy kinds have full documentation and a conformance kit.
Providers of the other kinds are experimental.

## Read the manifest first

The manifest says what the provider is and what it needs, before anything runs:

```toml
name = "kernel-build123d"
version = "1.0.0"
protocol = { min = 1, max = 1 }
kinds = ["kernel"]
hooks = [{ kind = "kernel", id = "build" }, { kind = "kernel", id = "export" }, { kind = "kernel", id = "inspect" }]
resident = false
command = ["python", "-m", "benchhand_kernel_build123d"]

[environment]
kind = "uv"
requires-python = ">=3.12,<3.13"
dependencies = ["build123d==0.13.0", "cadquery-ocp-novtk==8.0.1.1.0", "bd_warehouse==0.4.0", "benchhand-provider"]

[needs]
freecad = false
chromium = false
network = false
```

Check these entries:

- **`kinds` and `hooks`**: what the provider does. benchhand calls only the hooks the manifest declares.
- **`environment`**: where it runs. With `uv`, benchhand builds a uv environment from `requires-python` and the pinned `dependencies`. With `freecad`, it runs under the Python of a supported FreeCAD. With `system`, it runs as it is.
- **`needs`**: whether it needs FreeCAD, Chromium or the network.
- **`resident`**: whether it stays up for the whole session, such as a renderer that keeps Chromium warm.
- **`timeouts`**: the deadline of each hook, in seconds, where the defaults don't suit.

benchhand runs a provider without a trust step, because its gates guide the design process and aren't a security control.
Install a provider only from a source you trust.

## Install one

Add the provider to the project's `benchhand.toml`, or install the package that registers it.
Then check it:

```sh
benchhand doctor
```

`doctor` reads every provider's manifest without starting the provider, and reports each problem with its fix.
The agent gets the same report from `env.doctor`.

The server builds a provider's environment the first time it needs it.
Providers with the same resolved dependency set share one environment.

When the server starts the provider, the two agree on a protocol version, the hooks and the features.
The provider isn't used when:

- its versions and the server's don't overlap (`protocol-version-unsupported`);
- it requires a feature the server doesn't offer (`required-feature-missing`);
- its answer doesn't match its manifest: other kinds, a hook the manifest doesn't list, or other external needs (`provider-declaration-mismatch`).

A check that needs a hook no provider implements is UNKNOWN, never a pass.

A project can override a hook's deadline in `benchhand.toml`.

## Provider commands

A manifest can declare commands for the `benchhand` CLI:

```toml
[[cli]]
name = "probe"
summary = "Check the build123d environment."
```

Each is mounted as `benchhand <provider> <name>` and runs through the provider, so this one runs as:

```sh
benchhand kernel-build123d probe
```

## When a provider fails

[Troubleshooting](/guides/troubleshooting/#provider-errors) lists the errors a provider can cause, and what to do about each.
