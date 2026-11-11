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


def test_mcp_thread_metadata_keeps_parallel_handoffs_separate(monkeypatch, tmp_path):
    """The wire ids, not agent-supplied arguments, separate two tasks."""
    from mnemos import simple_mcp

    runtime = MnemosRuntime(db_path=str(tmp_path / 'memory.db'), use_dedicated_model=False)
    monkeypatch.setattr(simple_mcp, '_get_runtime', lambda: runtime)
    first = '11111111-1111-7111-8111-111111111111'
    second = '22222222-2222-7222-8222-222222222222'

    async def session():
        async with _client(simple_mcp.simple_mcp, 'codex') as client:
            for thread, text in [(first, 'First task: fix parser'), (second, 'Second task: review storage')]:
                result = await client.call_tool('mnemos_handoff', {'text': text}, meta={
                    'threadId': thread, 'sessionId': first,
                })
                assert not _failed(result), _text(result)
            result = await client.call_tool('mnemos_context', {}, meta={'threadId': first, 'sessionId': first})
            return _text(result)

    try:
        packet = anyio.run(session)
        notes = runtime._store.live_handoffs(**runtime._scope_args())
        assert {note['author_session'] for note in notes} == {first, second}
        assert packet.index('First task: fix parser') < packet.index('Second task: review storage')
    finally:
        runtime.close()


def test_metadata_survives_a_real_server_restart_and_recall_from_another_task(tmp_path):
    """Transport metadata must work across processes, with the shared scope unchanged."""
    import os
    import sys
    from mcp.client.session import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    path = tmp_path / 'served.db'
    first = '11111111-1111-7111-8111-111111111111'
    second = '22222222-2222-7222-8222-222222222222'
    args = ['-m', 'mnemos.cli', 'serve', '--mode', 'simple', '--db-path', str(path),
            '--agent-id', 'probe', '--person-id', 'person', '--project-scope', 'global']

    async def run(write):
        params = StdioServerParameters(command=sys.executable, args=args, env=dict(os.environ))
        async with stdio_client(params) as (reader, writer):
            async with ClientSession(reader, writer) as client:
                await client.initialize()
                schemas = await client.list_tools()
                assert all('ctx' not in tool.model_dump(by_alias=True)['inputSchema'].get('properties', {}) for tool in schemas.tools)
                if write:
                    result = await client.call_tool('mnemos_capture', {'content': 'The copper lantern inspection passed.'}, meta={
                        'threadId': first, 'sessionId': first,
                        'mnemos/origin': {'project_id': 'project-one', 'project_name': 'Mnemos', 'thread_title': 'Inspection'},
                    })
                else:
                    result = await client.call_tool('mnemos_recall', {'query': 'copper lantern inspection'}, meta={
                        'threadId': second, 'sessionId': second,
                    })
                assert not _failed(result), _text(result)
                return _text(result)

    assert 'Captured continuity.' in anyio.run(run, True)
    found = anyio.run(run, False)
    assert 'The copper lantern inspection passed.' in found
    assert 'project=Mnemos (project-one)' in found
    assert f'task=Inspection ({first})' in found


def test_missing_or_malformed_metadata_never_inherits_previous_task(monkeypatch, tmp_path):
    from mnemos import simple_mcp
    runtime = MnemosRuntime(db_path=str(tmp_path / 'memory.db'), use_dedicated_model=False)
    monkeypatch.setattr(simple_mcp, '_get_runtime', lambda: runtime)
    thread = '11111111-1111-7111-8111-111111111111'
    async def session():
        async with _client(simple_mcp.simple_mcp, 'codex') as client:
            await client.call_tool('mnemos_introduce', {'agent_model': 'gpt-6.1-sol'}, meta={'threadId': thread})
            for meta in ({'threadId': thread}, None, {'threadId': ['not', 'an', 'id']}, {'threadId': 'bad'}):
                result = await client.call_tool('mnemos_journal', {'text': 'A separate observation.'}, meta=meta)
                assert not _failed(result), _text(result)
    try:
        anyio.run(session)
        rows = runtime._store.journal_entries(**runtime._scope_args())
        assert [row['session_id'] for row in rows] == ['', '', '', thread]
        assert [row['model_id'] for row in rows] == ['', '', '', 'gpt-6.1-sol']
    finally:
        runtime.close()
