#!/usr/bin/env -S uv run --script

# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

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
from typing import Annotated, Any

from mcp.server.mcpserver import Context, Elicit, ElicitationResult, MCPServer, Resolve
from mcp.types import ImageContent, ResourceLink, TextContent
from pydantic import BaseModel

OUT = Path(os.environ.get("BENCHHAND_PROBE_OUT", "probe-results.jsonl")).resolve()


def _force_handshake_protocol() -> None:
    """BENCHHAND_PROBE_LEGACY=1 hides 2026-07-28, so a host negotiates 2025-11-25 or older.

    Dev-only diagnosis for hosts that connect on 2026-07-28 but never surface the tools.
    The SDK copies the version tuple into several modules, so each copy is replaced.
    """
    import importlib

    for name in (
        "mcp_types.version",
        "mcp.server.runner",
        "mcp.server.session",
        "mcp.server.connection",
        "mcp.server.lowlevel.server",
        "mcp.shared.inbound",
    ):
        module = importlib.import_module(name)
        if hasattr(module, "MODERN_PROTOCOL_VERSIONS"):
            module.MODERN_PROTOCOL_VERSIONS = ()


if os.environ.get("BENCHHAND_PROBE_LEGACY") == "1":
    _force_handshake_protocol()
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


def _ask_gate() -> Elicit[GateAnswer]:
    return Elicit("benchhand probe: do you see this form? Pick approve or changes.", GateAnswer)


@server.tool()
async def probe_form(
    ctx: Context, answer: Annotated[ElicitationResult[GateAnswer], Resolve(_ask_gate)]
) -> str:
    """Ask the person a two-field form. Uses the transport the protocol revision requires:
    multi round-trip (InputRequiredResult) on 2026-07-28, a mid-call request before it."""
    data = {"action": answer.action, "content": getattr(answer, "data", None)}
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
