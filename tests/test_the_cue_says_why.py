"""The cue answers, or says why it didn't (WP-E2).

On the maintainer's machine the cue failed 18 of 109 messages in a week: 12
recorded as ``timeout`` and 6 as ``error (OperationalError)``. Both were its
own deadline. The hook waited out a session's server that was slow to answer,
then started on words with too little of its time left; where it ran out
decided the name. Between queries it was a timeout. In the middle of one, the
hook's own deadline stopped SQLite, which raises "interrupted", and the hook
recorded the exception's class name. No lock was needed for either.

So the words answer now starts at once, beside the question to the answerer,
and is ready when the answerer's window closes: a slow, busy or loading server
costs the message its meaning, never the person's time. A query stopped at the
deadline is a timeout. A locked store is read once more, then counted as busy.
Every failure is counted by its kind, every answer by words says why it was by
words, and the health card says which kind dominates and the one thing that
fixes it. What the cue offers (the gate, the floors, the lines) is unchanged.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import socket
import sqlite3
import threading
import time
from datetime import datetime
from pathlib import Path

import pytest

from mnemos.simple_runtime import MnemosRuntime, format_health_card
from tests.test_the_cue import (  # noqa: F401  (meaning and home are fixtures)
    MESSAGE,
    SCOPE,
    _answerer,
    _fake_answerer,
    _gate_memories,
    _hook,
    _seen,
    _store,
    cue,
    home,
    meaning,
)


def _health(db: Path) -> tuple[dict, str]:
    rt = MnemosRuntime(db_path=str(db), use_dedicated_model=False, **SCOPE)
    try:
        data = rt.health()
    finally:
        rt.close()
    return data, format_health_card(data)


def _slow_words(monkeypatch, seconds: float) -> None:
    """The words answer takes ``seconds`` longer, as on a busy machine."""
    import mnemos.simple_runtime as simple_runtime

    real = simple_runtime.cue_memories

    def slow(*args, **kwargs):
        time.sleep(seconds)
        return real(*args, **kwargs)

    monkeypatch.setattr(simple_runtime, "cue_memories", slow)


def _lock(db: Path) -> sqlite3.Connection:
    """Another process holding ``db`` locked against readers."""
    conn = sqlite3.connect(str(db))
    conn.execute("PRAGMA journal_mode=DELETE")
    conn.execute("BEGIN EXCLUSIVE")
    return conn


def _unlock(conn: sqlite3.Connection) -> None:
    conn.rollback()
    conn.close()


# ── The person is never slowed ──


def test_a_cold_answerer_gives_a_words_answer_recorded_as_timeout_within_the_deadline(
    tmp_path, meaning, home,
):
    """The session's server is there but doesn't answer in time (its model
    still loading, or the machine busy). The hook answers by words this once,
    inside its own deadline, and says why: the server timed out. That is not a
    failure: the message was answered."""
    found = _gate_memories()
    db = _store(tmp_path / "memory.db", *found.values())
    key = cue.scope_key(str(db), **SCOPE)
    thread = _fake_answerer(cue.answerer_path(os.getpid(), key), None)  # accepts, never answers

    started = time.monotonic()
    block = _hook(db, MESSAGE, CLAUDE_PID=str(os.getpid()))
    took = time.monotonic() - started
    thread.join(5)

    assert found["worded"].id in block
    seen = _seen("session-one", db)
    assert seen["offers"][0]["via"] == "words"
    assert seen.get("words_because") == {"timeout": 1}, seen
    assert seen["failures"] == 0 and seen["silences"] == 0, seen
    assert took < cue.HOOK_BUDGET, took


def test_a_slow_answerer_and_a_slow_words_answer_never_add_up(tmp_path, meaning, home, monkeypatch):
    """The live failure: the hook waited out the answerer's window, then began
    on words with what was left. Now the words answer starts at once, beside the
    question, so a slow server and a slow machine cost the longer of the two,
    not their sum."""
    found = _gate_memories()
    db = _store(tmp_path / "memory.db", *found.values())
    key = cue.scope_key(str(db), **SCOPE)
    thread = _fake_answerer(cue.answerer_path(os.getpid(), key), None)
    _slow_words(monkeypatch, 0.4)

    started = time.monotonic()
    block = _hook(db, MESSAGE, CLAUDE_PID=str(os.getpid()))
    took = time.monotonic() - started
    thread.join(5)

    assert found["worded"].id in block
    assert _seen("session-one", db).get("words_because") == {"timeout": 1}
    assert took < cue.HOOK_BUDGET, took


# ── Naming what happened ──


def test_a_query_stopped_at_the_deadline_is_a_timeout_not_an_error(tmp_path, meaning, home, monkeypatch):
    """The hook's deadline stops a query still running. SQLite calls that
    "interrupted", an OperationalError; it is the hook running out of time."""
    db = _store(tmp_path / "memory.db", *_gate_memories().values())
    import mnemos.simple_runtime as simple_runtime

    def endless(store, *args, **kwargs):
        store._get_conn().execute(
            "WITH RECURSIVE n(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM n) SELECT count(*) FROM n"
        ).fetchone()
        return []

    monkeypatch.setattr(simple_runtime, "cue_memories", endless)

    with pytest.raises(cue.HookTimeout):
        _hook(db, MESSAGE, CLAUDE_PID="999999")

    seen = _seen("session-one", db)
    assert (seen["failures"], seen["last_failure"]) == (1, "timeout"), seen
    assert seen.get("failure_kinds") == {"timeout": 1}, seen


def test_a_lock_that_clears_is_read_again(tmp_path, meaning, home, monkeypatch):
    """A locked store is tried once more within the deadline: a lock that is
    gone by then costs nothing."""
    found = _gate_memories()
    db = _store(tmp_path / "memory.db", *found.values())
    import mnemos.simple_runtime as simple_runtime

    real = simple_runtime.cue_memories
    calls = []

    def locked_once(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise sqlite3.OperationalError("database is locked")
        return real(*args, **kwargs)

    monkeypatch.setattr(simple_runtime, "cue_memories", locked_once)

    block = _hook(db, MESSAGE, CLAUDE_PID="999999")

    assert found["worded"].id in block and len(calls) == 2
    seen = _seen("session-one", db)
    assert seen["failures"] == 0 and seen["offers"][0]["via"] == "words", seen


def test_a_lock_that_holds_is_counted_busy_well_inside_the_deadline(tmp_path, meaning, home):
    """Another process holds the store locked through the retry. The hook waits
    on it briefly, twice, and counts the message as busy: not an unnamed error,
    and not the whole of its time spent waiting."""
    db = _store(tmp_path / "memory.db", *_gate_memories().values())
    holder = _lock(db)
    raised = None
    try:
        started = time.monotonic()
        try:
            _hook(db, MESSAGE, CLAUDE_PID="999999")
        except Exception as exc:
            raised = exc
        took = time.monotonic() - started
    finally:
        _unlock(holder)

    seen = _seen("session-one", db)
    assert (seen["failures"], seen["last_failure"]) == (1, "busy"), seen
    assert seen.get("failure_kinds") == {"busy": 1}, seen
    assert isinstance(raised, cue.StoreBusy), raised
    assert took < 3 * cue.READ_BUSY_SECONDS + 0.2, took


def test_a_locked_store_gives_a_words_answer_recorded_as_busy(tmp_path, meaning, home):
    """The session's server reads a locked store: it tries once more, then says
    so at once ("busy") instead of waiting seconds on the lock, and the hook
    answers by words, saying why. (The answerer reads a locked copy here, so
    that only its reads meet the lock.)"""
    found = _gate_memories()
    db = _store(tmp_path / "memory.db", *found.values())
    locked = tmp_path / "locked.db"
    shutil.copyfile(db, locked)
    answerer = _answerer(db)
    answerer.db_path = str(locked)  # its reads go to the locked copy; its key stays db's
    holder = _lock(locked)
    try:
        block = _hook(db, MESSAGE, CLAUDE_PID=str(os.getpid()))
        seen = _seen("session-one", db)
        assert found["worded"].id in block
        assert seen["offers"][0]["via"] == "words" and seen.get("words_because") == {"busy": 1}, seen

        why: dict = {}
        started = time.monotonic()
        reply = cue.ask_answerer(answerer.key, MESSAGE, environ={"CLAUDE_PID": str(os.getpid())}, why=why)
        asked = time.monotonic() - started
    finally:
        _unlock(holder)
        answerer.stop()

    assert reply is None and why.get("reason") == "busy", why
    assert asked < cue.CONNECT_SECONDS + cue.ANSWER_SECONDS, asked


# ── The health card names the kind ──


def test_the_health_card_names_the_dominant_kind_and_what_fixes_it(tmp_path, meaning, home, monkeypatch):
    db = _store(tmp_path / "memory.db", *_gate_memories().values())
    import mnemos.simple_runtime as simple_runtime

    def locked(*args, **kwargs):
        raise sqlite3.OperationalError("database is locked")

    def endless(store, *args, **kwargs):
        store._get_conn().execute(
            "WITH RECURSIVE n(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM n) SELECT count(*) FROM n"
        ).fetchone()
        return []

    assert _hook(db, MESSAGE, session="answered", CLAUDE_PID="999999")
    with monkeypatch.context() as patched:
        patched.setattr(simple_runtime, "cue_memories", endless)
        for session in ("slow-one", "slow-two"):
            with pytest.raises(cue.HookTimeout):
                _hook(db, MESSAGE, session=session, CLAUDE_PID="999999")
        patched.setattr(simple_runtime, "cue_memories", locked)
        with pytest.raises(cue.StoreBusy):
            _hook(db, MESSAGE, session="locked-out", CLAUDE_PID="999999")

    data, card = _health(db)
    check = data["watchdog"]["checks"]["cue"]
    assert check["failures"] == 3 and check.get("failures_by_kind") == {"timeout": 2, "busy": 1}, check
    assert check["stalled"] is True, check
    attention = [line for line in card.splitlines() if line.startswith("ATTENTION") and "cue" in line]
    assert len(attention) == 1, card
    assert "3 of 4 messages" in attention[0] and "timeout" in attention[0], attention
    assert "nothing to fix" in attention[0], attention


def test_the_socket_path_is_checked_and_reported(tmp_path, meaning, monkeypatch, caplog):
    """A HOME so deep that the answerer's socket path can't be bound (100
    bytes or more): the server says so, the hook answers by words and says why,
    and the health card names the fix, a shorter HOME. Before, nothing said so
    but the fact that every answer came by words."""
    deep = tmp_path / ("h" * 90)
    deep.mkdir()
    monkeypatch.setenv("HOME", str(deep))
    found = _gate_memories()
    db = _store(tmp_path / "memory.db", *found.values())
    key = cue.scope_key(str(db), **SCOPE)
    assert len(os.fsencode(str(cue.answerer_path(os.getpid(), key)))) >= 100

    cue.mark_hook_in_use()
    answerer = cue.CueAnswerer(str(db), claude_pid=os.getpid(), **SCOPE)
    with caplog.at_level(logging.INFO, logger="mnemos.cue"):
        assert answerer.start()
        answerer.thread.join(10)
    assert not answerer.ready.is_set()
    told = [r for r in caplog.records if r.name == "mnemos.cue" and "socket" in r.getMessage()]
    assert told and told[0].levelno >= logging.WARNING and "shorter HOME" in told[0].getMessage(), told

    block = _hook(db, MESSAGE, CLAUDE_PID=str(os.getpid()))
    assert found["worded"].id in block
    assert _seen("session-one", db).get("words_because") == {"socket path too long": 1}

    data, card = _health(db)
    attention = [line for line in card.splitlines() if line.startswith("ATTENTION") and "cue" in line]
    assert len(attention) == 1 and "shorter HOME" in attention[0], card


def test_failures_counted_before_kinds_were_kept_stay_counted(tmp_path, home):
    """A session file an older hook wrote has a count and its newest reason
    only: the newest is counted under that reason, the rest as not named."""
    old = cue.SeenFile("older-session", "0123456789ab")
    old.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    old.path.write_text(
        '{"v": 2, "session": "older-session", "scope": "0123456789ab", "shown": [], "texts": [],'
        ' "offered": 0, "offers": [], "answers": {"words": 2}, "silences": 0, "failures": 3,'
        ' "last_failure": "error (OperationalError)"}'
    )
    summary = cue.offered_summary(key="0123456789ab")
    assert summary["failures"] == 3
    assert summary["failures_by_kind"] == {"error (OperationalError)": 1, "not named": 2}, summary


# ── Follow-ups: the wait, the flag's gate, the failures' times ──


def _late_answerer(path: Path, reply: dict, delay: float, asked: list) -> threading.Thread:
    """An answerer that answers ``reply`` after ``delay`` seconds: slow, not
    gone. What it was asked goes to ``asked``."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(str(path))
    listener.listen(4)
    listener.settimeout(5)

    def serve():
        try:
            conn, _ = listener.accept()
        except OSError:
            return
        with conn:
            asked.append(json.loads(conn.recv(65536).decode().split("\n", 1)[0]))
            time.sleep(delay)
            try:
                conn.sendall((json.dumps(reply) + "\n").encode())
            except OSError:
                pass
        listener.close()

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    return thread


def test_a_slow_answerer_is_waited_for_until_the_margin_before_the_deadline(tmp_path, meaning, home):
    """With the words answer running beside it, the hook can give the session's
    server until ANSWER_MARGIN before its deadline, not 0.35 s: a server that
    answers at 0.45 s answers by meaning, and the hook still ends in time."""
    found = _gate_memories()
    db = _store(tmp_path / "memory.db", *found.values())
    key = cue.scope_key(str(db), **SCOPE)
    line = {"id": found["near"].id, "text": "Trim the lamp and the beacon wick each evening.",
            "date": "2026-10-07", "key": cue.text_key("Trim the lamp and the beacon wick each evening."),
            "lesson": False, "similarity": 1.0}
    asked: list = []
    thread = _late_answerer(cue.answerer_path(os.getpid(), key),
                            {"v": cue.CUE_PROTOCOL, "ok": True, "meaning": True, "lines": [line], "why": None},
                            0.45, asked)

    started = time.monotonic()
    block = _hook(db, MESSAGE, CLAUDE_PID=str(os.getpid()))
    took = time.monotonic() - started
    thread.join(5)

    assert found["near"].id in block, "the answer by meaning was waited for"
    seen = _seen("session-one", db)
    assert seen["offers"][0]["via"] == "meaning" and not seen.get("words_because"), seen
    assert 0.45 < asked[0]["wait"] <= cue.HOOK_BUDGET - cue.ANSWER_MARGIN, asked
    assert took < cue.HOOK_BUDGET, took


def _messages(db: Path, answered: int, *failures: str) -> None:
    """A week's messages in one session: ``answered`` answered by words, then
    the ``failures``, each by its kind."""
    seen = cue.SeenFile("a-week", cue.scope_key(str(db), **SCOPE))
    for _ in range(answered):
        seen.record((), (), answered="words")
    for kind in failures:
        seen.record((), (), failure=kind)


def _cue_attention(card: str) -> list[str]:
    return [line for line in card.splitlines() if line.startswith("ATTENTION") and "cue" in line]


def test_a_few_timeouts_are_counted_but_not_flagged(tmp_path, meaning, home):
    """Timeouts (the machine was busy) pass on their own and nothing fixes
    them: they are counted in the cue's own line and raise no ATTENTION."""
    db = _store(tmp_path / "memory.db", *_gate_memories().values())
    _messages(db, 20, "timeout")  # 1 of 21

    data, card = _health(db)
    check = data["watchdog"]["checks"]["cue"]
    assert check["failures_by_kind"] == {"timeout": 1}, check
    assert "1 failure (1 timeout)" in check["seen"], check["seen"]
    assert check["stalled"] is False and not _cue_attention(card), card


def test_any_error_is_flagged_however_few(tmp_path, meaning, home):
    """An error is flagged whatever its share, and the flag names it, not the
    timeouts beside it that would pass on their own."""
    db = _store(tmp_path / "memory.db", *_gate_memories().values())
    _messages(db, 80, "timeout", "timeout", "error (RuntimeError)")  # 3 of 83

    data, card = _health(db)
    attention = _cue_attention(card)
    assert len(attention) == 1, card
    assert "3 of 83 messages" in attention[0] and "1 was error (RuntimeError)" in attention[0], attention
    assert "a restart of the session" in attention[0], attention


def test_timeouts_alone_are_flagged_at_a_quarter_of_the_week(tmp_path, meaning, home):
    """Alone, timeouts wait for ``CUE_PASSING_SHARE`` of the week's messages,
    a cue that mostly isn't answering; a failure something fixes is flagged
    from ``CUE_FLAG_SHARE`` (``test_any_error_is_flagged_however_few``)."""
    under = _store(tmp_path / "under.db", *_gate_memories().values())
    _messages(under, 16, *["timeout"] * 4)  # 4 of 20
    _data, card = _health(under)
    assert not _cue_attention(card), card

    at = _store(tmp_path / "at.db", *_gate_memories().values())
    _messages(at, 15, *["timeout"] * 5)  # 5 of 20
    _data, card = _health(at)
    attention = _cue_attention(card)
    assert len(attention) == 1 and "most often timeout (5 of 5)" in attention[0], card


def test_each_kind_keeps_the_times_of_its_last_twenty_failures(tmp_path, home):
    """For lining failures up with what else ran then: per kind, the times of
    the last 20, oldest first."""
    seen = cue.SeenFile("timed-session", "0123456789ab")
    for _ in range(23):
        seen.record((), (), failure="timeout")
    seen.record((), (), failure="busy")

    read = seen.read()
    assert read["failure_kinds"] == {"timeout": 23, "busy": 1}, read
    times = read.get("failure_times") or {}
    assert len(times.get("timeout", [])) == 20 and len(times.get("busy", [])) == 1, times
    moments = [datetime.fromisoformat(when) for when in times["timeout"]]
    assert moments == sorted(moments) and all(m.tzinfo is not None for m in moments), moments
