import re
import subprocess
import sys
from pathlib import Path

import pytest

from mnemos.consolidation.softening import _create_or_reinforce_lesson
from mnemos.simple_runtime import _FADING_QUESTION, MnemosRuntime, _early_window_hours


SCOPE = {"agent_id": "t", "person_id": "p", "project_scope": "g"}
SCOPE_ARGS = ["--agent-id", "t", "--person-id", "p", "--project-scope", "g"]
PROMPT = 'You keep returning to "vektor" (5 memories). Is that a belief you now hold? If it is, state it in one line with verdict hold; if it is not, decline. Or leave it. [theme:vektor]'
CONTENT = "Riley plans every trip around the ferry timetable."
IMPACT = "The ferry decides every trip."


@pytest.fixture
def runtime(tmp_path):
    runtime = MnemosRuntime(db_path=tmp_path / "memory.db", use_dedicated_model=False, **SCOPE)
    runtime._ensure_init()
    # These tests draw lessons and fading questions the way older rules did, so
    # the fading rule's code is taken to have first opened this store after
    # them (a test that needs otherwise sets its own time).
    from mnemos.store.sqlite_store import code_version_first_opened_key

    runtime._store._get_conn().execute(
        "UPDATE meta SET value = '2099-01-01T00:00:00+00:00' WHERE key = ?",
        (code_version_first_opened_key(13),),
    )
    runtime._store._commit()
    yield runtime
    runtime.close()


def _capture(runtime, content=CONTENT):
    said = runtime.capture(content, impact=IMPACT)
    return re.search(r"Memory ID: (engram_\w+)", said).group(1)


def _write(runtime, sql, params=()):
    runtime._store._get_conn().execute(sql, params)
    runtime._store._commit()


def _asks(runtime):
    return {row["id"] for row in runtime._store._get_conn().execute("SELECT id FROM reflection_queue").fetchall()}


def _word_store(runtime):
    ids = []
    for i in range(3):
        target = _capture(runtime, f"{CONTENT} Note {i}.")
        ids.append(runtime._store.enqueue_reflection("belief", target, PROMPT, **SCOPE))
    _write(runtime, "UPDATE reflection_queue SET answer = 'my words' WHERE id = ?", (ids[2],))
    return ids


def _lesson(runtime, accessibility=0.5):
    target = _capture(runtime)
    _write(runtime, "UPDATE engrams SET accessibility = ? WHERE id = ?", (accessibility, target))
    source = runtime._store.get_engram(target)
    lesson = _create_or_reinforce_lesson(source, runtime._store, {})
    assert lesson is not None
    return target, lesson


def test_word_questions_dry_run_changes_nothing(runtime):
    ids = _word_store(runtime)
    plan = runtime.repair_word_questions()
    assert len(plan["found"]["empty"]) == 2
    assert len(plan["found"]["worded"]) == 1
    assert set(ids) <= _asks(runtime)


def test_word_questions_write_removes_only_the_empty_ones(runtime):
    ids = _word_store(runtime)
    target = _capture(runtime, "vektor plugin loading improved")
    answered = runtime._store.enqueue_reflection("belief", target, PROMPT, **SCOPE)
    _write(runtime, "UPDATE reflection_queue SET answered_at = '2026-01-01T00:00:00+00:00', answer = 'held' WHERE id = ?", (answered,))
    plan = runtime.repair_word_questions(write=True)
    assert not set(ids[:2]) & _asks(runtime)
    assert {ids[2], answered} <= _asks(runtime)
    assert Path(plan["backup"]).exists()


def test_word_questions_leave_other_kinds_alone(runtime):
    target = _capture(runtime)
    ids = {runtime._store.enqueue_reflection(kind, target, PROMPT, **SCOPE) for kind in ("impact", "lesson")}
    runtime.repair_word_questions(write=True)
    assert ids <= _asks(runtime)


def test_early_lessons_folds_back_a_copy_of_an_unfaded_memory(runtime):
    target, lesson = _lesson(runtime)
    source = runtime._store.get_engram(target)
    before = (source.content, source.impact, source.state)
    runtime.repair_early_lessons(write=True)
    assert runtime._store.get_engram(lesson).state == "archived"
    assert not runtime._store._get_conn().execute("SELECT 1 FROM connections WHERE target_id = ? AND relation = 'distilled_into'", (lesson,)).fetchall()
    source = runtime._store.get_engram(target)
    assert (source.content, source.impact, source.state) == before


def test_early_lessons_keep_a_lesson_whose_memory_faded(runtime):
    _lesson(runtime, 0.1)
    plan = runtime.repair_early_lessons(write=True)
    assert plan["found"] == {"lessons": [], "questions": []}


def test_early_lessons_keep_a_signed_lesson(runtime):
    _, lesson = _lesson(runtime)
    _write(runtime, "UPDATE engrams SET author_model = 'claude-opus-5-5' WHERE id = ?", (lesson,))
    plan = runtime.repair_early_lessons(write=True)
    assert plan["found"] == {"lessons": [], "questions": []}


def test_early_lessons_remove_fading_questions_about_memories_in_reach(runtime):
    ids = []
    for i, accessibility in enumerate((0.5, 0.1)):
        target = _capture(runtime, f"{CONTENT} Note {i}.")
        _write(runtime, "UPDATE engrams SET accessibility = ? WHERE id = ?", (accessibility, target))
        ids.append(runtime._store.enqueue_reflection("lesson", target, _FADING_QUESTION, **SCOPE))
    runtime.repair_early_lessons(write=True)
    assert ids[0] not in _asks(runtime)
    assert ids[1] in _asks(runtime)


def test_both_repairs_print_and_exit_zero(runtime, tmp_path):
    _word_store(runtime)
    _lesson(runtime)
    home = tmp_path / "home"
    home.mkdir()
    for repair in ("word-questions", "early-lessons"):
        done = subprocess.run(
            [sys.executable, "-m", "mnemos.cli", "--db-path", str(runtime.db_path), *SCOPE_ARGS, "repair", repair],
            capture_output=True, text=True, timeout=180,
            env={"HOME": str(home), "PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "MNEMOS_DISABLE_DOTENV": "1", "PYTHONPATH": ":".join(sys.path)},
        )
        assert done.returncode == 0, done.stderr
        assert "Dry run: nothing changed." in done.stdout


def test_early_lessons_keep_a_lesson_drawn_after_its_memory_could_fade(runtime):
    """A memory that really faded, taught its lesson, and was recalled since is
    in reach again; its lesson is real and stays."""
    target, lesson = _lesson(runtime, 0.8)
    _write(runtime, "UPDATE engrams SET created_at = '2026-01-01T00:00:00+00:00' WHERE id = ?", (target,))
    _write(runtime, "UPDATE engrams SET created_at = '2026-01-20T00:00:00+00:00' WHERE id = ?", (lesson,))
    plan = runtime.repair_early_lessons(write=True)
    assert plan["found"] == {"lessons": [], "questions": []}
    assert runtime._store.get_engram(lesson).state == "active"


def test_early_lessons_keep_a_fading_question_asked_after_its_memory_could_fade(runtime):
    """A fading question asked once its memory really faded stays, though a
    recall since has put the memory back in reach."""
    target = _capture(runtime)
    _write(runtime, "UPDATE engrams SET accessibility = 0.8, created_at = '2026-01-01T00:00:00+00:00' WHERE id = ?", (target,))
    ask = runtime._store.enqueue_reflection("lesson", target, _FADING_QUESTION, **SCOPE)
    _write(runtime, "UPDATE reflection_queue SET created_at = '2026-01-20T00:00:00+00:00' WHERE id = ?", (ask,))
    runtime.repair_early_lessons(write=True)
    assert ask in _asks(runtime)


def test_early_lessons_leave_a_lesson_question_in_other_words(runtime):
    """Only the lesson pass's own question is folded back; a lesson question
    an integration asked in its own words is not this repair's to remove."""
    target = _capture(runtime)
    _write(runtime, "UPDATE engrams SET accessibility = 0.5 WHERE id = ?", (target,))
    ask = runtime._store.enqueue_reflection(
        "lesson", target, "What would you tell a newcomer about this?", **SCOPE,
    )
    runtime.repair_early_lessons(write=True)
    assert ask in _asks(runtime)


def _lesson_days_after(runtime, days):
    target, lesson = _lesson(runtime, 0.8)
    _write(runtime, "UPDATE engrams SET created_at = '2026-01-01T00:00:00+00:00' WHERE id = ?", (target,))
    _write(runtime, f"UPDATE engrams SET created_at = '2026-01-{1 + days:02d}T00:00:00+00:00' WHERE id = ?", (lesson,))
    return lesson


def test_early_lessons_fold_back_a_lesson_drawn_sooner_than_its_memory_could_fade(runtime):
    lesson = _lesson_days_after(runtime, 4)  # default decay: the fastest fade takes about 5 days
    plan = runtime.repair_early_lessons()
    assert plan["found"]["lessons"] == [lesson]


def test_early_lessons_read_the_configured_decay(runtime, monkeypatch):
    """With a faster configured decay a memory can really fade in three days
    (a first cycle after 72 hours catches up from 0.5 at once), so a lesson
    drawn four days after its memory may be real."""
    monkeypatch.setenv("MNEMOS_CONSOLIDATION_DECAY_RATE", "0.05")
    _lesson_days_after(runtime, 4)
    plan = runtime.repair_early_lessons()
    assert plan["found"]["lessons"] == []


def test_early_lessons_keep_a_lesson_a_later_memory_joined(runtime):
    """A memory written after the lesson that faded and reinforced it: the
    lesson's own time says nothing about that link, so the lesson stays."""
    first, lesson = _lesson(runtime, 0.5)
    later = _capture(runtime, f"{CONTENT} Again, weeks later.")
    _write(runtime, "UPDATE engrams SET created_at = '2026-01-01T00:00:00+00:00' WHERE id = ?", (first,))
    _write(runtime, "UPDATE engrams SET created_at = '2026-01-02T00:00:00+00:00' WHERE id = ?", (lesson,))
    _write(runtime, "UPDATE engrams SET created_at = '2026-01-20T00:00:00+00:00', accessibility = 0.8 WHERE id = ?", (later,))
    joined = runtime._store.get_engram(later)
    joined.add_connection(target_id=lesson, relation="distilled_into", strength=0.8, formed_by="consolidation")
    runtime._store.save_engram(joined)
    plan = runtime.repair_early_lessons()
    assert plan["found"]["lessons"] == []


def test_the_early_window_follows_the_configured_decay():
    # The sooner of: held at 0.4 for 72 hours then decaying (72 + ln(0.4/0.15)/0.01
    # = 170.1), or a first cycle after 72 hours catching up from 0.5 at once
    # (ln(0.5/0.15)/0.01 = 120.4, never under 72).
    assert round(_early_window_hours({}), 1) == 120.4
    assert round(_early_window_hours({"decay_rate": 0.05}), 1) == 72.0
    # Above the recency floor the floor holds nothing back: from 0.5 to 0.45
    # takes about 10.5 hours, so the minimum age (24) decides.
    assert _early_window_hours({"softening_threshold": 0.45}) == 24.0
    assert _early_window_hours({"softening_threshold": 0.6}) == 24.0
    assert _early_window_hours({"decay_rate": 0}) == 24.0
    assert _early_window_hours({"softening_threshold": 0.45, "softening_min_age_hours": 1}) == pytest.approx(10.536, abs=0.01)


def test_early_lessons_never_touch_what_the_new_rule_drew(runtime):
    """Whatever was drawn after the fading rule's code first opened the store
    was drawn by that rule, whatever the decay settings were then or are now,
    so the repair leaves it alone even when its timing looks early."""
    from mnemos.store.sqlite_store import code_version_first_opened_key

    target, lesson = _lesson(runtime, 0.5)
    _write(runtime, "UPDATE meta SET value = '2026-01-10T00:00:00+00:00' WHERE key = ?",
           (code_version_first_opened_key(13),))
    _write(runtime, "UPDATE engrams SET created_at = '2026-01-14T00:00:00+00:00' WHERE id = ?", (target,))
    _write(runtime, "UPDATE engrams SET created_at = '2026-01-15T00:00:00+00:00' WHERE id = ?", (lesson,))
    ask_target = _capture(runtime, f"{CONTENT} Asked under the new rule.")
    _write(runtime, "UPDATE engrams SET created_at = '2026-01-14T00:00:00+00:00', accessibility = 0.5 WHERE id = ?", (ask_target,))
    ask = runtime._store.enqueue_reflection("lesson", ask_target, _FADING_QUESTION, **SCOPE)
    _write(runtime, "UPDATE reflection_queue SET created_at = '2026-01-15T00:00:00+00:00' WHERE id = ?", (ask,))
    plan = runtime.repair_early_lessons(write=True)
    assert plan["found"] == {"lessons": [], "questions": []}


def test_the_first_open_of_each_code_version_is_kept_once(runtime):
    from mnemos.code_version import MAINTENANCE_CODE_VERSION
    from mnemos.store.sqlite_store import code_version_first_opened_key

    key = code_version_first_opened_key(MAINTENANCE_CODE_VERSION + 1)
    assert runtime._store.get_meta(key) is None
    runtime._store.raise_min_code_version(MAINTENANCE_CODE_VERSION + 1)
    first = runtime._store.get_meta(key)
    assert first
    runtime._store.raise_min_code_version(MAINTENANCE_CODE_VERSION + 1)
    assert runtime._store.get_meta(key) == first
