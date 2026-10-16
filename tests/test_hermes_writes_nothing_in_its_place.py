"""The Hermes provider writes nothing in the agent's place.

Until 2026-10-16 Provider Mode wrote memories by itself: a turn whose message
held "remember", "don't" or "actually," was stored word for word as a memory,
as was any long reply that said "fixed" or "added"; the end of a session and
the moment before compression stored up to five more such copies each; every
delegation and session switch left a record; and SOUL.md was copied in as the
agent's identity. Each was stored as the agent's own words. On Riley's Hermes
memory, 233 of its 303 memories had been written that way. Mnemos's rule is
that nothing writes the agent's memory for it, so the provider now only reads
(the wake, recall before a turn), keeps its upkeep, and mirrors what the
agent itself writes into Hermes's built-in memory. The agent writes with its
own tools. What the provider wrote before is labelled as a tool's words, on a
store from before authorship was recorded and on one after, so it can never
make the agent who it is.
"""

from __future__ import annotations

import json
import sqlite3

from mnemos.integrations.hermes import HermesMnemosConfig, MnemosMemoryProviderCore
from mnemos.simple_runtime import MnemosRuntime
from mnemos.store.sqlite_store import EngramStore, hermes_auto_written
from tests.test_authorship import _PRE_V12_SCHEMA, _rows, _write

REMEMBER = "Remember that Riley wants the staging box wiped every Friday, don't forget."
FIXED = (
    "Fixed and verified the staging wipe job: it now runs every Friday at six "
    "and leaves the seed data in place."
)


def _provider(tmp_path):
    provider = MnemosMemoryProviderCore(
        HermesMnemosConfig(
            db_path=str(tmp_path / "mnemos.db"),
            agent_id="coder",
            person_id="riley",
            project_scope="mnemos",
        )
    )
    provider.initialize("session-1", hermes_home=tmp_path, agent_identity="coder", platform="cli")
    return provider


def _written(tmp_path) -> tuple[int, int]:
    """Memories, and notes not of Mnemos's own upkeep, in the store."""
    db = tmp_path / "mnemos.db"
    [memories] = _rows(db, "SELECT COUNT(*) AS n FROM engrams")
    [notes] = _rows(db, "SELECT COUNT(*) AS n FROM hypomnema_entries WHERE authored_by != 'system'")
    return memories["n"], notes["n"]


def test_a_turn_writes_nothing(tmp_path):
    provider = _provider(tmp_path)
    try:
        provider.sync_turn(
            REMEMBER,
            FIXED,
            session_id="session-1",
            messages=[{"role": "user", "content": REMEMBER}, {"role": "assistant", "content": FIXED}],
        )
        provider.sync_turn("ok", "ok", session_id="session-1", messages=[
            {"role": "user", "content": REMEMBER}, {"role": "assistant", "content": FIXED},
        ])
    finally:
        provider.shutdown()

    assert _written(tmp_path) == (0, 0)


def test_compression_and_the_end_of_a_session_write_nothing(tmp_path):
    messages = [{"role": "user", "content": REMEMBER}, {"role": "assistant", "content": FIXED}]
    provider = _provider(tmp_path)
    try:
        assert provider.on_pre_compress(messages) == ""
        provider.on_session_end(messages)
    finally:
        provider.shutdown()

    assert _written(tmp_path) == (0, 0)


def test_a_delegation_and_a_session_switch_write_nothing(tmp_path):
    provider = _provider(tmp_path)
    try:
        provider.on_delegation("Wipe the staging box", FIXED, child_session_id="child-1")
        provider.on_session_switch("session-2", parent_session_id="session-1", reset=True)
    finally:
        provider.shutdown()

    assert _written(tmp_path) == (0, 0)


def test_soul_md_is_hermes_to_show_not_copied_in_as_identity(tmp_path):
    soul = tmp_path / "SOUL.md"
    soul.write_text("You are Hermes-Coder, a precise local-first engineering agent.", encoding="utf-8")
    (tmp_path / "AGENTS.md").write_text("Run the tests before calling anything done.", encoding="utf-8")

    _provider(tmp_path).shutdown()

    assert _written(tmp_path) == (0, 0)
    assert soul.read_text(encoding="utf-8") == "You are Hermes-Coder, a precise local-first engineering agent."


def test_what_the_agent_writes_is_still_kept(tmp_path):
    provider = _provider(tmp_path)
    try:
        captured = json.loads(provider.handle_tool_call(
            "mnemos_identity_capture",
            {"content": "The staging box is wiped every Friday at six; the seed data stays."},
        ))
        provider.on_memory_write("add", "memory", "Riley's staging box keeps its seed data.")
    finally:
        provider.shutdown()

    assert captured["status"] == "captured"
    assert _written(tmp_path) == (2, 2)
    kinds = {row["author_kind"] for row in _rows(tmp_path / "mnemos.db", "SELECT author_kind FROM engrams")}
    assert kinds == {"agent"}


# The provider's own openings, as it wrote them before 0.4.1.
AUTO_WRITTEN = [
    f"User continuity from Hermes turn: {REMEMBER}",
    f"Hermes project outcome: {FIXED}",
    f"Hermes session-end user continuity: {REMEMBER}",
    f"Hermes session-end outcome: {FIXED}",
    f"Hermes pre-compression user continuity: {REMEMBER}",
    f"Hermes pre-compression outcome: {FIXED}",
    f"Hermes turn-sync outcome: {FIXED}",
    "Hermes session continuity moved from session-1 to session-2.",
    f"Hermes delegation handoff recorded: task=Wipe the staging box result={FIXED}",
    "Hermes identity bootstrap from SOUL.md: You are Hermes-Coder.",
    "Hermes project-context bootstrap from AGENTS.md: Run the tests first.",
    "Hermes runtime identity bootstrap: profile=coder platform=cli scope=coder/riley/mnemos.",
    f"Uncertain Hermes continuity candidate: {REMEMBER}",
]
OWN = [
    "Hermes is the name Riley gave this agent; the staging box is mine to keep tidy.",
    "User continuity matters more than speed here, I think.",
]


def test_the_fingerprint_is_the_providers_openings_and_nothing_else():
    assert all(hermes_auto_written(text) for text in AUTO_WRITTEN)
    assert not any(hermes_auto_written(text) for text in OWN)


def _insert_memories(conn, schema_has_authors: bool) -> dict[str, str]:
    stamp = "2026-07-10T00:00:00+00:00"
    ids = {}
    for index, content in enumerate(AUTO_WRITTEN + OWN):
        engram_id = f"engram_{index:02d}"
        ids[engram_id] = content
        columns = ("id, content, content_at_encoding, tags, source, owner_agent_id, person_id, "
                   "project_scope, created_at, last_accessed")
        values = [engram_id, content, content, json.dumps(["continuity"]),
                  json.dumps({"type": "session"}), "coder", "riley", "mnemos", stamp, stamp]
        if schema_has_authors:
            columns += ", author_kind, author_model"
            values += ["agent", "gpt-6"]
        conn.execute(
            f"INSERT INTO engrams ({columns}) VALUES ({', '.join('?' for _ in values)})", values,
        )
        conn.execute(
            "INSERT INTO hypomnema_entries (id, agent_id, person_id, project_scope, content, "
            "source, created_at, last_revised_at, graduated_to_engram_id"
            + (", authored_by, author_model" if schema_has_authors else "")
            + ") VALUES (?, 'coder', 'riley', 'mnemos', ?, 'observed', ?, ?, ?"
            + (", 'agent', 'gpt-6'" if schema_has_authors else "") + ")",
            (f"hyp_{index:02d}", content, stamp, stamp, engram_id),
        )
    return ids


def _kinds(db) -> dict[str, tuple]:
    memories = {row["content"]: row["author_kind"] for row in _rows(db, "SELECT content, author_kind FROM engrams")}
    notes = {
        row["content"]: (row["authored_by"], row["author_model"])
        for row in _rows(db, "SELECT content, authored_by, author_model FROM hypomnema_entries")
    }
    return {content: (memories[content], *notes[content]) for content in memories}


def test_a_store_from_before_authorship_labels_them_a_tools(tmp_path):
    db = tmp_path / "hermes.db"
    conn = sqlite3.connect(str(db))
    conn.executescript(_PRE_V12_SCHEMA)
    conn.execute("INSERT INTO meta (key, value) VALUES ('schema_version', '11')")
    _insert_memories(conn, schema_has_authors=False)
    conn.commit()
    conn.close()

    EngramStore(str(db)).close()

    kinds = _kinds(db)
    assert {content: kind[0] for content, kind in kinds.items() if content in AUTO_WRITTEN} == {
        content: "tool" for content in AUTO_WRITTEN
    }
    assert {kinds[content][0] for content in OWN} == {"agent"}


def test_a_store_that_called_them_the_agents_is_put_right_once(tmp_path):
    db = tmp_path / "hermes.db"
    EngramStore(str(db)).close()
    conn = sqlite3.connect(str(db))
    _insert_memories(conn, schema_has_authors=True)
    conn.execute("DELETE FROM meta WHERE key = 'hermes_auto_writes_labeled'")
    conn.commit()
    conn.close()

    EngramStore(str(db)).close()

    kinds = _kinds(db)
    for content in AUTO_WRITTEN:
        assert kinds[content] == ("tool", "unknown", ""), content
    for content in OWN:
        assert kinds[content] == ("agent", "agent", "gpt-6"), content
    [(value,)] = [tuple(row.values()) for row in _rows(
        db, "SELECT value FROM meta WHERE key = 'hermes_auto_writes_labeled'")]
    assert json.loads(value)["memories"] == len(AUTO_WRITTEN)

    # Once: what the agent later writes in the same words is its own.
    _write(db, "UPDATE engrams SET author_kind = 'agent' WHERE content = ?", (AUTO_WRITTEN[0],))
    EngramStore(str(db)).close()
    assert _kinds(db)[AUTO_WRITTEN[0]][0] == "agent"


def test_recall_says_a_tools_words_are_not_the_agents(tmp_path):
    provider = _provider(tmp_path)
    try:
        provider.handle_tool_call("mnemos_identity_capture", {"content": "The staging box is wiped every Friday."})
        # As the provider wrote it before 0.4.1: through the agent's own capture.
        provider._capture(f"Hermes project outcome: {FIXED}")
    finally:
        provider.shutdown()
    _write(tmp_path / "mnemos.db", "DELETE FROM meta WHERE key = 'hermes_auto_writes_labeled'")

    runtime = MnemosRuntime(
        db_path=str(tmp_path / "mnemos.db"), agent_id="coder", person_id="riley", project_scope="mnemos",
    )
    try:
        recalled = runtime.recall("staging box wiped Friday", max_results=4)
    finally:
        runtime.close()

    rows = recalled.split("\n- ")
    [tools] = [row for row in rows if "Hermes project outcome" in row]
    [own] = [row for row in rows if "wiped every Friday." in row]
    assert "from a tool, not yours" in tools
    assert "from a tool" not in own
