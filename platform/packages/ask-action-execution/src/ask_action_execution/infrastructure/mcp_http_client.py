# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""
mcp_http_client.py — Async HTTP client for the MCP Streamable HTTP protocol.

Handles the 3-step session handshake and both JSON / SSE response formats.
Standalone — no project dependencies.
"""

from __future__ import annotations

import json
import logging
import uuid

import aiohttp

logger = logging.getLogger(__name__)


class MCPClient:
    """
    Stateful MCP client for a single server endpoint.
    One instance per server URL; session is reused across calls.
    """

    def __init__(self, base_url: str, timeout: int = 30):
        self.base_url = base_url.rstrip("/")
        self.mcp_url = f"{self.base_url}/mcp"
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self._session_id: str | None = None
        self._session: aiohttp.ClientSession | None = None

    async def connect(self) -> None:
        """Open HTTP session and perform MCP handshake."""
        self._session = aiohttp.ClientSession(
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
            },
            timeout=self.timeout,
        )
        await self._initialize()

    async def close(self) -> None:
        if self._session:
            await self._session.close()
            self._session = None
        self._session_id = None

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, *_):
        await self.close()

    async def list_tools(self) -> list[dict]:
        resp = await self._call("tools/list", {})
        return resp.get("result", {}).get("tools", [])

    async def call_tool(self, tool_name: str, arguments: dict) -> dict:
        resp = await self._call(
            "tools/call",
            {
                "name": tool_name,
                "arguments": arguments,
            },
        )
        result = resp.get("result", resp)
        # MCP tool errors: {"isError": true, "content": [{"type":"text","text":"Error: ..."}]}
        if result.get("isError"):
            texts = [
                c.get("text", "") for c in result.get("content", []) if c.get("type") == "text"
            ]
            error_msg = " ".join(texts).strip() or "MCP tool returned an error"
            return {"error": error_msg}
        # Unwrap content array to the text payload when present
        content = result.get("content")
        if isinstance(content, list) and content:
            text = content[0].get("text", "")
            try:
                return json.loads(text)
            except Exception:
                return {"text": text}
        return result

    async def _initialize(self) -> None:
        # Step 1 — initialize
        init_payload = {
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "clientInfo": {"name": "onibex-agenticai", "version": "1.0"},
                "capabilities": {},
            },
        }
        async with self._session.post(self.mcp_url, json=init_payload) as r:
            r.raise_for_status()
            self._session_id = r.headers.get("mcp-session-id")
            if not self._session_id:
                raise RuntimeError("MCP server did not return a session ID")
            logger.info("MCP session established: %s", self._session_id)

        # Step 2 — notifications/initialized
        notif_payload = {
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
            "params": {},
        }
        async with self._session.post(
            self.mcp_url,
            json=notif_payload,
            headers={"Mcp-Session-Id": self._session_id},
        ) as r:
            pass  # 204 expected

    async def _call(self, method: str, params: dict) -> dict:
        if not self._session_id:
            raise RuntimeError("MCP client not connected. Call connect() first.")
        payload = {
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": method,
            "params": params,
        }
        async with self._session.post(
            self.mcp_url,
            json=payload,
            headers={"Mcp-Session-Id": self._session_id},
        ) as r:
            r.raise_for_status()
            text = await r.text()
            return self._parse_mcp_body(text)

    @staticmethod
    def _parse_mcp_body(text: str) -> dict:
        """Parse MCP response body — handles plain JSON and SSE (data: {...}) format."""
        text = text.strip()
        if not text:
            return {}
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("data:"):
                payload = line[5:].strip()
                if payload and payload != "[DONE]":
                    return json.loads(payload)
        return json.loads(text)


def mcp_call_sync(mcp_url: str, tool_name: str, arguments: dict, timeout: int = 90) -> dict:
    """Synchronous wrapper — opens a fresh MCP session, calls one tool, closes.

    Runs in a dedicated thread so it is safe to call from inside a running
    event loop (e.g. FastAPI/uvicorn). asyncio.run() creates a fresh loop in
    the worker thread — no nesting issues.
    """
    import asyncio
    import concurrent.futures

    async def _run():
        async with MCPClient(mcp_url, timeout=timeout) as client:
            return await client.call_tool(tool_name, arguments)

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, _run()).result()


def mcp_list_tools_sync(mcp_url: str, timeout: int = 15) -> list[dict]:
    import asyncio
    import concurrent.futures

    async def _run():
        async with MCPClient(mcp_url, timeout=timeout) as client:
            return await client.list_tools()

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, _run()).result()
