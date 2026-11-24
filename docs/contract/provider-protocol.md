# benchhand provider protocol v1

Status: contract for benchhand 1.0. Decisions: [ADR-0013](../adr/0013-provider-protocol.md), [ADR-0017](../adr/0017-contracts.md). Schema: [`contracts/provider/protocol.schema.json`](../../contracts/provider/protocol.schema.json). The schema is the source of truth for every message shape. The rules below cover what a schema can't express: ordering, timing and process handling.

This protocol is modelled on the slopvac 3.0 plugin protocol (`slopvac/docs/contract/plugin-protocol.md`). Where this document doesn't say otherwise, slopvac's framing rules apply. It adds progress and artifact messages for long CAD jobs and resident providers, and it drops slopvac's trust step, because benchhand isn't a security boundary ([ADR-0003](../adr/0003-gates-guide.md)).

"Must" binds the party named in the sentence. The **host** is the benchhand MCP server process, and the **provider** is the subprocess.

## 1. Transport

A provider is a separate program. The host starts it as a subprocess and speaks JSON-RPC 2.0 to it over the provider's stdin and stdout.

- **Framing.** As in the Language Server Protocol, each message is `Content-Length: <n>\r\n\r\n<body>`. The body is one JSON object in UTF-8 without a BOM.
  - `Content-Length` is required and must not be repeated. A reader ignores every other header.
  - A header line has at most 1024 bytes, and a header block at most 8 lines.
  - A top-level array (a JSON-RPC batch) is invalid.
- **Standard output** carries frames and nothing else. Any other byte there is a framing error, which is fatal: the host kills the provider and fails its pending requests with `provider-protocol-violation`.
- **Standard error** is a human log. The host reads it continuously, keeps the last 64 KiB, and shows the last 4 KiB when the provider fails. Structured logs go through `$/log` (section 5); the host treats stderr as opaque text.

| Limit | Default | Rule |
|---|---|---|
| `maxMessageBytes` | 16 MiB | The host proposes it in `initialize`. The provider may lower it but not raise it. The lower value binds both directions. Before `initialize` completes, 1 MiB applies. |
| JSON nesting depth | 64 | Deeper values are a framing error. |
| Duplicate object keys | none | A framing error. |
| Integers | ±(2^53−1) | Values outside this range are invalid. |

Geometry, images, STEP files and meshes travel as files, and messages carry their paths (section 6). The `maxMessageBytes` check rejects a message that inlines them.

## 2. Lifecycle

```text
host                                   provider
 |-- spawn ------------------------------->|
 |-- initialize (request) ---------------->|
 |<-- initialize (result) -----------------|
 |-- initialized (notification) ---------->|
 |-- hook requests  <-->  responses ------>|
 |<-- $/progress, $/log (notifications) ---|
 |-- shutdown (request) ------------------>|
 |<-- shutdown (null) ---------------------|
 |-- exit (notification) ----------------->|
```

1. **Spawn.** The host reads the provider manifest (section 7), resolves the provider's environment, and starts the provider in a new process group with an allowlisted environment. The working directory is the project root.
2. **Initialize.** The first message must be `initialize`. Any other request gets `not-initialized`. The reply fixes the protocol version, the hooks, the features and the limits (section 3).
3. **Initialized.** The host then sends the `initialized` notification. The provider must not send notifications before receiving it.
4. **Work.** The host sends hook requests. The provider answers them and may send `$/progress` and `$/log` notifications about requests in flight.
5. **Shutdown.** The host sends `shutdown`. The provider finishes or abandons its work and answers `null`. The host then sends `exit`, and the provider exits with status 0.
6. **End of input.** A provider whose stdin closes behaves as if it got `exit`, and exits at once.
7. **Kill.** If the provider hasn't exited 2 s after `exit`, the host kills its whole process group, so the provider's children (FreeCAD, Chromium, solvers) die too.

**Residency.** A provider declared `resident = true` (section 7) stays up for the host's whole session, for example a viewer or renderer that keeps a warm Chromium or loaded OCP modules. Any other provider may be started for one job and shut down afterwards. No provider ever outlives the host: the host runs shutdown on a clean exit, and its signal handler kills every provider process group.

A provider that crashes fails its pending requests with `provider-exited`. The host may restart a resident provider once per session; a second crash marks it unavailable, and its hooks then report UNKNOWN coverage.

## 3. Capability negotiation

- **Versions.** `InitializeParams` carries `protocolVersion` (the highest version the host speaks) and `minProtocolVersion` (the lowest). The provider replies with the highest version in both ranges, or with `protocol-version-unsupported` and its own range. A version is a major version. Changes within a major version are additive.
- **Hooks.** The host lists the hook kinds it can call. The provider replies with each hook it implements, as `{kind, id}`. The host calls only hooks that were declared, and qualifies them in diagnostics as `<provider>:<kind>/<id>`.
- **Features.** The host lists the features it offers. The provider splits the features it wants into `required` and `optional`. A missing required feature stops the load with `required-feature-missing`. A missing optional feature is skipped silently. Names starting with `x-` are private.

  | Feature | Meaning |
  |---|---|
  | `progress` | The host accepts `$/progress` notifications. |
  | `artifacts` | Results may carry `artifacts` (section 6). |
  | `project-root` | `initialize` carries `projectRoot`. |
  | `cancel` | The host sends `$/cancelRequest`. |
- **Manifest agreement.** The `initialize` reply must agree with the manifest: the same kinds, no hooks the manifest doesn't list, and the same external needs. A mismatch is `provider-declaration-mismatch`, and the provider isn't used.

## 4. Hooks

Each hook is one request method named `<kind>/<hook>`. Its params and result are defined in the schema under `$defs`, as `<Kind><Hook>Params` and `<Kind><Hook>Result`.

| Kind | Methods | Purpose |
|---|---|---|
| `kernel` | `kernel/build`, `kernel/export`, `kernel/inspect` | Run `model.py` part scripts to STEP, export formats, query geometry. |
| `cad-app` | `cad-app/drawing`, `cad-app/assembly`, `cad-app/fem` | Run FreeCAD jobs (TechDraw, assembly solve, FEM preparation). |
| `solver` | `solver/solve` | Solve an analysis case, for example CalculiX static FEA. |
| `collision` | `collision/check`, `collision/sweep` | Interference, clearance and motion sweeps. |
| `renderer` | `renderer/render`, `renderer/snapshot` | PBR renders and quick snapshots. |
| `viewer` | `viewer/show`, `viewer/compare`, `viewer/capture` | Interactive viewing and captures. |
| `process-check` | `process-check/check` | Manufacturing-process checks for a part and route. |
| `store` | `store/put`, `store/get`, `store/list` | Artifact storage. |
| `policy` | `policy/evaluate` | Extra policy rules ([ADR-0014](../adr/0014-flow-rules-cel.md)). |
| `cli` | `cli/run` | A provider-declared CLI subcommand ([ADR-0001](../adr/0001-mcp-only-interface.md)). |

Rules that apply to every hook:

- **Reproducible.** The same request on the same inputs gives the same result, so the host may cache results by input digest. A result that depends on something the request doesn't carry (time, randomness, the network) must say so in `nondeterministic: true`.
- **Coverage is honest.** A hook that can't assess something returns `status: "unknown"` with a reason. The conformance kit checks that a hook given an input outside its declared coverage returns `unknown`. When no provider implements a needed hook, the host reports UNKNOWN coverage itself.
- **Writes stay in the output directory.** A hook may write files only under the `outDir` the request names. The host owns the design record (`hw/`); it accepts provider files only through `artifacts`.

## 5. Notifications from the provider

| Method | Params | Rule |
|---|---|---|
| `$/progress` | `{id, fraction?, message?, stage?}` | About request `id`, which must be in flight. `fraction` is 0..1 and must not decrease. The host forwards it as MCP progress, as task status, or as job-handle status. It doesn't extend any deadline. |
| `$/log` | `{level, message, data?}` | Levels are `debug`, `info`, `warning` and `error`. The host writes them to its log, and never to the MCP stream unless the client asked for logging. |

Any other notification method from the provider is dropped and logged once. In v1 only the host sends requests; the host answers a request from the provider with `invalid-request`.

## 6. Artifacts and paths

- Paths in requests are absolute. `projectRoot` and `outDir` are absolute directories.
- A result that produces files lists them in `artifacts`, each with an absolute `path` under `outDir`, a `mediaType`, a `role` (for example `step`, `glb`, `png` or `report`), `bytes` and `sha256`. The host verifies that each path exists under `outDir` and that the size and digest match. A mismatch is `provider-output-invalid`.
- The host moves accepted artifacts into the record, and is the only writer of `hw/`.

## 7. Provider manifest

Each provider ships a `benchhand-provider.toml`, validated against `contracts/provider/manifest.schema.json`. The host reads the manifest before spawning anything, and `benchhand doctor` checks it without starting the provider.

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

[[cli]]                           # optional: mounted as `benchhand kernel-build123d <name>`
name = "probe"
summary = "Check the build123d environment."
```

- `environment.kind = "uv"`: the host builds a uv environment from `requires-python` and `dependencies`, keyed by the resolved dependency set, so identical sets share one environment.
- `environment.kind = "freecad"`: the provider runs under FreeCAD's own Python (`freecadcmd`) from a supported version ([ADR-0005](../adr/0005-freecad-supported-versions.md)).
- The host starts each provider as its own process, so CadQuery (OCP 7.9) and build123d (OCP 8.0) run in separate interpreters.

## 8. Requests in flight, cancellation and timeouts

- **Ids.** Request ids are integers counting up from 1, never reused on a connection. A response to an unknown id is ignored and logged.
- **Concurrency.** The provider states `maxInFlight` in its reply. The host keeps at most that many requests pending, capped at 16.
- **Cancellation.** The host sends `$/cancelRequest {id}`. The provider should stop and answer, with the result or with `request-cancelled`. Cancellation is advisory: if there is no answer within the 5 s grace period, the host kills the process group.
- **Timeouts.** The host owns every timeout. A hook's deadline comes from its manifest `timeouts` table, or else from the defaults below. Per-project overrides go in `benchhand.toml`.

| Timer | Default | On expiry |
|---|---|---|
| `initialize` reply | 60 s | The provider is killed and reported as `provider-timeout`. First imports of OCP or FreeCAD are slow. |
| Hook request | 300 s | `$/cancelRequest`, then the cancel grace period. |
| `solver/solve`, `collision/sweep`, `cad-app/*` | 3600 s | The same. |
| Cancel grace | 5 s | The process group is killed. |
| `shutdown` reply | 5 s | `exit` is sent, then the kill rule applies. |
| Exit after `exit` | 2 s | The process group is killed. |

MCP-level deadlines are separate. A tool whose provider work can run past about 50 s returns a job handle or a task to the client (plan section 11), while the provider request keeps running under these timers.

## 9. Compatibility

- Each side ignores unknown fields it receives and never sends fields that aren't in the negotiated version's schema. The runtime validators enforce this in both directions ([ADR-0017](../adr/0017-contracts.md)).
- A new hook, feature, optional field or error code is a minor change. Removing or retyping anything needs a new major protocol version.

## 10. Error codes

Errors use the JSON-RPC error object. `data.code` holds the stable kebab-case name, and the schema requires it.

| Code | `data.code` | Meaning |
|---|---|---|
| -32700 | `parse-error` | The body isn't valid JSON. |
| -32600 | `invalid-request` | Not a valid message, a batch array, or the provider is shut down. |
| -32601 | `method-not-found` | Unknown method, or a hook the provider didn't declare. |
| -32602 | `invalid-params` | The params don't match the schema. |
| -32603 | `internal-error` | The provider failed. |
| -32001 | `protocol-version-unsupported` | No common version. `data.supported` holds the provider's range. |
| -32002 | `required-feature-missing` | The host lacks a feature the provider requires. |
| -32003 | `not-initialized` | A request arrived before `initialize` finished. |
| -32004 | `message-too-large` | A message exceeds `maxMessageBytes`. |
| -32005 | `request-cancelled` | The provider stopped after a cancel. |
| -32006 | `input-unsupported` | The provider can't process this input, for example an unsupported process or format. The host records UNKNOWN coverage. |
| -32007 | `external-missing` | A declared external need is unavailable, for example FreeCAD isn't installed or isn't a supported version. `data.fix` says what to do. |

The host also raises these codes in its own diagnostics. No message carries them: `provider-timeout`, `provider-exited`, `provider-protocol-violation`, `provider-output-invalid`, `provider-spawn-failed`, `provider-declaration-mismatch` and `provider-environment-failed`.

## 11. Conformance

`benchhand-provider` ships a conformance kit with two halves.

- **Host half:** a fake provider that sends each malformed frame (missing or duplicate `Content-Length`, oversized body, deep nesting, duplicate keys, stray stdout bytes). It also hangs on `initialize`, hangs on a hook, ignores a cancel, exits mid-request, and sends progress for an unknown id. The host must react as sections 1, 2 and 8 say.
- **Provider half:** a fake host that runs the lifecycle against a real provider. It sends requests before `initialize`, unknown methods, invalid params, a version range with no overlap, and a cancel. It checks every reply against the schema and the manifest.

The kit's valid and invalid example messages are generated from the `examples` in the schema, so the contract and the tests can't drift apart.
