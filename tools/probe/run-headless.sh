#!/bin/bash

# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

# Headless capability-probe driver (dev only, ADR-0016). Usage: run.sh <claude|codex|opencode|kiro|pi>
P=/Users/sjors/personal/dev/benchhand-next/tools/probe/probe.py
PROMPT="$(cat "$(dirname "$0")/prompt.txt")"
h=$1
d=/tmp/probe/$h
mkdir -p "$d"
cd "$d" || exit 1
export BENCHHAND_PROBE_OUT=$d/probe.jsonl
: > "$BENCHHAND_PROBE_OUT"
server_json="{\"command\":\"uv\",\"args\":[\"run\",\"--script\",\"$P\"],\"env\":{\"BENCHHAND_PROBE_OUT\":\"$BENCHHAND_PROBE_OUT\"}}"

case $h in
claude)
  claude -p "$PROMPT" --mcp-config "{\"mcpServers\":{\"probe\":$server_json}}" --strict-mcp-config \
    --allowedTools "mcp__probe" --max-turns 25
  ;;
codex)
  codex exec --skip-git-repo-check \
    -c 'mcp_servers.probe.command="uv"' \
    -c "mcp_servers.probe.args=[\"run\",\"--script\",\"$P\"]" \
    -c "mcp_servers.probe.env={BENCHHAND_PROBE_OUT=\"$BENCHHAND_PROBE_OUT\"}" \
    -c 'mcp_servers.probe.startup_timeout_sec=120' \
    -c 'mcp_servers.probe.default_tools_approval_mode="approve"' \
    "$PROMPT"
  ;;
opencode)
  printf '{"mcp":{"servers":{"probe":{"type":"local","command":["uv","run","--script","%s"],"environment":{"BENCHHAND_PROBE_OUT":"%s"}}}}}\n' \
    "$P" "$BENCHHAND_PROBE_OUT" > opencode.json
  opencode run "$PROMPT"
  ;;
kiro)
  mkdir -p .kiro/agents
  printf '{"name":"probe","description":"capability probe","prompt":"You test MCP capabilities.","tools":["@probe"],"mcpServers":{"probe":%s}}\n' \
    "$server_json" > .kiro/agents/probe.json
  kiro-cli chat --v3 --no-interactive --agent probe --trust-all-tools "$PROMPT"
  ;;
pi)
  mkdir -p .pi
  printf '{"mcpServers":{"probe":%s}}\n' "$server_json" > .pi/mcp.json
  pi -p --approve --model amazon-bedrock/global.anthropic.claude-sonnet-5-5 "$PROMPT"
  ;;
esac
