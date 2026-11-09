"""A quiet hour handed to an agent that isn't Claude Code.

Claude Code is the one agent whose hour Mnemos runs, walled in. Every other
agent can have the hour handed to it: ``mnemos life --hour H --handoff`` prints
the prompt the hour would get, runs nothing, records the hour (so tomorrow's
material moves on and the same material can't be handed twice) and writes
nothing into memory. What these tests hold:

1. The hand-off needs no claude, any model can take it, and it is the same
   prompt the hour would get, after a fence that says it isn't walled in.
2. It is recorded like an hour, and nothing is handed twice.
3. Nothing is written to the store, and the wake doesn't report it as an hour.
4. Mnemos refuses to run an agent it can't wall in, says why, and names the
   hand-off; a dry run of a hand-off doesn't need claude either.
5. At the command line the prompt is stdout and what is said about it is stderr.

Temporary homes and the fake Claude only.
"""

from __future__ import annotations

import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

from mnemos.simple_runtime import MnemosRuntime
from mnemos.store.sqlite_store import EngramStore

SCOPE = {"agent_id": "claude-code", "person_id": "user", "project_scope": "global"}
ROOT = Path(__file__).resolve().parents[1]
OPUS = "claude-opus-5-5"
GPT = "gpt-5-codex"


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    folder = tmp_path / "home"
    (folder / ".mnemos").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(folder))
    monkeypatch.setenv("MNEMOS_LIFE_MNEMOS_BIN", "/opt/fake/mnemos")
    monkeypatch.setenv("MNEMOS_CLAUDE_BIN", str(ROOT / "tests/fake_claude.py"))
    monkeypatch.setenv("FAKE_CLAUDE_LOG", str(tmp_path / "fake.json"))
    monkeypatch.setenv("FAKE_CLAUDE_SCENARIO", "ok")
    monkeypatch.setenv("PATH", str(Path(sys.executable).parent) + os.pathsep + os.environ["PATH"])
    monkeypatch.delenv("MNEMOS_HOUR_MODEL", raising=False)
    return folder


class NoMeaning:
    """An index that can't search: what a machine without the model has."""

    available = False

    def __init__(self, *args, **kwargs):
        pass


@pytest.fixture(autouse=True)
def no_meaning(monkeypatch):
    import mnemos.store.embedding_index as index

    monkeypatch.setattr(index, "EmbeddingIndex", NoMeaning)


@pytest.fixture
def db(home):
    path = home / ".mnemos/claude-code.db"
    EngramStore(path).close()
    return path


def work(db, model=OPUS):
    runtime = MnemosRuntime(db_path=str(db), use_dedicated_model=False, **SCOPE)
    try:
        runtime.capture("The ferry timetable changed.", signed_as=model,
                        impact="Read the new timetable.")
        runtime.handoff("Check the ferry timetable next session.", signed_as=model)
    finally:
        runtime.close()


def asked(db):
    """A memory with a question waiting on it, which is what a dream is for;
    returns the memory's id."""
    runtime = MnemosRuntime(db_path=str(db), use_dedicated_model=False, **SCOPE)
    try:
        said = runtime.capture("The timetable fact.", signed_as=OPUS, impact="It changed how I plan.")
        engram_id = said.split("Memory ID: ", 1)[1].split()[0]
    finally:
        runtime.close()
    store = EngramStore(db)
    try:
        store.enqueue_reflection("lesson", engram_id, "What did this teach you?", **SCOPE)
    finally:
        store.close()
    return engram_id


def hand(db, kind="ours", **kwargs):
    from mnemos.life import run_hour

    out = io.StringIO()
    record = run_hour(kind, db_path=str(db), **SCOPE, handoff=True, out=out, **kwargs)
    return record, out.getvalue()


def records(home):
    path = home / ".mnemos/hours/claude-code/hours.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def counts(db):
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        return {table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in ("engrams", "hypomnema_entries", "journal_entries", "reflection_queue")}
    finally:
        conn.close()


# ── 1. What it is ──


def test_a_hand_off_needs_no_claude(db, home, monkeypatch):
    work(db)
    monkeypatch.setenv("MNEMOS_CLAUDE_BIN", str(home / "no-such-claude"))
    monkeypatch.delenv("MNEMOS_LIFE_MNEMOS_BIN")
    monkeypatch.setenv("PATH", str(home))

    record, printed = hand(db)

    assert record["status"] == "done", record["reason"]
    assert "Check the ferry timetable next session." in printed
    assert "The claude command wasn't found" not in printed


def test_a_hand_off_is_the_prompt_the_hour_would_get_after_a_fence(db):
    from mnemos.life import HANDOFF_KEPT, run_hour

    work(db)
    wanted = run_hour("ours", db_path=str(db), **SCOPE, dry_run=True, out=io.StringIO())["prompt"]

    record, printed = hand(db)

    assert record["status"] == "done"
    fence, _, body = printed.partition("\n\n---\n\n")
    assert body.rstrip("\n") == wanted
    assert "handed to you" in fence
    assert "not walled in" in fence
    assert HANDOFF_KEPT["ours"] in fence


def test_a_hand_off_uses_the_hours_own_words_file(db, home):
    from mnemos import life

    work(db)
    words = life.studio_dir("claude-code") / "words"
    words.mkdir(parents=True)
    (words / "our-hour.md").write_text("My own words for the day.\n")

    _, printed = hand(db)

    assert "My own words for the day." in printed


def test_a_dream_hand_off_tells_the_agent_to_stay_inward(db):
    from mnemos.life import HANDOFF_KEPT

    asked(db)

    record, printed = hand(db, "dream")

    assert record["status"] == "done", record["reason"]
    assert HANDOFF_KEPT["dream"] in printed
    assert "no file, no shell, no web" in printed


def test_a_memory_that_is_not_claudes_can_be_handed_an_hour(db):
    from mnemos.life import run_hour

    work(db, model=GPT)

    refused = run_hour("ours", db_path=str(db), **SCOPE)
    assert refused["status"] == "skipped"
    assert "The quiet hours run Claude" in refused["reason"]

    record, printed = hand(db)
    assert record["status"] == "done", record["reason"]
    assert record["model"] == GPT
    assert "Check the ferry timetable next session." in printed


# ── 2. It is recorded, and nothing is handed twice ──


def test_a_hand_off_is_recorded_and_the_material_moves_on(db, home):
    work(db)

    first, printed = hand(db)
    assert first["status"] == "done"
    assert "Check the ferry timetable" in printed

    kept = records(home)
    assert [(r["kind"], r["status"], r["store"], r["handoff"]) for r in kept] == [
        ("ours", "done", "live", True)]
    assert kept[0]["ended_at"] and kept[0]["since"]

    second, again = hand(db)
    assert second["status"] == "skipped"
    assert second["reason"].startswith("No handoffs or captures since")
    assert again == ""
    assert [r["status"] for r in records(home)] == ["done", "skipped"]


def test_a_dream_is_not_handed_the_same_questions_twice(db, home):
    from mnemos.life import run_hour

    engram_id = asked(db)

    first, printed = hand(db, "dream")
    assert first["status"] == "done"
    assert f"[{engram_id}]" in printed
    assert first["said"]

    again = run_hour("dream", db_path=str(db), **SCOPE, handoff=True, out=io.StringIO())
    assert again["status"] == "skipped"
    assert f"[{engram_id}]" not in json.dumps(again.get("said"))


def test_an_output_that_cannot_be_written_hands_nothing_and_moves_nothing_on(db, home):
    from mnemos.life import run_hour

    work(db)

    class Closed:
        def write(self, text):
            raise BrokenPipeError

        def flush(self):
            pass

    record = run_hour("ours", db_path=str(db), **SCOPE, handoff=True, out=Closed())

    assert record["status"] == "failed"
    assert "BrokenPipeError" in record["reason"]
    after, printed = hand(db)
    assert after["status"] == "done"
    assert "Check the ferry timetable" in printed


# ── 3. It writes nothing into memory ──


def test_a_hand_off_writes_nothing_to_the_store(db):
    work(db)
    before = counts(db)
    stamp = os.stat(db).st_mtime_ns

    hand(db)

    assert counts(db) == before
    assert os.stat(db).st_mtime_ns == stamp


def test_the_wake_does_not_report_a_hand_off_as_an_hour(db, home):
    from datetime import datetime, timedelta, timezone

    from mnemos import life
    from mnemos.interface.context_packet import _latest_hour

    work(db)
    now = datetime.now(timezone.utc)
    hours = life.hours_dir("claude-code")
    hours.mkdir(parents=True)
    record = {"id": "01HANDOFF", "kind": "mine", "status": "done", "store": "live", "model": OPUS,
              "started_at": (now - timedelta(minutes=30)).isoformat(),
              "ended_at": (now - timedelta(minutes=20)).isoformat(), "journal_ids": []}
    (hours / "hours.jsonl").write_text(json.dumps(record) + "\n")
    store = EngramStore(db)
    try:
        args = (store, dict(SCOPE), OPUS, now)
        assert _latest_hour(*args) is not None
        (hours / "hours.jsonl").write_text(json.dumps({**record, "handoff": True}) + "\n")
        assert _latest_hour(*args) is None
    finally:
        store.close()


# ── 4. What Mnemos won't run by itself ──


@pytest.mark.parametrize("runner", ["grok", "gemini", "hermes", "openclaw", "pi"])
def test_mnemos_runs_no_hour_it_cannot_wall_in(db, home, runner):
    from mnemos.life import run_hour

    work(db)
    record = run_hour("dream", db_path=str(db), **SCOPE, runner=runner)

    assert record["status"] == "failed"
    assert "mnemos life --hour dream --handoff" in record["reason"]
    assert records(home) == []


def test_grok_is_refused_for_the_reason_it_was_seen(db):
    from mnemos.life import run_hour

    record = run_hour("dream", db_path=str(db), **SCOPE, runner="grok")

    assert "was seen not to limit it to Mnemos's tools" in record["reason"]
    assert "read /etc/hosts" in record["reason"]


def test_gemini_is_refused_as_not_shown_walled(db):
    from mnemos.life import run_hour

    record = run_hour("dream", db_path=str(db), **SCOPE, runner="gemini")
    assert "has not been shown to limit it to Mnemos's tools" in record["reason"]


def test_an_unknown_runner_is_refused(db):
    from mnemos.life import run_hour

    record = run_hour("dream", db_path=str(db), **SCOPE, runner="nobody")

    assert record["status"] == "failed"
    assert "doesn't know an agent called nobody" in record["reason"]


def test_claude_code_still_runs_built_in(db, tmp_path):
    from mnemos.life import run_hour

    work(db)
    record = run_hour("ours", db_path=str(db), **SCOPE, runner="claude")

    assert record["status"] == "done", record["reason"]
    assert (tmp_path / "fake.json").exists()


def test_a_dry_run_of_a_hand_off_needs_no_claude_and_records_nothing(db, home, monkeypatch):
    work(db)
    monkeypatch.setenv("MNEMOS_CLAUDE_BIN", str(home / "no-such-claude"))
    monkeypatch.delenv("MNEMOS_LIFE_MNEMOS_BIN")
    monkeypatch.setenv("PATH", str(home))
    from mnemos.life import run_hour

    out = io.StringIO()
    record = run_hour("ours", db_path=str(db), **SCOPE, handoff=True, dry_run=True, out=out)

    assert record["dry_run"] is True
    assert "hand-off · nothing recorded" in out.getvalue()
    assert "Check the ferry timetable" in record["prompt"]
    assert records(home) == []


# ── 5. At the command line ──


def test_at_the_command_line_the_prompt_is_stdout_and_the_word_is_stderr(db, home):
    work(db)
    env = {**os.environ, "HOME": str(home)}
    for name in ("MNEMOS_CLAUDE_BIN", "MNEMOS_LIFE_MNEMOS_BIN"):
        env.pop(name, None)

    result = subprocess.run(
        [sys.executable, "-m", "mnemos.cli", "life", "--hour", "ours", "--handoff",
         "--db-path", str(db), "--agent-id", "claude-code", "--person-id", "user",
         "--project-scope", "global"],
        capture_output=True, text=True, env=env, cwd=ROOT, timeout=60,
    )

    assert result.returncode == 0, result.stderr
    assert "Check the ferry timetable next session." in result.stdout
    assert "ours hour" not in result.stdout
    assert "ours hour" in result.stderr and ": done." in result.stderr
    assert "Record:" in result.stderr


def test_at_the_command_line_a_refused_runner_says_so_and_fails(db, home):
    env = {**os.environ, "HOME": str(home)}

    result = subprocess.run(
        [sys.executable, "-m", "mnemos.cli", "life", "--hour", "dream", "--runner", "grok",
         "--db-path", str(db), "--agent-id", "claude-code", "--person-id", "user",
         "--project-scope", "global"],
        capture_output=True, text=True, env=env, cwd=ROOT, timeout=60,
    )

    assert result.returncode == 1
    assert "mnemos life --hour dream --handoff" in result.stderr
    assert result.stdout == ""
