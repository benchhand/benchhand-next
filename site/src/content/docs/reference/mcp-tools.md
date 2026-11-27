---
title: MCP tools
description: The tools, resources, prompts and Apps of the benchhand MCP server, and the result envelope every tool returns.
---

The workflow runs through the benchhand MCP server, and through nothing else.
Your agent host starts it with `benchhand mcp` and talks to it over stdio.

A tool's description says what the tool does and what it needs first.
`flow.guide` says when to use it.
The server's instructions tell the agent to call `flow.guide` before it starts and whenever it is unsure, to follow the guide's next action, and to ask you at gates as instructed.

Each tool's input and output are published [contracts](/reference/contracts/).
The server registers its `inputSchema` and `outputSchema` from them, and validates every input and every result it sends.
A call that breaks a schema gets a typed error with the schema path, never a silent coercion.

To call a tool from the shell, through the same code path as an MCP call, use `benchhand debug call <tool> [json]`.

## The result envelope

Every tool returns one [result envelope](/reference/contracts/envelope/) as its `structuredContent`.
Its `status` is the outcome of the call, not a judgement of the design.

| `status` | Meaning | Also set |
|---|---|---|
| `ok` | The call did the requested work. | nothing |
| `refused` | The call is out of order, for example a transition that skips a gate. | `reason`, and at least one entry in `next_actions` |
| `pending` | The work runs as a job. | `job`, the [job handle](/reference/contracts/jobs/job/) |
| `error` | The tool failed. | at least one entry in `findings` |

A check returns a `verdict` on an `ok` result: `pass`, `fail`, or `unknown` when no provider or hook covers the check.
A refused, pending or failed call has no verdict.

The other parts of the envelope:

- `payload` is the tool's own result, narrowed by the tool's output schema.
- `findings` lists [findings](/reference/contracts/common/finding/).
- `next_actions` lists the calls that make sense next, most useful first.
  Each one names a tool and the arguments the server can fill in, says why the call helps, and sets `needs_user` when the call has to wait for you.
  Because every result carries them, the agent rarely needs to call `flow.guide` again.
- `artifacts` lists the files the call produced, each with its absolute path, media type, role, size and SHA-256.
- `guidance` tells the agent what the result means and how to go on.

The [generated envelope reference](/reference/contracts/envelope/envelope/) lists every field.

## Long calls

Every tool returns within about 30 seconds.
A tool whose work would take longer returns `pending` with a job handle, and the agent follows the job with `jobs.status` and `jobs.result`.
In the tables below, such a tool's result comes back "in the call or as a job".

## Tools

Access is `read` for a tool that changes nothing in the project, and `write` for one that writes `hw/`, `.benchhand/` or the flow state.

### Guidance and gates

| Tool | What it does | Access | Result |
|---|---|---|---|
| `flow.guide(role?, unit?)` | Returns the current stage and its goal, the steps for this stage and role, and the next action. It also lists the tools relevant at this point, with short notes on why and when, and the open gates with what each one needs. | read | in the call |
| `flow.record_decision` | Records your decision at a human gate. The engine writes the [decision record](/reference/contracts/record/decision/) itself. | write | in the call |

The steps that `flow.guide` returns come from the flow's stage guides, `flow/guides/<stage>.md`.
An agent profile, such as the part designer or a reviewer, calls it with its own role and unit.

`flow.record_decision` takes a [gate decision request](/reference/contracts/flow/#gate-decisions):

- `status` is `approved`, or `void` for a change you name at the gate.
- `channel` is `app` when you answered on the gate card, `chat` when you answered in the conversation, or `auto` for a gate whose mode is `auto`.
- Every channel except `auto` names who decided, in `by`, and quotes their words, in `quote`.

An empty or declined answer is no answer, and the gate stays open.

### Project and environment

| Tool | What it does | Access | Result |
|---|---|---|---|
| `project.open` | Opens the project the server works on, for a host that starts the server with no project directory, such as Claude Desktop. | read | in the call |
| `env.doctor` | Returns the `benchhand doctor` report, with a fix for each failed check and the progress of the first-start warm-up. It checks uv, the provider environments, Chromium, the three.js cache, FreeCAD, the provider manifests, each harness's MCP registration and the startup timeouts. | read | in the call |

Without `project.open`, the server takes the project from its working directory, from the MCP roots the client sends, or from `benchhand mcp --project`.

### Record

These tools write the record for the agent, so that nobody edits its YAML by hand.
Each one validates the record before it writes to disk.

| Tool | What it does | Access | Result |
|---|---|---|---|
| `record.add_requirement` | Adds a [requirement](/reference/contracts/record/requirements/). | write | in the call |
| `record.add_interface` | Adds an [interface](/reference/contracts/record/interfaces/). | write | in the call |
| `record.add_part` | Adds a [part](/reference/contracts/record/part/). | write | in the call |
| `record.set_route` | Sets a part's manufacturing route, the operations that make it. | write | in the call |
| `record.add_evidence` | Adds [evidence](/concepts/record/evidence/). | write | in the call |
| `record.add_bom_row` | Adds a [BOM row](/reference/contracts/record/bom-row/). | write | in the call |

### Jobs

| Tool | What it does | Access | Result |
|---|---|---|---|
| `jobs.start` | Starts long work as a job, in its own session and process group. | write | a job handle |
| `jobs.status` | Returns a job's handle, with its status and progress. | read | in the call |
| `jobs.result` | Returns a job's handle, with its result file once the job has succeeded. | read | in the call |

A [job handle](/reference/contracts/jobs/job/) carries the job's `jobId`, `kind`, `status` and `progress`, its log and result paths, and its exit code and error.
Its `status` is `queued`, `running`, `succeeded`, `failed` or `cancelled`.
The job's run record is kept under `.benchhand/runs/`.

### Build and export

The agent writes the geometry in `model.py`.
These tools do the routine work: each takes a version and returns its files as artifacts.

| Tool | What it does | Access | Result |
|---|---|---|---|
| `model.build` | Builds a version from `model.py` in the CadQuery or build123d kernel, and returns STEP AP242, GLB and the build manifest. | write | in the call or as a job |
| `model.export` | Exports a version's parts as STL and 3MF. | write | in the call or as a job |
| `motion.render` | Renders an assembly's motion. | write | in the call or as a job |

### Inspect

These tools inspect a built version.

| Tool | What it does | Access | Result |
|---|---|---|---|
| `model.measure` | Measures the version. | read | in the call or as a job |
| `model.section` | Cuts a section through it. | read | in the call or as a job |
| `model.mass_props` | Returns its mass properties. | read | in the call or as a job |
| `model.interference` | Checks it for interference. | read | in the call or as a job |

### Calculators

| Tool | What it does | Access | Result |
|---|---|---|---|
| `fits.lookup` | Looks up ISO 286 limits of size and the fit class, on the hole basis. | read | in the call |
| `fits.stackup` | Computes a one-dimensional linear tolerance stack-up: worst case, and statistical only where that is justified. | write | in the call |
| `fea.case_from_requirement` | Builds an FEA case from a requirement. | write | in the call |
| `motion.pose` | Poses an assembly at given joint values. | write | in the call or as a job |

### Concept and layout

| Tool | What it does | Access | Result |
|---|---|---|---|
| `concept.add_variant` | Adds a variant to the concept scene. | write | in the call |
| `concept.set_primitive` | Sets a primitive in the concept scene. | write | in the call |
| `concept.snapshot` | Takes a snapshot of the concept scene. | read | in the call |
| `layout.from_concept` | Writes a first layout from the concept. | write | in the call |

The concept tools check the scene after each edit and show it on the concept page.
`layout.from_concept` records each value it infers as a bounded assumption, which you accept or edit at the LAYOUT freeze.
That first layout can't be frozen unchanged.

### Preview and viewer

| Tool | What it does | Access | Result |
|---|---|---|---|
| `preview.part` | Builds a part without making a version, returns snapshots and updates the live viewer. | read | in the call or as a job |
| `preview.assembly` | Builds an assembly without making a version, returns snapshots and updates the live viewer. | read | in the call or as a job |
| `preview.serve(kind, target)` | Hosts the viewer, the concept page, the gallery, the flow view, or a prototype page or rendering the agent made, and returns its URL. | read | in the call |
| `preview.list` | Lists the pages being served. | read | in the call |
| `preview.stop` | Stops serving a page. | read | in the call |
| `viewer.show` | Shows a version in the viewer. | read | in the call |
| `viewer.compare` | Shows two versions side by side with a synced camera. | read | in the call |
| `viewer.capture` | Captures the displayed version into an immutable bundle. | write | in the call |
| `viewer.camera` | Sets the viewer's camera. | read | in the call |

The pages are served on a loopback address, and their URLs come back in the tool results.
[The preview UI](/concepts/clients/preview-ui/) describes each page.

## Resources and prompts

| Resource or prompt | What it holds |
|---|---|
| The record | The project's record. |
| The schemas | The published JSON Schemas of the contracts. |
| The accepted values | The values that the record's fields accept. |
| `guide://stage/<stage>` | The guide for a stage. |
| `/benchhand:stage` | The same stage guide, as a prompt. |
| `sdk://describe` | The signatures of the part SDK that `model.py` imports. |
| `policy.*` | The project's gate modes, from `hw/policy.yaml`. You change them with `benchhand policy set`, which records a decision record for each relaxation. |

The stage guides have one source, published as `flow.guide` results, as resources, as prompts, and as skills over MCP where the host supports them.
Not every host gives resources or prompts to the agent, so the workflow never depends on them.

## Apps

Where the host draws MCP Apps, the server offers three:

- The viewer App, `ui://benchhand/viewer`, is a thin shell around the same preview page that you open in the browser.
- The gate card shows the gate packet, the renders and the flow view, with **Approve** and **Request changes**.
  It records your answer through the channel `app`.
- A form asks the structured questions of the GROUND, INTENT and SPECIFY stages.

On a host without Apps, the agent gives you the preview URL and the gate page's URL in the conversation, asks you there, and records your words through the channel `chat`.
