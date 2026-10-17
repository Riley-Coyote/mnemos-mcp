"""A capture answers before its maintenance runs.

A capture that came due for maintenance ran the whole cycle before it
answered. In a Claude session on Oct 17 2026 two captures took 36.5 s and
37.1 s; the cycles they ran took 35.5 s and 35.1 s by their own log, and
changed nothing. A third capture, not due, took 0.9 s. Meanwhile the cycle's
writes held the store's lock, and other sessions' captures waited behind it.

Automatic maintenance now runs in a process of its own, started by the call
and detached from it, one at a time per scope. The call keeps what it needs:
recall's meaning index catches up before it answers.
"""

import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from mnemos import simple_runtime
from mnemos.consolidation.daemon import ConsolidationDaemon
from mnemos.simple_runtime import MnemosRuntime

FERRY = "Riley keeps the ferry timetable on the fridge."
FERN = "The fern by the window gets water on Sundays."


@pytest.fixture
def db(tmp_path, monkeypatch):
    # The default: the suite runs maintenance inline (conftest.py).
    monkeypatch.delenv("MNEMOS_MAINTENANCE", raising=False)
    return tmp_path / "memory.db"


@pytest.fixture
def runtime(db):
    runtime = MnemosRuntime(db_path=db, use_dedicated_model=False, agent_id="demo")
    yield runtime
    runtime.close()


@pytest.fixture
def started(monkeypatch):
    """The background processes calls start, recorded instead of started."""
    scopes = []
    monkeypatch.setattr(
        simple_runtime, "_spawn_upkeep", lambda scope: scopes.append(scope) or True, raising=False,
    )
    return scopes


@pytest.fixture
def cycles_here(monkeypatch):
    """The cycles that run in this process."""
    ran = []
    original = ConsolidationDaemon.run_cycle

    def run_cycle(self, *args, **kwargs):
        ran.append(kwargs)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(ConsolidationDaemon, "run_cycle", run_cycle)
    return ran


def _cycles_logged(db):
    conn = sqlite3.connect(db)
    try:
        return conn.execute(
            "SELECT COUNT(*) FROM consolidation_log WHERE pass_name = 'cycle'"
        ).fetchone()[0]
    finally:
        conn.close()


def test_a_capture_answers_before_its_maintenance_runs(runtime, started, cycles_here):
    said = runtime.capture(content=FERRY)

    assert cycles_here == [], "the cycle ran before the capture answered"
    assert [scope.agent_id for scope in started] == ["demo"]
    assert "Cycle: started in the background" in said, said


def test_the_background_process_runs_the_cycle(runtime, db):
    runtime.capture(content=FERRY)
    child = simple_runtime._UPKEEP_CHILDREN[-1]

    assert child.wait(timeout=180) == 0
    assert _cycles_logged(db) == 1
    assert not runtime._get_meta("upkeep_running"), "the claim outlived the process"
    assert not runtime._get_meta("upkeep_failed")


def test_one_process_at_a_time(runtime, db, started):
    runtime.capture(content=FERRY)
    # Another session, on the same store, while the first one's cycle runs.
    other = MnemosRuntime(db_path=db, use_dedicated_model=False, agent_id="demo")
    try:
        said = other.capture(content=FERN)
    finally:
        other.close()

    assert len(started) == 1
    assert "another process is running this memory's maintenance now" in said, said


def test_a_claim_left_by_a_process_that_died_lapses(runtime, started):
    runtime._set_meta("upkeep_running", json.dumps({
        "at": (datetime.now(timezone.utc) - timedelta(minutes=20)).isoformat(), "by": 1,
    }))

    said = runtime.capture(content=FERRY)

    assert len(started) == 1 and "Cycle: started in the background" in said, said


def test_nothing_starts_until_maintenance_is_due(runtime, started):
    runtime.maintain()  # asked for: runs here, and logs its cycle

    said = runtime.capture(content=FERRY)

    assert started == []
    assert "Completed: no maintenance needed yet (ran recently)" in said, said


def test_when_the_process_cannot_start_the_cycle_runs_here(runtime, monkeypatch, cycles_here):
    monkeypatch.setattr(simple_runtime, "_spawn_upkeep", lambda scope: False, raising=False)

    said = runtime.capture(content=FERRY)

    assert len(cycles_here) == 1 and "Cycle: shallow" in said, said
    assert not runtime._get_meta("upkeep_running")


def test_what_went_wrong_in_the_background_is_said_until_it_goes_right(runtime, db, started, monkeypatch):
    from mnemos.simple_runtime import run_background_upkeep

    scope = [str(db), "demo", runtime.scope.person_id, runtime.scope.project_scope]
    original = ConsolidationDaemon.run_cycle

    def locked(self, *args, **kwargs):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(ConsolidationDaemon, "run_cycle", locked)
    assert run_background_upkeep(scope) == 1
    said = runtime.capture(content=FERRY)
    assert "Last background maintenance" in said and "database is locked" in said, said

    monkeypatch.setattr(ConsolidationDaemon, "run_cycle", original)
    runtime._set_meta("upkeep_running", "")
    assert run_background_upkeep(scope) == 0
    said = runtime.capture(content=FERN)
    assert "Last background maintenance" not in said, said
    assert not runtime._get_meta("upkeep_running")


def test_inside_a_transaction_maintenance_stays_with_it(runtime, started, cycles_here):
    runtime._ensure_init()
    with runtime._store.transaction():
        runtime.maintain(auto=True)

    assert started == [] and len(cycles_here) == 1


def test_inline_runs_it_in_the_call_as_before(runtime, started, cycles_here, monkeypatch):
    monkeypatch.setenv("MNEMOS_MAINTENANCE", "inline")

    said = runtime.capture(content=FERRY)

    assert started == [] and len(cycles_here) == 1 and "Cycle: shallow" in said, said
