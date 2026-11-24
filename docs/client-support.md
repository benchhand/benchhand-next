# Client support

These are measured results from the dev probe (`tools/probe/`, ADR-0016), one row for each host tested at release (ADR-0009). They are rechecked by hand before each release. The research table in `docs/design-plan.md` section 13 holds the documented claims these rows replace.

Run 1 used each CLI headless, on 2026-11-24, driven by the prompt in `tools/probe/README.md`. Headless runs show what the protocol does, but not what a person would see: no one was there to answer a form. Claude Desktop and the Codex / ChatGPT desktop app have no headless mode. They need a manual run.

| Host | Version | Protocol | Advertised | Form (headless) | Image reaches model | Progress | 75 s call | Resources | Prompts to agent | MCP Apps |
|---|---|---|---|---|---|---|---|---|---|---|
| Claude Code CLI (`-p`) | 2.1.330 | 2026-07-28 | `elicitation {form, url}`, `roots` | Fails: `NoBackChannelError: this transport context has no back-channel for server-initiated requests` | Yes, model described the colours | Call succeeds; no notifications reached the model | Succeeds | List and read | No (slash commands are for the person) | Text only; `ui://` resource listed |
| Codex CLI (`exec`) | 0.171.0 | 2025-06-18 | `elicitation {form, url}`, `codex/auth-change` | Auto-answered `cancel` | No: PNG received but not shown to the model | Succeeds | Succeeds (with `tool_timeout_sec` default) | List and read | No | Text only |
| OpenCode (`run`) | 2.2.1 | 2025-11-25 | `elicitation {form, url}`, `roots` | Waited about 80 s, then the connection dropped (`ECONNRESET`) and the run aborted | Not reached | Succeeds | Not reached | Not reached | Not reached | Not reached |
| Kiro CLI (`--no-interactive`, v3 and default) | 3.5.0 | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | Server configured in `kiro_default` and the workspace, but no MCP tools appeared in the session. `builder-mcp` was missing too, so this looks like a headless or policy limit to investigate. |
| Pi (`-p`) | 1.6.0 | 2025-11-25 | `roots` only | `Method not found: elicitation/create` | Yes as a block; not visible inside codemode scripts | Succeeds | Fails: `MCP request timed out after 60000ms` | No resource tool in `-p` with codemode | No | Text only |
| Claude Desktop | | | | | | | | | | manual run needed |
| Codex / ChatGPT desktop | | | | | | | | | | manual run needed |

What run 1 changes in the design (section 11 of the plan):

- **Form elicitation can't be trusted headless, even when advertised.** Claude Code `-p` advertises it but can't send it, Codex auto-cancels, and OpenCode hangs and then drops the connection. The gate chain must try a form only in an interactive session. It must also bound the wait (about 30 s), and fall back to the chat channel on an error, a cancel or a timeout. A cancel is no answer, and the gate stays open.
- **Pi times out at 60 s, and progress doesn't extend that.** Job handles stay the main path for anything longer than about 50 s.
- **The model doesn't always see images.** Codex `exec` got the PNG but didn't show it to the model. Snapshots for the agent's own review need a text summary (bounding box, mass, visible parts) beside the image.

## Template for manual runs

| Host | Version | Date | Protocol | Form | Image | Progress | Timeout (s) | Resources | Prompts | MCP Apps | Notes |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Claude Code CLI | | | | | | | | | | | not yet probed |
| Claude Desktop | | | | | | | | | | | not yet probed |
| Codex CLI | | | | | | | | | | | not yet probed |
| Codex / ChatGPT desktop | | | | | | | | | | | not yet probed |
| OpenCode | | | | | | | | | | | not yet probed |
| Kiro CLI | | | | | | | | | | | not yet probed |
| Pi | | | | | | | | | | | not yet probed |
