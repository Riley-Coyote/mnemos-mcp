"""Default tool paths, separate agents and processes, never the real home."""
import os
import re
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from mnemos.simple_runtime import MnemosRuntime
from mnemos.mcp_compat import wire

WORDS = "The cedar observatory keeps spare telescope lenses in the west cabinet."


@pytest.fixture(autouse=True)
def shared_home(monkeypatch):
    monkeypatch.setenv("MNEMOS_SHARED_MEMORY_DB", str(Path.home() / "shared-memory.db"))
    monkeypatch.delenv("MNEMOS_SHARED_MEMORY", raising=False)
    monkeypatch.setenv("MNEMOS_AGENT_MODEL", "test-model")


def runtime(monkeypatch, agent):
    monkeypatch.setenv("MNEMOS_AGENT_ID", agent)
    return MnemosRuntime(use_dedicated_model=False)


def share_id(reply):
    match = re.search(r"shared_engram_\w+", reply)
    assert match, reply
    return match[0]


def rows(sql, params=()):
    with sqlite3.connect(f"file:{os.environ['MNEMOS_SHARED_MEMORY_DB']}?mode=ro", uri=True) as conn:
        return conn.execute(sql, params).fetchall()


def process(agent, code):
    env = dict(os.environ, MNEMOS_AGENT_ID=agent)
    return subprocess.run([sys.executable, "-c", "from mnemos.simple_runtime import MnemosRuntime\nr=MnemosRuntime(use_dedicated_model=False)\n" + code + "\nr.close()"],
                          env=env, text=True, capture_output=True, check=True).stdout.strip()


def test_two_processes_defaults():
    written = process("writer", f"print(r.capture({WORDS!r}, shared=True))")
    memory_id = share_id(written)
    found = process("reader", "print(r.recall('telescope lenses'))")
    assert WORDS in found
    assert "[shared]" in found and "writer | test-model | " in found
    assert datetime.now().astimezone().date().isoformat() in found
    assert memory_id in found
    assert not (Path.home() / ".mnemos/writer.db").exists()
    assert not (Path.home() / ".mnemos/shared.db").exists()
    assert rows("SELECT access_count FROM engrams WHERE id=?", (memory_id,))[0][0] > 0


def test_it_is_dated_on_this_machines_calendar(monkeypatch):
    # Written in the evening in Honolulu, it's already tomorrow in UTC. A real agent
    # reading that took a note written minutes before for one with a wrong date.
    monkeypatch.setenv("TZ", "Pacific/Honolulu")
    time.tzset()
    try:
        r = runtime(monkeypatch, "writer")
        memory_id = share_id(r.capture(WORDS, shared=True))
        with sqlite3.connect(os.environ["MNEMOS_SHARED_MEMORY_DB"]) as conn:
            conn.execute("UPDATE engrams SET created_at = '2026-11-07T02:00:00+00:00' WHERE id = ?", (memory_id,))
        found = r.recall("telescope lenses")
        r.close()
    finally:
        monkeypatch.undo()
        time.tzset()
    assert "| 2026-11-06\n" in found and "2026-11-07" not in found


def test_sharing_leaves_own_file_unchanged_and_own_rows_first(monkeypatch):
    r = runtime(monkeypatch, "writer")
    r.capture("The telescope lenses need cleaning before Friday.")
    r.recall("telescope lenses", max_results=1)  # once-per-session reinforcement
    before = r.recall("telescope lenses", max_results=1)
    dump = "\n".join(r._store._get_conn().iterdump())
    for i in range(5):
        share_id(r.capture(WORDS + f" Shelf {i}.", shared=True))
    assert "\n".join(r._store._get_conn().iterdump()) == dump
    after = r.recall("telescope lenses", max_results=1)
    assert after.split("\n\nShared memory:")[0] == before
    assert after.count("[shared]") == 3
    assert not r._store._get_conn().execute("SELECT id FROM engrams WHERE id LIKE 'shared_%'").fetchall()
    assert WORDS not in r.context()
    r.close()


def test_absent_file_is_never_created(monkeypatch):
    r = runtime(monkeypatch, "reader")
    from mnemos import shared_memory
    assert "[shared]" not in r.recall("telescope")
    assert not shared_memory.maintain()
    assert not shared_memory.path().exists()
    assert not (Path.home() / ".mnemos/shared.db").exists()
    r.close()


def test_author_only_correction_and_withdrawal(monkeypatch):
    writer = runtime(monkeypatch, "writer")
    old = share_id(writer.capture(WORDS, shared=True))
    other = runtime(monkeypatch, "reader")
    before = rows("SELECT id, content, state FROM engrams")
    for action in ("update", "archive"):
        assert "Only the agent" in other.correct("replacement", target_id=old, action=action)
    assert rows("SELECT id, content, state FROM engrams") == before
    new = share_id(writer.correct("The telescope lenses are now in the east cabinet.", target_id=old))
    assert "east cabinet" in other.recall(new)
    assert WORDS not in other.recall(old)
    assert "Withdrawn" in writer.correct("", target_id=old, action="archive")
    assert "east cabinet" not in other.recall("telescope lenses", include_archived=True)
    assert "east cabinet" not in other.recall(new)
    assert rows("SELECT state FROM engrams ORDER BY id") == [("archived",), ("archived",)]
    assert len(rows("SELECT id FROM archive")) == 2
    writer.close(); other.close()


def test_off_switch(monkeypatch):
    r = runtime(monkeypatch, "writer")
    memory_id = share_id(r.capture(WORDS, shared=True))
    before = rows("SELECT id, content, state, access_count FROM engrams")
    monkeypatch.setenv("MNEMOS_SHARED_MEMORY", "off")
    assert "off" in r.capture("Another memory", shared=True)
    assert "[shared]" not in r.recall("telescope lenses")
    assert WORDS not in r.recall(memory_id)
    assert "off" in r.correct("", target_id=memory_id, action="archive")
    from mnemos import shared_memory
    assert not shared_memory.maintain()
    assert rows("SELECT id, content, state, access_count FROM engrams") == before
    r.close()


def test_four_hour_gate_and_process_lock(monkeypatch):
    from mnemos import shared_memory as sm
    r = runtime(monkeypatch, "writer")
    r.capture(WORDS, shared=True)
    assert sm.maintain()
    first = rows("SELECT value FROM meta WHERE key=?", (sm.LAST_PASS,))[0][0]
    assert not sm.maintain()
    with sqlite3.connect(sm.path()) as conn:
        conn.execute("UPDATE meta SET value=? WHERE key=?", ((datetime.now(timezone.utc)-timedelta(hours=4, minutes=1)).isoformat(), sm.LAST_PASS))
    lock = sqlite3.connect(sm.path())
    lock.execute("BEGIN IMMEDIATE")
    assert process("reader", "from mnemos.shared_memory import maintain\nprint(maintain())") == "False"
    lock.rollback(); lock.close()
    assert sm.maintain()
    assert rows("SELECT value FROM meta WHERE key=?", (sm.LAST_PASS,))[0][0] != first
    assert rows("SELECT COUNT(*) FROM reflection_queue")[0][0] == 0
    r.close()


def test_corrupt_file_never_breaks_recall_or_upkeep(monkeypatch):
    from mnemos import shared_memory as sm
    r = runtime(monkeypatch, "reader")
    r.capture("The telescope lenses need cleaning.")
    r.recall("telescope lenses")
    before = r.recall("telescope lenses")
    sm.path().write_bytes(b"not a sqlite database")
    assert r.recall("telescope lenses") == before
    assert "Completed:" in r.maintain()
    assert sm.path().read_bytes() == b"not a sqlite database"
    r.close()


def test_default_path_and_standing_refusal(monkeypatch):
    from mnemos import shared_memory as sm
    monkeypatch.delenv("MNEMOS_SHARED_MEMORY_DB")
    assert sm.path() == Path.home() / ".mnemos/shared-memory.db"
    monkeypatch.setenv("MNEMOS_SHARED_MEMORY_DB", str(Path.home() / "shared-memory.db"))
    r = runtime(monkeypatch, "writer")
    assert "cannot be standing" in r.capture(WORDS, shared=True, standing=True)
    assert not sm.path().exists()
    r.close()


def test_shared_id_returns_whole_and_reinforces(monkeypatch):
    r = runtime(monkeypatch, "writer")
    content = WORDS + " A long account." * 500
    memory_id = share_id(r.capture(content, shared=True))
    assert content in r.recall(memory_id)
    assert rows("SELECT access_count FROM engrams WHERE id=?", (memory_id,))[0][0] == 1
    assert not r.db_path.exists()
    r.close()


def test_meaning_search_with_no_shared_query_words(monkeypatch):
    import mnemos.store.embedding_index as ei

    class Vector(list):
        def tolist(self):
            return list(self)

    class Model:
        def encode(self, texts, **kwargs):
            def vector(text):
                return Vector([1.0, 0.0] if any(w in text.lower() for w in ("beacon", "lighthouse")) else [0.0, 1.0])
            return vector(texts) if isinstance(texts, str) else [vector(t) for t in texts]

    class Embedder(ei._LocalEmbedder):
        def _get_model(self):
            return Model()

    monkeypatch.setattr(ei, "_check_local_deps", lambda: True)
    monkeypatch.setattr(ei, "_LocalEmbedder", Embedder)
    r = runtime(monkeypatch, "writer")
    memory_id = share_id(r.capture("The lighthouse shines nightly.", shared=True))
    reader = runtime(monkeypatch, "reader")
    assert memory_id in reader.recall("beacon")
    assert rows("SELECT COUNT(*) FROM passage_vectors")[0][0] > 0
    r.close(); reader.close()


@pytest.mark.lived_time
def test_existing_passes_fade_and_link_across_authors(monkeypatch):
    from mnemos import shared_memory as sm
    from mnemos.store.sqlite_store import EngramStore
    a = runtime(monkeypatch, "writer")
    first = share_id(a.capture(WORDS, shared=True))
    b = runtime(monkeypatch, "reader")
    second = share_id(b.capture("The cedar observatory telescope lenses need a clean west cabinet.", shared=True))
    old = datetime.now(timezone.utc) - timedelta(days=4)
    store = EngramStore(sm.path())
    for memory_id in (first, second):
        memory = store.get_engram(memory_id)
        memory.last_accessed = old.isoformat()
        store.save_engram(memory)
        for day in range(5):
            store.mark_lived(memory.owner_agent_id, old + timedelta(days=day))
    store.close()
    assert sm.maintain()
    assert all(value < .5 for (value,) in rows("SELECT strength FROM engrams"))
    assert rows("SELECT source_id, target_id FROM connections WHERE source_id=? AND target_id=?", (first, second))
    assert rows("SELECT COUNT(*) FROM reflection_queue")[0][0] == 0
    assert rows("SELECT COUNT(*) FROM hypomnema_entries")[0][0] == 0
    a.close(); b.close()


def test_dormant_shared_memory_wakes(monkeypatch):
    from mnemos import shared_memory as sm
    r = runtime(monkeypatch, "writer")
    memory_id = share_id(r.capture(WORDS, shared=True))
    with sqlite3.connect(sm.path()) as conn:
        conn.execute("UPDATE engrams SET state='dormant', accessibility=.03 WHERE id=?", (memory_id,))
    reader = runtime(monkeypatch, "reader")
    assert memory_id in reader.recall("telescope lenses")
    assert rows("SELECT state FROM engrams WHERE id=?", (memory_id,)) == [("active",)]
    r.close(); reader.close()


def test_upkeep_integration_and_failure_isolation(monkeypatch):
    from mnemos import shared_memory as sm
    r = runtime(monkeypatch, "writer")
    r.capture(WORDS, shared=True)
    assert "Completed:" in r.maintain()
    assert rows("SELECT value FROM meta WHERE key=?", (sm.LAST_PASS,))
    r.close()


def test_mcp_tools_keep_twelve_and_shared_capture(monkeypatch):
    import anyio
    from mnemos import simple_mcp
    from mnemos.mcp_compat import Server
    from mnemos.simple_runtime import SIMPLE_TOOL_NAMES
    r = runtime(monkeypatch, "writer")
    monkeypatch.setattr(simple_mcp, "_get_runtime", lambda: r)
    server = Server("shared-test")
    simple_mcp.register_simple_tools(server)

    async def check():
        tools = await server.list_tools()
        assert {t.name for t in tools} == set(SIMPLE_TOOL_NAMES)
        assert len(tools) == 12
        capture = next(t for t in tools if t.name == "mnemos_capture")
        assert wire(capture)["inputSchema"]["properties"]["shared"]["default"] is False
        result = await server.call_tool("mnemos_capture", {"content": WORDS, "shared": True})
        assert "Saved to shared memory" in str(result)
        assert not r.db_path.exists()
    anyio.run(check)
    assert "shared" not in simple_mcp.SERVER_INSTRUCTIONS.lower().replace("may share this memory", "")
    r.close()


def test_failed_pass_rolls_back_and_releases_lock(monkeypatch):
    from mnemos import shared_memory as sm
    import mnemos.consolidation.decay as decay
    r = runtime(monkeypatch, "writer")
    r.capture(WORDS, shared=True)
    original = decay.run_decay_pass

    def broken(store, *args, **kwargs):
        store.set_meta("half-finished", "yes")
        raise RuntimeError("pass failed")

    monkeypatch.setattr(decay, "run_decay_pass", broken)
    assert not sm.maintain()
    assert not rows("SELECT key FROM meta WHERE key IN (?, ?)", (sm.LAST_PASS, "half-finished"))
    monkeypatch.setattr(decay, "run_decay_pass", original)
    assert sm.maintain()
    r.close()


def test_faded_id_restores_but_withdrawn_never_does(monkeypatch):
    from mnemos import shared_memory as sm
    from mnemos.store.sqlite_store import EngramStore
    r = runtime(monkeypatch, "writer")
    memory_id = share_id(r.capture(WORDS, shared=True))
    store = EngramStore(sm.path())
    store.archive_engram(store.get_engram(memory_id), reason="decay_below_threshold")
    store.close()
    assert WORDS in r.recall(memory_id)
    assert rows("SELECT state FROM engrams WHERE id=?", (memory_id,)) == [("active",)]
    assert "Withdrawn" in r.correct("", target_id=memory_id, action="archive")
    assert WORDS not in r.recall(memory_id)
    r.close()


def test_notebook_reads_without_creating_and_handles_off_and_failure(monkeypatch):
    from mnemos import shared_memory as sm
    from mnemos.companion.export import Exporter
    exporter = Exporter.for_scope(agent_id="reader")
    assert exporter.export()[0]["shared"] == {"status": "ready", "rows": []}
    assert not sm.path().exists()
    monkeypatch.setenv("MNEMOS_SHARED_MEMORY", "off")
    assert exporter.export()[0]["shared"]["status"] == "off"
    assert "error" in sm.notebook_act({"action": "add", "text": WORDS})
    assert not sm.path().exists()
    monkeypatch.delenv("MNEMOS_SHARED_MEMORY")
    sm.path().write_bytes(b"broken")
    assert exporter.export()[0]["shared"]["status"] == "error"
    assert sm.path().read_bytes() == b"broken"


def test_notebook_person_signature_correction_and_agent_recall():
    from mnemos import shared_memory as sm
    from mnemos.companion.export import Exporter
    from mnemos.companion.server import LogServer
    from mnemos.simple_scope import resolve_scope
    with LogServer(Exporter.for_scope(agent_id="writer")) as server:
        added = server.act({"command": "shared", "action": "add", "text": WORDS,
                            "author_kind": "agent", "agent_id": "pretender"})
        memory_id = share_id(added["result"])
        assert rows("SELECT author_kind, owner_agent_id, author_model FROM engrams") == [("person", sm.PERSON_OWNER, "")]
        assert resolve_scope(agent_id=sm.PERSON_OWNER).agent_id != sm.PERSON_OWNER
        assert "Only the agent" in sm.correct(memory_id, "", action="archive", agent_id=sm.PERSON_OWNER, model="test-model")
        found = process("reader", "print(r.recall('telescope lenses'))")
        assert WORDS in found and "the person" in found and "model unknown" not in found
        changed = server.act({"command": "shared", "action": "correct", "memory_id": memory_id, "text": "The telescope lenses are upstairs."})
        new_id = share_id(changed["result"])
        listed = server.exporter.export()[0]["shared"]["rows"]
        assert [r["id"] for r in listed] == [new_id]
        assert listed[0]["person"] and listed[0]["editable"]
        assert "upstairs" in process("reader", f"print(r.recall({new_id!r}))")
        assert rows("SELECT archive_reason FROM archive") == [("shared_corrected",)]


def test_person_withdraws_agent_but_agents_cannot_withdraw_others():
    from mnemos import shared_memory as sm
    memory_id = share_id(sm.capture(WORDS, agent_id="writer", model="test-model"))
    assert "Only the agent" in sm.correct(memory_id, "", action="archive", agent_id="reader", model="test-model")
    assert "error" in sm.notebook_act({"action": "correct", "memory_id": memory_id, "text": "Rewritten"})
    assert "error" in sm.notebook_act({"action": "forget", "memory_id": memory_id})
    assert sm.notebook()["rows"][0]["id"] == memory_id
    assert "result" in sm.notebook_act({"action": "forget", "memory_id": memory_id, "confirmed": True})
    assert sm.notebook()["rows"] == []
    assert rows("SELECT state FROM engrams") == [("archived",)]
    assert rows("SELECT archive_reason FROM archive") == [("shared_withdrawn",)]
    assert WORDS not in process("reader", f"print(r.recall({memory_id!r}))")



def test_notebook_lists_newest_first_without_writing_and_omits_superseded(monkeypatch):
    from mnemos import shared_memory as sm
    monkeypatch.setattr(sm, "_index_saved", lambda *args: None)
    first = share_id(sm.capture("First words", agent_id="writer", model="test-model"))
    second = share_id(sm.capture("Second words", agent_id="reader", model="other-model"))
    with sqlite3.connect(sm.path()) as conn:
        conn.execute("UPDATE engrams SET created_at='2026-01-01T00:00:00+00:00' WHERE id=?", (first,))
        conn.execute("UPDATE engrams SET created_at='2026-01-02T00:00:00+00:00' WHERE id=?", (second,))
    before = sm.path().read_bytes()
    assert [r["id"] for r in sm.notebook()["rows"]] == [second, first]
    assert sm.path().read_bytes() == before
    with sqlite3.connect(sm.path()) as conn:
        conn.execute('UPDATE engrams SET lineage=? WHERE id=?', ('{"superseded_by":"replacement"}', second))
    assert [r["id"] for r in sm.notebook()["rows"]] == [first]
    monkeypatch.setenv("MNEMOS_SHARED_MEMORY", "off")
    before = sm.path().read_bytes()
    assert sm.notebook() == {"status": "off", "rows": []}
    assert "error" in sm.notebook_act({"action": "forget", "memory_id": first, "confirmed": True})
    assert sm.path().read_bytes() == before


@pytest.mark.parametrize("payload", [{"action": []}, {"action": "add", "text": 3},
                                    {"action": "add", "text": "  "}, {"action": "correct", "memory_id": []}])
def test_notebook_bad_requests_create_nothing(payload):
    from mnemos import shared_memory as sm
    assert "error" in sm.notebook_act(payload)
    assert not sm.path().exists()


def test_a_persons_shared_words_are_standing_and_an_agents_are_not(monkeypatch):
    """The decay pass skips standing memories; what a person asks to keep never fades."""
    from mnemos.shared_memory import notebook_act

    agent = share_id(runtime(monkeypatch, "writer").capture(WORDS, shared=True))
    added = share_id(notebook_act({"action": "add", "text": "Riley keeps the spare keys in the blue tin."})["result"])
    assert rows("SELECT standing FROM engrams WHERE id = ?", (agent,)) == [(0,)]
    assert rows("SELECT standing FROM engrams WHERE id = ?", (added,)) == [(1,)]
    corrected = share_id(notebook_act({"action": "correct", "memory_id": added, "text": "The spare keys are in the red tin."})["result"])
    assert rows("SELECT standing FROM engrams WHERE id = ?", (corrected,)) == [(1,)]
    assert notebook_act({"action": "forget", "memory_id": corrected, "confirmed": True}).get("result")
    assert rows("SELECT state FROM engrams WHERE id = ?", (corrected,)) == [("archived",)]


def test_recall_waits_out_another_agents_write_instead_of_finding_nothing(monkeypatch):
    import threading
    import time

    from mnemos import shared_memory as sm

    r = runtime(monkeypatch, "writer")
    share_id(r.capture(WORDS, shared=True))
    held = threading.Event()

    def write_briefly():
        conn = sqlite3.connect(sm.path())
        conn.execute("BEGIN IMMEDIATE")
        held.set()
        time.sleep(0.3)
        conn.rollback()
        conn.close()

    thread = threading.Thread(target=write_briefly)
    thread.start()
    held.wait()
    found = sm.recall("cedar observatory telescope lenses", agent_id="reader")
    thread.join()
    assert WORDS in found
    r.close()
