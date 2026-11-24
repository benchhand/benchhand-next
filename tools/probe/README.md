# Capability probe (dev only)

This tool is not shipped and not run in CI (ADR-0016). It measures what an MCP host really supports, so the interaction layer's defaults rest on evidence.

1. Register the probe as a stdio MCP server in the host, using the host's own config:
   - command: `uv`
   - args: `run --script /abs/path/to/tools/probe/probe.py`
   - env: `BENCHHAND_PROBE_OUT=/abs/path/probe-<host>.jsonl`
2. Ask the agent: "Call every probe_* tool once, in order, and report what you saw." Run `probe_timeout` last, because it blocks for 90 s.
3. Note what you saw yourself: whether the form appeared, whether the image was visible, whether the App page rendered, and whether `probe_prompt` appears as a command.
4. Copy the results into `docs/client-support.md`, with the host version and date.
