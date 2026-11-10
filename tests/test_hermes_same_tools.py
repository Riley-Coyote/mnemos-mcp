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


def _page_address(said: str) -> str:
    return re.search(r"http://127\.0\.0\.1:\d+/\S+", said).group()


def _answers(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=10) as answer:
            return answer.status == 200
    except OSError:
        return False


def _close_pages() -> None:
    for page in list(provider_module._pages.values()):
        page.shutdown()
        page.server_close()
    provider_module._pages.clear()
    provider_module._page_holders.clear()
    provider_module._pages_closing.clear()


def test_the_page_opens_once_for_a_memory(tmp_path):
    first, second = _provider(tmp_path), _provider(tmp_path)
    try:
        url = _page_address(_call(first, "mnemos_page"))
        assert url in _call(second, "mnemos_page")
        assert _answers(url)
    finally:
        first.shutdown()
        second.shutdown()
        _close_pages()


def _page_act(url: str, agent: str, **request) -> dict:
    """What the page's own script sends when the person writes on it, for the mind it is showing."""
    base = url.rsplit("/log/", 1)[0]
    port = re.search(r":(\d+)/", url).group(1)
    asked = urllib.request.Request(
        f"{base}/act?agent={agent}", data=json.dumps(request).encode(), method="POST",
        headers={"Content-Type": "application/json", "Origin": f"http://127.0.0.1:{port}"},
    )
    try:
        with urllib.request.urlopen(asked, timeout=10) as answer:
            return json.loads(answer.read())
    except urllib.error.HTTPError as refused:
        return json.loads(refused.read())


def _held(path) -> list[tuple]:
    """Every memory and note a store holds, to see that nothing in it moved."""
    conn = sqlite3.connect(path)
    try:
        return [
            *conn.execute("SELECT id, content, state FROM engrams ORDER BY id").fetchall(),
            *(conn.execute("SELECT * FROM notes ORDER BY 1").fetchall()
              if conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'notes'").fetchone() else []),
        ]
    finally:
        conn.close()


def test_a_hermes_agents_page_writes_in_no_other_agents_memory(tmp_path, monkeypatch):
    """The page shows the other agents whose memory is kept beside this one's,
    and the plugin's README and catalog entry said it only read them. It wrote
    in them too: a note, a correction, a memory let go, in the memory of an
    agent Hermes doesn't run, and in the shared memory, where it could let go
    of what another agent had shared (Nous's review of the catalog entry,
    2026-11-09). Inside Hermes it reads them, and writes in its own."""
    from mnemos import llm

    shared = tmp_path / "shared.db"
    monkeypatch.setenv("MNEMOS_SHARED_MEMORY_DB", str(shared))
    monkeypatch.delenv("MNEMOS_SHARED_MEMORY", raising=False)
    mine, other = _provider(tmp_path, "a"), _provider(tmp_path, "b")
    try:
        _call(mine, "mnemos_capture", content="The kiln at the studio fires on Tuesdays.")
        _call(other, "mnemos_capture", content="The glaze room is locked after six.")
        _call(other, "mnemos_capture", content="Everyone should know the studio closes at nine.", shared=True)
        theirs = _row(tmp_path, "The glaze room is locked after six.", "b")["id"]
        conn = sqlite3.connect(shared)
        (shared_id,) = conn.execute("SELECT id FROM engrams").fetchone()
        conn.close()
        llm.take_secrets_from(lambda name, default=None: default)  # inside Hermes, as its provider says at its start
        url = _page_address(_call(mine, "mnemos_page"))
        base = url.rsplit("/log/", 1)[0]

        with urllib.request.urlopen(f"{base}/data/memories.json?agent=b", timeout=10) as shown:
            assert "glaze room" in shown.read().decode(), "the other agent's memory is no longer shown"

        before = _held(tmp_path / "b.db"), _held(shared)
        for asked in (
            {"command": "note", "text": "Left through another agent's page."},
            {"command": "correct", "memory_id": theirs, "text": "The glaze room is never locked."},
            {"command": "forget", "memory_id": theirs, "confirmed": True},
            {"command": "read", "note_ids": ["any"]},
        ):
            refused = _page_act(url, "b", **asked)
            assert "only reads your other agents' memories" in refused.get("error", ""), (asked, refused)
        for asked in (
            {"action": "add", "text": "Written into the shared memory from a Hermes page."},
            {"action": "correct", "memory_id": shared_id, "text": "The studio never closes."},
            {"action": "forget", "memory_id": shared_id, "confirmed": True},
        ):
            for agent in ("a", "b"):  # whichever mind the page is showing
                refused = _page_act(url, agent, command="shared", **asked)
                assert "only reads the shared memory" in refused.get("error", ""), (asked, refused)
        assert (_held(tmp_path / "b.db"), _held(shared)) == before, "the page wrote outside its own agent's memory"

        own = _page_act(url, "a", command="note", text="Left on my own agent's page.")
        assert own.get("result", {}).get("text") == "Left on my own agent's page.", own
    finally:
        mine.shutdown()
        other.shutdown()
        _close_pages()


def test_anywhere_else_the_page_is_the_persons_over_all_of_it(tmp_path, monkeypatch):
    """Outside Hermes the page is the person's own, as it was: they write in
    any of their agents' memories, and in the shared one."""
    from mnemos import llm
    from mnemos.companion.server import open_page

    monkeypatch.setenv("MNEMOS_SHARED_MEMORY_DB", str(tmp_path / "shared.db"))
    monkeypatch.delenv("MNEMOS_SHARED_MEMORY", raising=False)
    for name, words in (("a", "The kiln fires on Tuesdays."), ("b", "The glaze room is locked after six.")):
        provider = _provider(tmp_path, name)
        _call(provider, "mnemos_capture", content=words)
        provider.shutdown()
    llm.take_secrets_from(None)  # no host hands out the keys: an agent's own server, or `mnemos page`
    said, page = open_page({"db_path": str(tmp_path / "a.db"), "agent_id": "a",
                            "person_id": "user", "project_scope": "global"})
    try:
        url = _page_address(said)
        there = _page_act(url, "b", command="note", text="Left through another agent's page.")
        assert there.get("result", {}).get("text") == "Left through another agent's page.", there
        added = _page_act(url, "a", command="shared", action="add", text="The studio closes at nine.")
        assert "result" in added, added
    finally:
        page.shutdown()
        page.server_close()


def test_a_hermes_agents_page_looks_at_nothing_else_on_the_machine(tmp_path, monkeypatch):
    """To say whether quiet hours were scheduled, the page read every
    LaunchAgent, systemd unit and crontab line of the person's, ran
    ``launchctl``, ``systemctl`` and ``crontab`` to ask, and looked for Jev's
    key file, each time it was read, while the plugin's README said it started
    no other program. Inside Hermes the hours and Jev aren't set from the page,
    and it looks for none of it."""
    from mnemos import jev, llm
    from mnemos.companion import export

    looked: list[str] = []

    def seen(what, answer):
        def look(*args, **kwargs):
            looked.append(what)
            return answer
        return look

    nowhere = tmp_path / "nowhere"
    monkeypatch.setattr(export, "_launch_agents", seen("LaunchAgents", nowhere))
    monkeypatch.setattr(export, "_systemd_units", seen("systemd units", nowhere))
    monkeypatch.setattr(export, "_crontab", seen("crontab", ""))
    monkeypatch.setattr(export.subprocess, "run", seen("a program", None))
    monkeypatch.setattr(jev, "status", seen("Jev's key", {
        "switched_on": False, "key": False, "host": "", "message_chars": 0, "candidates": 0, "line_chars": 0,
    }))

    provider = _provider(tmp_path)
    try:
        _call(provider, "mnemos_capture", content="The kiln at the studio fires on Tuesdays.")
        llm.take_secrets_from(lambda name, default=None: default)  # inside Hermes
        _call(provider, "mnemos_page")
        (page,) = provider_module._pages.values()
        life = json.loads(page.documents()[0])
        assert life["schedule"] == [] and life["jev"] == {"on": False, "key": False, "env": False}
        assert looked == [], f"the page looked at {looked}"

        llm.take_secrets_from(None)  # anywhere else the page says what runs the hours, as before
        page._home.forget()
        json.loads(page.documents()[0])
        assert {"LaunchAgents", "systemd units", "crontab", "Jev's key"} <= set(looked), looked
    finally:
        provider.shutdown()
        _close_pages()


def test_the_pages_own_threads_read_none_of_hermes_keys(tmp_path):
    """Hermes binds a profile's keys to the task it runs for that profile. The
    page answers a browser on threads of its own, outside every one, where a
    read falls back to the process's own environment: on a process serving
    several profiles, the keys and the choice of provider of the profile it
    was started for. A search or a correction on the page read them there, and
    would have sent one profile's words out on another's key. The page's
    threads read none."""
    import threading

    from mnemos import llm

    read: list[tuple[str, str]] = []

    def hermes_says(name, default=None):
        read.append((name, threading.current_thread().name))
        return {"MNEMOS_EMBEDDING_PROVIDER": "gemini", "GEMINI_API_KEY": "the-launch-profiles",
                "MNEMOS_LLM_PROVIDER": "openrouter", "OPENROUTER_API_KEY": "the-launch-profiles"}.get(name, default)

    provider = _provider(tmp_path)
    try:
        _call(provider, "mnemos_capture", content="The kiln at the studio fires on Tuesdays.")
        mine = _row(tmp_path, "The kiln at the studio fires on Tuesdays.")["id"]
        llm.take_secrets_from(hermes_says)
        url = _page_address(_call(provider, "mnemos_page"))
        base = url.rsplit("/log/", 1)[0]
        read.clear()

        with urllib.request.urlopen(f"{base}/data/search.json?q=kiln", timeout=30) as found:
            assert found.status == 200
        corrected = _page_act(url, "a", command="correct", memory_id=mine, text="The kiln fires on Wednesdays.")
        assert "result" in corrected, corrected
        noted = _page_act(url, "a", command="note", text="Left on my own agent's page.")
        assert "result" in noted, noted
        (page,) = provider_module._pages.values()
        for mind in (page._home, *page.others().values()):
            if mind.interface is not None:
                mind.interface._loaded()  # the search's own thread, if it started one
        assert read == [], f"the page's threads read {sorted(set(read))}"

        # The conversation's own calls still read them, for the profile Hermes runs them for.
        _call(provider, "mnemos_health")
        llm.chosen_provider()
        assert ("MNEMOS_LLM_PROVIDER", threading.current_thread().name) in read
    finally:
        provider.shutdown()
        _close_pages()


def test_the_page_closes_when_its_conversations_have_ended_and_it_is_left_alone(tmp_path, monkeypatch):
    """A page an agent opened was served for as long as Hermes ran: on a gateway,
    for days after the conversation that opened it had ended (Nous's review of
    the catalog entry, 2026-11-09). It stays while a conversation that opened it
    goes on, and while somebody has it open, and then closes."""
    import time

    # A second, so a slow machine's pause between two asks isn't taken for leaving.
    monkeypatch.setattr(provider_module, "_PAGE_LEFT_ALONE_SECONDS", 1.0)
    first, second = _provider(tmp_path), _provider(tmp_path)
    try:
        url = _page_address(_call(first, "mnemos_page"))
        assert url in _call(second, "mnemos_page")

        first.shutdown()
        time.sleep(1.6)  # left alone, but the other conversation goes on
        assert _answers(url), "the page closed under a conversation that had it open"

        second.shutdown()
        for _ in range(6):  # somebody reading it: an open page keeps asking
            time.sleep(0.25)
            assert _answers(url), "the page closed on someone who had it open"

        time.sleep(3.0)  # nobody: the wait, the watch's next look, and the server's own stop
        assert not _answers(url), "the page was still served after everyone had left it"
        assert not provider_module._pages and not provider_module._pages_closing

        # Asked for again, it opens anew.
        third = _provider(tmp_path)
        again = _page_address(_call(third, "mnemos_page"))
        assert again != url and _answers(again)
        third.shutdown()
    finally:
        _close_pages()


def test_a_conversation_that_asks_again_keeps_the_page(tmp_path, monkeypatch):
    """Between the last conversation ending and the page closing, one that asks
    for the page takes it back: the same page, at the same address."""
    import time

    monkeypatch.setattr(provider_module, "_PAGE_LEFT_ALONE_SECONDS", 1.0)
    first, later = _provider(tmp_path), _provider(tmp_path)
    try:
        url = _page_address(_call(first, "mnemos_page"))
        first.shutdown()
        assert url in _call(later, "mnemos_page")
        time.sleep(2.5)
        assert _answers(url), "the page closed under the conversation that took it back"
    finally:
        later.shutdown()
        _close_pages()


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


_FENCED = "<memory-context>\n[System note: recalled memory]\n\n- an older memory\n</memory-context>"


@pytest.mark.parametrize("message, left", [
    (f"which port is staging on?\n\n{_FENCED}", "which port is staging on?"),
    (f"{_FENCED}\n\nwhich port is staging on?", "which port is staging on?"),
    (f"first {_FENCED} then {_FENCED} last", "first  then  last"),
    ("< MEMORY-CONTEXT >what Hermes added< / memory-context >my own words", "my own words"),
    # Words about the fence are the person's own: a tag alone fences nothing.
    ("the <memory-context> tag opens it", "the <memory-context> tag opens it"),
    ("and </memory-context> closes it", "and </memory-context> closes it"),
])
def test_what_hermes_fenced_into_a_message_comes_off(message, left):
    assert provider_module._clean_text(message) == left


@pytest.mark.parametrize("pasted", [
    "<" * 51_000,
    "< " * 25_500,
    "<" + " " * 51_000,
    "</" * 25_500,
    "<memory-context>" * 3_187,
    "<div class='row'><span>cell</span><a href='#'>more</a></div>\n" * 850,
    "#" + " " * 51_000,
], ids=["angle-brackets", "brackets-and-spaces", "a-bracket-then-spaces", "closing-brackets",
        "fences-never-closed", "a-page-of-markup", "a-heading-of-spaces"])
def test_a_long_paste_of_markup_is_cleaned_at_once(pasted):
    """The pattern that took the fence off tried every ``<`` against all that
    followed: 51,000 of them took seconds (3.7 on the machine this was written
    on), on every message, with Hermes waiting on its recall. Now one pass, a
    millisecond; the bound is loose so a slow machine doesn't fail it."""
    import time

    began = time.perf_counter()
    provider_module._clean_text(pasted)
    assert time.perf_counter() - began < 0.25


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
