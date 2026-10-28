"""The dream: a short time each night for what in a memory needs a mind.

The deep upkeep links and fades what it can; what needs judgement it asks the
agent, and a session at work lets most of it pass (three showings, and the
asking stops). The dream is the time set aside for it, after the upkeep, as
dreaming follows deep sleep. What these tests hold:

1. What it's given: what's fading, what keeps coming back, every belief (each
   asked whether it still holds beside its words), what came in since the last
   dream, and new memories beside older ones that rhyme. Questions sessions
   stopped asking come too, and each question is given in one dream only.
2. What it can reach: its memory's tools and nothing else; no note, no page,
   no handoff; and it wakes light, so it spends nothing a session would.
3. When it runs: only when something waits, nightly after the deep upkeep.
4. What it did: the questions it was given, and which it answered.

Temporary homes and the fake Claude only; meaning is a fake index.
"""

from __future__ import annotations

import io
import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from mnemos.core.belief import Belief
from mnemos.simple_runtime import MnemosRuntime
from mnemos.store.sqlite_store import EngramStore

SCOPE = {"agent_id": "claude-code", "person_id": "user", "project_scope": "global"}
ROOT = Path(__file__).resolve().parents[1]
OPUS = "claude-opus-5-5"


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


def capture(db, words, *, days_ago=0):
    """A memory of the agent's, with what it changed already said: one without
    is asked about by Mnemos itself, and a test asks only what it means to."""
    rt = MnemosRuntime(db_path=str(db), use_dedicated_model=False, **SCOPE)
    try:
        engram_id = rt.capture(words, signed_as=OPUS, impact="It changed how I plan.").split(
            "Memory ID: ", 1)[1].split()[0]
    finally:
        rt.close()
    if days_ago:
        when = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()
        conn = sqlite3.connect(db)
        try:
            conn.execute("UPDATE engrams SET created_at = ? WHERE id = ?", (when, engram_id))
            conn.commit()
        finally:
            conn.close()
    return engram_id


def ask(db, kind, target, prompt, *, shown=0):
    store = EngramStore(db)
    try:
        question = store.enqueue_reflection(kind, target, prompt, **SCOPE)
        if shown:
            with store.transaction() as conn:
                conn.execute("UPDATE reflection_queue SET surfaced_count = ? WHERE id = ?", (shown, question))
        return question
    finally:
        store.close()


def believe(db, words, confidence=0.4):
    store = EngramStore(db)
    try:
        store.save_belief(Belief(agent_id=SCOPE["agent_id"], content=words, confidence=confidence))
    finally:
        store.close()


def dream(db, **kwargs):
    from mnemos.life import run_hour

    return run_hour("dream", db_path=str(db), **SCOPE, **kwargs)


def log(tmp_path):
    return json.loads((tmp_path / "fake.json").read_text())


def records(home):
    path = home / ".mnemos/hours/claude-code/hours.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


# ── 1. What it's given ──

def test_a_dream_is_given_what_needs_a_mind(db, tmp_path):
    fading = capture(db, "The 7:40 ferry became the 7:55, and I missed it twice.")
    returning = capture(db, "Riley wants the feeling first, then the picture.")
    held = capture(db, "Checking the live render beats reasoning about it.")
    new = capture(db, "Today the page learned to mark a note read once it was seen.")
    ask(db, "lesson", fading, "This is fading. What did it teach you? The lesson outlives the details.", shown=3)
    ask(db, "belief", returning, 'On 4 different days you wrote something like this:\n'
        '- "The felt thing comes first." (October 2)\n- "Find the feeling, then the form." (October 9)\n'
        "Is there something you believe here? If there is, say it in one line with verdict hold; "
        "if not, decline. Or leave it. [evidence:engram_A,engram_B]")
    believe(db, "I trust what's been checked against the real thing over what I've reasoned out.")
    believe(db, "With Riley, the felt thing comes before the literal picture.", 0.55)
    ask(db, "reaffirm", held, 'You hold this belief: "I trust what\'s been checked against the real thing '
        "over what I've reasoned…\". Still true? Verdict hold if it still holds, retire if it no longer does.")
    ask(db, "impact", new, "What did this change in how you understand things? One sentence.")

    planned = dream(db, dry_run=True, out=io.StringIO())
    record = dream(db)
    prompt = log(tmp_path)["stdin"]
    assert planned["prompt"] == prompt
    assert record["status"] == "done", record
    assert prompt.startswith("This is your dream: the part of sleep only you can do.")
    assert f"What's fading\n- The 7:40 ferry became the 7:55, and I missed it twice. (kept " in prompt
    assert f"[{fading}]" in prompt, "a question sessions stopped asking is the dream's to ask"
    assert ("What keeps coming back\n- On 4 different days you wrote something like this:\n"
            '  - "The felt thing comes first." (October 2)\n'
            '  - "Find the feeling, then the form." (October 9)\n'
            f"  [{returning}]") in prompt
    assert "evidence:" not in prompt and "verdict hold" not in prompt
    assert ("- I trust what's been checked against the real thing over what I've reasoned out. "
            f"(held at 40%) Still true? [{held}]") in prompt
    assert "- With Riley, the felt thing comes before the literal picture. (held at 55%)\n" in prompt
    assert f"New since the last dream\n- Today the page learned to mark a note read once it was seen. [{new}]" in prompt
    assert record["waiting"] == {"fading": 1, "returning": 1, "reaffirm": 1, "new": 1, "rhymes": 0, "questions": 4}
    assert len(record["said"]) == 4


def test_each_question_is_given_in_one_dream(db, home, tmp_path):
    fading = capture(db, "The harbour survey moved to Thursdays.")
    ask(db, "lesson", fading, "This is fading. What did it teach you?")
    first = dream(db)
    assert first["status"] == "done" and len(first["said"]) == 1
    again = dream(db)
    assert again["status"] == "skipped" and again["reason"].startswith("Nothing to dream over"), again
    assert [r["kind"] for r in records(home)] == ["dream", "dream"]


def test_a_practice_dream_uses_up_nothing(db, home):
    fading = capture(db, "The harbour survey moved to Thursdays.")
    ask(db, "lesson", fading, "This is fading. What did it teach you?")
    practice = dream(db, store_copy=True)
    assert practice["store"] == "copy" and practice["said"]
    live = dream(db)
    assert live["status"] == "done" and live["said"] == practice["said"]


def test_new_is_what_came_since_the_last_dream(db):
    old = capture(db, "Riley's studio faces north.")
    ask(db, "impact", old, "What did this change in how you understand things? One sentence.")
    conn = sqlite3.connect(db)
    try:
        conn.execute("UPDATE reflection_queue SET created_at = ?",
                     ((datetime.now(timezone.utc) - timedelta(days=3)).isoformat(),))
        conn.commit()
    finally:
        conn.close()
    planned = dream(db, dry_run=True, out=io.StringIO())
    assert planned["waiting"]["new"] == 0 and planned["skip"].startswith("Nothing to dream over")


class Rhyming:
    """An index whose nearness is set by the test: each new memory's words name
    the older memories near them, with how near."""

    available = True
    near: dict[str, list[tuple[str, float]]] = {}

    def __init__(self, *args, **kwargs):
        pass

    def search_candidates(self, query, candidates, *, k=30, floor=0.0, **kwargs):
        found = [(i, s) for i, s in self.near.get(query, []) if i in set(candidates) and s >= floor]
        return sorted(found, key=lambda pair: -pair[1])[:k]


def test_new_memories_meet_older_ones_that_rhyme(db, monkeypatch, tmp_path):
    import mnemos.store.embedding_index as index

    then = capture(db, "Python's plain HTTPServer serves one connection at a time.", days_ago=29)
    same = capture(db, "A threaded server answers a browser's burst of requests.", days_ago=20)
    recent = capture(db, "Last week the preview hung on its fonts.", days_ago=5)
    linked = capture(db, "The flake was the test server, not the app.", days_ago=40)
    now = capture(db, "Today the e2e flake was the test web server resetting connections.")
    store = EngramStore(db)
    try:
        with store.transaction() as conn:
            conn.execute("INSERT INTO connections (source_id, target_id, relation, strength, formed_at, formed_by) "
                         "VALUES (?, ?, 'supports', 0.5, ?, 'test')", (now, linked, datetime.now(timezone.utc).isoformat()))
    finally:
        store.close()
    Rhyming.near = {"Today the e2e flake was the test web server resetting connections.": [
        (linked, 0.80),   # already linked: the upkeep found it
        (same, 0.90),     # so near it's the same thought again
        (recent, 0.70),   # not old enough to be remote
        (then, 0.48),     # this one
    ]}
    monkeypatch.setattr(index, "EmbeddingIndex", Rhyming)
    record = dream(db)
    prompt = log(tmp_path)["stdin"]
    assert record["waiting"]["rhymes"] == 1 and record["status"] == "done"
    assert ("Side by side\n- now: Today the e2e flake was the test web server resetting connections. "
            f"[{now}]\n  then, ") in prompt
    assert f"Python's plain HTTPServer serves one connection at a time. [{then}]" in prompt


# ── 2. What it can reach ──

def test_a_dream_reaches_nothing_but_its_memory(db, home, tmp_path):
    from mnemos.life import DREAM_DENY

    (home / "Documents/Repositories").mkdir(parents=True)
    (home / ".mnemos/config.json").write_text(json.dumps({"life": {"read_dirs": ["Documents/Repositories"]}}))
    fading = capture(db, "The harbour survey moved to Thursdays.")
    ask(db, "lesson", fading, "This is fading. What did it teach you?")
    record = dream(db)
    argv = log(tmp_path)["argv"]
    assert argv[argv.index("--tools") + 1] == "", "no file, shell or web tool"
    assert "--add-dir" not in argv, "a dream reads no folder"
    folder = home / ".mnemos/hours/claude-code" / record["id"]
    settings = json.loads((folder / "settings.json").read_text())
    assert settings["permissions"]["allow"] == ["mcp__mnemos"]
    assert all(tool in settings["permissions"]["deny"] for tool in DREAM_DENY)
    assert {"mcp__mnemos__mnemos_note", "mcp__mnemos__mnemos_page", "mcp__mnemos__mnemos_handoff"} == set(DREAM_DENY)
    hook = settings["hooks"]["SessionStart"][0]["hooks"][0]["command"]
    assert hook.endswith("--wake light"), "a dream wakes light and spends nothing a session would"
    mcp = json.loads((folder / "mcp.json").read_text())["mcpServers"]["mnemos"]
    assert mcp["env"]["MNEMOS_HOUR_ID"] == record["id"]


def test_the_other_hours_wake_as_they_did(db, home, tmp_path):
    record = __import__("mnemos.life", fromlist=["run_hour"]).run_hour("mine", db_path=str(db), **SCOPE)
    settings = json.loads((home / ".mnemos/hours/claude-code" / record["id"] / "settings.json").read_text())
    assert "--wake" not in settings["hooks"]["SessionStart"][0]["hooks"][0]["command"]


# ── 3. When it runs ──

def test_a_dream_skips_when_nothing_waits(db, tmp_path):
    believe(db, "Beliefs alone are no reason to dream.")
    record = dream(db)
    assert record["status"] == "skipped" and record["reason"].startswith("Nothing to dream over"), record
    assert not (tmp_path / "fake.json").exists(), "nothing ran"


def test_the_dream_is_scheduled_after_the_deep_upkeep():
    from mnemos.setup import scheduler

    jobs = {job.name: job for job in scheduler.hour_jobs()}
    deep = next(job for job in scheduler.JOBS if job.name == "maintain-deep")
    assert jobs["hour-dream"].args == ("life", "--hour", "dream")
    assert jobs["hour-dream"].daily_at == (3, 30) and deep.daily_at == (3, 0)
    moved = {job.name: job for job in scheduler.hour_jobs(dream_at=(4, 15))}
    assert moved["hour-dream"].daily_at == (4, 15) and moved["hour-mine"].daily_at == (8, 0)


def test_the_page_knows_a_scheduled_dream(home):
    from mnemos.companion.export import HOUR_KIND

    assert HOUR_KIND.search("mnemos --agent-id claude-code life --hour dream ").group(1) == "dream"
    words = (ROOT / "mnemos/companion/page/shared/words.js").read_text()
    assert "dream: 'A dream'" in words


# ── 4. What it did ──

def test_the_record_says_what_the_dream_answered(db, monkeypatch):
    first = capture(db, "The harbour survey moved to Thursdays.")
    second = capture(db, "The ferry timetable changed twice.")
    ask(db, "lesson", first, "This is fading. What did it teach you?")
    ask(db, "lesson", second, "This is fading. What did it teach you?")
    monkeypatch.setenv("FAKE_CLAUDE_SCENARIO", "dream_answers")
    record = dream(db)
    assert record["status"] == "done", record
    assert len(record["said"]) == 2 and len(record["answered"]) == 1
    assert set(record["answered"]) <= set(record["said"])
