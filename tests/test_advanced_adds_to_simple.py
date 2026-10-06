"""Advanced mode adds to simple mode, and switches nothing off.

Riley, 2026-10-06: "advanced mode is only supposed to be additive to simple
mode." It wasn't. `mnemos serve --mode advanced` served an older recall in
place of simple mode's: it couldn't look a memory up by id, had no standing
filter, cut each row to 150 characters and waited on setup, so the two recalls
an agent's notes make at the start of a session, `mnemos_recall(query="",
standing=true)` and `mnemos_recall("<handoff id>")`, found nothing. It never
started the cue's answerer, so the prompt hook lost meaning search and its
judge, and its shutdown closed only its own store. And it refused to run, or
to be installed, without MNEMOS_ENABLE_EXPERIMENTAL=1.

Now advanced mode is every simple tool, unchanged, with simple mode's start
and shutdown, plus its own tools. It needs no switch, and says once that it
is less tested than simple mode.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import signal
import sys
from pathlib import Path

import anyio
import pytest

import mnemos.mcp_server as mcp_server
import mnemos.simple_mcp as simple_mcp
from mnemos.cli import main
from mnemos.simple_runtime import SIMPLE_TOOL_NAMES
from mnemos.simple_scope import resolve_scope

SCOPE = {"agent_id": "nova", "person_id": "riley", "project_scope": "demo"}
SCOPE_ARGS = ["--agent-id", "nova", "--person-id", "riley", "--project-scope", "demo"]
MODEL = "claude-opus-5-5"
STANDING = "Riley wants the answer first, then the reasoning, in every reply."
# Longer than the 150 characters the old advanced recall kept of a row.
HANDOFF = (
    "I was making advanced mode add to simple mode: its old recall is gone, "
    "run_server starts the cue's answerer and stops it at shutdown, and serve "
    "needs no switch. Next I run the whole suite, then open the pull request."
)
SETUP_GATE = "isn't configured yet"
NOTE = "it's less tested than simple mode"


def _tools(server) -> dict:
    return {tool.name: tool for tool in asyncio.run(server.list_tools())}


def _advanced(name: str):
    """A tool as the advanced server serves it."""
    return mcp_server.mcp._tool_manager.get_tool(name).fn


def _text(result) -> str:
    if isinstance(result, str):
        return result
    return "\n".join(
        block.text for block in result.content if getattr(block, "type", None) == "text"
    )


@pytest.fixture
def runtime_on(tmp_path, monkeypatch):
    """The simple tools' runtime on a store of the test's own, as either server
    configures it, and nobody has run advanced setup. Closed after."""
    monkeypatch.setattr(simple_mcp, "_runtime", None)
    monkeypatch.setattr(
        simple_mcp, "_runtime_kwargs", {"db_path": str(tmp_path / "memory.db"), **SCOPE}
    )
    monkeypatch.setattr(mcp_server, "_config", None)
    yield
    if simple_mcp._runtime is not None:
        simple_mcp._runtime.close()


class _Answerer:
    def __init__(self) -> None:
        self.stopped = 0

    def stop(self) -> None:
        self.stopped += 1


@pytest.fixture
def server_start(monkeypatch):
    """run_server without serving: the cue's answerer, the stdio loop and the
    signal handlers are recorded instead of started, and every global it sets
    is put back."""
    seen: dict = {"answerers": [], "handlers": {}, "served": 0}

    def start_cue_answerer():
        seen["answerers"].append(_Answerer())
        return seen["answerers"][-1]

    def run(*args, **kwargs):
        seen["served"] += 1

    monkeypatch.setattr(simple_mcp, "start_cue_answerer", start_cue_answerer)
    monkeypatch.setattr(mcp_server.mcp, "run", run)
    monkeypatch.setattr(signal, "signal", lambda signum, handler: seen["handlers"].__setitem__(signum, handler))
    for name in ("_store", "_encoder", "_embedding_index", "_shared_pool", "_llm_client", "_config"):
        monkeypatch.setattr(mcp_server, name, None)
    monkeypatch.setattr(mcp_server, "_default_agent_id", "default")
    monkeypatch.setattr(simple_mcp, "_runtime", None)
    monkeypatch.setattr(simple_mcp, "_runtime_kwargs", {})
    yield seen
    if simple_mcp._runtime is not None:
        simple_mcp._runtime.close()
    mcp_server._close_advanced_store()
    # run_server names the server's agent in the environment; the next test
    # starts without it.
    os.environ.pop("MNEMOS_AGENT_ID", None)


# ── The tools a client is shown ──


def test_advanced_serves_every_simple_tool_and_more():
    simple, advanced = _tools(simple_mcp.simple_mcp), _tools(mcp_server.mcp)

    assert set(simple) == set(SIMPLE_TOOL_NAMES)
    assert set(simple) < set(advanced), sorted(set(simple) - set(advanced))


@pytest.mark.parametrize("name", SIMPLE_TOOL_NAMES)
def test_every_simple_tool_is_the_same_in_advanced_mode(name):
    simple = _tools(simple_mcp.simple_mcp)[name]
    advanced = _tools(mcp_server.mcp)[name]

    assert advanced.inputSchema == simple.inputSchema
    # And the rest of what a client is shown: its description, annotations
    # and output schema.
    assert advanced.model_dump() == simple.model_dump()


def test_advanced_instructions_are_the_simple_ones_and_one_line():
    added = mcp_server.ADVANCED_INSTRUCTIONS.removeprefix(simple_mcp.SERVER_INSTRUCTIONS + "\n\n")

    assert added != mcp_server.ADVANCED_INSTRUCTIONS, "the simple instructions don't come first"
    assert added.strip() and "\n" not in added


# ── What the tools do ──


def test_the_recalls_a_session_starts_with_work_in_advanced_mode(runtime_on):
    """What an agent's session-start notes call: every standing memory with no
    query, and the last handoff by its id, whole."""
    _advanced("mnemos_capture")(content=STANDING, standing=True, signed_as=MODEL)
    said = _advanced("mnemos_handoff")(text=HANDOFF, signed_as=MODEL)
    handoff_id = re.search(r"Handoff ID: (\S+)", said).group(1)

    standing = _advanced("mnemos_recall")(query="", standing=True)
    by_id = _advanced("mnemos_recall")(query=handoff_id)

    assert STANDING in standing, standing
    assert HANDOFF in " ".join(by_id.split()), by_id


def test_no_simple_tool_waits_on_advanced_setup(runtime_on):
    """Before anyone runs mnemos_setup, every simple tool in advanced mode works
    as it does in simple mode: the setup gate is the advanced tools' own."""
    assert mcp_server._setup_gate() is not None, "this install should not be set up"
    calls = {
        "mnemos_context": {},
        "mnemos_handoff": {"text": "I was checking advanced mode.", "signed_as": MODEL},
        "mnemos_journal": {},
        "mnemos_note": {"text": "Advanced mode adds now.", "kind": "noticed", "signed_as": MODEL},
        "mnemos_capture": {"content": "Riley keeps advanced mode optional.", "signed_as": MODEL},
        "mnemos_recall": {"query": "advanced mode optional"},
        "mnemos_correct": {"correction": "Riley keeps advanced mode optional and less tested.",
                           "query": "advanced mode optional"},
        "mnemos_maintain": {},
        "mnemos_reflect": {"target_id": "engram_NOTREAL", "text": "Nothing to add."},
        "mnemos_introduce": {"agent_model": MODEL},
        "mnemos_health": {},
    }
    assert set(calls) == set(SIMPLE_TOOL_NAMES)

    gated = {}
    for name, args in calls.items():
        out = _text(_advanced(name)(**args))
        if SETUP_GATE in out:
            gated[name] = out

    assert not gated, gated


# ── The server's start and shutdown ──


def test_run_server_starts_the_cue_answerer_and_shuts_down_as_simple_mode_does(server_start, tmp_path):
    mcp_server.run_server(db_path=str(tmp_path / "memory.db"), **SCOPE)

    assert len(server_start["answerers"]) == 1, "the prompt hook's answerer never started"
    assert server_start["served"] == 1

    runtime = simple_mcp._get_runtime()
    runtime.capture(STANDING)
    store, index, pool = mcp_server._store, mcp_server._embedding_index, mcp_server._shared_pool
    assert runtime._store is not None and store._conn is not None and pool._store._conn is not None

    with pytest.raises(SystemExit):
        server_start["handlers"][signal.SIGTERM](signal.SIGTERM, None)

    assert server_start["answerers"][0].stopped == 1, "the answerer was left running"
    assert runtime._store is None, "the simple runtime was left open"
    assert store._conn is None, "the advanced store was left open"
    assert index._conn is None, "the advanced store's meaning index was left open"
    assert pool._store._conn is None, "the shared pool was left open"


def test_run_server_with_no_store_named_opens_the_one_simple_mode_would(server_start):
    mcp_server.run_server(**SCOPE)

    expected = Path(resolve_scope(**SCOPE).db_path).expanduser()
    assert mcp_server._store.db_path == expected
    assert simple_mcp._get_runtime().db_path == expected


# ── The command line ──


def test_serve_runs_advanced_mode_without_a_switch_and_says_it_is_less_tested(
    monkeypatch, capsys, tmp_path,
):
    started = []
    monkeypatch.setattr(mcp_server, "run_server", lambda **kwargs: started.append(kwargs))
    db = tmp_path / "memory.db"

    assert main(["serve", "--mode", "advanced", "--db-path", str(db), *SCOPE_ARGS]) == 0

    assert started == [{"db_path": str(db), **SCOPE}]
    err = capsys.readouterr().err
    assert NOTE in err, err
    assert "MNEMOS_ENABLE_EXPERIMENTAL" not in err


def test_advanced_mode_installs_without_a_switch(capsys):
    assert main(["mcp", "install", "generic", "--mode", "advanced"]) == 0

    out, err = capsys.readouterr()
    assert json.loads(out)["mcpServers"]["mnemos"]["args"] == ["serve", "--mode", "advanced"]
    assert NOTE in err, err


def test_an_advanced_server_answers_a_sessions_first_recalls_over_stdio(tmp_path):
    """The whole path an agent takes: `mnemos serve --mode advanced` with no
    switch, a capture and a handoff, then the session-start recalls, over the
    real protocol."""
    from mcp.client.session import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "mnemos.cli", "serve", "--mode", "advanced",
              "--db-path", str(tmp_path / "memory.db"), *SCOPE_ARGS],
        env={
            "HOME": os.environ["HOME"],
            "PATH": "/usr/bin:/bin",
            "MNEMOS_DISABLE_DOTENV": "1",
            "PYTHONPATH": os.pathsep.join(sys.path),
        },
    )
    seen: dict[str, str] = {}

    async def run() -> None:
        with open(tmp_path / "stderr.log", "w") as errlog:
            async with stdio_client(params, errlog=errlog) as streams:
                async with ClientSession(*streams) as session:
                    await session.initialize()
                    await session.call_tool(
                        "mnemos_capture", {"content": STANDING, "standing": True, "signed_as": MODEL})
                    said = _text(await session.call_tool(
                        "mnemos_handoff", {"text": HANDOFF, "signed_as": MODEL}))
                    handoff_id = re.search(r"Handoff ID: (\S+)", said).group(1)
                    seen["standing"] = _text(await session.call_tool(
                        "mnemos_recall", {"query": "", "standing": True}))
                    seen["by_id"] = _text(await session.call_tool(
                        "mnemos_recall", {"query": handoff_id}))

    anyio.run(run)

    assert STANDING in seen["standing"], seen["standing"]
    assert HANDOFF in " ".join(seen["by_id"].split()), seen["by_id"]
    assert NOTE in (tmp_path / "stderr.log").read_text()
