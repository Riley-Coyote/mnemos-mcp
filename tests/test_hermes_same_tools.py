"""A Hermes agent in Provider Mode has the tools every other agent has, by the
same names.

Until 0.6.4 the provider offered four of its own under other names. What it woke
with, its first session's questions and its memory's own questions named the real
ones, which it didn't have. Its capture took no ``standing``, ``impact`` or
``signed_as``, so "always remember this" faded like anything else, and every save
went unsigned, which kept its first session's questions coming.
"""

from __future__ import annotations

import json
import re
import sqlite3
import subprocess
import sys
import types
import urllib.request

import pytest

from mnemos.integrations.hermes import HermesMnemosConfig, MnemosMemoryProviderCore
from mnemos.integrations.hermes import installer
from mnemos.integrations.hermes import provider as provider_module
from mnemos.integrations.hermes.tools import TOOL_SCHEMAS
from mnemos.setup import state
from mnemos.simple_mcp import plain_tool_schemas
from mnemos.simple_tools import SERVER_INSTRUCTIONS

HOST_MODEL = "anthropic/claude-opus-4.7"
NAMES = {tool["name"] for tool in TOOL_SCHEMAS}


def _provider(tmp_path, name: str = "a", **init) -> MnemosMemoryProviderCore:
    provider = MnemosMemoryProviderCore(
        HermesMnemosConfig(
            db_path=str(tmp_path / f"{name}.db"),
            agent_id=name,
            person_id="user",
            project_scope="global",
            deep_maintenance=False,
        )
    )
    provider.initialize("session-1", hermes_home=str(tmp_path), platform="cli", **init)
    return provider


def _call(provider: MnemosMemoryProviderCore, tool: str, **args) -> str:
    reply = json.loads(provider.handle_tool_call(tool, args))
    assert reply["ok"], reply
    return reply["result"]


def _row(tmp_path, content: str, name: str = "a") -> sqlite3.Row:
    conn = sqlite3.connect(tmp_path / f"{name}.db")
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute("SELECT * FROM engrams WHERE content = ?", (content,)).fetchone()
    finally:
        conn.close()


# ── The same tools ──


def test_they_are_every_agents_tools():
    # What the MCP server offers today, but for the wake the provider does itself.
    live = {tool["name"]: tool for tool in plain_tool_schemas() if tool["name"] != "mnemos_context"}
    assert {tool["name"]: tool for tool in TOOL_SCHEMAS} == live, "run scripts/generate_hermes_tools.py"


def test_every_tool_is_handled_and_every_handler_offered():
    assert set(provider_module._TOOLS) == NAMES


def test_the_rule_about_waking_is_the_one_replaced():
    # If the rule's words change, this says the provider's copy of them is stale.
    assert provider_module._RULE_ONE in SERVER_INSTRUCTIONS
    assert "mnemos_context" not in provider_module._RULES_HERE


def test_what_it_wakes_with_names_only_tools_it_has(tmp_path):
    provider = _provider(tmp_path)
    try:
        wake = provider.system_prompt_block()
    finally:
        provider.shutdown()
    assert "ONBOARDING" in wake and "mnemos_introduce" in wake
    assert set(re.findall(r"\bmnemos_[a-z_]+\b", wake)) <= NAMES


def test_hermes_own_python_needs_no_mcp_library():
    code = (
        "import sys\n"
        "sys.modules['mcp'] = None\n"
        "from mnemos.integrations.hermes import MnemosMemoryProviderCore as Core\n"
        "print(len(Core().get_tool_schemas()), 'mnemos.simple_mcp' in sys.modules)\n"
    )
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    assert done.stdout.split() == [str(len(NAMES)), "False"]


def test_the_manifest_lists_them():
    yaml = pytest.importorskip("yaml")
    manifest = yaml.safe_load(installer.render_plugin_manifest())
    assert set(manifest["provides_tools"]) == NAMES


def test_a_bad_call_comes_back_as_an_answer(tmp_path):
    provider = _provider(tmp_path)
    try:
        unknown = json.loads(provider.handle_tool_call("mnemos_identity_capture", {"content": "x"}))
        empty = json.loads(provider.handle_tool_call("mnemos_capture", {}))
    finally:
        provider.shutdown()
    assert unknown["ok"] is False and "Unknown" in unknown["error"]
    assert empty["ok"] is False and empty["tool"] == "mnemos_capture"


@pytest.mark.parametrize(("asked", "rows"), [(30, 30), (99, 50), ("many", 16)])
def test_recall_asks_for_as_many_rows_as_the_server_allows(tmp_path, monkeypatch, asked, rows):
    """Up to 50, as the tool's own words say; a number that can't be read gets
    the default, not the most."""
    provider = _provider(tmp_path)
    seen: dict = {}
    try:
        monkeypatch.setattr(provider._runtime, "recall", lambda query, **options: seen.update(options) or "")
        _call(provider, "mnemos_recall", query="harbour tide", max_results=asked)
    finally:
        provider.shutdown()
    assert seen["max_results"] == rows


# ── What used to be dropped ──


def test_always_remember_stays_and_what_it_taught_is_kept(tmp_path):
    words = "Always keep the staging box wiped on Fridays."
    taught = "I see now why Fridays belong to staging."
    provider = _provider(tmp_path)
    try:
        said = _call(provider, "mnemos_capture", content=words, standing=True, impact=taught, signed_as="gpt-5.5")
        standing = _call(provider, "mnemos_recall", query="", standing=True)
    finally:
        provider.shutdown()
    row = _row(tmp_path, words)
    assert row["standing"] and row["impact"] == taught and row["author_model"] == "gpt-5.5"
    assert "Standing: yes" in said and words in standing


def test_the_shared_flag_reaches_the_shared_memory(tmp_path, monkeypatch):
    monkeypatch.setenv("MNEMOS_SHARED_MEMORY_DB", str(tmp_path / "shared.db"))
    monkeypatch.delenv("MNEMOS_SHARED_MEMORY", raising=False)
    words = "Everyone on this machine should know the backups run at noon."
    provider = _provider(tmp_path)
    try:
        _call(provider, "mnemos_capture", content=words, shared=True)
        found = _call(provider, "mnemos_recall", query="backups noon")
    finally:
        provider.shutdown()
    assert words in found and _row(tmp_path, words) is None


# ── Who wrote it ──


def test_the_model_hermes_names_signs_what_is_written(tmp_path):
    provider = _provider(tmp_path, model=HOST_MODEL)
    try:
        said = _call(provider, "mnemos_capture", content="The shop boiler was replaced this spring.")
        _call(provider, "mnemos_capture", content="The lease renews in June.", signed_as="gpt-5.5")
        provider.on_turn_start(2, "hello", model="openrouter/qwen-3")
        _call(provider, "mnemos_capture", content="The van needs new tyres.")
    finally:
        provider.shutdown()
    assert "Opus 4.7" in said
    assert _row(tmp_path, "The shop boiler was replaced this spring.")["author_model"] == HOST_MODEL
    assert _row(tmp_path, "The lease renews in June.")["author_model"] == "gpt-5.5"
    assert _row(tmp_path, "The van needs new tyres.")["author_model"] == "openrouter/qwen-3"


def test_a_host_that_says_nothing_leaves_it_to_the_agent(tmp_path):
    # Hermes before autumn 2026 passes no model. Nothing is made up in its place.
    provider = _provider(tmp_path)
    try:
        provider.on_turn_start(1, "hello")
        _call(provider, "mnemos_introduce", agent_model=HOST_MODEL)
        _call(provider, "mnemos_capture", content="The kiln fires on Tuesdays.")
    finally:
        provider.shutdown()
    assert _row(tmp_path, "The kiln fires on Tuesdays.")["author_model"] == HOST_MODEL


def test_the_first_sessions_questions_end(tmp_path):
    provider = _provider(tmp_path, model=HOST_MODEL)
    try:
        assert "ONBOARDING" in provider.system_prompt_block()
        _call(provider, "mnemos_capture", content="They like to be called Sam.")
        _call(provider, "mnemos_introduce", agent_model=HOST_MODEL)
        assert "ONBOARDING" not in provider.system_prompt_block()
    finally:
        provider.shutdown()


# ── The page ──


def test_the_page_opens_once_for_a_memory(tmp_path):
    first, second = _provider(tmp_path), _provider(tmp_path)
    try:
        said = _call(first, "mnemos_page")
        url = re.search(r"http://127\.0\.0\.1:\d+/\S+", said).group()
        assert url in _call(second, "mnemos_page")
        with urllib.request.urlopen(url, timeout=10) as answer:
            assert answer.status == 200
    finally:
        first.shutdown()
        second.shutdown()
        for page in provider_module._pages.values():
            page.shutdown()
            page.server_close()
        provider_module._pages.clear()


# ── Room for many conversations ──


pytest.importorskip("resource")

_RAISE = """
import resource, sys
soft, hard = {start}
resource.setrlimit(resource.RLIMIT_NOFILE, (soft, hard))
from mnemos.integrations.hermes import HermesMnemosConfig, MnemosMemoryProviderCore
core = MnemosMemoryProviderCore(HermesMnemosConfig(
    db_path=sys.argv[1], agent_id="a", person_id="user", project_scope="global", deep_maintenance=False,
))
core.initialize("s", hermes_home=sys.argv[2], platform="cli")
core.shutdown()
print(resource.getrlimit(resource.RLIMIT_NOFILE)[0])
"""


def _soft_after_start(tmp_path, start: str) -> int:
    done = subprocess.run(
        [sys.executable, "-c", _RAISE.format(start=start), str(tmp_path / "a.db"), str(tmp_path)],
        capture_output=True, text=True, timeout=120,
    )
    assert done.returncode == 0, done.stderr
    return int(done.stdout.strip().splitlines()[-1])


def test_a_mac_start_asks_for_room_to_hold_its_files(tmp_path):
    import resource

    hard = resource.getrlimit(resource.RLIMIT_NOFILE)[1]
    wanted = 4096 if hard == resource.RLIM_INFINITY else min(4096, hard)
    assert _soft_after_start(tmp_path, "256, resource.getrlimit(resource.RLIMIT_NOFILE)[1]") == wanted


def test_it_goes_no_higher_than_the_ceiling(tmp_path):
    assert _soft_after_start(tmp_path, "256, 512") == 512


def test_it_never_lowers_what_is_already_higher(tmp_path):
    import resource

    hard = resource.getrlimit(resource.RLIMIT_NOFILE)[1]
    if hard != resource.RLIM_INFINITY and hard < 5000:
        pytest.skip("this machine's ceiling is below the test's start")
    assert _soft_after_start(tmp_path, "5000, resource.getrlimit(resource.RLIMIT_NOFILE)[1]") == 5000


def test_where_there_is_no_such_limit_nothing_breaks(monkeypatch):
    monkeypatch.setattr(provider_module, "_resource", None)
    monkeypatch.setattr(provider_module, "_open_files_seen", False)
    provider_module._make_room_for_files()


# ── From a shell ──


def _shell_tool(capsys, tmp_path, name: str, arguments: str | None = None, **stdin) -> tuple[int, str, str]:
    from mnemos.cli import main

    words = ["hermes", "tool", name]
    if arguments is not None:
        words.append(arguments)
    words += ["--db-path", str(tmp_path / "a.db"), "--agent-id", "a", "--person-id", "user", "--project-scope", "global"]
    code = main(words)
    said = capsys.readouterr()
    return code, said.out, said.err


def test_a_job_with_no_provider_has_the_same_tools_from_its_shell(tmp_path, capsys, monkeypatch):
    # Hermes from before September 2026 runs a job without its memory provider.
    code, out, err = _shell_tool(capsys, tmp_path, "mnemos_capture", json.dumps(
        {"content": "A thought from my quiet hour.", "standing": True, "signed_as": "gpt-5.5"}
    ))
    assert code == 0, err
    assert "Captured continuity" in out and "Signed: GPT" in out or "gpt-5.5" in out
    row = _row(tmp_path, "A thought from my quiet hour.")
    assert row["standing"] and row["author_model"] == "gpt-5.5"

    monkeypatch.setattr(sys, "stdin", types.SimpleNamespace(read=lambda: '{"query": "quiet hour"}\n'))
    code, out, err = _shell_tool(capsys, tmp_path, "mnemos_recall")
    assert code == 0 and "A thought from my quiet hour." in out, err


def test_what_goes_wrong_there_says_so(tmp_path, capsys):
    code, out, err = _shell_tool(capsys, tmp_path, "mnemos_capture", "not json")
    assert code == 1 and "aren't JSON" in err
    code, out, err = _shell_tool(capsys, tmp_path, "mnemos_capture", "[1]")
    assert code == 1 and "JSON object" in err
    code, out, err = _shell_tool(capsys, tmp_path, "mnemos_nothing", "{}")
    assert code == 1 and "Unknown" in err


# ── The command it is told to run ──


def test_the_command_is_found_from_inside_hermes_own_python(tmp_path, monkeypatch):
    # Inside Hermes, argv[0] and the interpreter's folder are Hermes', and its
    # shell may not have Mnemos on its path at all.
    monkeypatch.setattr(sys, "argv", [str(tmp_path / "hermes")])
    monkeypatch.setattr(sys, "executable", str(tmp_path / "venv" / "bin" / "python"))
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.delenv("MNEMOS_COMMAND", raising=False)
    assert state.mnemos_command() == "mnemos"
    monkeypatch.setenv("MNEMOS_COMMAND", "/opt/mnemos/bin/mnemos")
    assert state.mnemos_command() == "/opt/mnemos/bin/mnemos"


def test_the_plugin_tells_hermes_where_the_command_is(monkeypatch):
    registered = []
    agent = types.ModuleType("agent")
    memory = types.ModuleType("agent.memory_provider")
    memory.MemoryProvider = object
    monkeypatch.setitem(sys.modules, "agent", agent)
    monkeypatch.setitem(sys.modules, "agent.memory_provider", memory)
    monkeypatch.setenv("MNEMOS_COMMAND", "placeholder")
    monkeypatch.delenv("MNEMOS_COMMAND")
    monkeypatch.setattr(state, "mnemos_command", lambda: "/opt/mnemos/bin/mnemos")
    monkeypatch.setattr(installer, "mnemos_command", lambda: "/opt/mnemos/bin/mnemos")

    namespace: dict = {}
    exec(installer.render_plugin_shim(), namespace)  # noqa: S102 - the file we write, as Hermes loads it
    namespace["register"](types.SimpleNamespace(register_memory_provider=registered.append))

    assert registered and registered[0].name == "mnemos"
    import os

    assert os.environ["MNEMOS_COMMAND"] == "/opt/mnemos/bin/mnemos"


def test_words_about_recall_are_kept_whole(tmp_path):
    # Everything after "Mnemos recall" used to go, with ok true.
    provider = _provider(tmp_path)
    said = "We agreed the Mnemos recall threshold stays at 0.4 until the lab says otherwise."
    try:
        assert json.loads(provider.handle_tool_call("mnemos_capture", {"content": said}))["ok"]
        recalled = json.loads(provider.handle_tool_call("mnemos_recall", {"query": "recall threshold"}))["result"]
        assert "until the lab says otherwise" in recalled
    finally:
        provider.shutdown()


@pytest.mark.parametrize("words", [
    "Mnemos recall is slow on this machine.",
    "What's the Mnemos Identity Continuity heading for?",
    "See the notes:\n# Mnemos recall tuning, part two\nlower it after the test.",
])
def test_a_person_or_agent_can_say_these_words(words):
    assert provider_module._clean_text(words) == words


@pytest.mark.parametrize("pasted, left", [
    ("# Mnemos Recall\n- [2026-11-01] an older memory", ""),
    ("my own words\n\n# Mnemos Recall\n- [2026-11-01] an older memory", "my own words"),
    ("# Mnemos Identity Continuity\nthe whole wake\nof many lines", ""),
])
def test_what_the_provider_put_in_a_message_still_comes_off(pasted, left):
    assert provider_module._clean_text(pasted) == left


def test_what_comes_with_a_message_says_it_isnt_a_search(tmp_path):
    # Headed "recall", it read as a search already done: asked to check its memory, an agent
    # took it for the answer and said it had nothing about what was in shared memory.
    provider = _provider(tmp_path)
    try:
        provider.handle_tool_call("mnemos_capture", {"content": "The kiln at the studio fires on Tuesdays."})
        block = provider.prefetch("when does the kiln fire?")
        wake = provider.system_prompt_block()
    finally:
        provider.shutdown()
    assert block.startswith("# Mnemos: from memory, maybe bearing on this message\n")
    assert "mnemos_recall searches" in block and "shared memory" in block
    assert "fires on Tuesdays" in block and "Mnemos recall for" not in block
    assert "to look for something, use mnemos_recall" in wake
    # And it comes off a message the way the rest of what the provider adds does.
    assert provider_module._clean_text(f"my own words\n\n{block}") == "my own words"
