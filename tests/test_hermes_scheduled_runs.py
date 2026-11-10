"""A run nobody is in reads the memory and writes nothing by itself.

Hermes gives a memory provider to its scheduled jobs too, and tells it so
(``agent_context="cron"``): its provider guide asks that automatic writes be
skipped there. Mnemos skipped its upkeep and its mirror of Hermes's own memory,
and the rest ran as in a conversation: the job was woken (a session counted,
what shows once spent on a run nobody reads), what came up with its prompt was
strengthened by it, and the rules told it to leave a handoff, which the next
chat then woke to. The README said scheduled jobs never write.

The agent's own tools still work there: a job can be its quiet hour
(``mnemos connect hermes --hours``), where what it keeps is the point.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3

from mnemos.integrations.hermes.provider import MnemosMemoryProviderCore
from mnemos.integrations.hermes.scope import HermesMnemosConfig


def _provider(tmp_path, session: str, **init) -> MnemosMemoryProviderCore:
    provider = MnemosMemoryProviderCore(
        HermesMnemosConfig(
            db_path=str(tmp_path / "a.db"), agent_id="a", person_id="user", project_scope="global",
            deep_maintenance=False,
        )
    )
    provider.initialize(session, hermes_home=str(tmp_path), platform=init.pop("platform", "cli"), **init)
    return provider


def _call(provider: MnemosMemoryProviderCore, tool: str, **args) -> dict:
    return json.loads(provider.handle_tool_call(tool, args))


def _everything(path) -> dict[str, str]:
    """Every table of a store, each as one digest: to see that nothing moved."""
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        held = {}
        for (name,) in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall():
            try:
                rows = conn.execute(f'SELECT * FROM "{name}" ORDER BY 1').fetchall()
            except sqlite3.Error:  # a virtual table whose module isn't loaded here
                continue
            held[name] = hashlib.sha256(repr(rows).encode()).hexdigest()
        return held
    finally:
        conn.close()


def _a_memory_in_use(tmp_path) -> None:
    chat = _provider(tmp_path, "chat-1")
    for words in (
        "The kiln is fired on Tuesdays, and the glaze is mixed the night before.",
        "Mara wants the morning digest short: three lines, no greeting.",
    ):
        assert _call(chat, "mnemos_capture", content=words)["ok"]
    assert _call(chat, "mnemos_handoff", text="Left off glazing the second batch; the blue is still too thin.")["ok"]
    chat.system_prompt_block()
    chat.on_session_end([])
    chat.shutdown()


def test_a_scheduled_run_writes_nothing_by_itself(tmp_path, monkeypatch):
    monkeypatch.setenv("MNEMOS_MAINTENANCE", "inline")
    _a_memory_in_use(tmp_path)
    before = _everything(tmp_path / "a.db")

    job = _provider(tmp_path, "cron-1", platform="cron", agent_context="cron")
    woke = job.system_prompt_block()
    job.on_turn_start(1, "Write Mara's morning digest about the kiln.", model="some-model")
    came = job.prefetch("Write Mara's morning digest about the kiln.", session_id="cron-1")
    job.queue_prefetch("Write Mara's morning digest about the kiln.", session_id="cron-1")
    job.sync_turn("Write Mara's morning digest about the kiln.", "The kiln fires Tuesday.", session_id="cron-1")
    job.on_memory_write("add", "memory", "The digest went out at seven.")
    job.on_session_end([])
    job.shutdown()

    after = _everything(tmp_path / "a.db")
    assert {name for name in after if before.get(name) != after[name]} == set(), "a scheduled run changed the memory"

    # It read the memory all the same: where things stand, and what bears on its task.
    assert "a scheduled run" in woke and "blue is still too thin" in woke
    assert "kiln is fired on Tuesdays" in came or "morning digest short" in came
    # And it isn't told to leave a handoff, as a conversation is.
    assert "Refresh mnemos_handoff" not in woke and "Leave no handoff" in woke


def test_what_a_scheduled_run_reads_isnt_spent(tmp_path, monkeypatch):
    """A wake counts a session. Read by a job, the count stays where the last
    conversation left it, so the next conversation is the session it would
    have been."""
    monkeypatch.setenv("MNEMOS_MAINTENANCE", "inline")
    _a_memory_in_use(tmp_path)

    def sessions() -> str:
        conn = sqlite3.connect(tmp_path / "a.db")
        try:
            row = conn.execute("SELECT value FROM meta WHERE key LIKE '%session_counter'").fetchone()
            return row[0] if row else ""
        finally:
            conn.close()

    counted = sessions()
    for night in range(3):
        job = _provider(tmp_path, f"cron-{night}", platform="cron", agent_context="cron")
        job.system_prompt_block()
        job.shutdown()
    assert sessions() == counted


def test_a_scheduled_run_keeps_what_its_task_asks_it_to(tmp_path, monkeypatch):
    """The agent's own tools are its own act, in a job as in a chat: its quiet
    hour is a job. What it keeps there is there for the next conversation."""
    monkeypatch.setenv("MNEMOS_MAINTENANCE", "inline")
    _a_memory_in_use(tmp_path)

    job = _provider(tmp_path, "cron-1", platform="cron", agent_context="cron")
    assert _call(job, "mnemos_capture", content="The feed the digest reads moved to the new address in March.")["ok"]
    assert "kiln" in _call(job, "mnemos_recall", query="when is the kiln fired")["result"]
    job.shutdown()

    chat = _provider(tmp_path, "chat-2")
    assert "new address in March" in _call(chat, "mnemos_recall", query="where does the digest read its feed")["result"]
    chat.shutdown()


def _cycles(tmp_path) -> int:
    conn = sqlite3.connect(tmp_path / "a.db")
    try:
        return conn.execute("SELECT COUNT(*) FROM consolidation_log").fetchone()[0]
    finally:
        conn.close()


def test_what_a_scheduled_run_keeps_starts_no_upkeep(tmp_path, monkeypatch):
    """After a save in a conversation the memory's upkeep runs, when it is due:
    fading, linking and lessons, across all of it. A job that keeps one thing
    asked for one thing. It was followed by a cycle all the same, so a
    scheduled job did write by itself, which the README said it didn't. Now the
    cycle waits for a conversation, or for being asked for by name."""
    monkeypatch.setenv("MNEMOS_MAINTENANCE", "inline")
    monkeypatch.setenv("MNEMOS_CONSOLIDATION_MIN_IDLE_MINUTES", "0")  # due at every chance
    _a_memory_in_use(tmp_path)
    ran = _cycles(tmp_path)

    job = _provider(tmp_path, "cron-1", platform="cron", agent_context="cron")
    kept = _call(job, "mnemos_capture", content="The feed the digest reads moved to the new address in March.")
    changed = _call(job, "mnemos_correct", query="kiln fired Tuesdays", correction="The kiln is fired on Wednesdays now.")
    assert kept["ok"] and changed["ok"]
    assert _cycles(tmp_path) == ran, "a save in a scheduled run was followed by the memory's upkeep"
    assert "waits for a conversation" in kept["result"]

    # Asked for by name, it runs there too: that is the job's own act.
    assert _call(job, "mnemos_maintain")["ok"]
    assert _cycles(tmp_path) == ran + 1
    job.shutdown()

    # And in a conversation a save is followed by it, as before.
    chat = _provider(tmp_path, "chat-2")
    assert _call(chat, "mnemos_capture", content="Mara reads the digest on the tram, so it has to fit one screen.")["ok"]
    assert _cycles(tmp_path) == ran + 2
    chat.shutdown()


def test_what_a_scheduled_run_keeps_starts_no_process(tmp_path, monkeypatch):
    """The same, where upkeep runs in a process of its own: a job's save
    starts none."""
    from mnemos import simple_runtime

    started: list[tuple] = []

    def start(*args, **kwargs) -> bool:
        started.append(args)
        return True

    monkeypatch.setattr(simple_runtime, "_spawn_upkeep", start)
    monkeypatch.setenv("MNEMOS_CONSOLIDATION_MIN_IDLE_MINUTES", "0")
    monkeypatch.delenv("MNEMOS_MAINTENANCE", raising=False)

    job = _provider(tmp_path, "cron-1", platform="cron", agent_context="cron")
    assert _call(job, "mnemos_capture", content="The feed the digest reads moved to the new address in March.")["ok"]
    job.on_session_end([])
    job.shutdown()
    assert started == [], "a scheduled run started the upkeep process"

    chat = _provider(tmp_path, "chat-1")
    assert _call(chat, "mnemos_capture", content="Mara reads the digest on the tram, so it has to fit one screen.")["ok"]
    chat.shutdown()
    assert len(started) == 1


def test_a_scheduled_run_opens_no_page(tmp_path):
    """The page is served for a person to read, and closes once the run that
    opened it has ended and nobody has it open: from a job, before anyone
    could look. It says so, and starts no server."""
    job = _provider(tmp_path, "cron-1", platform="cron", agent_context="cron")
    offered = {tool["name"] for tool in job.get_tool_schemas()}
    said = _call(job, "mnemos_page")
    woke = job.system_prompt_block()
    job.shutdown()
    assert said["ok"] is False and "nobody is in this run" in said["error"]
    assert job._page_key is None
    # Nor is it offered one, though the rest of its tools are; and a memory
    # with nothing in it yet says so, and promises nothing "below".
    assert "mnemos_page" not in offered and {"mnemos_capture", "mnemos_recall"} <= offered
    assert "nothing to wake with yet" in woke and "below" not in woke

    chat = _provider(tmp_path, "chat-1")
    assert "mnemos_page" in {tool["name"] for tool in chat.get_tool_schemas()}
    chat.shutdown()


def test_a_run_called_on_after_it_ended_is_still_the_run_it_was(tmp_path, monkeypatch):
    """Hermes can call a provider it has already shut down (a late hook, a
    tool call that was still on its way). The provider starts again, and it
    started with nothing Hermes had told it: the default home in place of the
    profile's, and a scheduled run taken for a conversation."""
    monkeypatch.setenv("MNEMOS_MAINTENANCE", "inline")
    _a_memory_in_use(tmp_path)
    before = _everything(tmp_path / "a.db")

    job = _provider(tmp_path, "cron-1", platform="cron", agent_context="cron", gateway_session_key="cron:digest")
    was = (job._scope.hermes_home, job._scope.conversation, job._writes_enabled)
    job.shutdown()
    woke = job.system_prompt_block()  # after the end
    assert (job._scope.hermes_home, job._scope.conversation, job._writes_enabled) == was
    assert "a scheduled run" in woke
    job.shutdown()
    assert _everything(tmp_path / "a.db") == before


def test_a_conversation_started_twice_leaves_nothing_open(tmp_path):
    chat = _provider(tmp_path, "chat-1")
    first = chat._runtime
    assert first._store is not None
    chat.initialize("chat-1", hermes_home=str(tmp_path), platform="cli")
    assert first._store is None and chat._runtime is not first
    chat.shutdown()
