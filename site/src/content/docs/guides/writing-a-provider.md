---
title: Writing a provider
description: Build a provider with the runtime and prove it with the conformance kit.
sidebar:
  order: 5
---

A provider is a separate program that benchhand starts and speaks JSON-RPC 2.0 to, over the provider's standard input and output.
It can be written in any language.
The [provider protocol](/reference/contracts/provider-protocol/) is the contract, and its schema defines every message.
[What providers are](/concepts/providers/overview/) explains how benchhand runs one.

## The runtime

`benchhand-provider` is the Python runtime for providers.
It speaks the protocol for you: the framing, the lifecycle, progress notifications and artifacts.
List it in your manifest's dependencies.
Its API is in the [Python API reference](/reference/python-api/benchhand-provider/).

A provider in another language implements the rules below itself.

## The manifest

Each provider ships a `benchhand-provider.toml`, checked against the [manifest contract](/reference/contracts/provider/manifest/).
benchhand reads it before it starts anything:

```toml
name = "kernel-build123d"
version = "1.0.0"
protocol = { min = 1, max = 1 }
kinds = ["kernel"]
hooks = [{ kind = "kernel", id = "build" }, { kind = "kernel", id = "export" }, { kind = "kernel", id = "inspect" }]
resident = false
command = ["python", "-m", "benchhand_kernel_build123d"]

[environment]
kind = "uv"                       # "uv" | "freecad" | "system"
requires-python = ">=3.12,<3.13"
dependencies = ["build123d==0.13.0", "cadquery-ocp-novtk==8.0.1.1.0", "bd_warehouse==0.4.0", "benchhand-provider"]

[needs]
freecad = false
chromium = false
network = false

[[cli]]
name = "probe"
summary = "Check the build123d environment."
```

- **`name`** is lowercase letters, digits and hyphens, and starts with a letter.
- **`protocol`** is the range of protocol major versions the provider speaks.
- **`kinds` and `hooks`** list what it implements. A hook is `{kind, id}`, and its method is `<kind>/<id>`, such as `kernel/build`.
- **`command`** starts it. benchhand runs it in the provider's environment, with the project root as its working directory.
- **`environment`** is `uv`, with `requires-python` and pinned `dependencies`; `freecad`, to run under the Python of a supported FreeCAD; or `system`.
- **`needs`** declares FreeCAD, Chromium and the network.
- **`resident`**, when true, keeps the provider up for the whole session, with its imports warm.
- **`timeouts`**, optional, gives a hook method its deadline in seconds, such as `timeouts = { "solver/solve" = 3600 }`.
- **`cli`**, optional, declares commands that run as `benchhand <name> <command>`, through the `cli/run` hook.

What the provider says when it starts must match the manifest: the same kinds, no hook the manifest doesn't list, and the same needs.
Otherwise benchhand doesn't use it.

## Start and stop

1. **`initialize`** is the first request. Reply with the highest protocol version in both your range and the host's, or with the error `protocol-version-unsupported` and your range. Declare each hook you implement, split the features you want into `required` and `optional`, and give `maxInFlight`, the number of requests you accept at once.
2. **`initialized`** follows. Send no notification before it.
3. **Hook requests** arrive, and you answer each.
4. **`shutdown`** asks you to finish or abandon your work and answer `null`. Then **`exit`** arrives, and you exit with status 0.

Exit at once when your standard input closes.
If you are still running 2 s after `exit`, benchhand kills your whole process group, your child processes included.

## Write to the right places

- **Standard output carries protocol frames only.** Each is `Content-Length: <n>\r\n\r\n` followed by one JSON object in UTF-8. Any other byte there is fatal: benchhand kills the provider.
- **Standard error is a plain log**, for a person reading it when something fails. Send structured logs as `$/log` notifications, with a level of `debug`, `info`, `warning` or `error`.
- **Files go to the request's output directory**, `outDir`, and nowhere else. benchhand owns the record, `hw/`, and moves your files into it.
- **Large data travels as files.** Geometry, images, STEP files and meshes are files, and messages carry their paths. A message is at most 16 MiB, or less if you lower it in your `initialize` reply.

## Answer a hook

Each hook's params and result are defined in the protocol schema, as `<Kind><Hook>Params` and `<Kind><Hook>Result`.
Every hook keeps these rules:

- **Same inputs, same result.** benchhand may cache a result by the digest of its inputs. If the result depends on something the request doesn't carry, such as the time, randomness or the network, set `nondeterministic: true`.
- **Say when you can't tell.** For something you can't assess, an input outside your declared coverage included, return `status: "unknown"` with a reason. When you can't process the input at all, such as a format you don't read, return the error `input-unsupported`. benchhand records both as UNKNOWN coverage.
- **List every file you write.** Each artifact gives its absolute `path` under `outDir`, its `mediaType`, its `role` (such as `step`, `glb`, `png` or `report`), its size in `bytes` and its `sha256`. benchhand checks each one and refuses a mismatch.
- **Name a missing need.** When FreeCAD or another declared need is missing, return `external-missing` with the fix in `data.fix`.

Every error is a JSON-RPC error object, and its `data.code` holds the stable name.

## Long jobs and cancellation

For a long job, send `$/progress` notifications about the request in flight: `{id, fraction, message, stage}`, where only `id` is required.
`fraction` runs from 0 to 1 and never goes down.
benchhand passes it on to the agent, and it doesn't extend the deadline.

benchhand owns every timeout.
A hook's deadline is its manifest's `timeouts` entry, or the default: 60 s for the `initialize` reply, 300 s for a hook, and 3600 s for `solver/solve`, `collision/sweep` and the `cad-app` hooks.
On expiry benchhand sends `$/cancelRequest {id}`.
Stop and answer within 5 s, with the result or the error `request-cancelled`, or your process group is killed.

## Stay compatible

Ignore fields you don't know, and never send a field that the negotiated protocol version doesn't define.
Within a major version, changes only add things: a new hook, feature, optional field or error code.

## Run the conformance kit

`benchhand-provider` ships a conformance kit.
Its provider half is a fake host that runs the lifecycle against your provider:

- requests before `initialize`;
- unknown methods and invalid params;
- a protocol version range that doesn't overlap yours;
- a cancel;
- an input outside your declared coverage, which must give `unknown`.

It checks every reply against the protocol schema and your manifest.
Its valid and invalid messages come from the examples in the schema, so the kit and the contract agree.
Run it before you publish the provider, then [install it](/guides/installing-providers/) in a project.
