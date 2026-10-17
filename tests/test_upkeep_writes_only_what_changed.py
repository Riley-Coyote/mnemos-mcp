"""A maintenance pass writes only what it changed.

The decay pass saved every memory it read, whole: its row, its word index
entry (a delete that reads the whole index) and every one of its links, each
in a write of its own. The softening pass saved every memory it looked at,
softened or not. On a copy of a real store that was about 1,700 writes and
12,000 link rows in one cycle that changed nothing but the fourth decimal of
how accessible memories were: 3.5 s for decay and 3.1 s for softening, and the
stream of writes held the store's lock against other sessions' captures, which
waited up to 7 s behind it. Now decay writes the four numbers it moves, for
the memories whose numbers moved, in one transaction, and softening saves a
memory only when it changed its words: 0.11 s and 0.07 s on the same copy.
"""

from datetime import datetime, timedelta, timezone

import pytest

from mnemos.consolidation.decay import run_decay_pass
from mnemos.consolidation.softening import run_softening_pass
from mnemos.simple_runtime import MnemosRuntime
from mnemos.store.sqlite_store import EngramStore

LONG_AGO = "2026-01-01T00:00:00+00:00"


@pytest.fixture
def runtime(tmp_path):
    runtime = MnemosRuntime(db_path=tmp_path / "memory.db", use_dedicated_model=False, agent_id="demo")
    yield runtime
    runtime.close()


def _capture(runtime, content):
    said = runtime.capture(content=content)
    return next(line.split(": ", 1)[1] for line in said.splitlines() if line.startswith("Memory ID: "))


def _untouched_since(runtime, engram_id, accessibility, resolution=1.0):
    runtime._store._get_conn().execute(
        "UPDATE engrams SET created_at = ?, last_accessed = ?, accessibility = ?, resolution = ? "
        "WHERE id = ?",
        (LONG_AGO, LONG_AGO, accessibility, resolution, engram_id),
    )
    runtime._store._commit()


def _lived_every_day_since(runtime, start):
    day = datetime.fromisoformat(start)
    while day <= datetime.now(timezone.utc):
        runtime._store.mark_lived("demo", day)
        day += timedelta(days=1)


def _calls(monkeypatch, store, name):
    """Every call ``store`` gets to ``name``, still made; none when it has no
    such method."""
    calls = []
    original = getattr(store, name, None)
    if original is None:
        return calls

    def spy(*args, **kwargs):
        calls.append(args)
        return original(*args, **kwargs)

    monkeypatch.setattr(store, name, spy)
    return calls


def _decay(runtime, max_elapsed_hours):
    return run_decay_pass(
        runtime._store, {}, agent_id="demo",
        person_id=runtime.scope.person_id, project_scope=runtime.scope.project_scope,
        max_elapsed_hours=max_elapsed_hours,
    )


def test_decay_writes_the_numbers_it_moved_and_saves_no_memory_whole(runtime, monkeypatch, tmp_path):
    ids = [
        _capture(runtime, "Riley keeps the ferry timetable on the fridge."),
        _capture(runtime, "The fern by the window gets water on Sundays."),
    ]
    for engram_id in ids:
        _untouched_since(runtime, engram_id, accessibility=0.5)
    _lived_every_day_since(runtime, LONG_AGO)
    whole = _calls(monkeypatch, runtime._store, "save_engram")
    moved = _calls(monkeypatch, runtime._store, "save_fading")

    stats = _decay(runtime, max_elapsed_hours=24 * 30)

    assert whole == [], "a decay pass saved a memory whole"
    assert stats["engrams_decayed"] == 2, stats
    assert len(moved) == 1 and {engram.id for engram in moved[0][0]} == set(ids)
    # And what it wrote is what another process reads.
    reopened = EngramStore(tmp_path / "memory.db")
    try:
        for engram_id in ids:
            assert reopened.get_engram(engram_id).accessibility < 0.5
    finally:
        reopened.close()


def test_decay_writes_nothing_when_nothing_moved(runtime, monkeypatch):
    _capture(runtime, "Riley keeps the ferry timetable on the fridge.")
    _capture(runtime, "The fern by the window gets water on Sundays.")
    whole = _calls(monkeypatch, runtime._store, "save_engram")
    moved = _calls(monkeypatch, runtime._store, "save_fading")

    stats = _decay(runtime, max_elapsed_hours=0)

    assert stats["engrams_processed"] == 2, stats
    assert whole == [] and moved == []


def test_a_memory_that_goes_dormant_is_written_dormant(runtime, tmp_path):
    engram_id = _capture(runtime, "Riley keeps the ferry timetable on the fridge.")
    _untouched_since(runtime, engram_id, accessibility=0.055)
    _lived_every_day_since(runtime, LONG_AGO)

    stats = _decay(runtime, max_elapsed_hours=24)

    assert stats["engrams_dormant"] == 1, stats
    reopened = EngramStore(tmp_path / "memory.db")
    try:
        assert reopened.get_engram(engram_id).state == "dormant"
    finally:
        reopened.close()


def test_softening_saves_only_the_memories_it_softened(runtime, monkeypatch):
    ids = [
        _capture(runtime, "Riley keeps the ferry timetable on the fridge."),
        _capture(runtime, "The fern by the window gets water on Sundays."),
    ]
    for engram_id in ids:
        # Faded, with no meaning written yet, and no licence to blur its words.
        _untouched_since(runtime, engram_id, accessibility=0.1)
    whole = _calls(monkeypatch, runtime._store, "save_engram")

    stats = run_softening_pass(
        runtime._store, {}, None, agent_id="demo",
        person_id=runtime.scope.person_id, project_scope=runtime.scope.project_scope,
    )

    assert stats["engrams_evaluated"] == 2 and stats["engrams_softened"] == 0, stats
    assert whole == [], "softening saved memories whose words it left alone"
