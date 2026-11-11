"""`mnemos connect`: one command to set Mnemos up for an agent (0.7.0).

Someone on Codex, Grok, Gemini CLI, Hermes or OpenClaw can connect Mnemos and
get everything their agent can take, or be told exactly what is missing.
These tests run it against fake agent commands (a script that records its
arguments) and each agent's own folders under the test's home, and check what
it wrote, what it left alone, and what it said.

The facts about each agent are in one table (mnemos/setup/harnesses.py).
Nothing here talks to a real agent.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import sys

import pytest

from mnemos import cli
from mnemos.cli import main
from mnemos.setup import connect as cn
from mnemos.setup import harnesses as hs
from mnemos.simple_runtime import MnemosRuntime

MNEMOS = "/opt/mnemos/bin/mnemos"


@pytest.fixture(autouse=True)
def _a_known_mnemos(monkeypatch):
    from mnemos.setup import state

    monkeypatch.setattr(state, "mnemos_command", lambda: MNEMOS)
    monkeypatch.setattr(cli, "_mnemos_command", lambda: MNEMOS)


@pytest.fixture
def agents(tmp_path, monkeypatch):
    """Fake agent commands on PATH that record how they were run, and an
    agent folder of each kind under the test's home. Returns the call log."""
    folder = tmp_path / "bin"
    folder.mkdir()
    log = tmp_path / "calls.log"
    for command in ("codex", "grok", "gemini", "hermes", "openclaw"):
        script = folder / command
        script.write_text(f'#!/bin/sh\necho "{command} $@" >> "{log}"\nexit 0\n')
        script.chmod(0o755)
    monkeypatch.setenv("PATH", f"{folder}{os.pathsep}{os.environ.get('PATH', '')}")
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex"))
    monkeypatch.setenv("GROK_HOME", str(tmp_path / "grok"))
    monkeypatch.setenv("GEMINI_CLI_HOME", str(tmp_path / "gemini"))
    monkeypatch.setenv("HERMES_HOME", str(Path.home() / ".hermes"))
    monkeypatch.setenv("OPENCLAW_STATE_DIR", str(tmp_path / "openclaw"))
    monkeypatch.setenv("OPENCLAW_CONFIG_PATH", str(tmp_path / "openclaw" / "openclaw.json"))
    return log


def _calls(log: Path) -> list[str]:
    return log.read_text().splitlines() if log.exists() else []


def _out(capsys) -> str:
    return capsys.readouterr().out


# ── The table ──


def test_the_table_has_each_agent_once_and_says_where_each_fact_comes_from():
    keys = [h.key for h in hs.HARNESSES]
    assert len(set(keys)) == len(keys)
    assert {"claude-code", "codex", "grok", "gemini", "hermes", "openclaw", "pi", "muse"} <= set(keys)
    assert "cursor" not in keys
    for h in hs.HARNESSES:
        for ability in (h.mcp, h.wake, h.after_compaction, h.cue):
            assert ability.proof in (hs.SAW, hs.DOCS, hs.UNTESTED)
    # Only what was seen reach a model says "saw it": Grok's hooks were run
    # with a marker and nothing reached the model; Gemini's never were.
    assert hs.get("grok").wake.works is False and hs.get("grok").wake.proof == hs.SAW
    assert hs.get("gemini").wake.proof == hs.UNTESTED and hs.get("gemini").cue.proof == hs.UNTESTED
    assert hs.get("claude").key == "claude-code"


def test_an_agent_is_known_by_what_connect_wrote_then_by_its_handshake(monkeypatch):
    # What the real clients send (Grok, Gemini and OpenClaw read or seen;
    # Hermes sends the SDK's default name, which says nothing).
    for name, key in (
        ("grok-shell-mnemos", "grok"),
        ("gemini-cli-mcp-client", "gemini"),
        ("openclaw-bundle-mcp", "openclaw"),
        ("claude-code", "claude-code"),
    ):
        assert hs.identify(client_name=name, environ={}).key == key
    assert hs.identify(client_name="mcp", environ={}) is None
    assert hs.identify(client_name="", environ={}) is None
    assert hs.identify(client_name="mcp", environ={"MNEMOS_HARNESS": "hermes"}).key == "hermes"
    assert hs.identify(declared="grok", client_name="gemini-cli-mcp-client", environ={}).key == "grok"
    assert hs.identify(environ={"CLAUDECODE": "1"}).key == "claude-code"


# ── Previewing writes nothing; the list reads the machine ──


def test_a_preview_and_the_list_write_nothing(agents, tmp_path, capsys):
    before = sorted(p for p in tmp_path.rglob("*") if p.is_file())
    assert main(["connect"]) == 0
    listing = _out(capsys)
    assert "Gemini CLI: on this machine" in listing and "Pi: not installed here" in listing
    for key in ("codex", "grok", "gemini", "hermes", "openclaw", "pi", "muse"):
        assert main(["connect", key]) == 0
        assert "can read and add to the machine's shared memory" in _out(capsys)
    assert sorted(p for p in tmp_path.rglob("*") if p.is_file()) == before
    assert not (tmp_path / "calls.log").exists()
    assert not (Path.home() / ".mnemos").exists()


def test_the_list_says_what_each_agent_has_and_what_is_missing(agents, capsys):
    assert main(["connect"]) == 0
    listing = _out(capsys)
    grok = listing.split("Grok:")[1].split("Gemini CLI:")[0]
    assert "no Mnemos server yet" in grok or "borrowed" in grok
    assert "can't here" in grok  # its hooks cannot reach the model
    gemini = listing.split("Gemini CLI:")[1].split("Hermes:")[0]
    assert "not set (not tested)" in gemini
    assert "mnemos connect gemini --write" in gemini


# ── Its own memory by default; an existing one stays where it is ──


def test_each_agent_gets_its_own_memory_and_agent_id_shares_one(agents, tmp_path, capsys):
    assert main(["connect", "gemini", "--write", "--no-upkeep"]) == 0
    text = _out(capsys)
    assert "Memory: its own, gemini" in text and str(Path.home() / ".mnemos" / "gemini.db") in text
    call = [c for c in _calls(agents) if c.startswith("gemini mcp add")][0]
    assert "--agent-id gemini" in call and "MNEMOS_HARNESS=gemini" in call

    assert main(["connect", "codex", "--agent-id", "shared", "--write", "--no-upkeep"]) == 0
    call = [c for c in _calls(agents) if c.startswith("codex mcp add")][0]
    assert "--agent-id shared" in call and "shared.db" in call


def test_an_agent_that_already_has_mnemos_keeps_its_memory(agents, tmp_path, capsys):
    codex = tmp_path / "codex"
    codex.mkdir()
    (codex / "config.toml").write_text(
        '[mcp_servers.mnemos]\ncommand = "/old/mnemos"\n'
        'args = ["serve", "--agent-id", "old-codex", "--db-path", "/data/old-codex.db"]\n'
    )
    assert main(["connect", "codex"]) == 0
    text = _out(capsys)
    assert "old-codex" in text and "Left where it is" in text
    # Asking for another memory does not move it.
    assert main(["connect", "codex", "--agent-id", "other", "--write"]) == 1
    assert "I don't move a memory" in _out(capsys)
    assert _calls(agents) == []


# ── Hooks: the cue reaches Codex and Gemini, Grok's can't reach a model ──


def test_connecting_codex_adds_the_server_the_wake_and_the_cue(agents, tmp_path, capsys, os_scheduler):
    assert main(["connect", "codex", "--write"]) == 0
    text = _out(capsys)
    hooks = json.loads((tmp_path / "codex" / "hooks.json").read_text())["hooks"]
    assert set(hooks) == {"SessionStart", "UserPromptSubmit"}
    assert hooks["SessionStart"][0]["matcher"] == "startup|resume|clear|compact"
    assert "--agent-id codex" in hooks["SessionStart"][0]["hooks"][0]["command"]
    assert "open /hooks" in text.lower() or "/hooks" in text
    assert "Upkeep between sessions is on" in text
    assert "Codex can run a memory-only nightly dream" in text
    # And the status now says so, read from the machine.
    st = cn.status(hs.get("codex"), "codex", str(Path.home() / ".mnemos" / "codex.db"))
    assert (st.wake, st.cue) == ("set", "set")


def test_connecting_gemini_says_it_cannot_wake_again_after_compaction(agents, tmp_path, capsys):
    assert main(["connect", "gemini", "--write", "--no-upkeep"]) == 0
    text = _out(capsys)
    settings = json.loads((tmp_path / "gemini" / ".gemini" / "settings.json").read_text())
    assert set(settings["hooks"]) == {"SessionStart", "BeforeAgent"}
    assert "After Gemini CLI compacts a long session, nothing wakes it again" in text
    assert "was not tested on this machine" in text


def test_connecting_grok_installs_no_hook_because_none_reaches_the_model(agents, tmp_path, capsys):
    claude_json = Path.home() / ".claude.json"
    borrowed = json.dumps({"mcpServers": {"mnemos": {
        "command": "/usr/local/bin/mnemos",
        "args": ["serve", "--agent-id", "claude-code", "--db-path", "/data/claude-code.db"],
    }}})
    claude_json.write_text(borrowed)
    claude_settings = Path.home() / ".claude" / "settings.json"
    claude_settings.parent.mkdir()
    claude_settings.write_text("{}")

    assert main(["connect", "grok"]) == 0
    text = _out(capsys)
    # It says plainly that Grok has taken Claude Code's server, and whose memory that is.
    assert "has taken Claude Code's Mnemos server" in text and "claude-code" in text
    assert "GROK_CLAUDE_HOOKS_ENABLED=0" in text
    assert "can't be given its memory before the first message" in text

    assert main(["connect", "grok", "--write", "--no-upkeep"]) == 0
    capsys.readouterr()
    call = [c for c in _calls(agents) if c.startswith("grok mcp add")][0]
    assert "--agent-id grok" in call and "MNEMOS_HARNESS=grok" in call and "claude-code" not in call
    # Claude Code's config is exactly as it was, and Grok got no hooks file.
    assert claude_json.read_text() == borrowed and claude_settings.read_text() == "{}"
    assert not (tmp_path / "grok" / "hooks").exists()


def test_a_grok_with_its_own_server_is_not_borrowing(agents, tmp_path):
    (Path.home() / ".claude.json").write_text(json.dumps({"mcpServers": {"mnemos": {
        "command": "/x/mnemos", "args": ["serve", "--agent-id", "claude-code"]}}}))
    (tmp_path / "grok").mkdir()
    (tmp_path / "grok" / "config.toml").write_text(
        '[mcp_servers.mnemos]\ncommand = "/x/mnemos"\nargs = ["serve", "--agent-id", "grok"]\n'
    )
    st = cn.status(hs.get("grok"), "grok", str(Path.home() / ".mnemos" / "grok.db"))
    assert st.mcp == "set" and st.borrowed is None


def test_grok_does_not_borrow_when_told_not_to(agents, monkeypatch):
    (Path.home() / ".claude.json").write_text(json.dumps({"mcpServers": {"mnemos": {
        "command": "/x/mnemos", "args": ["serve"]}}}))
    monkeypatch.setenv("GROK_CLAUDE_MCPS_ENABLED", "0")
    assert cn.servers(hs.get("grok")) == []


def test_connecting_openclaw_writes_the_server_and_a_wake_hook(agents, tmp_path, capsys):
    assert main(["connect", "openclaw", "--write", "--no-upkeep"]) == 0
    text = _out(capsys)
    calls = _calls(agents)
    assert any(c.startswith("openclaw mcp set mnemos") and "MNEMOS_HARNESS" in c for c in calls)
    assert any(c == "openclaw hooks enable mnemos-wake" for c in calls)
    folder = tmp_path / "openclaw" / "hooks" / "mnemos-wake"
    handler = (folder / "handler.js").read_text()
    assert "agent" in handler and "bootstrap" in handler and "openclaw.db" in handler
    assert (folder / "HOOK.md").read_text().startswith("---\nname: mnemos-wake")
    assert "gateway restart" in text and "was not tested" in text


# ── Pi and Muse: printed, marked untested, nothing installed ──


@pytest.mark.parametrize("key", ["pi", "muse"])
def test_pi_and_muse_print_their_setup_marked_untested(key, agents, tmp_path, capsys):
    assert main(["connect", key, "--write"]) == 0
    text = _out(capsys)
    assert "NOT TESTED" in text and "Nothing is written" in text
    assert "mnemos_context" in text
    assert _calls(agents) == [] and not (Path.home() / ".mnemos").exists()


# ── Hermes: provider mode where the slot is free, tools only where it isn't ──


@pytest.mark.parametrize(
    "memory_block, mode, activates",
    [
        ("", "provider", True),
        ("memory:\n  provider: honcho\n", "sidecar", False),
        ("memory:\n  provider: mnemos\n", "provider", True),
    ],
)
def test_connect_hermes_respects_the_memory_provider_slot(
    memory_block, mode, activates, agents, tmp_path, monkeypatch, capsys
):
    from mnemos.integrations.hermes import installer

    monkeypatch.setitem(sys.modules, "yaml", None)
    home = Path.home() / ".hermes"
    home.mkdir()
    (home / "config.yaml").write_text("model:\n  provider: openai-codex\n" + memory_block)
    seen = {}

    class Done:
        warnings: list = []

        def summary(self):
            return "stub summary"

    def fake_install(**kwargs):
        seen.update(kwargs)
        return Done()

    monkeypatch.setattr(installer, "install_hermes_plugin", fake_install)
    assert main(["connect", "hermes", "--write", "--no-upkeep"]) == 0
    if mode == "sidecar":
        assert seen["mode"] == "sidecar" and seen["activate"] is False and seen["agent_safe"] is True
        assert "memory provider is honcho" in capsys.readouterr().out
    else:
        assert seen["mode"] == "provider" and seen["activate"] is activates
    # A provider carries its tools; only with another in the slot is a server how it has them.
    assert seen["configure_mcp"] is (mode == "sidecar") and seen["agent_id"] == "hermes"


def test_agent_safe_leaves_the_hermes_provider_alone(agents, tmp_path, monkeypatch):
    from mnemos.integrations.hermes import installer

    seen = {}

    class Done:
        warnings: list = []

        def summary(self):
            return ""

    monkeypatch.setattr(installer, "install_hermes_plugin", lambda **kw: seen.update(kw) or Done())
    assert main(["connect", "hermes", "--agent-safe", "--write", "--no-upkeep"]) == 0
    assert seen["mode"] == "sidecar" and seen["activate"] is False


def test_hermes_wake_counts_only_for_the_memory_its_provider_names(agents, tmp_path):
    from mnemos.integrations.hermes import installer

    home = Path.home() / ".hermes"
    home.mkdir()
    (home / "config.yaml").write_text("memory:\n  provider: mnemos\n")
    (home / "mnemos.json").write_text(json.dumps({"agent_id": "hermes", "db_path": str(tmp_path / "h.db")}))
    plugin = installer.provider_plugin_dirs(home)[0]
    plugin.mkdir(parents=True)
    (plugin / "__init__.py").write_text(installer.render_plugin_shim())
    here = cn.status(hs.get("hermes"), "hermes", str(tmp_path / "h.db"))
    other = cn.status(hs.get("hermes"), "someone-else", str(tmp_path / "x.db"))
    assert here.wake == "set" and other.wake == "missing"
    assert here.mcp == "provider" and other.mcp == "elsewhere"

    # Named in the config, with no plugin there to load, nothing wakes it.
    (plugin / "__init__.py").unlink()
    assert cn.status(hs.get("hermes"), "hermes", str(tmp_path / "h.db")).wake == "missing"


# ── The retired OpenClaw cron jobs ──


def test_setup_openclaw_is_retired_and_registers_nothing(tmp_path, capsys):
    jobs = tmp_path / "cron" / "jobs.json"
    assert main(["setup-openclaw"]) == 1
    err = capsys.readouterr().err
    assert "retired" in err and "mnemos connect openclaw" in err
    assert "mnemos_consolidate" in err and not jobs.exists()


# ── The first session says what is true for the agent that reads it ──


def test_the_first_session_in_grok_says_it_wakes_by_mnemos_context_and_has_no_quiet_hours(agents, tmp_path):
    runtime = MnemosRuntime(db_path=str(tmp_path / "m.db"), agent_id="zed", use_dedicated_model=False)
    runtime.client_name = "grok-shell-mnemos"
    try:
        packet = runtime.context()
    finally:
        runtime.close()
    assert "Grok can't load your memory before the first message" in packet
    assert "call mnemos_context yourself" in packet
    assert "no hour runs by itself in Grok" in packet and "Quiet hours: no one has asked" not in packet
    assert "goes to xAI" in packet and "life --hour mine --handoff" in packet
    assert "use some of its usage" not in packet and "goes to Anthropic" not in packet
    assert "connect grok --write" in packet  # upkeep is not scheduled yet
    assert "1. Ask what they would like you to call them." in packet  # the ritual is as it was


def test_the_first_session_names_the_exact_command_for_gemini(agents, tmp_path):
    runtime = MnemosRuntime(db_path=str(tmp_path / "m.db"), agent_id="zed", use_dedicated_model=False)
    runtime.client_name = "gemini-cli-mcp-client"
    try:
        packet = runtime.context()
    finally:
        runtime.close()
    line = f"{MNEMOS} --agent-id zed --db-path {tmp_path / 'm.db'} connect gemini --write"
    assert line in packet
    assert "waking with this memory, and the memories that bear on each message" in packet


def test_an_agent_that_cannot_be_told_is_told_so_and_pointed_at_connect(agents, tmp_path):
    runtime = MnemosRuntime(db_path=str(tmp_path / "m.db"), agent_id="zed", use_dedicated_model=False)
    runtime.client_name = "some-other-client"
    try:
        packet = runtime.context()
    finally:
        runtime.close()
    assert "I can't tell which agent you are running in" in packet
    assert f"--agent-id zed --db-path {tmp_path / 'm.db'} connect\n" in packet
    assert "I can't say what they would cost" in packet and "don't offer them" in packet


def test_no_client_at_all_changes_nothing_about_the_ritual(agents, tmp_path):
    runtime = MnemosRuntime(db_path=str(tmp_path / "m.db"), agent_id="zed", use_dedicated_model=False)
    try:
        packet = runtime.context()
    finally:
        runtime.close()
    assert "can't tell which agent" not in packet and "Quiet hours" not in packet


def test_hermes_is_known_by_what_connect_wrote_into_its_server(agents, tmp_path, monkeypatch):
    monkeypatch.setenv("MNEMOS_HARNESS", "hermes")
    runtime = MnemosRuntime(db_path=str(tmp_path / "m.db"), agent_id="zed", use_dedicated_model=False)
    runtime.client_name = "mcp"  # all Hermes sends
    try:
        packet = runtime.context()
    finally:
        runtime.close()
    assert "Not set up yet for Hermes" in packet


# ── The handshake really reaches the server ──


def test_the_clients_name_in_the_handshake_reaches_the_first_session(agents, tmp_path):
    """Over a real stdio MCP connection: what the client calls itself in
    `initialize` decides which agent the first session talks to."""
    from mcp import ClientSession, StdioServerParameters, types
    from mcp.client.stdio import stdio_client

    async def first(name: str) -> str:
        env = {k: v for k, v in os.environ.items() if k not in ("CLAUDECODE", "AI_AGENT", "MNEMOS_HARNESS")}
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "mnemos.cli", "serve", "--agent-id", "zed", "--db-path", str(tmp_path / f"{name}.db")],
            env=env,
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(
                read, write, client_info=types.Implementation(name=name, version="1")
            ) as session:
                await session.initialize()
                result = await session.call_tool("mnemos_context", {})
                return result.content[0].text

    assert "Grok can't load your memory" in asyncio.run(first("grok-shell-mnemos"))
    assert "Not set up yet for Gemini CLI" in asyncio.run(first("gemini-cli-mcp-client"))


# ── And the way out ──


def test_uninstall_takes_out_what_connect_put_in_and_only_that(agents, tmp_path, capsys):
    """Connect Gemini and OpenClaw, then uninstall: their hooks and hook folder
    go, the agents are asked to forget Mnemos's server, and someone else's
    hook in the same file stays."""
    gemini_settings = tmp_path / "gemini" / ".gemini" / "settings.json"
    assert main(["connect", "gemini", "--write", "--no-upkeep"]) == 0
    assert main(["connect", "openclaw", "--write", "--no-upkeep"]) == 0
    data = json.loads(gemini_settings.read_text())
    mine = {"hooks": [{"type": "command", "command": "echo mine"}]}
    data["hooks"]["BeforeAgent"].append(mine)
    data["mcpServers"] = {"mnemos": {"command": MNEMOS, "args": ["serve"]}}
    gemini_settings.write_text(json.dumps(data))
    # Servers the agents themselves hold; the fake commands do not edit configs.
    (tmp_path / "openclaw" / "openclaw.json").write_text(json.dumps(
        {"mcp": {"servers": {"mnemos": {"command": MNEMOS, "args": ["serve"]}}}}
    ))
    capsys.readouterr()
    agents.write_text("")

    assert main(["uninstall", "--write"]) == 0
    capsys.readouterr()
    assert json.loads(gemini_settings.read_text())["hooks"] == {"BeforeAgent": [mine]}
    assert not (tmp_path / "openclaw" / "hooks" / "mnemos-wake").exists()
    calls = _calls(agents)
    assert "gemini mcp remove --scope user mnemos" in calls
    assert "openclaw mcp unset mnemos" in calls and "openclaw hooks disable mnemos-wake" in calls
    # Grok had no server of its own here, so nothing was asked of it.
    assert not any(c.startswith("grok ") for c in calls)
