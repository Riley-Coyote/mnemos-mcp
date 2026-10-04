"""Lived time: memories fade with the days the agent lived, not the calendar.

Mnemos is the memory of one mind, and that mind lives only while it runs. A
month in which the person never opened a session cost the agent a month of
fading, so how often the person came back decided how much the agent
remembered. Now a day counts when the agent did anything at all, and decay,
the recency floor, softening's minimum age and the month before a belief is
put again run on those days. An agent used every day keeps wall-clock time.

The new modules are imported inside each test, so each fails on the code
before this at its own line.
"""

from __future__ import annotations

import math
import re
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from mnemos.core.belief import Belief
from mnemos.core.engram import Engram
from mnemos.simple_runtime import MnemosRuntime
from mnemos.store.sqlite_store import EngramStore

pytestmark = pytest.mark.lived_time

SCOPE = {"agent_id": "nova", "person_id": "riley", "project_scope": "demo"}
STORE_SCOPE = {"owner_agent_id": "nova", "person_id": "riley", "project_scope": "demo"}


def _utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


def _today() -> datetime:
    return datetime.now(timezone.utc)


def _day(days_ago: int) -> str:
    return (_today() - timedelta(days=days_ago)).date().isoformat()


def _memory(store: EngramStore, *, accessibility: float, last_accessed: datetime) -> str:
    engram = Engram(
        content="The harbour ledger balances at the end of each month.",
        accessibility=accessibility, stability=0.0,
        last_accessed=last_accessed.isoformat(), **STORE_SCOPE,
    )
    store.save_engram(engram)
    return engram.id


def _live(store: EngramStore, *days_ago: int) -> None:
    for ago in days_ago:
        store.mark_lived("nova", _today() - timedelta(days=ago))


def _decay(store: EngramStore, config: dict) -> None:
    from mnemos.consolidation.decay import run_decay_pass

    run_decay_pass(store, config, **SCOPE)


def _wall_decay(accessibility: float, hours: float, rate: float) -> float:
    """What the pass made of a memory with no stability, links or tags before
    lived time: ``hours`` of wall-clock decay, stored to four places."""
    return round(accessibility * math.exp(-rate * hours), 4)


# 1. The clock


def test_the_clock_counts_only_lived_days():
    from mnemos.consolidation.lived import LivedClock

    clock = LivedClock(["2026-10-01", "2026-10-03"])
    start = "2026-10-01T06:00:00+00:00"
    end = _utc(2026, 10, 3, 6)
    # 18 hours of the 1st, none of the 2nd, 6 of the 3rd.
    assert clock.hours_between(start, end) == 24.0
    assert clock.days_since(start, end) == 1


# 2. An absence


def _state(engram: Engram) -> str:
    return str(getattr(engram.state, "value", engram.state))


def test_an_absence_costs_no_memory(tmp_path):
    store = EngramStore(str(tmp_path / "memory.db"))
    try:
        engram_id = _memory(store, accessibility=0.5,
                            last_accessed=_today() - timedelta(days=30))
        before = _state(store.get_engram(engram_id))
        _decay(store, {})
        after = store.get_engram(engram_id)
        assert after.accessibility == 0.5
        assert _state(after) == before
    finally:
        store.close()


def test_the_floor_holds_what_was_used_in_the_last_lived_hours(tmp_path):
    # After an absence, the last memories the agent used are still the last it
    # lived with: held at the floor, as they would have been then.
    store = EngramStore(str(tmp_path / "memory.db"))
    try:
        engram_id = _memory(store, accessibility=0.3,
                            last_accessed=_today() - timedelta(days=30))
        _decay(store, {})
        after = store.get_engram(engram_id)
        assert after.accessibility == 0.4
        assert _state(after) not in ("archived", "dormant")
    finally:
        store.close()


# 3. A lived month (guard of the calibration)


def test_a_lived_month_fades_as_before(tmp_path):
    rate = 0.001
    store = EngramStore(str(tmp_path / "memory.db"))
    try:
        last = _today() - timedelta(days=30)
        engram_id = _memory(store, accessibility=0.9, last_accessed=last)
        _live(store, *range(31))  # the day of its last use through today
        hours = (_today() - last).total_seconds() / 3600
        _decay(store, {"decay_rate": rate})
        after = store.get_engram(engram_id)
        assert after.accessibility == pytest.approx(_wall_decay(0.9, hours, rate), abs=1e-6)
    finally:
        store.close()


# 4. Two lived days in a month


def test_two_lived_days_in_a_month_are_two_days_of_fading(tmp_path):
    store = EngramStore(str(tmp_path / "memory.db"))
    try:
        engram_id = _memory(store, accessibility=0.9,
                            last_accessed=_today() - timedelta(days=30))
        _live(store, 20, 10)  # neither the day of its last use nor today
        _decay(store, {})
        after = store.get_engram(engram_id)
        expected = _wall_decay(0.9, 48.0, 0.01)
        assert expected > 0.4  # above the recency floor: not floored
        assert after.accessibility == pytest.approx(expected, abs=1e-6)
    finally:
        store.close()


# 5. What marks a day


def test_living_marks_the_day(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / ".mnemos").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    today = _today().date().isoformat()

    captured = tmp_path / "captured.db"
    runtime = MnemosRuntime(db_path=str(captured), use_dedicated_model=False, **SCOPE)
    try:
        runtime.capture("The harbour ledger balances at the end of each month.")
    finally:
        runtime.close()
    store = EngramStore(str(captured))
    try:
        assert store.lived_days("nova") == [today]
    finally:
        store.close()

    from mnemos.cli import main

    woken = tmp_path / "woken.db"
    EngramStore(str(woken)).close()
    assert main(["hook", "session-start", "--db-path", str(woken), "--agent-id", "nova",
                 "--person-id", "riley", "--project-scope", "demo"]) == 0
    store = EngramStore(str(woken))
    try:
        assert store.lived_days("nova") == [today]
    finally:
        store.close()

    maintained = tmp_path / "maintained.db"
    runtime = MnemosRuntime(db_path=str(maintained), use_dedicated_model=False, **SCOPE)
    try:
        runtime.maintain()
    finally:
        runtime.close()
    store = EngramStore(str(maintained))
    try:
        assert store.lived_days("nova") == []
    finally:
        store.close()


def test_a_person_at_the_command_line_isnt_the_agent_living(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / ".mnemos").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    from mnemos.cli import main

    remembered = tmp_path / "remembered.db"
    assert main(["remember", "The harbour ledger balances at the end of each month.",
                 "--db-path", str(remembered), "--agent-id", "nova",
                 "--person-id", "riley", "--project-scope", "demo"]) == 0
    store = EngramStore(str(remembered))
    try:
        assert store.count_engrams("nova") == 1  # the remember happened
        assert store.lived_days("nova") == []
    finally:
        store.close()

    # The MCP server's runtime is a default one: the agent's own call.
    captured = tmp_path / "captured.db"
    runtime = MnemosRuntime(db_path=str(captured), use_dedicated_model=False, **SCOPE)
    try:
        runtime.capture("The harbour ledger balances at the end of each month.")
    finally:
        runtime.close()
    store = EngramStore(str(captured))
    try:
        assert store.lived_days("nova") == [_today().date().isoformat()]
    finally:
        store.close()


# 6. Older stores


def test_older_stores_are_backfilled(tmp_path):
    from mnemos.store.sqlite_store import SCHEMA_VERSION

    db = tmp_path / "memory.db"
    EngramStore(str(db)).close()
    conn = sqlite3.connect(str(db))
    for at in ("2026-09-01T10:00:00+00:00", "2026-09-01T23:00:00+00:00",
               "2026-09-14T08:30:00.123456+00:00", "2026-10-02T12:00:00+00:00"):
        conn.execute("INSERT INTO memory_trace (at, tool, agent_id) VALUES (?, 'capture', 'nova')", (at,))
    conn.execute("DROP TABLE IF EXISTS lived_days")
    conn.execute("UPDATE meta SET value = ? WHERE key = 'schema_version'", (str(SCHEMA_VERSION - 1),))
    conn.commit()
    conn.close()

    store = EngramStore(str(db))
    try:
        assert store.lived_days("nova") == ["2026-09-01", "2026-09-14", "2026-10-02"]
        assert store.get_meta("schema_version") == str(SCHEMA_VERSION)
    finally:
        store.close()


# 7. The reaffirmation month


@pytest.mark.parametrize("lived, put", [(5, 0), (30, 1)])
def test_reaffirmation_waits_for_lived_days(tmp_path, lived, put):
    runtime = MnemosRuntime(db_path=str(tmp_path / "memory.db"), use_dedicated_model=False, **SCOPE)
    try:
        result = runtime.capture("The rendered page showed the missing alignment.",
                                 impact="The render is the honest judge.")
        target = re.search(r"Memory ID: (engram_\w+)", result).group(1)
        long_ago = (_today() - timedelta(days=40)).isoformat()
        belief = Belief(agent_id="nova", content="The render is the honest judge.",
                        confidence=0.6, source="agent", supporting_engram_ids=[target])
        belief.last_challenged = long_ago
        belief.created_at = long_ago
        runtime._store.save_belief(belief)
        conn = runtime._store._get_conn()
        conn.execute("DELETE FROM lived_days")
        conn.commit()
        _live(runtime._store, *range(lived))  # the last `lived` days, today among them

        assert runtime._enqueue_belief_reaffirmation(set()) == put
    finally:
        runtime.close()
