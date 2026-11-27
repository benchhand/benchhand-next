---
title: Agent hosts
description: Notes for each of the 7 agent hosts that benchhand supports.
sidebar:
  order: 1
---

The results of the dev probe in each host are in [client-support.md](repo:docs/client-support.md).

## The supported hosts

benchhand is tested and supported in seven agent hosts:

- Claude Code CLI
- Claude Desktop
- Codex CLI
- the Codex and ChatGPT desktop app
- OpenCode
- Kiro CLI
- Pi

[Install](/getting-started/install/) shows what `benchhand install` writes for each one.

## What a host needs

Hosts differ in what they support, so benchhand starts from what all of them do: tool calls with text results.
Every workflow completes on that baseline.
A richer channel is an enhancement, used only where the host declares it, and the baseline path stays behind it:

| Need | Baseline, in every host | Enhancement, where the host declares it |
|---|---|---|
| A human gate, or a structured question | The agent asks in the conversation and records your reply through a tool. | The MCP App gate card |
| An image for the agent | A text summary, such as the bounding box, the mass and the visible parts, with the file path | The image itself |
| A preview for you | A loopback preview URL in the result | An MCP App that embeds the same page |
| Work over about 30 s | A job handle, followed with `jobs.status` and `jobs.result` | The MCP tasks extension, and progress notifications |
| Content to read | A tool that returns it | The same content as an MCP resource |

benchhand asks every question through the conversation or an MCP App, and uses no form elicitation.
An empty, declined or cancelled answer is no answer, and the gate stays open.
Images are scaled down to stay under each host's output limits.

## Claude Code CLI

- **Registration:** the benchhand plugin, with its `.mcp.json`, skill and agents, or a project `.mcp.json`. The plugin also installs from the Claude Code plugin marketplace.
- **Interactions:** image results reach the model. The host shows MCP App resources as text only, so gates are asked in the conversation. It declares the MCP tasks extension.
- **Limits:** tool output is capped by `MAX_MCP_OUTPUT_TOKENS`, 25,000 tokens by default.

## Claude Desktop

- **Registration:** a `.mcpb` bundle that runs `uvx benchhand mcp`. Its settings hold the FreeCAD path and whether to use the container.
- **Interactions:** Claude Desktop draws MCP App widgets, so it can show the gate card and the viewer in the conversation. Image results reach the model.
- **Limits:** a tool call times out in under 75 s, so long work goes through job handles. The host doesn't give resources to the agent, so everything the agent reads comes from tool results. It starts servers without a project directory: the project comes from the bundle's settings, or the agent opens it with `project.open`.

## Codex CLI

- **Registration:** the Codex plugin, or `[mcp_servers.benchhand]` in `config.toml`, with agent profiles in `.codex/agents/`.
- **Interactions:** Codex receives image results but doesn't pass them to the model, so the agent works from the text summary beside each image.
- **Limits:** the default startup timeout is 10 s, so `install` sets `startup_timeout_sec` to 120 s. The tool timeout, `tool_timeout_sec`, is 60 s by default, and tool output is capped by `output_token_limit`.

## Codex and ChatGPT desktop app

- **Registration:** the app shares `~/.codex/config.toml` with Codex CLI, so one registration serves both.
- **Interactions:** the baseline channels.

## OpenCode

- **Registration:** `mcp.servers.benchhand` in `opencode.json`, as a `local` server, with skills in `.opencode/skills` and agents in `.opencode/agents`.
- **Limits:** OpenCode waits 30 s for a server to start, and `install` checks that setting.

## Kiro CLI

- **Registration:** `mcp.json`, and `mcpServers` in the agent profile, with skills in `.kiro/skills` and agents in `.kiro/agents`.
- **Interactions:** the baseline channels.

## Pi

- **Registration:** the benchhand Pi package, whose extension registers the server, or `.pi/mcp.json`.
- **Interactions:** the package's extension adds a gate dialog and opens preview URLs. Image results reach the model.
- **Limits:** Pi times out a tool call at 60 s, and progress doesn't extend it, so long work goes through job handles.

## Other MCP hosts

Other MCP hosts can run benchhand through the baseline channels, without a guarantee.
Everything benchhand serves is local, so a web host that can't reach your machine, such as Claude.ai's web connectors, can't use it.
