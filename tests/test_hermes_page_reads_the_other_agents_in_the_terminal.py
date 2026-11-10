"""In Hermes's terminal the page shows the other agents again, only to read.

After Nous's review the page a Hermes agent opens was narrowed to that agent's
memory alone: it had written in the other agents' memories it showed, and on a
gateway one profile's page served every other profile's memory. Narrowed
everywhere, it also took from the person at Hermes's own terminal (platform
"cli") the switch between their agents that the page gives them anywhere else.

In the terminal the page lists the same agents again, and shows each whole. It
writes in none of them: the server refuses every request that would, whatever
the page sends, and the page shows them without the controls. Another agent's
file is opened so that nothing in it changes. Anywhere but the terminal the
page is still this agent's alone.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from mnemos import llm
from mnemos.integrations.hermes import HermesMnemosConfig, MnemosMemoryProviderCore
from mnemos.integrations.hermes import provider as provider_module

OWN_ONLY = "From inside Hermes this page writes only in this agent's own memory."
# Said after it, for the shared memory and for another agent's (the run in a real Hermes, W3).
SHARED_IS_THEIRS = " An agent changes what it shared itself, with its own tools."
ONLY_READ = " The other agents are only read here."


def _provider(tmp_path, name: str, platform: str = "cli") -> MnemosMemoryProviderCore:
    provider = MnemosMemoryProviderCore(HermesMnemosConfig(
        db_path=str(tmp_path / f"{name}.db"), agent_id=name, person_id="user",
        project_scope="global", deep_maintenance=False,
    ))
    provider.initialize("session-1", hermes_home=str(tmp_path / f"home-{name}"), platform=platform)
    return provider


def _call(provider: MnemosMemoryProviderCore, tool: str, **args) -> str:
    reply = json.loads(provider.handle_tool_call(tool, args))
    assert reply["ok"], reply
    return reply["result"]


def _close_pages() -> None:
    for page in list(provider_module._pages.values()):
        page.shutdown()
        page.server_close()
    provider_module._pages.clear()
    provider_module._page_holders.clear()


def _base(said: str) -> str:
    return re.search(r"http://127\.0\.0\.1:\d+/\S+", said).group().rsplit("/log/", 1)[0]


def _get(url: str) -> tuple[int, str]:
    try:
        with urllib.request.urlopen(url, timeout=60) as answer:
            return answer.status, answer.read().decode()
    except urllib.error.HTTPError as refused:
        return refused.code, refused.read().decode()


def _act(base: str, agent: str, request: dict) -> tuple[int, dict]:
    """What the page's own script sends when the person writes on it."""
    port = re.search(r":(\d+)/", base + "/").group(1)
    asked = urllib.request.Request(
        f"{base}/act?agent={agent}", data=json.dumps(request).encode(), method="POST",
        headers={"Content-Type": "application/json", "Origin": f"http://127.0.0.1:{port}"},
    )
    try:
        with urllib.request.urlopen(asked, timeout=60) as answer:
            return answer.status, json.loads(answer.read())
    except urllib.error.HTTPError as refused:
        return refused.code, json.loads(refused.read())


def _whole(path: Path) -> dict:
    """Everything a store is: every table's rows and its schema, digested, and
    the file's size and modified time. Read so the reading changes nothing, and
    with what its log holds that isn't in the file yet, when it has one."""
    logged = Path(f"{path}-wal").exists()
    conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro{'' if logged else '&immutable=1'}", uri=True)
    try:
        tables = {}
        for name, sql in conn.execute("SELECT name, sql FROM sqlite_master WHERE type = 'table' ORDER BY name"):
            digest = hashlib.sha256((sql or "").encode())
            for row in conn.execute(f'SELECT * FROM "{name}" ORDER BY 1'):
                digest.update(repr(row).encode())
            tables[name] = digest.hexdigest()
    finally:
        conn.close()
    stat = path.stat()
    return {"tables": tables, "size": stat.st_size, "mtime_ns": stat.st_mtime_ns}


def _two_agents(tmp_path, monkeypatch, platform: str = "cli"):
    """This agent ("a", the one the page is opened from) and another ("b")
    whose memory is kept beside it: a memory, a note of its own unread, and a
    store a writing open would bring up to date (an older schema stamp)."""
    monkeypatch.setenv("MNEMOS_SHARED_MEMORY_DB", str(tmp_path / "shared.db"))
    monkeypatch.delenv("MNEMOS_SHARED_MEMORY", raising=False)
    mine, other = _provider(tmp_path, "a", platform), _provider(tmp_path, "b")
    _call(mine, "mnemos_capture", content="The kiln at the studio fires on Tuesdays.")
    _call(other, "mnemos_capture", content="The glaze room is locked after six.")
    _call(other, "mnemos_capture", content="Everyone should know the studio closes at nine.", shared=True)
    _call(other, "mnemos_note", text="I moved the glaze buckets to the back shelf.", kind="noticed")
    other.shutdown()
    conn = sqlite3.connect(tmp_path / "b.db")
    with conn:
        conn.execute("UPDATE meta SET value = '1' WHERE key = 'schema_version'")
        conn.execute("DELETE FROM meta WHERE key = 'min_code_version'")
    conn.close()  # the last connection: what was written is in the file, and nothing is left beside it
    return mine


def test_in_the_terminal_the_page_shows_the_other_agents_whole(tmp_path, monkeypatch):
    import threading

    read: list[tuple[str, str]] = []

    def hermes_says(name, default=None):  # inside Hermes, with a key for every provider
        read.append((name, threading.current_thread().name))
        return {"MNEMOS_EMBEDDING_PROVIDER": "gemini", "GEMINI_API_KEY": "a-profiles-key"}.get(name, default)

    mine = _two_agents(tmp_path, monkeypatch)
    try:
        llm.take_secrets_from(hermes_says)
        base = _base(_call(mine, "mnemos_page"))
        read.clear()
        minds = json.loads(_get(f"{base}/data/minds.json")[1])["minds"]
        assert [(m["agentId"], m["home"]) for m in minds] == [("a", True), ("b", False)], minds

        status, memories = _get(f"{base}/data/memories.json?agent=b")
        assert status == 200 and "glaze room is locked" in memories
        status, life = _get(f"{base}/data/life.json?agent=b")
        life = json.loads(life)
        assert status == 200 and [n["text"] for n in life["notes"]] == ["I moved the glaze buckets to the back shelf."]
        # The page is told whose notebook it is, and that this one is only read here.
        assert life["identity"]["onlyReadIn"] == json.loads(_get(f"{base}/data/life.json")[1])["identity"]["name"]
        assert "onlyReadIn" not in json.loads(_get(f"{base}/data/life.json")[1])["identity"]
        status, found = _get(f"{base}/data/search.json?agent=b&q=glaze")
        assert status == 200 and "glaze room is locked" in found, found
        assert _get(f"{base}/data/pulse.json?agent=b")[0] == 200
        # Still not the shared memory, nor anything that looks at the machine.
        assert life["shared"] == {"status": "elsewhere", "rows": []} and life["schedule"] == []
        assert "studio closes at nine" not in json.dumps(life)
        # and the page's own threads read no key, for this agent or another
        (page,) = provider_module._pages.values()
        for mind in (page._home, *page._others[1].values()):
            if mind.interface is not None:
                mind.interface._loaded()
        assert read == [], f"the page's threads read {sorted(set(read))}"
    finally:
        mine.shutdown()
        _close_pages()


def test_nothing_the_page_sends_writes_in_another_agents_memory(tmp_path, monkeypatch):
    mine = _two_agents(tmp_path, monkeypatch)
    conn = sqlite3.connect(f"{(tmp_path / 'b.db').resolve().as_uri()}?mode=ro&immutable=1", uri=True)
    theirs = conn.execute("SELECT id FROM engrams WHERE content LIKE 'The glaze room%'").fetchone()[0]
    (note,) = conn.execute("SELECT id FROM notes").fetchone()
    conn.close()
    conn = sqlite3.connect(tmp_path / "shared.db")
    (shared_id,) = conn.execute("SELECT id FROM engrams").fetchone()
    conn.close()
    before = _whole(tmp_path / "b.db"), _whole(tmp_path / "shared.db")
    beside = sorted(p.name for p in tmp_path.glob("b.db*"))
    try:
        llm.take_secrets_from(lambda name, default=None: default)  # inside Hermes
        base = _base(_call(mine, "mnemos_page"))
        for view in ("minds.json", "life.json?agent=b", "memories.json?agent=b", "pulse.json?agent=b",
                     "search.json?agent=b&q=", "search.json?agent=b&q=glaze"):
            assert _get(f"{base}/data/{view}")[0] == 200, view
        assert _get(f"{base}/mind/?agent=b")[0] == 200
        for request in (
            {"command": "reply", "note_id": note, "text": "Thanks for moving them."},
            {"command": "note", "text": "Left through another agent's page."},
            {"command": "read", "note_ids": [note]},
            {"command": "correct", "memory_id": theirs, "text": "The glaze room is never locked."},
            {"command": "forget", "memory_id": theirs, "confirmed": True},
            {"command": "hours", "on": False},
            {"command": "jev", "on": False},
            {"command": "shared", "action": "add", "text": "Written into the shared memory from a Hermes page."},
            {"command": "shared", "action": "correct", "memory_id": shared_id, "text": "The studio never closes."},
            {"command": "shared", "action": "forget", "memory_id": shared_id, "confirmed": True},
        ):
            status, answer = _act(base, "b", request)
            said = OWN_ONLY + (SHARED_IS_THEIRS if request["command"] == "shared" else ONLY_READ)
            assert status == 400 and answer["error"] == said, (request, status, answer)
        assert (_whole(tmp_path / "b.db"), _whole(tmp_path / "shared.db")) == before, "another agent's memory moved"
        # A search reads it through a read-only connection, which SQLite gives an
        # empty log and its index beside the file, as it does outside Hermes.
        assert beside == ["b.db"] and (tmp_path / "b.db-wal").stat().st_size == 0
        assert sorted(p.name for p in tmp_path.glob("b.db*")) == ["b.db", "b.db-shm", "b.db-wal"]

        status, own = _act(base, "a", {"command": "note", "text": "Left on my own agent's page."})
        assert status == 200 and own["result"]["text"] == "Left on my own agent's page.", own
    finally:
        mine.shutdown()
        _close_pages()


@pytest.mark.parametrize("platform", ["telegram", "discord", "api_server"])
def test_anywhere_but_the_terminal_the_page_is_this_agents_alone(tmp_path, monkeypatch, platform):
    """There the agent may be a bot other people talk to, and it is handed the
    page's link. Its page is the one it was, though a terminal in the same
    Hermes has one of its own over the same memory."""
    there = _two_agents(tmp_path, monkeypatch, platform)
    terminal = _provider(tmp_path, "a")
    try:
        llm.take_secrets_from(lambda name, default=None: default)  # inside Hermes
        base = _base(_call(there, "mnemos_page"))
        terminal_base = _base(_call(terminal, "mnemos_page"))
        assert terminal_base != base, "the terminal's page was the chat's"
        assert [m["agentId"] for m in json.loads(_get(f"{base}/data/minds.json")[1])["minds"]] == ["a"]
        for view in ("memories.json", "life.json", "pulse.json", "search.json?q=glaze"):
            joiner = "&" if "?" in view else "?"
            status, said = _get(f"{base}/data/{view}{joiner}agent=b")
            assert status == 404 and "glaze" not in said, (view, status, said[:200])
        assert [m["agentId"] for m in json.loads(_get(f"{terminal_base}/data/minds.json")[1])["minds"]] == ["a", "b"]
        # and asked again from the chat, it is still the chat's own page
        assert _base(_call(there, "mnemos_page")) == base
    finally:
        there.shutdown()
        terminal.shutdown()
        _close_pages()


def test_outside_hermes_the_other_agents_are_the_persons_as_before(tmp_path, monkeypatch):
    from mnemos.companion.server import open_page

    _two_agents(tmp_path, monkeypatch).shutdown()
    llm.take_secrets_from(None)  # no host hands out the keys: an agent's own server, or `mnemos log`
    said, page = open_page({"db_path": str(tmp_path / "a.db"), "agent_id": "a",
                            "person_id": "user", "project_scope": "global"})
    try:
        base = _base(said)
        assert "onlyReadIn" not in json.loads(_get(f"{base}/data/life.json?agent=b")[1])["identity"]
        status, there = _act(base, "b", {"command": "note", "text": "Left through another agent's page."})
        assert status == 200 and there["result"]["text"] == "Left through another agent's page.", there
    finally:
        page.shutdown()
        page.server_close()


def test_the_agent_is_told_what_its_page_shows_where_it_is(tmp_path):
    """The tool's words and the first session's say the page lets the person
    read the other agents only where it does: in the terminal."""
    told_of_others = "the memory of the other agents kept beside yours in ~/.mnemos, only to read"
    first_session = "the page also lets them read the memory of the other agents Mnemos keeps on this computer"
    terminal, chat = _provider(tmp_path, "a"), _provider(tmp_path, "c", "telegram")
    try:
        for provider, here in ((terminal, True), (chat, False)):
            tool = next(t["description"] for t in provider.get_tool_schemas() if t["name"] == "mnemos_page")
            woke = provider.system_prompt_block()
            assert "ONBOARDING" in woke
            assert (told_of_others in " ".join(tool.split())) is here, tool
            assert (first_session in " ".join(woke.split())) is here, woke
    finally:
        terminal.shutdown()
        chat.shutdown()


def test_where_the_other_agents_arent_shown_the_refusal_says_only_what_is_true(tmp_path, monkeypatch):
    there = _two_agents(tmp_path, monkeypatch, "telegram")
    try:
        llm.take_secrets_from(lambda name, default=None: default)  # inside Hermes
        base = _base(_call(there, "mnemos_page"))
        status, answer = _act(base, "b", {"command": "note", "text": "Left through another agent's page."})
        assert status == 400 and answer["error"] == OWN_ONLY, answer
        status, answer = _act(base, "a", {"command": "shared", "action": "add", "text": "For everyone."})
        assert status == 400 and answer["error"] == OWN_ONLY + SHARED_IS_THEIRS, answer
    finally:
        there.shutdown()
        _close_pages()
