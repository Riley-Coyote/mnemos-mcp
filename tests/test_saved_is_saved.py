"""A write whose words are saved never reports failure afterwards.

A capture saves its memory and its note in one transaction, and then writes
meta (the session it was captured in, the empty-packet streak), its vector,
and starts its maintenance. When one of those later writes met another
process's lock, the capture raised "database is locked": the agent was told
its capture failed although the memory was kept, and an agent told that
captures again, so one thing was remembered twice.

Everything after the save is bookkeeping now (MnemosRuntime._after_saving).
It never fails the call: the first failure stops the rest, is logged once, and
the call answers with what it saved, as usual. The correction, the handoff and
the journal keep the same rule for what follows their saves. A note writes
nothing after its save but its trace row, which already never failed a call;
its test documents that.
"""

import json
import logging
import re
import sqlite3
from contextlib import contextmanager

import pytest

from mnemos.encoding.encoder import Encoder
from mnemos.simple_runtime import MnemosRuntime
from mnemos.store.sqlite_store import EngramStore

FERRY = "Riley keeps the ferry timetable on the fridge."
FERN = "The fern by the window gets water on Sundays."
LOCKED = "database is locked"


@pytest.fixture
def db(tmp_path):
    return tmp_path / "memory.db"


@pytest.fixture
def runtime(db):
    runtime = MnemosRuntime(db_path=db, use_dedicated_model=False, agent_id="demo")
    runtime._ensure_init()
    # A lock is given up on after a tenth of a second here, not the store's five.
    runtime._store._get_conn().execute("PRAGMA busy_timeout=100")
    yield runtime
    runtime.close()


@contextmanager
def _another_process_writing(db):
    """The store's write lock, held by another connection."""
    other = sqlite3.connect(db, timeout=0)
    other.execute("BEGIN IMMEDIATE")
    try:
        yield
    finally:
        other.rollback()
        other.close()


@pytest.fixture
def locked_meta(monkeypatch, db):
    """Meta writes, named, that meet another process's lock: a real one, held
    while the write runs and let go when it has failed."""
    names: set[str] = set()
    original = MnemosRuntime._set_meta

    def set_meta(self, name, value):
        if name not in names:
            return original(self, name, value)
        with _another_process_writing(db):
            return original(self, name, value)

    monkeypatch.setattr(MnemosRuntime, "_set_meta", set_meta)
    return names


def _locked(*args, **kwargs):
    raise sqlite3.OperationalError(LOCKED)


def _rows(db, sql, *params):
    conn = sqlite3.connect(db)
    try:
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


def _memories(db, state="active"):
    return [row[0] for row in _rows(db, "SELECT id FROM engrams WHERE state = ? ORDER BY id", state)]


def _said(result, label):
    match = re.search(rf"{label}: (\S+)", result)
    assert match, f"no {label} in: {result}"
    return match.group(1).rstrip(".")


def _logged(caplog):
    return [
        record for record in caplog.records
        if record.name == "mnemos.simple_runtime" and LOCKED in record.getMessage()
    ]


# ── The capture ──


def test_a_capture_whose_meta_write_meets_a_lock_answers_with_its_memory(
    runtime, db, locked_meta, caplog,
):
    locked_meta.add("last_capture_session")

    with caplog.at_level(logging.WARNING, logger="mnemos.simple_runtime"):
        said = runtime.capture(content=FERRY)

    memory_id = _said(said, "Memory ID")
    assert said.startswith("Captured continuity."), said
    assert _memories(db) == [memory_id], "one capture, one memory: the one it named"
    assert _rows(db, "SELECT COUNT(*) FROM hypomnema_entries WHERE entry_kind = 'continuity'") == [(1,)]
    assert f"Completed: not this time (OperationalError: {LOCKED}); the next call starts it" in said, said
    assert len(_logged(caplog)) == 1, "logged once"
    # Its trace row says what it wrote, as any capture's does.
    written = [json.loads(row[0]) for row in _rows(db, "SELECT written_ids FROM memory_trace WHERE tool = 'capture'")]
    assert written and memory_id in written[0], written

    # And the store is as the next call needs it.
    locked_meta.clear()
    said = runtime.capture(content=FERN)
    assert said.startswith("Captured continuity.") and len(_memories(db)) == 2, said


def test_a_capture_whose_vector_write_fails_answers_with_its_memory(runtime, db, monkeypatch):
    monkeypatch.setattr(Encoder, "finish", _locked)

    said = runtime.capture(content=FERRY)

    assert _memories(db) == [_said(said, "Memory ID")]


def test_a_capture_whose_maintenance_fails_answers_with_its_memory(runtime, db, monkeypatch):
    monkeypatch.setattr(MnemosRuntime, "maintain", _locked)

    said = runtime.capture(content=FERRY)

    assert _memories(db) == [_said(said, "Memory ID")]
    assert "Cycle: skipped" in said, said


def test_inside_a_host_mutation_the_failure_rolls_the_whole_write_back(runtime, db, monkeypatch):
    """There the save has not committed: the mutation is one durable
    operation, and a failure anywhere in it rolls all of it back. (Its
    transaction holds the lock, so the failure is raised, not met.)"""
    original = MnemosRuntime._set_meta

    def set_meta(self, name, value):
        if name == "last_capture_session":
            raise sqlite3.OperationalError(LOCKED)
        return original(self, name, value)

    monkeypatch.setattr(MnemosRuntime, "_set_meta", set_meta)

    with pytest.raises(sqlite3.OperationalError, match=LOCKED):
        runtime.execute_host_mutation(
            "capture", {"content": FERRY}, host_namespace="test", idempotency_key="one",
        )

    assert _memories(db) == []
    assert _rows(db, "SELECT COUNT(*) FROM host_mutations") == [(0,)]


# ── The other writes ──


def test_a_correction_whose_vector_write_fails_answers_with_its_replacement(runtime, db, monkeypatch):
    old = _said(runtime.capture(content=FERN), "Memory ID")
    monkeypatch.setattr(Encoder, "finish", _locked)

    said = runtime.correct("The fern by the window gets water on Saturdays.", target_id=old)

    new = re.search(r"captured correction (engram_\w+)", said).group(1)
    assert said.startswith(f"Archived memory {old} and captured correction {new}."), said
    assert _memories(db) == [new], "one correction, one replacement"
    assert _memories(db, "archived") == [old]


def test_a_correction_by_query_whose_maintenance_fails_answers_with_its_replacement(
    runtime, db, monkeypatch,
):
    old = _said(runtime.capture(content=FERRY), "Memory ID")
    monkeypatch.setattr(MnemosRuntime, "maintain", _locked)

    said = runtime.correct(
        "Riley keeps the ferry timetable in the drawer.", query="ferry timetable fridge",
    )

    new = _said(said, "Memory ID")
    assert said.startswith("Updated closest continuity note"), said
    assert _memories(db) == [new] and _memories(db, "archived") == [old]
    assert "Completed: not this time" in said, said


def test_a_correction_of_a_handoff_whose_indexing_fails_answers(runtime, db, monkeypatch):
    handoff = _said(runtime.handoff("Where I am: the ferry list."), "Handoff ID")
    monkeypatch.setattr(MnemosRuntime, "_index_for_recall", _locked)

    said = runtime.correct("Where I am: the fern list.", target_id=handoff)

    assert said == f"Updated continuity note {handoff}.", said
    assert _rows(db, "SELECT content FROM hypomnema_entries WHERE id = ?", handoff) == [
        ("Where I am: the fern list.",)
    ]


def test_a_handoff_whose_indexing_fails_answers_with_its_id(runtime, db, monkeypatch):
    monkeypatch.setattr(MnemosRuntime, "_index_for_recall", _locked)

    said = runtime.handoff("Where I am: the ferry list.")

    handoff = _said(said, "Handoff ID")
    assert said.startswith("Session handoff saved exactly as written."), said
    assert _rows(db, "SELECT id FROM hypomnema_entries WHERE entry_kind = 'handoff'") == [(handoff,)]


def test_a_journal_entry_whose_indexing_fails_answers_with_its_id(runtime, db, monkeypatch):
    monkeypatch.setattr(MnemosRuntime, "_index_for_recall", _locked)

    said = runtime.journal("The ferry was late and I didn't mind.")

    entry = _said(said, "Journal ID")
    assert said.startswith("Journal entry kept exactly as written."), said
    assert _rows(db, "SELECT id FROM journal_entries") == [(entry,)]


def test_a_note_whose_trace_write_fails_answers_with_its_id(runtime, db, monkeypatch):
    """Its one write after the save is the trace row, which never failed a
    call: this documents that, and passed before the change too."""
    monkeypatch.setattr(EngramStore, "record_trace", _locked)

    said = runtime.note("I made the ferry list.", kind="made")

    note = _said(said, "Note ID")
    assert said.startswith("Note kept exactly as written."), said
    assert _rows(db, "SELECT id FROM notes") == [(note,)]
