"""One maintenance cycle at a time, the scheduled job's too.

A capture's maintenance runs in a process of its own, and the capture claims
the scope's maintenance first (``upkeep_running``), so two sessions' captures
never start two cycles. The scheduled job (``mnemos consolidate``, every four
hours, and ``--deep`` daily) took no claim, and the activity gate a capture
asks reads the cycle log, which a cycle writes when it ends. A capture while
the job's cycle ran found nothing running and nothing recent, and started a
second cycle beside it: on a scratch store (Oct 19 2026) a capture made while
the job's cycle ran started one in the background, which ran and finished
inside the job's.

Now the job holds the same claim while it runs and gives it up when it ends,
whether or not its cycle went right. A capture that finds the claim held
starts no cycle, and a job that finds a capture's maintenance running starts
none either. Each claim carries the token of whoever took it, and only that
token gives it up: a holder that ran past the claim's lapse (fifteen minutes)
and finds a newer claim when it ends leaves it in place.
"""

import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from mnemos import simple_runtime
from mnemos.cli import main
from mnemos.consolidation.daemon import ConsolidationDaemon
from mnemos.simple_runtime import MnemosRuntime, run_background_upkeep

FERRY = "Riley keeps the ferry timetable on the fridge."
FERN = "The fern by the window gets water on Sundays."
SCOPE = {"agent_id": "demo", "person_id": "riley", "project_scope": "home"}
CLAIM = "simple:demo:riley:home:upkeep_running"
RUNNING = "another process is running this memory's maintenance now"


@pytest.fixture
def db(tmp_path, monkeypatch):
    # Captures maintain in the background, the default (the suite runs it
    # inline: conftest.py).
    monkeypatch.delenv("MNEMOS_MAINTENANCE", raising=False)
    return tmp_path / "memory.db"


@pytest.fixture
def started(monkeypatch):
    """The background processes captures start, recorded instead of started:
    each one's scope, and the token of the claim it would give up."""
    processes = []
    monkeypatch.setattr(
        simple_runtime, "_spawn_upkeep",
        lambda scope, token="": processes.append((scope, token)) or True, raising=False,
    )
    return processes


@pytest.fixture
def during_the_cycle(monkeypatch):
    """What happens while a cycle runs: each callable, once, as the cycle
    starts (in the job, after it took its claim)."""
    calls = []
    original = ConsolidationDaemon.run_cycle

    def run_cycle(self, *args, **kwargs):
        while calls:
            calls.pop(0)()
        return original(self, *args, **kwargs)

    monkeypatch.setattr(ConsolidationDaemon, "run_cycle", run_cycle)
    return calls


@pytest.fixture
def seeded(db, started):
    """A store with one memory, its maintenance due: no cycle has run, and no
    claim is held (the capture's process, recorded and not started, would
    have let go of its claim)."""
    runtime = MnemosRuntime(db_path=db, use_dedicated_model=False, **SCOPE)
    try:
        runtime.capture(content=FERRY)
        runtime._release_upkeep()
    finally:
        runtime.close()
    started.clear()
    return db


def _job(db):
    """The scheduled job, as launchd runs it."""
    return main([
        "--agent-id", SCOPE["agent_id"], "--person-id", SCOPE["person_id"],
        "--project-scope", SCOPE["project_scope"], "--db-path", str(db), "consolidate",
    ])


def _claim(db):
    conn = sqlite3.connect(db)
    try:
        row = conn.execute("SELECT value FROM meta WHERE key = ?", (CLAIM,)).fetchone()
    finally:
        conn.close()
    return json.loads(row[0]) if row and row[0] else None


def _lapse(db):
    """The claim as it stands once its holder has run past the lapse."""
    conn = sqlite3.connect(db)
    try:
        claim = json.loads(conn.execute("SELECT value FROM meta WHERE key = ?", (CLAIM,)).fetchone()[0])
        claim["at"] = (datetime.now(timezone.utc) - timedelta(minutes=20)).isoformat()
        conn.execute("UPDATE meta SET value = ? WHERE key = ?", (json.dumps(claim), CLAIM))
        conn.commit()
    finally:
        conn.close()


def _cycles_logged(db):
    conn = sqlite3.connect(db)
    try:
        return conn.execute(
            "SELECT COUNT(*) FROM consolidation_log WHERE pass_name = 'cycle'"
        ).fetchone()[0]
    finally:
        conn.close()


def test_the_job_holds_the_claim_while_its_cycle_runs(seeded, during_the_cycle):
    seen = []
    during_the_cycle.append(lambda: seen.append(_claim(seeded)))

    assert _job(seeded) == 0

    assert seen[0] and seen[0]["by"] == os.getpid(), f"no claim while the job's cycle ran: {seen}"
    assert _claim(seeded) is None, "the claim outlived the job"
    assert _cycles_logged(seeded) == 1


def test_the_job_gives_the_claim_up_when_its_cycle_fails(seeded, monkeypatch):
    seen = []

    def locked(self, *args, **kwargs):
        seen.append(_claim(seeded))
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(ConsolidationDaemon, "run_cycle", locked)

    with pytest.raises(sqlite3.OperationalError):
        _job(seeded)

    assert seen[0], "no claim while the job's cycle ran"
    assert _claim(seeded) is None, "a failed job kept the claim"


def test_a_capture_while_the_job_runs_starts_no_cycle(seeded, started, during_the_cycle):
    said = []

    def capture():
        runtime = MnemosRuntime(db_path=seeded, use_dedicated_model=False, **SCOPE)
        try:
            said.append(runtime.capture(content=FERN))
        finally:
            runtime.close()

    during_the_cycle.append(capture)

    assert _job(seeded) == 0

    assert started == [], "the capture started a cycle beside the job's"
    assert RUNNING in said[0], said[0]
    assert _cycles_logged(seeded) == 1


def test_the_job_starts_no_cycle_while_a_captures_maintenance_runs(db, started, capsys):
    runtime = MnemosRuntime(db_path=db, use_dedicated_model=False, **SCOPE)
    try:
        runtime.capture(content=FERRY)  # its process holds the claim until it ends
    finally:
        runtime.close()
    held = _claim(db)
    assert len(started) == 1 and held, "premise: the capture's maintenance is running"
    capsys.readouterr()

    assert _job(db) == 0
    out = capsys.readouterr().out

    assert _cycles_logged(db) == 0, "the job ran a cycle beside the capture's"
    assert "Consolidation skipped: no passes ran." in out, out
    assert "Another process is running this memory's maintenance now." in out, out
    assert _claim(db) == held, "the job let go of a claim that wasn't its own"


def test_a_job_that_cannot_take_the_claim_runs_no_cycle(seeded, monkeypatch, capsys):
    """The store's lock couldn't be had to write the claim: running without
    it could put a second cycle beside a capture's, so the job runs none."""
    monkeypatch.setattr(
        simple_runtime, "claim_upkeep", lambda store, key, token="", due=None: "busy", raising=False,
    )
    capsys.readouterr()

    assert _job(seeded) == 0
    out = capsys.readouterr().out

    assert _cycles_logged(seeded) == 0, "the job ran a cycle without the claim"
    assert "Consolidation skipped: no passes ran.\nThe store was busy; the next run starts it." in out, out


def test_a_holder_past_the_lapse_leaves_a_newer_claim_in_place(db, started, during_the_cycle):
    """A capture's maintenance that ran past the claim's lapse, and finds the
    job's claim when it ends, leaves it: only the token that took a claim
    gives it up."""
    runtime = MnemosRuntime(db_path=db, use_dedicated_model=False, **SCOPE)
    try:
        runtime.capture(content=FERRY)  # takes the claim
        old = _claim(db)
        _lapse(db)  # and holds it past the lapse
        seen = []

        def the_old_holder_ends():
            runtime._release_upkeep()
            seen.append(_claim(db))

        during_the_cycle.append(the_old_holder_ends)
        assert _job(db) == 0
    finally:
        runtime.close()

    assert seen[0] is not None, "the old holder cleared the job's claim"
    assert seen[0]["token"] != old["token"], "premise: the claim left is the job's"
    assert _claim(db) is None, "the job's own claim outlived it"


def test_the_background_process_gives_up_only_its_own_claim(db, started):
    first = MnemosRuntime(db_path=db, use_dedicated_model=False, **SCOPE)
    try:
        first.capture(content=FERRY)  # its process holds the claim, and runs long
    finally:
        first.close()
    _lapse(db)
    second = MnemosRuntime(db_path=db, use_dedicated_model=False, **SCOPE)
    try:
        second.capture(content=FERN)  # the lapsed claim no longer holds: a newer one
    finally:
        second.close()
    (_, first_token), (_, second_token) = started
    newer = _claim(db)
    assert newer["token"] == second_token != first_token, "premise: a newer claim"

    # The first process ends: the newer claim stays.
    assert run_background_upkeep([str(db), *SCOPE.values(), first_token]) == 0
    assert _claim(db) == newer, "the first process cleared a claim taken since"

    # The second process ends: its own claim goes.
    assert run_background_upkeep([str(db), *SCOPE.values(), second_token]) == 0
    assert _claim(db) is None, "the second process kept its own claim"
