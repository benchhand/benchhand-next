#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["mcp==2.3.0"]
# ///
"""Dev-only capability probe (ADR-0016). Not shipped, not run in CI.

Register it by hand in a host as a stdio MCP server:

    uv run --script /abs/path/tools/probe/probe.py

Then ask the agent: "Call every probe_* tool once, in order, and report what you saw."
Each tool appends a JSON line to $BENCHHAND_PROBE_OUT (default ./probe-results.jsonl): what the
client advertised and what happened. Fill docs/client-support.md from it, including what the
person saw (form shown? image visible? App rendered?), which the server can't observe.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import struct
import time
import zlib
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import Context, MCPServer
from mcp.types import ImageContent, ResourceLink, TextContent
from pydantic import BaseModel

OUT = Path(os.environ.get("BENCHHAND_PROBE_OUT", "probe-results.jsonl")).resolve()
APP_URI = "ui://benchhand-probe/app"

server = MCPServer(
    name="benchhand-probe",
    instructions=(
        "Capability probe for benchhand development. Call each probe_* tool once and report the result."
    ),
)


def _record(probe: str, ctx: Context, **data: Any) -> dict[str, Any]:
    entry = {"probe": probe, "time": time.time(), **data}
    try:
        entry["protocol_version"] = str(ctx.protocol_version)
        caps = ctx.client_capabilities
        entry["client_capabilities"] = caps.model_dump(mode="json", exclude_none=True) if caps else None
    except Exception as error:  # a host may lack what the SDK expects; record it rather than fail
        entry["context_error"] = repr(error)
    with OUT.open("a") as handle:
        handle.write(json.dumps(entry, default=str) + "\n")
    return entry


def _png(width: int = 64, height: int = 64) -> bytes:
    rows = b"".join(
        b"\x00" + b"".join(bytes((x * 4 % 256, y * 4 % 256, 160)) for x in range(width))
        for y in range(height)
    )

    def chunk(kind: bytes, body: bytes) -> bytes:
        return (
            struct.pack(">I", len(body))
            + kind
            + body
            + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)
        )

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )


@server.tool()
async def probe_capabilities(ctx: Context) -> str:
    """Record the protocol version and the capabilities this client advertised."""
    return json.dumps(_record("capabilities", ctx), indent=2, default=str)


class GateAnswer(BaseModel):
    decision: str = "approve"
    rationale: str = ""


@server.tool()
async def probe_form(ctx: Context) -> str:
    """Ask the person a two-field form through form-mode elicitation."""
    try:
        result = await ctx.elicit(
            "benchhand probe: do you see this form? Pick approve or changes.", GateAnswer
        )
        data = {"action": result.action, "content": getattr(result, "data", None)}
    except Exception as error:
        data = {"error": repr(error)}
    _record("form", ctx, **data)
    return json.dumps(data, default=str)


@server.tool()
async def probe_image(ctx: Context) -> list[Any]:
    """Return a small PNG as image content and a resource link to the same file."""
    png = _png()
    path = OUT.with_suffix(".png")
    path.write_bytes(png)
    _record("image", ctx, bytes=len(png), path=str(path))
    return [
        TextContent(type="text", text="A 64x64 gradient image follows. Describe its colours."),
        ImageContent(type="image", data=base64.b64encode(png).decode(), mime_type="image/png"),
        ResourceLink(type="resource_link", uri=path.as_uri(), name="probe.png", mime_type="image/png"),
    ]


@server.tool()
async def probe_progress(ctx: Context, seconds: int = 8) -> str:
    """Run for a few seconds while sending progress notifications."""
    for step in range(seconds):
        await ctx.report_progress(step, seconds, f"step {step + 1} of {seconds}")
        await asyncio.sleep(1)
    _record("progress", ctx, seconds=seconds)
    return "done"


@server.tool()
async def probe_timeout(ctx: Context, seconds: int = 90) -> str:
    """Sleep without progress to find this host's tool-call timeout. Default 90 s."""
    _record("timeout-start", ctx, seconds=seconds)
    await asyncio.sleep(seconds)
    _record("timeout-end", ctx, seconds=seconds)
    return f"slept {seconds} s"


@server.resource(APP_URI, mime_type="text/html;profile=mcp-app")
def probe_app_html() -> str:
    body = "<body style='font:16px system-ui;padding:1em'>benchhand probe: MCP App rendered.</body>"
    return f"<!doctype html><html>{body}</html>"


@server.tool(meta={"ui": {"resourceUri": APP_URI}})
async def probe_app(ctx: Context) -> str:
    """Return a result linked to an MCP App UI resource. A host with Apps renders a small page."""
    _record("app", ctx)
    return "If your host supports MCP Apps, a page saying 'MCP App rendered' should appear."


@server.resource("probe://readme", mime_type="text/plain")
def probe_resource() -> str:
    return "benchhand probe resource: if the agent can read this, resources work."


@server.prompt()
def probe_prompt() -> str:
    """A prompt; check whether the host exposes it as a slash command."""
    return "benchhand probe prompt: if you see this as a command, prompts work."


@server.tool()
async def probe_report(ctx: Context, report: str) -> str:
    """Save the agent's final report of the probe run, verbatim, next to the probe results."""
    _record("report", ctx, report=report)
    path = OUT.with_suffix(".report.md")
    path.write_text(report)
    return f"saved to {path}"


if __name__ == "__main__":
    server.run()
