# Result envelope

Status: provisional, version `0.1.0`. Phase 2 builds the flow engine's `next_actions`, and Phase 3 builds the MCP tools that return this envelope. Decisions: [ADR-0011](../adr/0011-guidance-from-server.md), [ADR-0017](../adr/0017-contracts.md), [ADR-0018](../adr/0018-baseline-and-no-forms.md). Source: [`contracts/envelope/envelope.tsp`](../../contracts/envelope/envelope.tsp). Reference: [the generated envelope reference](generated/envelope/envelope.md).

Every benchhand MCP tool returns one envelope as its `structuredContent`. Each part of the envelope has a meaning and a status that it belongs to.

## Status and verdict

`status` is the outcome of the call. It doesn't judge the design.

| `status` | Meaning | Also required |
|---|---|---|
| `ok` | The call did the requested work. | nothing |
| `refused` | The call is out of order, for example a transition that skips a gate. The result says why and what comes first. | `reason`, and at least one entry in `next_actions` |
| `pending` | The work runs as a job. | `job`, the job handle from [`jobs/job`](generated/jobs/job.md) |
| `error` | The tool failed. | at least one entry in `findings` |

`verdict` is the outcome of a check: `pass`, `fail`, or `unknown` when no provider or hook covers the check. Only a check-type tool sets it, and only on an `ok` result. A refused, pending or failed call has no verdict. This follows the prototype's `emit.py`, which takes the verdict from the producer's own result.

## The other parts

- `payload` is the tool's own result. Each tool's output schema narrows it.
- `findings` uses the [finding](generated/common/finding.md) shape, which the record service reports too.
- `next_actions` lists the tool calls that make sense next, most useful first. Each entry names the tool and holds the arguments that the server can fill in. The agent supplies the rest. `reason` says why the call helps. `needs_user` is true when the call has to wait for the user, such as recording a human-gate decision.

  Since every result carries `next_actions`, the agent rarely needs `flow.guide` again (plan section 9).
- `artifacts` reuses the provider protocol's `Artifact`:
  - an absolute path
  - a media type and a role
  - the size and the sha256

  The prototype's gate control requires an absolute path for every file a report names.
- `guidance` is text for the agent: what the result means and how to go on.

## Long calls

A call that would run past a host's tool timeout returns `pending` with a job handle, and the agent follows it with `jobs.status` and `jobs.result`. The envelope schema sets no threshold. The design documents give two numbers: plan section 11 says about 50 s, and ADR-0018 says about 30 s. Phase 3 settles the number with the MCP tools.
