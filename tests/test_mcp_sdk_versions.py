"""Mnemos's servers work on both majors of the MCP SDK.

mcp 2.0 renamed FastMCP to MCPServer and moved it, so until
mnemos/mcp_compat.py, importing either server on 2.x raised
ModuleNotFoundError. Hermes pins mcp 2 in its own environment, which is where
its plugin catalog installs Mnemos, while the lockfile, and so most of CI,
holds 1.x. These run on whichever is installed; CI runs them on both (the
mcp2 job in release-hardening.yml).
"""

from __future__ import annotations

import anyio
import pytest

pytest.importorskip("mcp")

from mcp import types  # noqa: E402

from mnemos.mcp_compat import MCP_MAJOR  # noqa: E402
from mnemos.simple_runtime import SIMPLE_TOOL_NAMES, MnemosRuntime  # noqa: E402


def _client(server, name: str):
    """A client connected to ``server`` in memory, whose handshake gives
    ``name``, as Claude Code's gives claude-code."""
    info = types.Implementation(name=name, version="0")
    if MCP_MAJOR >= 2:
        from mcp.client import Client

        return Client(server, client_info=info)
    from mcp.shared.memory import create_connected_server_and_client_session

    return create_connected_server_and_client_session(server, client_info=info)


def _text(result) -> str:
    return "\n".join(b.text for b in result.content if getattr(b, "type", "") == "text")


def _failed(result) -> bool:
    # is_error on 2.x, isError on 1.x
    return bool(getattr(result, "is_error", getattr(result, "isError", False)))


def test_both_servers_build_with_every_simple_tool():
    from mnemos.mcp_server import mcp
    from mnemos.simple_mcp import simple_mcp

    async def names(server):
        return {tool.name for tool in await server.list_tools()}

    assert anyio.run(names, simple_mcp) == set(SIMPLE_TOOL_NAMES)
    assert set(SIMPLE_TOOL_NAMES) < anyio.run(names, mcp)


def test_a_client_wakes_saves_and_recalls_and_mnemos_knows_its_name(monkeypatch, tmp_path):
    from mnemos import simple_mcp

    runtime = MnemosRuntime(
        db_path=str(tmp_path / "memory.db"), agent_id="nova", person_id="riley", project_scope="demo"
    )
    monkeypatch.setattr(simple_mcp, "_get_runtime", lambda: runtime)

    async def session():
        async with _client(simple_mcp.simple_mcp, "sdk-version-check") as client:
            listed = await client.list_tools()
            context = next(t for t in listed.tools if t.name == "mnemos_context")
            # The request the SDK hands the tool is never an argument a client sends.
            assert "ctx" not in context.model_dump(by_alias=True)["inputSchema"]["properties"]
            woke = await client.call_tool("mnemos_context", {})
            saved = await client.call_tool("mnemos_capture", {"content": "Sam prefers tabs over spaces."})
            found = await client.call_tool("mnemos_recall", {"query": "tabs"})
            return woke, saved, found

    try:
        results = anyio.run(session)
        for result in results:
            assert not _failed(result), _text(result)
        woke, _saved, found = (_text(r) for r in results)
        assert woke.strip()
        assert "Sam prefers tabs over spaces." in found
        assert runtime.client_name == "sdk-version-check"
    finally:
        runtime.close()
