#!/usr/bin/env python3
"""Functional MCP test for garmin-mcp (Streamable HTTP by default)."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from typing import Any

from mcp import ClientSession

MCP_URL = os.environ.get("GARMIN_MCP_URL", "http://127.0.0.1:8000/mcp")
MCP_TRANSPORT = os.environ.get("MCP_TRANSPORT", "streamable-http").lower()
CONNECT_TIMEOUT = 30
TOOL_TIMEOUT = 180


def _tool_payload(result: Any) -> dict[str, Any] | list[Any]:
    if result.isError:
        raise RuntimeError(f"Tool error: {result.content}")
    texts = [
        block.text for block in result.content if hasattr(block, "text") and block.text
    ]
    if not texts:
        raise RuntimeError("Tool returned no text content")
    if len(texts) == 1:
        return json.loads(texts[0])
    parsed = [json.loads(text) for text in texts]
    if all(isinstance(item, dict) for item in parsed):
        return parsed
    return parsed


def _connect(url: str):
    if MCP_TRANSPORT == "sse":
        from mcp.client.sse import sse_client

        return sse_client(url)
    from mcp.client.streamable_http import streamablehttp_client

    return streamablehttp_client(url)


async def _run() -> None:
    print(f"Connecting to {MCP_URL} (transport={MCP_TRANSPORT}) ...")
    async with asyncio.timeout(CONNECT_TIMEOUT):
        async with _connect(MCP_URL) as transport:
            if MCP_TRANSPORT == "sse":
                read, write = transport
            else:
                read, write, _get_session_id = transport
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                tool_names = sorted(t.name for t in tools.tools)
                print(f"Tools ({len(tool_names)}): {', '.join(tool_names)}")

                removed = (
                    "get_weekly_review",
                    "get_plan_weeks",
                    "get_training_plan",
                    "get_weekly_report",
                    "get_coach_prompt",
                )
                for name in removed:
                    if name in tool_names:
                        raise RuntimeError(f"Removed tool still exposed: {name}")

                if "get_coaching_brief" not in tool_names:
                    raise RuntimeError("Missing tool: get_coaching_brief")

                async with asyncio.timeout(TOOL_TIMEOUT):
                    report_result = await session.call_tool(
                        "get_coaching_brief", arguments={}
                    )
                report = _tool_payload(report_result)
                if isinstance(report, dict) and report.get("error"):
                    raise RuntimeError(f"get_coaching_brief error: {report['error']}")
                if "training_plan" not in report:
                    raise RuntimeError("get_coaching_brief missing training_plan")
                if "plan_weeks" in report:
                    raise RuntimeError("get_coaching_brief still has plan_weeks")
                if "coaching_brief" not in report:
                    raise RuntimeError("get_coaching_brief missing coaching_brief")
                if "weekly_stats" in report:
                    raise RuntimeError("get_coaching_brief still has weekly_stats")
                print(
                    f"get_coaching_brief: OK "
                    f"(training_plan weeks={len(report['training_plan'])}, "
                    f"profile keys={list(report.get('profile', {}).keys())[:3]})"
                )

                resources = await session.list_resources()
                resource_uris = sorted(r.uri for r in resources.resources)
                print(f"Resources: {', '.join(resource_uris)}")
                if "garmin://weekly-report" not in resource_uris:
                    raise RuntimeError("Missing garmin://weekly-report resource")
                if "garmin://coach-prompt" in resource_uris:
                    raise RuntimeError("Removed resource still exposed: coach-prompt")

    print("ALL MCP FUNCTIONAL TESTS PASSED")


if __name__ == "__main__":
    try:
        asyncio.run(_run())
    except Exception as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        sys.exit(1)
