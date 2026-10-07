"""The contradiction question, retired.

Maintenance asked the agent: "This memory surprised you. Does it contradict
an earlier one: …?" Without a model, a memory surprises when nothing like it
is held, and the question paired it with whichever memory shared the most
words with it, so the pair was a coincidence of common words. On the
maintainer's store all 5 answered questions were "not related", and 46
waited unanswered.

What these tests hold:

1. Upkeep never asks it, even about a surprising capture with a neighbour by
   shared words, and the store refuses to queue one.
2. Upkeep clears the ones still waiting. Answered ones stay as history, and
   one the agent already wrote on is closed with its words, never deleted.
3. Before upkeep has run, a waiting one reaches neither wake (the runtime's,
   or the real session-start hook in another process), nor the health card,
   nor `mnemos log`.
4. An agent that answers one it was shown before is told plainly: its words
   are kept with the question, and nothing is linked or changed. An answer to
   the question it was shown never lands on a retired one.
"""

from __future__ import annotations

import json
import re
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import mnemos.store.embedding_index as ei
from mnemos.companion import export as log_export
from mnemos.companion.export import Exporter
from mnemos.core.engram import Connection
from mnemos.interface.context_packet import build_context_packet
from mnemos.simple_runtime import MnemosRuntime, format_health_card
from mnemos.store.fts import fts_words, or_query
from mnemos.store.sqlite_store import EngramStore

SCOPE = {"agent_id": "nova", "person_id": "riley", "project_scope": "demo"}
SCOPE_ARGS = ["--agent-id", "nova", "--person-id", "riley", "--project-scope", "demo"]


@pytest.fixture(autouse=True)
def _words_only_and_no_scheduler(monkeypatch):
    """Recall by words alone, whatever this machine has installed, and the
    log asks no real scheduler anything."""
    monkeypatch.setattr(ei, "_check_local_deps", lambda: False)
    monkeypatch.setattr(log_export, "_launchd_loaded", lambda label: False)
    monkeypatch.setattr(log_export, "_systemd_active", lambda timer: False)
    monkeypatch.setattr(log_export, "_crontab", lambda: "")


# ── Helpers ──


def _runtime(db: Path) -> MnemosRuntime:
    return MnemosRuntime(db_path=str(db), use_dedicated_model=False, **SCOPE)


def _memory(rt: MnemosRuntime, content: str) -> str:
    """Capture a memory that carries its own meaning, so nothing asks about it."""
    said = rt.capture(content, impact="Kept for the test.")
    return re.search(r"Memory ID: (engram_\w+)", said).group(1)


def _ago(**delta) -> str:
    return (datetime.now(timezone.utc) - timedelta(**delta)).isoformat()


def _all(db: Path, sql: str, params: tuple = ()) -> list[tuple]:
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        return [tuple(row) for row in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def _row(db: Path, ask_id: str) -> dict | None:
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("SELECT * FROM reflection_queue WHERE id = ?", (ask_id,)).fetchone()
        return dict(row) if row is not None else None
    finally:
        conn.close()


def _old_ask(
    db: Path, ask_id: str, target: str, other: str, *, kind: str = "contradiction",
    prompt: str | None = None, shown: int = 0, created: str | None = None,
    answered_at: str | None = None, answer: str | None = None, project_scope: str = "demo",
) -> None:
    """A question as a store from before the retirement holds one, in the
    words maintenance used to ask it."""
    excerpt = "Riley always ships through pull requests, never to main."
    created = created or _ago(hours=2)
    conn = sqlite3.connect(str(db))
    try:
        conn.execute(
            "INSERT INTO reflection_queue (id, agent_id, person_id, project_scope, kind, "
            "target_id, prompt, surfaced_count, created_at, expires_at, answered_at, answer) "
            "VALUES (?, 'nova', 'riley', ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                ask_id, project_scope, kind, target,
                prompt or (
                    f'This memory surprised you. Does it contradict an earlier one: "{excerpt}"? '
                    f"Verdict contradicts, compatible or unsure, and say why. [ref:{other}]"
                ),
                shown, created,
                (datetime.fromisoformat(created) + timedelta(days=30)).isoformat(),
                answered_at, answer,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _graph(db: Path) -> list[tuple]:
    return _all(
        db,
        "SELECT source_id, target_id, relation, strength, formed_by FROM connections "
        "ORDER BY source_id, target_id, relation",
    )


def _memories(db: Path) -> list[tuple]:
    return _all(
        db,
        "SELECT id, content, impact, strength, state FROM engrams ORDER BY id",
    )


def _hook(db: Path, tmp_path: Path) -> str:
    """The real SessionStart hook, in another process."""
    home = tmp_path / "hook-home"
    (home / ".mnemos").mkdir(parents=True, exist_ok=True)
    done = subprocess.run(
        [sys.executable, "-m", "mnemos.cli", "hook", "session-start", "--db-path", str(db),
         *SCOPE_ARGS],
        input=json.dumps({"hook_event_name": "SessionStart", "source": "startup",
                          "session_id": "33333333-cccc-4ddd-8eee-000000000003"}),
        capture_output=True, text=True, timeout=180,
        env={"HOME": str(home), "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
             "MNEMOS_DISABLE_DOTENV": "1", "PYTHONPATH": ":".join(sys.path)},
    )
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)["hookSpecificOutput"]["additionalContext"]


# ── 1. Never asked ──


def test_upkeep_never_asks_whether_a_surprising_capture_contradicts(tmp_path):
    db = tmp_path / "memory.db"
    rt = _runtime(db)
    try:
        earlier = _memory(rt, "Riley always ships through pull requests, never to main.")
        # A capture that surprised the encoding, as the question was asked about.
        surprising = rt._encoder.encode(
            content="Riley now pushes small fixes straight to main without a pull request",
            agent_id="nova",
        )
        surprising.encoding_context.surprise_level = 0.7
        rt._store.save_engram(surprising)
        # The premise: it has a neighbour by shared words, the pair the
        # question was made from.
        words = fts_words(surprising.content, min_len=4)
        neighbours = [r.id for r in rt._store.search_fts(or_query(words[:8]), limit=5)]
        assert earlier in neighbours, "premise: no neighbour by shared words"

        said = rt.maintain()
    finally:
        rt.close()

    assert "Completed: local deterministic maintenance completed" in said, said
    assert _all(db, "SELECT id, prompt FROM reflection_queue WHERE kind = 'contradiction'") == []


def test_the_store_never_queues_one(tmp_path):
    store = EngramStore(str(tmp_path / "memory.db"))
    try:
        with pytest.raises(ValueError, match="retired"):
            store.enqueue_reflection("contradiction", "engram_X", "Do these contradict?", **SCOPE)
    finally:
        store.close()


# ── 2. Cleared by upkeep; history kept ──


def test_upkeep_clears_the_waiting_ones_and_keeps_the_rest(tmp_path):
    db = tmp_path / "memory.db"
    rt = _runtime(db)
    try:
        a = _memory(rt, "Riley now pushes small fixes straight to main.")
        b = _memory(rt, "Riley always ships through pull requests.")
        c = _memory(rt, "The staging server restarts every Sunday night.")
        d = _memory(rt, "Riley keeps the release notes in docs/releases.")
    finally:
        rt.close()
    _old_ask(db, "waiting", a, b)
    _old_ask(db, "elsewhere", a, b, project_scope="another-project")
    _old_ask(db, "worded", b, a, answer="I can't tell yet.")  # written on, no verdict
    _old_ask(db, "answered", c, a, answered_at=_ago(days=3), answer="Not related.")
    _old_ask(db, "lesson", d, a, kind="lesson",
             prompt="This is fading. What did it teach you? The lesson outlives the details.")
    answered, lesson = _row(db, "answered"), _row(db, "lesson")

    rt = _runtime(db)
    try:
        rt.maintain()
    finally:
        rt.close()

    assert _row(db, "waiting") is None, "a waiting contradiction question survived upkeep"
    assert _row(db, "elsewhere") is None, "a waiting one in another scope survived"
    worded = _row(db, "worded")
    assert worded is not None, "the agent's words on a waiting question were deleted"
    assert worded["answer"] == "I can't tell yet." and worded["answered_at"] is not None
    assert _row(db, "answered") == answered, "an answered question was changed"
    assert _row(db, "lesson") == lesson, "a question still asked was touched"
    assert _all(db, "SELECT COUNT(*) FROM reflection_queue WHERE kind = 'contradiction' "
                    "AND answered_at IS NULL") == [(0,)]


# ── 3. Never shown, even before upkeep ──


def test_a_waiting_one_is_never_shown_before_upkeep_clears_it(tmp_path):
    db = tmp_path / "memory.db"
    rt = _runtime(db)
    try:
        fresh = _memory(rt, "Riley now pushes small fixes straight to main.")
        stale = _memory(rt, "Riley merged the hotfix without a review.")
        old = _memory(rt, "The staging server restarts every Sunday night.")
        other = _memory(rt, "Riley always ships through pull requests.")
        asked = _memory(rt, "Riley keeps the release notes in docs/releases.")
    finally:
        rt.close()
    # Never shown, and older than the question still asked: the wake shows
    # the oldest first, so it would have been this one.
    _old_ask(db, "fresh", fresh, other, created=_ago(hours=3))
    # Shown three times and never answered, days ago: the health card would flag it.
    _old_ask(db, "stale", stale, other, shown=3, created=_ago(days=3))
    # Answered: history, which the log keeps.
    _old_ask(db, "answered", old, other, answered_at=_ago(days=2), answer="Not related.")
    # A question still asked, so there is a question to show.
    _old_ask(db, "impact", asked, other, kind="impact", created=_ago(hours=1),
             prompt="What did this change in how you understand things? One sentence.")
    retired = _all(db, "SELECT * FROM reflection_queue WHERE kind = 'contradiction' ORDER BY id")

    rt = _runtime(db)
    try:
        waiting = rt.pending_reflections(limit=10)
        packet = build_context_packet(rt._store, "", include_engrams=False, mark_surfaced=False,
                                      **SCOPE)
        data = rt.health()
    finally:
        rt.close()
    hook = _hook(db, tmp_path)
    life, memories = Exporter.for_scope(db_path=str(db), **SCOPE).export()

    assert [item["id"] for item in waiting] == ["impact"], "the wake shows a retired question"
    assert [item["id"] for item in packet["reflections"]] == ["impact"]
    assert "contradict" not in packet["prompt"]
    assert "What did this change in how you understand things?" in hook, hook
    assert "contradict" not in hook, hook
    check = data["watchdog"]["checks"]["questions"]
    assert check["stalled"] is False and check["unanswered_after_showings"] == 0, check
    assert "never answered" not in format_health_card(data)
    questions = life["questions"]
    assert (questions["open"], questions["byKind"]) == (1, {"impact": 1}), questions
    assert [a["id"] for a in questions["asked"]] == ["impact"]
    assert [(a["kind"], a["answer"]) for a in questions["answered"]] == [
        ("contradiction", "Not related.")
    ], "an answered one left the history"
    assert {m["id"] for m in memories["memories"] if m["asked"]} == {asked}
    # Looking is not upkeep: nothing was cleared, only left out.
    assert _all(db, "SELECT * FROM reflection_queue WHERE kind = 'contradiction' ORDER BY id") == retired


# ── 4. Answering one shown before ──


@pytest.mark.parametrize("verdict", ["contradicts", "compatible", "unsure", ""])
def test_answering_one_shown_before_keeps_the_words_and_changes_nothing(tmp_path, verdict):
    db = tmp_path / "memory.db"
    rt = _runtime(db)
    try:
        later = _memory(rt, "Riley now pushes small fixes straight to main.")
        earlier = _memory(rt, "Riley always ships through pull requests.")
        # A contradiction link an earlier answer made: compatible used to remove it.
        rt._store.save_connection(later, Connection(
            target_id=earlier, relation="contradicts", strength=0.7, formed_by="agent_reflection",
        ))
    finally:
        rt.close()
    _old_ask(db, "shown-before", later, earlier, shown=1)
    graph, memories, beliefs = _graph(db), _memories(db), _all(db, "SELECT * FROM beliefs")

    rt = _runtime(db)
    try:
        said = rt.reflect(later, "They fit: that fix was an emergency.", verdict=verdict)
    finally:
        rt.close()

    assert said.startswith("That question is retired: Mnemos no longer asks whether a memory "
                           "contradicts an earlier one."), said
    assert "mnemos_correct" in said
    row = _row(db, "shown-before")
    assert row["answer"] == "They fit: that fix was an emergency." and row["answered_at"], row
    assert _graph(db) == graph, "a link was made or removed"
    assert _memories(db) == memories, "a memory was changed"
    assert _all(db, "SELECT * FROM beliefs") == beliefs


@pytest.mark.parametrize("verdict", ["contradicts", "compatible", "unsure"])
def test_its_verdict_with_nothing_waiting_is_answered_plainly(tmp_path, verdict):
    """After upkeep has cleared it, the verdict is still understood: not
    "is not a verdict", but what happened to the question."""
    db = tmp_path / "memory.db"
    rt = _runtime(db)
    try:
        target = _memory(rt, "Riley now pushes small fixes straight to main.")
        graph = _graph(db)
        said = rt.reflect(target, "No, they don't contradict.", verdict=verdict)
    finally:
        rt.close()

    assert said == (
        "Nothing recorded: Mnemos no longer asks whether a memory contradicts an earlier "
        "one, so nothing was linked or changed. If a memory is wrong, correct it with "
        "mnemos_correct."
    )
    assert _graph(db) == graph


def test_an_answer_goes_to_the_question_shown_not_to_a_retired_one(tmp_path):
    """A memory a stale contradiction question waits on can also be asked
    what it taught. The wake shows only the lesson question, so the answer is
    the lesson, even though the retired one is older."""
    db = tmp_path / "memory.db"
    rt = _runtime(db)
    try:
        fading = _memory(rt, "Riley missed the last ferry and walked home in the rain.")
        other = _memory(rt, "Riley takes the ferry every winter weekend.")
    finally:
        rt.close()
    _old_ask(db, "retired", fading, other, created=_ago(days=2))
    _old_ask(db, "lesson", fading, other, kind="lesson", created=_ago(hours=1),
             prompt="This is fading. What did it teach you? The lesson outlives the details.")

    rt = _runtime(db)
    try:
        [shown] = rt.pending_reflections(limit=10)
        said = rt.reflect(fading, "Check the timetable before the last crossing.")
    finally:
        rt.close()

    assert shown["id"] == "lesson"
    assert said.startswith("Lesson recorded."), said
    assert _row(db, "lesson")["answered_at"] is not None
    assert _row(db, "retired")["answered_at"] is None, "the answer landed on the retired question"
