---
title: Troubleshooting
description: Find what went wrong with benchhand doctor, findings and tool results, and fix it.
sidebar:
  order: 6
---

benchhand reports a problem in one of three ways: a failed `doctor` check, a finding, or a tool result that isn't `ok`.
Each names what went wrong and, where it can, the fix.

## Run benchhand doctor

Start with:

```sh
benchhand doctor
```

`doctor` checks:

- uv, and the provider environments;
- Chromium, and the viewer's three.js cache;
- FreeCAD, against the supported versions;
- every provider manifest, without starting the provider;
- the MCP registration of each host you registered, and its startup timeouts.

Each failed check comes with its fix.
`--json` prints the report as JSON, and the agent gets the same report from `env.doctor`.

With the container, `doctor` also reports the container runtime it picked, why, its version, and whether its daemon or virtual machine is running.
It checks that the image matches the pinned version, and that a project file can be written and read through the mount.

## Read a finding

A finding is one problem, in the shape of the [finding contract](/reference/contracts/common/finding/):

- `code`, a stable name such as `record.version_unsupported`;
- `severity`: `error`, `warning` or `info`;
- `path`, the file it is about;
- `message`, what is wrong;
- optionally `pointer`, the place in the file, `action`, the fix, and `subject`, the item it is about.

A malformed record gives a named finding, never a crash.
A `benchhand` command exits 1 when it refuses or fails with findings, and 2 when its arguments are wrong.

## Read a tool result

Every benchhand tool returns a [result envelope](/reference/contracts/envelope/).
Its `status` says how the call went:

| `status` | Meaning | What to do |
|---|---|---|
| `ok` | The call did its work. | Read `verdict` for a check: `pass`, `fail` or `unknown`. |
| `refused` | The call came out of order, such as a transition that skips a gate. | Read `reason`, and follow `next_actions`, which lists what comes first. |
| `pending` | The work runs as a job. | Follow it with `jobs.status` and `jobs.result`. |
| `error` | The tool failed. | Read its `findings`. |

`next_actions` lists the calls that make sense next, and marks the ones that wait for you with `needs_user`.
When the agent is unsure where it is, `flow.guide` gives the stage, the open gates and the next action.

A verdict of `unknown` means that no provider or hook covers the check, or a rule failed while it ran.
A gate that needs the check to pass stays closed.
[Evidence](/concepts/record/evidence/) explains how `unknown`, `not_assessed` and stale results count.

## Common problems

| Problem | Cause | Fix |
|---|---|---|
| The host reports that the server failed to start, or timed out. | The host's startup timeout is shorter than the server's first start. Codex waits 10 s by default. | Register the host again with `benchhand install --harness <host>`, which sets 120 s for Codex, and run `doctor` to check OpenCode's 30 s timeout. |
| The only tool the server offers is `env.doctor`. | The container launcher couldn't reach the container runtime. | Call `env.doctor` for the fix. On macOS, start Docker Desktop, Colima (`colima start`), OrbStack, Rancher Desktop or podman machine (`podman machine start`). |
| Containers are left running after the host was killed. | The launcher was killed before it could stop its container. | The next start removes them, or run `benchhand doctor --clean`. |
| FreeCAD is refused. | Its version isn't on the supported list. | The finding names the supported versions. Run `benchhand setup` to download one. |
| The record is refused with `record.version_unsupported`. | It is a prototype record, or has no `record_version`. | [Migrate it](/guides/migration/). |
| The flow doesn't load, and names `benchhand rules compile`. | A rule list changed, or a benchhand upgrade changed its scope, so its compiled entry is stale or missing. | Run `benchhand rules compile --project .` ([Writing CEL rules](/guides/writing-cel-rules/#when-a-list-fails-to-load)). |
| A gate stays open after you answered. | An empty or declined answer is no answer. | Approve explicitly, or name the change you want. |
| Claude Desktop doesn't find the project. | Claude Desktop starts servers without a project directory. | Set the project in the bundle's settings, or have the agent call `project.open`. |
| Validation reports a file under `hw/` you edited by hand. | benchhand doesn't stop direct edits, and reports what they break. | Fix the file as the finding says, or let the agent change it through its `record.*` tools. |

## Provider errors

When a provider fails, benchhand shows the last 4 KiB of its standard error.
It keeps the last 64 KiB while the provider runs.

| Code | Meaning | What to do |
|---|---|---|
| `external-missing` | Something the provider needs is missing, such as FreeCAD, or a FreeCAD that isn't a supported version. | Follow the fix the error gives. |
| `input-unsupported` | The provider can't process this input, such as a process or format it doesn't cover. | Nothing breaks: the check is UNKNOWN coverage. Add a provider that covers it. |
| `protocol-version-unsupported` | The provider and benchhand speak no common protocol version. | Install a version of the provider that matches this benchhand. |
| `required-feature-missing` | The provider requires a feature this benchhand doesn't offer. | The same. |
| `provider-declaration-mismatch` | What the provider says at start differs from its manifest. | The provider isn't used. Report it to the provider's author. |
| `provider-environment-failed` | benchhand couldn't build the provider's environment. | Run `benchhand doctor`, which checks the provider environments. |
| `provider-spawn-failed` | benchhand couldn't start the provider. | The same. |
| `provider-timeout` | The provider didn't answer in time. The first start of OpenCASCADE or FreeCAD is slow. | Try again. A project can raise a hook's deadline in `benchhand.toml`. |
| `provider-exited` | The provider crashed with requests in flight. | A resident provider is restarted once. After a second crash it is unavailable for the session, and its checks are UNKNOWN. |
| `provider-protocol-violation` | The provider wrote something other than a protocol message to its standard output. | Report it to the provider's author. |
| `provider-output-invalid` | A file the provider reported is missing, outside its output directory, or doesn't match its size or SHA-256. | The same. |

[Installing other providers](/guides/installing-providers/) explains what a provider's manifest declares.
