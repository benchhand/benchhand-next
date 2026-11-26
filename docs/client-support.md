# Client support

These are measured results from the dev probe (`tools/probe/`, ADR-0016), one row for each host tested at release (ADR-0009). They are rechecked by hand before each release. The research table in `docs/design-plan.md` section 13 holds the documented claims these rows replace.

Run 1 used each CLI headless, on 2026-11-24, driven by the prompt in `tools/probe/README.md`. Headless runs show what the protocol does, but not what a person would see: no one was there to answer a form. Claude Desktop and the Codex / ChatGPT desktop app have no headless mode. They need a manual run.

| Host | Version | Protocol | Advertised | Form (headless) | Image reaches model | Progress | 75 s call | Resources | Prompts to agent | MCP Apps |
|---|---|---|---|---|---|---|---|---|---|---|
| Claude Code CLI (`-p`) | 2.1.330 | 2026-07-28 | `elicitation {form, url}`, `roots` | Fails: `NoBackChannelError: this transport context has no back-channel for server-initiated requests` | Yes, model described the colours | Call succeeds; no notifications reached the model | Succeeds | List and read | No (slash commands are for the person) | Text only; `ui://` resource listed |
| Codex CLI (`exec`) | 0.171.0 | 2025-06-18 | `elicitation {form, url}`, `codex/auth-change` | Auto-answered `cancel` | No: PNG received but not shown to the model | Succeeds | Succeeds (with `tool_timeout_sec` default) | List and read | No | Text only |
| OpenCode (`run`) | 2.2.1 | 2025-11-25 | `elicitation {form, url}`, `roots` | Waited about 80 s, then the connection dropped (`ECONNRESET`) and the run aborted | Not reached | Succeeds | Not reached | Not reached | Not reached | Not reached |
| Pi (`-p`) | 1.6.0 | 2025-11-25 | `roots` only | `Method not found: elicitation/create` | Yes as a block; not visible inside codemode scripts | Succeeds | Fails: `MCP request timed out after 60000ms` | No resource tool in `-p` with codemode | No | Text only |
| Claude Code CLI (interactive) | 2.1.330, Opus 5.5 | 2026-07-28 | `elicitation {form, url}`, `roots`, extension `io.modelcontextprotocol/tasks` | Probe bug: it used a mid-call request, which 2026-07-28 forbids (`NoBackChannelError`). Fixed to use multi round-trip; rerun needed. | Yes, colours described | No notifications reached the model | Succeeds | List and read | Not to the model; slash command unchecked | Text only |
| Pi (interactive, codemode) | 1.6.0 | 2025-11-25 | `roots` only | `Method not found: elicitation/create` | Yes, after codemode's `image()` helper | No notifications visible in codemode | Fails at 60.5 s: `MCP request timed out after 60000ms` | List and read (server name `probe`, not `mcp__probe`) | No | Text only |
| Kiro CLI (interactive and headless, default and custom agent) | 3.5.0 | 2026-07-28 (also 2025-11-25 with `BENCHHAND_PROBE_LEGACY=1`) | n/a | n/a | n/a | n/a | n/a | n/a | n/a | Kiro's log shows `mcp.connect.ok` and `mcp.listTools.ok` for `probe` on both protocol revisions, but the tools never reach the model. The default agent's tool policy filters them out. A custom agent with `tools: ["@probe"]`, which Kiro upgraded to V3 with a `mcp probe/*` allow rule, still shows no probe tools. Open: needs Kiro's V3 tool-exposure rules. |
| Claude Desktop (Code tab, Bedrock build `Claude-3p`, run by hand) | 6.28899.6, Sonnet 5.5 | 2025-11-25 | `roots`, extension `io.modelcontextprotocol/ui` (`text/html;profile=mcp-app`); no elicitation, no sampling | Fails: `Client did not declare the form elicitation capability required by resolver '__main__:_ask_gate'` | Yes, colours described | Call succeeds; no notifications reached the model | Fails: `Request timed out` (limit under 75 s, not measured) | No: list returns nothing, read gives `Server "benchhand-probe" does not support resources` | No prompt tool | A widget appears but is blank. The probe page is static HTML and does no MCP Apps handshake with the host, which is a likely cause; probe fix pending. |
| Codex / ChatGPT desktop | | | | | | | | | | manual run needed |

What run 1 changes in the design (section 11 of the plan):

- **On 2026-07-28 a form must use multi round-trip** (`InputRequiredResult`, then the client retries the call with the answer). A mid-call request fails with `NoBackChannelError`. The benchhand server must use the SDK's `Resolve(Elicit)` path, never `ctx.elicit`.
- **Form elicitation can't be trusted headless, even when advertised.** Claude Code `-p` failed through the probe bug above, Codex auto-cancels, and OpenCode hangs and then drops the connection. The gate chain must try a form only in an interactive session. It must also bound the wait (about 30 s), and fall back to the chat channel on an error, a cancel or a timeout. A cancel is no answer, and the gate stays open.
- **Claude Code advertises the tasks extension** (`io.modelcontextprotocol/tasks`), so long jobs can use tasks there once the SDK implements it.
- **Pi times out at 60 s, and progress doesn't extend that.** Job handles stay the main path for anything longer than about 30 s (ADR-0018).
- **Claude Desktop has no forms and times out before 75 s.** It also hides resources from the agent, so anything the agent must read goes through a tool result, not a resource. It is the only host so far that draws an MCP App widget, which makes it the first target for the preview host.
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
