"""What the edge-case tester found in "quiet the noise", fixed.

- Softening read the 5,000 most accessible memories, so on a larger store the
  faded ones, the only ones it teaches, were the ones it never reached.
- ``repair early-lessons`` archived lessons with a reason recall can't reach,
  though its help says recall still finds them.
- A note cut at a cap ran four characters past it: " […]" was added after.
- A standing memory was taught like any other, and asked what it taught.
- ``--wake sideways`` and ``--wake LIGHT`` exited 2 with no wake at all.
- A name with a newline in it was kept on two lines.
- A store that never ran ``repair word-questions`` still showed the old word
  questions, and they stood in the way of a belief's reaffirmation.
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

from mnemos.consolidation import softening
from mnemos.consolidation.softening import _create_or_reinforce_lesson, run_softening_pass
from mnemos.core.belief import Belief
from mnemos.interface.context_packet import LIGHT_HANDOFF_CHARS, cut_at_sentence
from mnemos.simple_runtime import MnemosRuntime
from mnemos.store.sqlite_store import code_version_first_opened_key


SCOPE = {"agent_id": "nova", "person_id": "riley", "project_scope": "demo"}
SCOPE_ARGS = ["--agent-id", "nova", "--person-id", "riley", "--project-scope", "demo"]
OPUS = "claude-opus-5-5"
EARLIER = "11111111-aaaa-4aaa-8aaa-111111111111"
FRESH = "22222222-bbbb-4bbb-8bbb-222222222222"
CONTENT = "Riley plans every trip around the ferry timetable."
IMPACT = "The ferry decides every trip."
JOURNAL = "The harbour ledger balances."
HANDOFF = "Where I stopped: the harbour ledger balances. Next: the spring timetable. " + "The harbour ledger lists every crossing, one line each. " * 30
WORD_ASK = (
    'You keep returning to "ferry" (5 memories). Is that a belief you now hold? '
    "If it is, state it in one line with verdict hold; if it is not, decline. "
    "Or leave it. [theme:ferry]"
)


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    runtime = MnemosRuntime(db_path=tmp_path / "memory.db", use_dedicated_model=False, **SCOPE)
    runtime._ensure_init()
    yield runtime
    runtime.close()


def _capture(runtime, content=CONTENT, impact=IMPACT) -> str:
    said = runtime.capture(content, impact=impact)
    return re.search(r"Memory ID: (engram_\w+)", said).group(1)


def _iso(days_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()


def _set(runtime, engram_id, *, accessibility, days_ago=5):
    runtime._store._get_conn().execute(
        "UPDATE engrams SET accessibility = ?, created_at = ?, last_accessed = ? WHERE id = ?",
        (accessibility, _iso(days_ago), _iso(days_ago), engram_id),
    )
    runtime._store._commit()


def _pass(runtime):
    return run_softening_pass(runtime._store, {}, None, **SCOPE)


def _lessons(runtime):
    return [
        engram for engram in runtime._store.get_engrams_in_states(
            ("active",), agent_id="nova", limit=5000,
        )
        if "lesson" in engram.tags
    ]


def _taught(runtime, source_id):
    """The lessons drawn from ``source_id`` and linked from it."""
    source = runtime._store.get_engram(source_id)
    linked = {c.target_id for c in source.connections if c.relation == "distilled_into"}
    return [lesson for lesson in _lessons(runtime) if lesson.id in linked]


# ── The faded first ──


def test_a_faded_memory_is_taught_however_many_others_there_are(runtime, monkeypatch):
    monkeypatch.setattr(softening, "SOFTENING_LIMIT", 10)
    for n in range(12):
        vivid = _capture(runtime, f"Vivid memory number {n} about the harbour crossing.", "Kept for the test.")
        _set(runtime, vivid, accessibility=0.9)
    faded = _capture(runtime)
    _set(runtime, faded, accessibility=0.05)

    _pass(runtime)

    taught = _taught(runtime, faded)
    assert [lesson.content for lesson in taught] == [IMPACT], "the faded memory was never reached"


# ── Early lessons stay recallable ──


@pytest.fixture
def old(runtime):
    """A store as older code left it: the fading rule's code first opened it in 2099."""
    runtime._store._get_conn().execute(
        "UPDATE meta SET value = ? WHERE key = ?",
        ("2099-01-01T00:00:00+00:00", code_version_first_opened_key(13)),
    )
    runtime._store._commit()
    return runtime


def _early_lesson(runtime):
    """A memory with an agent impact and the unsigned lesson softening drew
    from it a day later, both in January 2026."""
    source = _capture(runtime)
    runtime._store._get_conn().execute(
        "UPDATE engrams SET accessibility = 0.5, created_at = ? WHERE id = ?",
        ("2026-01-01T00:00:00+00:00", source),
    )
    runtime._store._commit()
    lesson = _create_or_reinforce_lesson(runtime._store.get_engram(source), runtime._store, {})
    assert lesson, "premise: a lesson was drawn"
    runtime._store._get_conn().execute(
        "UPDATE engrams SET created_at = ? WHERE id = ?", ("2026-01-02T00:00:00+00:00", lesson),
    )
    runtime._store._commit()
    return source, lesson


def test_the_archived_lesson_is_recallable_with_include_archived(old):
    """repair_early_lessons docstring: "archived (recall still finds it by id or with ``include_archived``)"."""
    _, lesson = _early_lesson(old)
    old.repair_early_lessons(write=True)
    said = old.recall("ferry decides every trip", include_archived=True)
    assert lesson in said, said


def test_the_archived_lesson_is_recallable_by_its_id(old):
    _, lesson = _early_lesson(old)
    old.repair_early_lessons(write=True)
    said = old.recall(lesson)
    assert IMPACT in said, said


def test_the_faded_count_agrees_with_the_faded(old):
    _, lesson = _early_lesson(old)
    old.repair_early_lessons(write=True)
    store = old._store
    faded = store.faded_engrams(**SCOPE)
    assert [engram.id for engram in faded] == [lesson], "premise: the early lesson is among the faded"
    assert store.count_faded(**SCOPE) == len(faded)


def test_an_early_lesson_asked_to_retire_is_retired(old):
    _, lesson = _early_lesson(old)
    old.repair_early_lessons(write=True)
    store = old._store
    assert store.archive_reason(lesson) == "drawn before its memory faded", "premise"

    assert store.retire_engram(store.get_engram(lesson), reason="forgotten") is True
    assert store.archive_reason(lesson) == "forgotten"
    assert IMPACT not in old.recall(lesson), "recall still brings back what was retired"


# ── A standing memory is never taught ──


def test_a_standing_memory_is_never_taught(runtime):
    standing = _capture(runtime, "Riley wants plain words and short replies.", "Plain words, short replies.")
    assert runtime._store.set_standing(standing, True, by=OPUS)
    _set(runtime, standing, accessibility=0.05)

    stats = _pass(runtime)
    runtime.maintain()

    assert stats.get("standing") == 1, stats
    assert _taught(runtime, standing) == []
    assert not [lesson for lesson in _lessons(runtime) if lesson.content == "Plain words, short replies."]
    asked = runtime._store._get_conn().execute(
        "SELECT id FROM reflection_queue WHERE kind = 'lesson' AND target_id = ?", (standing,),
    ).fetchall()
    assert asked == []


# ── The hook: caps, wake values ──


def _store(tmp_path: Path, handoff=HANDOFF):
    db = tmp_path / "memory.db"
    runtime = MnemosRuntime(db_path=db, use_dedicated_model=False, **SCOPE)
    try:
        runtime.introduce(OPUS)
        runtime._store.write_handoff(handoff, **SCOPE, author_model=OPUS, author_session=EARLIER)
        runtime._store.write_journal_entry(JOURNAL, **SCOPE, model_id=OPUS, session_id=EARLIER)
    finally:
        runtime.close()
    return db


def _hook(db: Path, tmp_path: Path, *, extra: tuple[str, ...] = ()):
    home = tmp_path / "home"
    (home / ".mnemos").mkdir(parents=True, exist_ok=True)
    folder = tmp_path / "work" / "harbour-app"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / ".git").mkdir(exist_ok=True)
    payload = {
        "hook_event_name": "SessionStart", "source": "startup", "session_id": FRESH,
        "cwd": str(folder), "model": OPUS,
    }
    return subprocess.run(
        [sys.executable, "-m", "mnemos.cli", "hook", "session-start", "--db-path", str(db), *SCOPE_ARGS, *extra],
        input=json.dumps(payload), capture_output=True, text=True, timeout=180,
        env={"HOME": str(home), "PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "MNEMOS_DISABLE_DOTENV": "1", "PYTHONPATH": ":".join(sys.path)},
    )


def _packet(done):
    assert done.returncode == 0, (done.returncode, done.stdout, done.stderr)
    return json.loads(done.stdout)["hookSpecificOutput"]["additionalContext"]


def _light_note(packet):
    body = packet.split("\n\n### for the memory tools\n", 1)[0]
    heading = "### where i left off\n"
    assert heading in body, body[:400]
    return body.split(heading, 1)[1].split(":\n", 1)[1]


@pytest.mark.parametrize("shape,text", [
    ("no_spaces_ascii", "x" * 3000),
    ("url_like", "https://example.org/" + "a/" * 1500),
    ("cjk_no_spaces", "港口的账本每一行都记录一次渡轮。" * 120),
    ("spaces_exactly_at_the_cut", ("word " * 139) + "abcd " + "tail " * 50),
], ids=lambda v: v if len(v) < 40 else "text")
def test_the_light_note_never_runs_past_the_cap(tmp_path, shape, text):
    db = _store(tmp_path, handoff=text)
    shown = _light_note(_packet(_hook(db, tmp_path, extra=("--wake", "light"))))
    assert len(shown) <= LIGHT_HANDOFF_CHARS, (shape, len(shown), shown[-60:])


@pytest.mark.parametrize("n", [701, 702])
def test_the_light_note_at_the_edge_of_the_cap(tmp_path, n):
    db = _store(tmp_path, handoff="a" * (n - 1) + ".")
    shown = _light_note(_packet(_hook(db, tmp_path, extra=("--wake", "light"))))
    assert len(shown) <= LIGHT_HANDOFF_CHARS, (n, len(shown))


def test_cut_at_sentence_never_returns_more_than_its_limit():
    for text in ("x" * 3000, "a b " * 1000, "港口" * 1000, ("word " * 139) + "abcd " + "tail " * 50):
        out, cut = cut_at_sentence(text, 700)
        assert cut and out.endswith(" […]")
        assert len(out) <= 700, (len(out), out[-40:])


def test_half_the_room_is_counted_without_the_mark():
    # The room is 100 - 4 = 96, so half of it is 48: a sentence ending at 49 is kept whole.
    first = "The harbour ledger balances at the end of day." + "ab."
    assert len(first) == 49
    out, cut = cut_at_sentence(first + " " + "crossing " * 30, 100)
    assert cut and out == first + " […]", out


def test_a_limit_under_the_mark_never_counts_from_the_end():
    out, cut = cut_at_sentence("harbour ledger balances", 2)
    assert cut and out == "h […]", out


def test_a_cue_line_keeps_a_sentence_ending_at_196():
    from mnemos.cue import CUE_LINE_CHARS, line_parts

    first = "The keeper " + "trims the lamp " * 12 + "and sleeps."
    first = first[: 196 - len(" sleeps.")].rstrip() + " sleeps."
    assert 192 < len(first) <= 196, len(first)
    _, words = line_parts(first + " " + "Then the beacon turns all night. " * 3, "2026-10-01")
    assert words == first + " […]", words
    assert len(words) <= CUE_LINE_CHARS


def test_an_upper_case_wake_value_wakes_light(tmp_path):
    db = _store(tmp_path)
    done = _hook(db, tmp_path, extra=("--wake", "LIGHT"))
    packet = _packet(done)
    assert "### where i left off" in packet
    assert JOURNAL not in packet, "woke in full"
    assert len(_light_note(packet)) <= LIGHT_HANDOFF_CHARS


def test_an_unknown_wake_value_wakes_full_with_a_note(tmp_path):
    db = _store(tmp_path)
    done = _hook(db, tmp_path, extra=("--wake", "sideways"))
    assert done.returncode == 0, (done.returncode, done.stderr)
    assert JOURNAL in _packet(done), "did not wake in full"
    assert "unknown wake mode 'sideways'; using full" in done.stderr


# ── A name is one line ──


def test_a_name_with_a_newline_is_kept_on_one_line(runtime):
    said = runtime.introduce(OPUS, "Ash\nWood")
    assert "Agent name: Ash Wood\n" in said, said
    assert runtime._get_meta("agent_name", "") == "Ash Wood"


# ── Old word questions are inert ──


def test_an_old_word_question_is_not_shown_and_does_not_block_a_reaffirmation(runtime):
    target = _capture(runtime, CONTENT, "Kept for the test.")
    runtime._store._get_conn().execute("DELETE FROM reflection_queue")
    runtime._store._commit()
    when = _iso(31)
    belief = Belief(
        agent_id="nova", content="Riley's trips bend to the ferry.", confidence=0.4, domain="ferry",
        supporting_engram_ids=[target], source="agent",
        created_at=when, last_revised=when, last_challenged=when,
    )
    runtime._store.save_belief(belief)
    assert runtime._store.enqueue_reflection("belief", target, WORD_ASK, **SCOPE)

    runtime.maintain()
    packet = runtime.context()

    assert "You keep returning to" not in packet, packet
    reaffirm = runtime._store._get_conn().execute(
        "SELECT prompt FROM reflection_queue WHERE kind = 'reaffirm' AND target_id = ? "
        "AND answered_at IS NULL", (target,),
    ).fetchall()
    assert len(reaffirm) == 1 and f"[belief:{belief.id}]" in reaffirm[0][0]


def test_an_expired_reaffirmation_is_put_again_beside_an_old_word_question(runtime):
    target = _capture(runtime, CONTENT, "Kept for the test.")
    runtime._store._get_conn().execute("DELETE FROM reflection_queue")
    runtime._store._commit()
    when = _iso(31)
    belief = Belief(
        agent_id="nova", content="Riley's trips bend to the ferry.", confidence=0.4, domain="ferry",
        supporting_engram_ids=[target], source="agent",
        created_at=when, last_revised=when, last_challenged=when,
    )
    runtime._store.save_belief(belief)
    asked = runtime._store.enqueue_reflection(
        "reaffirm", target, f'You hold this belief: "{belief.content}". Still true? [belief:{belief.id}]',
        **SCOPE,
    )
    assert asked
    conn = runtime._store._get_conn()
    conn.execute(
        "UPDATE reflection_queue SET created_at = ?, expires_at = ? WHERE id = ?",
        (_iso(40), _iso(10), asked),
    )
    runtime._store._commit()
    assert runtime._store.enqueue_reflection("belief", target, WORD_ASK, **SCOPE)

    runtime.maintain()

    [row] = conn.execute(
        "SELECT expires_at, surfaced_count FROM reflection_queue WHERE id = ?", (asked,),
    ).fetchall()
    assert datetime.fromisoformat(row[0]) > datetime.now(timezone.utc), "the reaffirmation was not put again"
    assert row[1] == 0
