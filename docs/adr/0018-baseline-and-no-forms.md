# ADR-0018: Plain tool calls are the baseline; forms are dropped from v1

Status: accepted. Source: the probe results in [client support](../client-support.md), decided in the Inbox thread "benchhand-next build". It narrows [ADR-0008](0008-adaptive-interaction.md).

## Context

The probe measured seven hosts. Only tool calls with text results work in all of them. Everything else is missing or unreliable somewhere:

- **Forms:** Claude Desktop and Pi declare no elicitation, Codex `exec` auto-cancels a form, and OpenCode hangs and then drops the connection.
- **Images:** Codex receives the image but doesn't show it to the model.
- **Progress:** notifications reach the model on no host.
- **Long calls:** Pi times out at 60 s, and Claude Desktop before 75 s.
- **Resources:** Claude Desktop and Pi `-p` don't give them to the agent.
- **Prompts:** they reach the model on no host.
- **MCP Apps:** only Claude Desktop draws a widget.
- **Protocol revisions:** hosts range from 2025-06-18 to 2026-07-28.

## Decision

The baseline is a client that declares nothing beyond tool calls with text results. Every workflow must complete on that baseline. A richer channel is only an enhancement, and only where the host declares it, with the baseline path behind it.

| Need | Baseline (always) | Enhancement, where declared |
|---|---|---|
| Human gate and structured questions | The agent asks in chat and records the reply through a tool (`channel: chat`) | MCP App gate card |
| Image for the agent | A text summary (bounding box, mass, visible parts) and the file path | Image content |
| Preview for the person | A loopback preview URL in the text result | MCP App shell embedding the same page |
| Work over about 30 s | A job handle with `jobs.status` and `jobs.result` | Tasks extension; progress notifications |
| Readable content | A tool that returns it | The same content as a resource |
| Agent guidance | Tool descriptions and the installed skill | none |
| Protocol | 2025-06-18 and later | 2026-07-28 features |

Form elicitation is not used in v1. The chat path is needed anyway, and no host runs forms reliably. A second gate path would double the gate tests. Forms come back only after the probe shows a host that runs them reliably.

## Consequences

- Every tool returns within about 30 s; longer work returns a job handle.
- The golden end-to-end run on the chat-only profile is the release gate. The Apps and tasks profiles test the enhancements.
- The probe keeps its form tool to track host support, but the server has no form code.
