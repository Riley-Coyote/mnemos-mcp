"""Promotion by lasting attention (WP-R12).

A note becomes a long-term memory because the agent kept coming back to it,
not because a timer or a word count said so: the agent revised it at least
once (a revision its model signed) and recalled it in at least two distinct
sessions, in its own words.

Since a capture is one object (R07), a capture's note is its memory's pair
from the start, and is never promoted. What can still become a memory is a
note with no memory of its own: one the advanced console wrote (a session
closed with the agent's synthesis), one older code kept for an answer it
could not apply, or one an integration wrote. Promotion read a confidence and
a salience its words were given, let a foundational note through unrevised,
and took notes in anyone's words but Mnemos's. It never fired on the
maintainer's store.

1. The rule: revised by the agent and recalled in two sessions, a note
   becomes a memory, across processes.
2. Recalled in one session only, never revised, or revised by no one who
   signed, a note stays a note, however sure or foundational.
3. A use is a request: a note returned among other rows was not used.
4. In the agent's own words: the memory's words are the note's and its
   meaning is left empty; a note in anyone else's words never becomes one.
5. Honest counts: health and the maintenance report say how many notes are
   ready and how many were promoted, each ready note with the rule's two
   numbers, and a capture is not counted as a promotion.
6. Code from before this change stands down once this code opens the store,
   and code older than its store promotes nothing.

No test reaches a real network, a real model or a real ~/.mnemos.
"""

from __future__ import annotations

import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import mnemos.store.embedding_index as ei
from mnemos.code_version import MAINTENANCE_CODE_VERSION
from mnemos.simple_runtime import MnemosRuntime, format_health_card
from mnemos.store.sqlite_store import EngramStore

SCOPE = {"agent_id": "nova", "person_id": "riley", "project_scope": "demo"}
MODEL = "claude-opus-5-5"

TIMETABLE = "The ferry timetable changes on the first Monday of each month."
TIMETABLE_REVISED = (
    "The ferry timetable changes on the first Monday of each month, "
    "and the harbour office posts it the Friday before."
)


@pytest.fixture(autouse=True)
def _no_model(monkeypatch):
    """No test loads the embedding model: recall finds by words alone."""
    monkeypatch.setattr(ei, "_check_local_deps", lambda: False)


def _runtime(db: Path) -> MnemosRuntime:
    return MnemosRuntime(db_path=str(db), use_dedicated_model=False, **SCOPE)


def _read(db: Path, sql: str, params: tuple = ()) -> list[tuple]:
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        return [tuple(row) for row in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def _closed_with_synthesis(db: Path, words: str, n: int = 0) -> str:
    """A note with no memory of its own, in the agent's words: what the
    advanced console's mnemos_session_close writes when the agent closes a
    session with its own synthesis."""
    store = EngramStore(str(db))
    try:
        session = f"harbour-watch-{n}"
        store.start_memory_session(session_id=session, **SCOPE, title=f"Harbour watch {n}")
        return store.close_session_to_hypomnema(session, synthesis=words, **SCOPE)["hypomnema_id"]
    finally:
        store.close()


def _revised(db: Path, note: str, words: str, *, by: str = MODEL) -> None:
    """A revision of the note in place, as mnemos_hypomnema_revise makes one:
    the reviser's words, signed by the reviser's model (``by``; empty for a
    revision no one signed, as a repair's)."""
    store = EngramStore(str(db))
    try:
        store.revise_hypomnema_entry(
            note, words, reason="said it better", **SCOPE, author_model=by, revised_by=by,
        )
    finally:
        store.close()


def _recalled(db: Path, monkeypatch, query: str, session: str) -> str:
    """One recall, in the named Claude Code session."""
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", session)
    rt = _runtime(db)
    try:
        return rt.recall(query)
    finally:
        rt.close()
        monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)


def _maintained(db: Path) -> str:
    rt = _runtime(db)
    try:
        return rt.maintain()
    finally:
        rt.close()


def _pair_of(db: Path, note: str) -> str | None:
    return _read(db, "SELECT graduated_to_engram_id FROM hypomnema_entries WHERE id = ?",
                 (note,))[0][0]


def _memories(db: Path) -> set[str]:
    return {row[0] for row in _read(db, "SELECT id FROM engrams")}


# ── 1. The rule ──

_IN_ANOTHER_PROCESS = """
import sys
import mnemos.store.embedding_index as ei
ei._check_local_deps = lambda: False
from mnemos.simple_runtime import MnemosRuntime

runtime = MnemosRuntime(db_path=sys.argv[1], agent_id="nova", person_id="riley",
                        project_scope="demo", use_dedicated_model=False)
try:
    print(getattr(runtime, sys.argv[2])(*sys.argv[3:]))
finally:
    runtime.close()
"""


def _in_another_process(db: Path, home: Path, call: str, *args: str, session: str = "") -> str:
    """One runtime call in a process of its own, as each session is."""
    env = {
        "HOME": str(home),
        "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
        "MNEMOS_DISABLE_DOTENV": "1",
        "PYTHONPATH": ":".join(sys.path),
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    if session:
        env["CLAUDE_CODE_SESSION_ID"] = session
    done = subprocess.run(
        [sys.executable, "-c", _IN_ANOTHER_PROCESS, str(db), call, *args],
        capture_output=True, text=True, timeout=180, env=env,
    )
    assert done.returncode == 0, done.stderr
    return done.stdout


def test_a_note_revised_and_recalled_in_two_sessions_becomes_a_memory(tmp_path):
    """Written in one process, revised in another, asked for by its id in two
    sessions (each its own process), promoted by a maintenance cycle in a
    fifth, and recalled as a memory in a sixth."""
    db = tmp_path / "memory.db"
    home = tmp_path / "home"
    home.mkdir()
    note = _closed_with_synthesis(db, TIMETABLE)
    _revised(db, note, TIMETABLE_REVISED)
    for session in ("session-monday", "session-friday"):
        shown = _in_another_process(db, home, "recall", note, session=session)
        assert TIMETABLE_REVISED in shown, shown

    said = _in_another_process(db, home, "maintain")

    memory = _pair_of(db, note)
    assert memory, f"a note the agent kept coming back to stayed a note:\n{said}"
    assert "Promoted continuity notes: 1 of 1 candidate" in said, said
    assert (
        f"note {note}: revised 1 time, recalled in 2 sessions; now memory {memory}" in said
    ), said
    found = _in_another_process(db, home, "recall", "harbour office posts the timetable")
    assert "Durable memories:" in found and memory in found, found


# ── 2. One session, never revised, or revised by no one who signed ──


@pytest.mark.parametrize(
    "case",
    ["recalled in one session", "never revised", "revised by no one who signed"],
)
def test_a_note_without_lasting_attention_stays_a_note(tmp_path, monkeypatch, case):
    """Each note is as sure and as salient as promotion used to want, and
    foundational: by the old rule each became a memory at the next cycle."""
    db = tmp_path / "memory.db"
    store = EngramStore(str(db))
    try:
        note = store.write_hypomnema_entry(
            TIMETABLE, **SCOPE, source="observed", authored_by="agent", author_id="nova",
            author_model=MODEL, confidence=0.95, salience=0.9, foundational=True,
        )
    finally:
        store.close()
    if case != "never revised":
        unsigned = case == "revised by no one who signed"
        _revised(db, note, TIMETABLE_REVISED, by="" if unsigned else MODEL)
    sessions = ["session-monday"] * 2 if case == "recalled in one session" else [
        "session-monday", "session-friday",
    ]
    for session in sessions:
        assert "The ferry timetable changes" in _recalled(db, monkeypatch, note, session)

    said = _maintained(db)

    assert _pair_of(db, note) is None, f"{case}, and it became a memory:\n{said}"
    assert "Promoted continuity notes: 0 of 0 candidates" in said, said



def test_uses_older_than_the_trace_keeps_do_not_count(tmp_path, monkeypatch):
    """A store idle past TRACE_KEEP_DAYS still holds its old recall rows until
    the trace next writes, which maintenance does only after promoting: those
    stale uses must not count."""
    db = tmp_path / "memory.db"
    store = EngramStore(str(db))
    try:
        note = store.write_hypomnema_entry(
            TIMETABLE, **SCOPE, source="observed", authored_by="agent", author_id="nova",
            author_model=MODEL,
        )
    finally:
        store.close()
    _revised(db, note, TIMETABLE_REVISED)
    for session in ("session-monday", "session-friday"):
        _recalled(db, monkeypatch, note, session)
    conn = sqlite3.connect(str(db))
    try:
        old = (datetime.now(timezone.utc) - timedelta(days=91)).isoformat()
        conn.execute("UPDATE memory_trace SET at = ? WHERE tool = 'recall'", (old,))
        conn.commit()
    finally:
        conn.close()

    said = _maintained(db)

    assert _pair_of(db, note) is None, f"stale uses promoted the note:\n{said}"


# ── 3. A use is a request ──


def test_a_note_returned_among_other_rows_was_not_used(tmp_path, monkeypatch):
    """A recall that returns the note beside other memories, in two sessions,
    is not the agent coming back to it. Asked for by its id in two sessions,
    the same note is. The note is as sure and salient as the old rule wanted,
    and revised: by the old rule it became a memory at the first cycle."""
    db = tmp_path / "memory.db"
    rt = _runtime(db)
    try:
        for words in (
            "The ferry crew counts passengers at the gangway before the ferry leaves.",
            "Storm warnings close the ferry pier until the harbour master reopens it.",
        ):
            rt.capture(words, signed_as=MODEL)
        note = rt._store.write_hypomnema_entry(
            TIMETABLE, **SCOPE, source="observed", authored_by="agent", author_id="nova",
            author_model=MODEL, confidence=0.95, salience=0.9,
        )
    finally:
        rt.close()
    _revised(db, note, TIMETABLE_REVISED)

    for session in ("session-monday", "session-friday"):
        shown = _recalled(db, monkeypatch, "ferry", session)
        assert note in shown and "Durable memories:" in shown, (
            f"premise: the note comes back among other rows\n{shown}"
        )
    said = _maintained(db)
    assert _pair_of(db, note) is None, f"merely returned, and it became a memory:\n{said}"

    for session in ("session-saturday", "session-sunday"):
        _recalled(db, monkeypatch, note, session)
    said = _maintained(db)
    assert _pair_of(db, note), f"asked for in two sessions, and it stayed a note:\n{said}"


# ── 4. In the agent's own words ──


def _kept_coming_back_to(db: Path, monkeypatch, note: str) -> None:
    _revised(db, note, _read(db, "SELECT content FROM hypomnema_entries WHERE id = ?",
                             (note,))[0][0] + " Checked again at dawn.")
    for session in ("session-monday", "session-friday"):
        _recalled(db, monkeypatch, note, session)


def test_only_the_agents_own_words_become_a_memory_and_unchanged(tmp_path, monkeypatch):
    """Notes in someone else's words get the same attention as the agent's:
    revised and asked for in two sessions. The old rule promoted every one
    but Mnemos's. Only the agent's becomes a memory, holding exactly the
    note's words, with no meaning written for it, signed as the note was."""
    db = tmp_path / "memory.db"
    store = EngramStore(str(db))
    try:
        sure = {"confidence": 0.95, "salience": 0.9, "foundational": True}
        others = {
            # setup's frame around the person's own answer
            "co-formed": store.write_hypomnema_entry(
                "Riley starting context: the harbour is where we work.",
                **SCOPE, source="co-formed", domain="identity", **sure,
            ),
            # a note whose writer nobody recorded
            "unknown": store.write_hypomnema_entry(
                "The chandlery on the quay sells rope by the fathom.",
                **SCOPE, source="observed", **sure,
            ),
            # Mnemos's summary of a session closed without the agent's words
            "system": store.write_hypomnema_entry(
                "Session continuity from Harbour watch: decision: the pier gate sticks.",
                **SCOPE, source="synthesized", authored_by="system", **sure,
            ),
        }
    finally:
        store.close()
    mine = _closed_with_synthesis(db, TIMETABLE)
    for note in (*others.values(), mine):
        _kept_coming_back_to(db, monkeypatch, note)
    words = _read(db, "SELECT content FROM hypomnema_entries WHERE id = ?", (mine,))[0][0]
    before = _memories(db)

    said = _maintained(db)

    assert {kind: _pair_of(db, note) for kind, note in others.items()} == {
        kind: None for kind in others
    }, f"a note in someone else's words became a memory:\n{said}"
    memory = _pair_of(db, mine)
    assert memory and _memories(db) - before == {memory}, said
    assert _read(
        db,
        "SELECT content, impact, impact_source, author_kind, author_model FROM engrams "
        "WHERE id = ?",
        (memory,),
    ) == [(words, "", "", "agent", MODEL)]


def test_setups_note_in_the_persons_words_never_becomes_a_memory(tmp_path, monkeypatch):
    """Advanced setup keeps the person's answer as their own memory, and a
    foundational note framing it ("Riley starting context: ..."). The old rule
    made that note a memory at the first cycle: the person's words, a second
    time, as nobody's."""
    pytest.importorskip("mcp.server.fastmcp")
    from mnemos import mcp_server
    from mnemos.config.loader import save_config

    for name in ("_store", "_encoder", "_llm_client", "_embedding_index", "_shared_pool"):
        monkeypatch.setattr(mcp_server, name, None)
    save_config({"setup_step": 3, "agent_id": "nova", "user_name": "Riley", "person_id": "riley"})
    mcp_server._config_invalidate()
    try:
        mcp_server.mnemos_setup("I'm Riley. Keep the harbour log private.")
        db = Path(mcp_server._store.db_path)
    finally:
        if mcp_server._store is not None:
            mcp_server._store.close()
        mcp_server._config_invalidate()
    [(note, by)] = _read(
        db, "SELECT id, authored_by FROM hypomnema_entries WHERE content LIKE 'Riley starting context:%'"
    )
    assert by == "coauthored", "premise"
    before = _memories(db)

    rt = MnemosRuntime(db_path=str(db), use_dedicated_model=False,
                       agent_id="nova", person_id="riley", project_scope="global")
    try:
        said = rt.maintain()
    finally:
        rt.close()

    assert _pair_of(db, note) is None, said
    assert _memories(db) == before, said


# ── 5. Honest counts ──


def test_health_and_the_maintenance_report_say_what_is_ready_and_what_was_promoted(
    tmp_path, monkeypatch,
):
    db = tmp_path / "memory.db"
    rt = _runtime(db)
    try:
        # A capture: its note is its memory's from the start, never promoted.
        rt.capture("Riley moors the dinghy at the north ladder.", signed_as=MODEL)
    finally:
        rt.close()
    often = _closed_with_synthesis(db, TIMETABLE, 1)
    _revised(db, often, TIMETABLE_REVISED)
    _revised(db, often, TIMETABLE_REVISED + " Twice, in summer.")
    for session in ("session-monday", "session-friday", "session-sunday"):
        _recalled(db, monkeypatch, often, session)
    twice = _closed_with_synthesis(db, "The tide turns an hour later at the outer buoy.", 2)
    _kept_coming_back_to(db, monkeypatch, twice)

    rt = _runtime(db)
    try:
        health = rt.health()
    finally:
        rt.close()
    assert health["counts"]["continuity_notes_promotion_candidates"] == 2
    assert health["counts"]["continuity_notes_promoted"] == 0, (
        "a capture's note was counted as promoted"
    )
    assert health["promotion"] == {
        "rule": {"revisions": 1, "sessions": 2},
        "candidates": 2,
        "promoted": 0,
        "ready": [
            {"id": often, "revised_by_agent": 2, "used_in_sessions": 3},
            {"id": twice, "revised_by_agent": 1, "used_in_sessions": 2},
        ],
    }
    card = format_health_card(health)
    assert (
        "Promotion:     2 notes ready to become memories, 0 promoted "
        "(ready: revised at least 1 time and recalled in at least 2 sessions)"
    ) in card, card
    assert f"note {often}: revised 2 times, recalled in 3 sessions" in card, card
    assert f"note {twice}: revised 1 time, recalled in 2 sessions" in card, card

    said = _maintained(db)

    first, second = _pair_of(db, often), _pair_of(db, twice)
    assert first and second, said
    assert "Promoted continuity notes: 2 of 2 candidates" in said, said
    assert f"note {often}: revised 2 times, recalled in 3 sessions; now memory {first}" in said
    assert f"note {twice}: revised 1 time, recalled in 2 sessions; now memory {second}" in said

    rt = _runtime(db)
    try:
        health = rt.health()
    finally:
        rt.close()
    assert health["promotion"]["candidates"] == 0
    assert health["promotion"]["promoted"] == 2
    assert health["counts"]["continuity_notes_promoted"] == 2
    assert "Promotion:     0 notes ready to become memories, 2 promoted" in format_health_card(health)


# ── 6. Code older than the store ──

VERSIONED = ("mnemos.code_version", "mnemos.simple_runtime", "mnemos.store.sqlite_store",
             "mnemos.retrieval.reactive")


def test_code_older_than_the_store_promotes_nothing(tmp_path, monkeypatch):
    """A server still running the code before this change promotes by the old
    rule: this foundational note became a memory at its next cycle, revised
    or not. Once this code has opened the store, that server stands down, and
    code older than its store promotes nothing, even a note the agent kept
    coming back to."""
    assert MAINTENANCE_CODE_VERSION >= 20, (
        "what promotion takes changed, and the code version was not raised"
    )
    db = tmp_path / "memory.db"
    store = EngramStore(str(db))
    try:
        note = store.write_hypomnema_entry(
            TIMETABLE, **SCOPE, source="observed", authored_by="agent", author_id="nova",
            author_model=MODEL, confidence=0.95, salience=0.9, foundational=True,
        )
    finally:
        store.close()
    _revised(db, note, TIMETABLE_REVISED)
    for session in ("session-monday", "session-friday"):
        _recalled(db, monkeypatch, note, session)
    assert _read(db, "SELECT value FROM meta WHERE key = 'min_code_version'") == [
        (str(MAINTENANCE_CODE_VERSION),)
    ]

    for module in VERSIONED:
        monkeypatch.setattr(f"{module}.MAINTENANCE_CODE_VERSION", MAINTENANCE_CODE_VERSION - 1,
                            raising=False)
    rt = _runtime(db)
    try:
        said = rt.maintain()
        promotion = rt._promote_candidates()
    finally:
        rt.close()

    assert "Cycle: skipped" in said, said
    assert promotion == {"candidates": [], "promoted": 0}
    assert _pair_of(db, note) is None
