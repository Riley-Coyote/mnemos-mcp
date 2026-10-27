"""Waking in my own words.

The waking note was mostly records about the agent: event notes it was
"carrying", foundational notes filed under the person's name, and upkeep's own
report. It is now the agent's own words, in the order a mind wakes: what it has
come to see, where it was, what has been changing in it, what it keeps coming
back to, the person, one question, and while it was away.

Packets are built with ``build_context_packet`` and an explicit reader: the
hook reads the launch line with ``ps``, which the build sandbox blocks.
"""

from __future__ import annotations

import json
import math
import random
import re
from datetime import datetime, timedelta, timezone

import pytest

from mnemos import life
from mnemos.authorship import model_line
from mnemos.core.belief import Belief
from mnemos.core.engram import Engram
from mnemos.interface.context_packet import build_context_packet
from mnemos.simple_runtime import MnemosRuntime

OPUS = "claude-opus-5-5"
SONNET = "claude-sonnet-5-5"
SCOPE = {"agent_id": "nova", "person_id": "riley", "project_scope": "demo"}


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / ".mnemos").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    rt = MnemosRuntime(db_path=str(tmp_path / "memory.db"), use_dedicated_model=False, **SCOPE)
    rt._ensure_init()
    yield rt
    rt.close()


def _packet(rt, reader_model=OPUS, **kwargs):
    kwargs.setdefault("mark_surfaced", False)
    return build_context_packet(rt._store, **SCOPE, reader_model=reader_model,
                                person_name="Riley", **kwargs)


def _id(result):
    return re.search(r"Memory ID: (engram_\w+)", result).group(1)


def _headings(text):
    return [line[4:] for line in text.splitlines() if line.startswith("### ")]


def _section(text, heading):
    assert f"### {heading}\n" in text, text
    return text.split(f"### {heading}\n", 1)[1].split("\n\n### ", 1)[0]


def _impacts(rt, count, model, *, start=0):
    """``count`` captures with impacts signed by ``model``, a minute apart,
    oldest first; returns their impacts in that order."""
    now = datetime.now(timezone.utc)
    impacts = []
    for index in range(start, start + count):
        impact = f"Change number {index} taught me to look again at the harbour."
        target = _id(rt.capture(f"Riley and I checked harbour item {index}.",
                                impact=impact, signed_as=model))
        rt._store._get_conn().execute(
            "UPDATE engrams SET created_at = ? WHERE id = ?",
            ((now - timedelta(hours=1, minutes=100 - index)).isoformat(), target),
        )
        rt._store._commit()
        impacts.append(impact)
    return impacts


# ── C1 · The full wake, in this order ──


def test_the_full_wake_is_in_the_agents_own_order(runtime):
    runtime._store.save_belief(Belief(agent_id="nova", content="The render is the honest judge.",
                                      confidence=0.4, author_model=OPUS))
    runtime.handoff("Where I stopped: the harbour ledger balances.", signed_as=OPUS)
    _impacts(runtime, 3, OPUS)
    runtime.capture("Riley wants short bullets.", signed_as=OPUS, standing=True)
    target = _id(runtime.capture("The rendered page showed the missing alignment.",
                                 impact="The render is where I check the work.", signed_as=OPUS))
    runtime._store.enqueue_reflection(
        "belief", target, f"Is there something you believe here? [evidence:{target}]",
        **SCOPE, for_model="opus",
    )
    text = _packet(runtime)["prompt"]
    assert _headings(text) == [
        "what i'm starting to see", "where i was", "what's been changing in me", "Riley",
        "a question waiting for me", "for the memory tools",
    ], text
    for absent in ("what i'm carrying", "also:", "while i was away"):
        assert absent not in text, text


def test_changing_is_the_readers_own_newest_impacts(runtime):
    opus = _impacts(runtime, 7, OPUS)
    sonnet = _impacts(runtime, 1, SONNET, start=7)
    unsigned = _impacts(runtime, 1, "", start=8)
    assert runtime._store._get_conn().execute(
        "SELECT author_model FROM engrams WHERE impact = ?", (unsigned[0],),
    ).fetchone()[0] == "", "premise: one line is unsigned"

    shown = _section(_packet(runtime)["prompt"], "what's been changing in me")
    assert [line.split(" (", 1)[0] for line in shown.splitlines()] == [
        f"- {impact}" for impact in reversed(opus[2:])
    ], shown

    as_sonnet = _packet(runtime, reader_model=SONNET)["prompt"]
    shown = _section(as_sonnet, "what has been changing in this mind")
    assert [line.split(" (", 1)[0] for line in shown.splitlines()] == [f"- {sonnet[0]}"], shown
    assert unsigned[0] not in as_sonnet


def test_a_lesson_and_its_memory_are_one_line(runtime):
    impact = "Checking the real page outranks reasoning about it."
    target = _id(runtime.capture("Riley and I looked at the live ferry page.", impact=impact,
                                 signed_as=OPUS))
    memory = runtime._store.get_engram(target)
    runtime._store.save_engram(Engram(
        content=impact, impact=impact, impact_source="agent", kind="procedural",
        tags=["lesson", "distilled"], owner_agent_id="nova", person_id="riley",
        project_scope="demo", author_kind="agent", author_model=OPUS,
    ))
    assert memory.author_model == OPUS
    text = _packet(runtime)["prompt"]
    assert _section(text, "what's been changing in me").count(impact) == 1, text


def test_returning_shows_found_ideas_until_they_are_held(runtime):
    runtime.handoff("Where I stopped: the harbour ledger balances.", signed_as=OPUS)
    first = {"ids": ["engram_A1", "engram_A2", "engram_A3"], "days": 3,
             "quote": "The render is the only honest judge."}
    second = {"ids": ["engram_B1", "engram_B2", "engram_B3"], "days": 4,
              "quote": "Riley reads the result before the code."}
    runtime._set_meta("ideas_returning", json.dumps([first, second]))

    shown = _section(_packet(runtime)["prompt"], "what i keep coming back to")
    assert shown.splitlines() == [
        '- "The render is the only honest judge." (3 days)',
        '- "Riley reads the result before the code." (4 days)',
    ], shown

    runtime._store.save_belief(Belief(agent_id="nova", content="The render judges.",
                                      confidence=0.6, author_model=OPUS,
                                      supporting_engram_ids=list(first["ids"])))
    shown = _section(_packet(runtime)["prompt"], "what i keep coming back to")
    assert shown.splitlines() == ['- "Riley reads the result before the code." (4 days)'], shown


def test_a_quiet_hour_shows_while_i_was_away(runtime):
    runtime.handoff("Where I stopped: the harbour ledger balances.", signed_as=OPUS)
    entry = runtime._store.write_journal_entry(
        "\nThe tide came in while I read.\nThen I wrote about the ledger.", **SCOPE,
        written="between_sessions", model_id=OPUS, hour_id="hour-1",
    )
    now = datetime.now(timezone.utc)
    runtime._set_meta("last_context_delivery_at", (now - timedelta(hours=2)).isoformat())
    hours = life.hours_dir("nova")
    hours.mkdir(parents=True)
    record = {"id": "hour-1", "kind": "mine", "status": "done", "store": "live", "model": OPUS,
              "started_at": (now - timedelta(hours=1, minutes=30)).isoformat(),
              "ended_at": (now - timedelta(hours=1)).isoformat(), "journal_ids": [entry]}
    (hours / "hours.jsonl").write_text(json.dumps(record) + "\n")

    first = _packet(runtime, mark_surfaced=True)["prompt"]
    away = _section(first, "while i was away")
    assert away == "- my quiet hour (1 hour ago): The tide came in while I read.", first

    second = _packet(runtime, mark_surfaced=True)["prompt"]
    assert "- my quiet hour (" not in second, second


def test_a_reader_no_one_named_gets_the_residents_quiet_hour(runtime):
    """Quiet hours are on unless the person says no, and most people start
    Claude Code without naming a model to its hooks: the resident's hour
    shows to a reader no one named, as its notes do (Riley, 2026-10-27)."""
    runtime.handoff("Where I stopped: the harbour ledger balances.", signed_as=OPUS)
    entry = runtime._store.write_journal_entry(
        "\nThe tide came in while I read.\nThen I wrote about the ledger.", **SCOPE,
        written="between_sessions", model_id=OPUS, hour_id="hour-1",
    )
    now = datetime.now(timezone.utc)
    runtime._set_meta("last_context_delivery_at", (now - timedelta(hours=2)).isoformat())
    hours = life.hours_dir("nova")
    hours.mkdir(parents=True)
    record = {"id": "hour-1", "kind": "mine", "status": "done", "store": "live", "model": OPUS,
              "started_at": (now - timedelta(hours=1, minutes=30)).isoformat(),
              "ended_at": (now - timedelta(hours=1)).isoformat(), "journal_ids": [entry]}
    (hours / "hours.jsonl").write_text(json.dumps(record) + "\n")

    prompt = _packet(runtime, reader_model="", mark_surfaced=True)["prompt"]
    assert "if I'm not Opus 5.5, I'm visiting." in prompt, prompt
    assert "- my quiet hour (1 hour ago): The tide came in while I read." in prompt, prompt
    assert "### where i was\n" in prompt, prompt


def test_a_reader_no_one_named_reads_its_own_journal_as_its_own(runtime):
    runtime.capture("Riley keeps the harbour ledger in ledger/2026.csv.", signed_as=OPUS)
    runtime._store.write_journal_entry("The ledger balanced at last.", **SCOPE, model_id=OPUS)

    prompt = _packet(runtime, reader_model="")["prompt"]
    assert "### where i was\nlast time I wrote in my journal (" in prompt, prompt
    assert "): The ledger balanced at last." in prompt, prompt


def test_replies_now_wake_under_while_i_was_away(runtime):
    note = runtime.note("Do you want the harbour survey redone?", "question", signed_as=OPUS)
    note_id = re.search(r"Note ID: (\S+)", note).group(1)
    runtime.reply_to_note(note_id, "Yes, on Thursday.")

    first = _packet(runtime, mark_surfaced=True)["prompt"]
    away = _section(first, "while i was away")
    assert away == '- Riley replied to my note "Do you want the harbour survey redone?": Yes, on Thursday.', first
    delivered = runtime._store._get_conn().execute(
        "SELECT delivered_at FROM notes WHERE author = 'person'").fetchall()
    assert [row[0] is not None for row in delivered] == [True]

    second = _packet(runtime, mark_surfaced=True)["prompt"]
    assert "Yes, on Thursday." not in second, second


# ── C2 · The noticer keeps what it found ──


def _unit(vector):
    norm = math.sqrt(sum(value * value for value in vector))
    return [value / norm for value in vector]


def _cosine(left, right):
    return sum(a * b for a, b in zip(left, right))


def _vectors(groups=1, size=3, background=37):
    """Fixed 384-dimensional unit vectors (seed 1004): idea groups of members
    close to one base each, and independent background vectors."""
    from mnemos.simple_runtime import _IDEA_FLOOR

    rng = random.Random(1004)
    ideas = []
    for _ in range(groups):
        base = _unit([rng.gauss(0.0, 1.0) for _ in range(384)])
        ideas.append([_unit([value + rng.gauss(0.0, 0.01) for value in base]) for _ in range(size)])
    spread = [_unit([rng.gauss(0.0, 1.0) for _ in range(384)]) for _ in range(background)]
    inside = min(_cosine(a, b) for group in ideas for i, a in enumerate(group) for b in group[i + 1:])
    everything = [vector for group in ideas for vector in group] + spread
    outside = max(_cosine(a, b) for a in spread for b in everything if b is not a)
    assert inside >= 0.9, f"the smallest cosine inside a group is {inside}"
    assert outside < inside, f"a background vector reaches {outside}, the group's smallest is {inside}"
    assert outside < _IDEA_FLOOR, f"a background vector reaches {outside}, the floor is {_IDEA_FLOOR}"
    return ideas, spread


_IDEA_WORDS = (
    ("Riley and I compared draft {index} with what the page rendered.",
     "The render is the only honest judge, draft {index} showed it."),
    ("Riley and I timed ferry crossing {index} against the printed table.",
     "The printed table lies about crossing {index}; I trust the clock now."),
)


def _idea_store(rt, monkeypatch, ideas_count=1):
    """37 background impact lines and ``ideas_count`` ideas each returning
    three times, all the agent's own; returns the first idea's memory ids,
    oldest first, and the background ids (with two ideas, a list of each
    idea's ids in place of the first)."""
    rt.handoff("I will judge the next alignment in the render.", signed_as=OPUS)
    rt.handoff("The rendered page is where I check the work.", signed_as=OPUS)
    ideas, spread = _vectors(groups=ideas_count)
    vectors = {}
    background = []
    for index, vector in enumerate(spread):
        target = _id(rt.capture(f"Background note {index}: Riley looked at item {index} of the list.",
                                impact=f"Item {index} of the list changed how I read entry {index}.",
                                signed_as=OPUS))
        vectors[target] = vector
        background.append(target)
    groups = []
    for idea, members in enumerate(ideas):
        content, impact = _IDEA_WORDS[idea]
        group = []
        for index, vector in enumerate(members):
            target = _id(rt.capture(content.format(index=index), impact=impact.format(index=index),
                                    signed_as=OPUS))
            vectors[target] = vector
            group.append(target)
        groups.append(group)
    now = datetime.now(timezone.utc)
    conn = rt._store._get_conn()
    for index, target in enumerate(background):
        conn.execute("UPDATE engrams SET created_at = ?, author_session = ? WHERE id = ?",
                     ((now - timedelta(days=index + 1, hours=1)).isoformat(), f"background-{index}", target))
    for idea, group in enumerate(groups):
        for index, target in enumerate(group):
            conn.execute("UPDATE engrams SET created_at = ?, author_session = ? WHERE id = ?",
                         ((now - timedelta(days=9 - 3 * index + idea, hours=2)).isoformat(),
                          f"idea{idea}-{index}", target))
    conn.execute("DELETE FROM meta WHERE key = ?", (rt._meta_key("ideas_noticed_at"),))
    rt._store._commit()
    monkeypatch.setattr(rt._embedding_index, "impact_vectors",
                        lambda impacts: {item: vectors[item] for item in impacts if item in vectors})
    return (groups[0] if ideas_count == 1 else groups), background


def test_the_noticer_saves_groups_while_a_question_is_open(runtime, monkeypatch):
    group, background = _idea_store(runtime, monkeypatch)
    runtime._store.enqueue_reflection(
        "belief", background[0], f"Is there something you believe here? [evidence:{background[0]}]",
        **SCOPE, for_model="opus",
    )
    before = runtime._store._get_conn().execute(
        "SELECT COUNT(*) FROM reflection_queue WHERE kind = 'belief'").fetchone()[0]

    assert runtime._enqueue_returning_idea() == 0
    after = runtime._store._get_conn().execute(
        "SELECT COUNT(*) FROM reflection_queue WHERE kind = 'belief'").fetchone()[0]
    assert after == before == 1
    assert json.loads(runtime._get_meta("ideas_returning") or "null") == [{
        "ids": group, "days": 3, "quote": "The render is the only honest judge, draft 2 showed it.",
    }]


# ── C3 · No meaning asked of a standing memory ──


def test_standing_memories_are_not_asked_what_they_changed(runtime):
    target = _id(runtime.capture("Riley wants short bullets.", signed_as=OPUS, standing=True))
    runtime.maintain()
    asked = runtime._store._get_conn().execute(
        "SELECT COUNT(*) FROM reflection_queue WHERE kind = 'impact' AND target_id = ?", (target,),
    ).fetchone()[0]
    assert asked == 0


# ── C4 · Quiet hours see the questions addressed to them ──


def test_the_hour_gathers_questions_addressed_to_it(runtime):
    target = _id(runtime.capture("The rendered page showed the missing alignment.",
                                 impact="The render is where I check the work.", signed_as=OPUS))
    runtime._store.enqueue_reflection(
        "belief", target, f"Is there something you believe here? [evidence:{target}]",
        **SCOPE, for_model=model_line(life.HOUR_MODEL),
    )
    since = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    _, _, questions, _ = life._gather("mine", runtime._store.db_path, since, SCOPE)
    assert [(question["kind"], question["target_id"]) for question in questions
            if question["kind"] == "belief"] == [("belief", target)]


# ── Round 2 ──


def test_one_idea_seen_from_three_seeds_is_saved_once(runtime, monkeypatch):
    group, _ = _idea_store(runtime, monkeypatch)
    runtime._enqueue_returning_idea()
    saved = json.loads(runtime._get_meta("ideas_returning") or "null")
    assert [entry["ids"] for entry in saved] == [group], saved


def test_two_distinct_ideas_are_saved_as_two(runtime, monkeypatch):
    groups, _ = _idea_store(runtime, monkeypatch, ideas_count=2)
    runtime._enqueue_returning_idea()
    saved = json.loads(runtime._get_meta("ideas_returning") or "null")
    assert sorted(entry["ids"] for entry in saved) == sorted(groups), saved


def _the_ideas_question(rt):
    return rt._store._get_conn().execute(
        "SELECT id, target_id, answered_at FROM reflection_queue "
        "WHERE kind = 'belief' AND instr(prompt, '[evidence:') > 0").fetchall()


def test_an_idea_whose_question_is_open_is_not_shown_twice(runtime, monkeypatch):
    _idea_store(runtime, monkeypatch)
    assert runtime._enqueue_returning_idea() == 1
    asked = _the_ideas_question(runtime)
    assert len(asked) == 1 and asked[0]["answered_at"] is None, "premise: one open question"

    text = _packet(runtime)["prompt"]
    assert "### a question waiting for me" in text, text
    assert "### what i keep coming back to" not in text, text


def test_an_idea_whose_question_was_declined_still_returns(runtime, monkeypatch):
    _idea_store(runtime, monkeypatch)
    assert runtime._enqueue_returning_idea() == 1
    runtime.reflect(_the_ideas_question(runtime)[0]["target_id"], "Nothing I hold yet.",
                    verdict="decline", signed_as=OPUS)
    assert _the_ideas_question(runtime)[0]["answered_at"] is not None, "premise: declined"
    runtime._set_meta("ideas_noticed_at", "")
    runtime._enqueue_returning_idea()

    shown = _section(_packet(runtime)["prompt"], "what i keep coming back to")
    assert shown.splitlines() == [
        '- "The render is the only honest judge, draft 2 showed it." (3 days)',
    ], shown


def test_an_open_question_keeps_the_noticer_to_once_a_day(runtime, monkeypatch):
    from mnemos import simple_runtime

    _, background = _idea_store(runtime, monkeypatch)
    runtime._store.enqueue_reflection(
        "belief", background[0], f"Is there something you believe here? [evidence:{background[0]}]",
        **SCOPE, for_model="opus",
    )
    calls = []
    real = simple_runtime._idea_similarities

    def spy(values):
        calls.append(len(values))
        return real(values)

    monkeypatch.setattr(simple_runtime, "_idea_similarities", spy)
    runtime.maintain()
    assert len(calls) == 1, "premise: the first maintain computes the groups"
    runtime.maintain()
    assert len(calls) == 1


def _quiet_hour(rt, first_line="The tide came in while I read."):
    """One done, live, own quiet hour by Opus that ended an hour ago, with the
    journal entry it wrote; no delivery recorded. Returns the entry's id."""
    entry = rt._store.write_journal_entry(
        f"\n{first_line}\nThen I wrote about the ledger.", **SCOPE,
        written="between_sessions", model_id=OPUS, hour_id="hour-1",
    )
    now = datetime.now(timezone.utc)
    hours = life.hours_dir("nova")
    hours.mkdir(parents=True)
    record = {"id": "hour-1", "kind": "mine", "status": "done", "store": "live", "model": OPUS,
              "started_at": (now - timedelta(hours=1, minutes=30)).isoformat(),
              "ended_at": (now - timedelta(hours=1)).isoformat(), "journal_ids": [entry]}
    (hours / "hours.jsonl").write_text(json.dumps(record) + "\n")
    return entry


def test_each_quiet_hour_shows_once(runtime):
    _quiet_hour(runtime)
    assert runtime._get_meta("last_context_delivery_at") is None, "premise: no delivery"

    light = _packet(runtime, mark_surfaced=True, wake="light")["prompt"]
    assert "my quiet hour" not in light, light
    assert runtime._get_meta("last_hour_shown") is None

    first = _packet(runtime, mark_surfaced=True)["prompt"]
    assert "- my quiet hour (1 hour ago): The tide came in while I read." in first, first
    second = _packet(runtime, mark_surfaced=True)["prompt"]
    assert "my quiet hour" not in second, second


def test_the_hours_journal_entry_is_said_once(runtime):
    _quiet_hour(runtime)
    text = _packet(runtime)["prompt"]
    assert "- my quiet hour (1 hour ago): The tide came in while I read." in text, text
    assert text.count("The tide came in while I read.") == 1, text


def _settled(rt):
    """A store past onboarding, so the wake is all that ``context`` says."""
    rt._set_meta("onboarding_stage", "complete")
    rt._set_meta("verified_at", "skipped")


def test_an_empty_memory_says_nothing_has_carried_over(runtime):
    _settled(runtime)
    assert runtime.context() == (
        "Nothing has carried over yet: no handoff, notes or beliefs in this "
        "memory. Capture durable context as the conversation gives it."
    )


def test_kept_memories_with_nothing_to_wake_with_are_counted(runtime, monkeypatch):
    # Unsigned memories, written and read by a session that can't name its
    # model: none is the reader's own words, and each already says what it
    # changed, so no question is asked.
    monkeypatch.setattr(runtime, "author_model", lambda signed_as="": "")
    _settled(runtime)
    runtime.capture("Riley moved the harbour survey to Thursday.",
                    impact="Plans with Riley move; I check the day before.")
    active = "SELECT COUNT(*) FROM engrams WHERE state = 'active' AND author_model = ''"
    assert runtime._store._get_conn().execute(active).fetchone()[0] == 1, "premise: one memory"
    assert runtime.context() == (
        "Nothing to wake with yet in my own words, but 1 memory is kept: "
        "recall finds them when something needs them."
    )

    runtime.capture("Riley keeps the tide tables on the kitchen wall.",
                    impact="The tides are Riley's to read; I ask before planning.")
    assert runtime.context() == (
        "Nothing to wake with yet in my own words, but 2 memories are kept: "
        "recall finds them when something needs them."
    )


# ── Round 3 ──


_EMPTY_WARNING = "carried no continuity"


def _changing_and_returning(rt):
    """A store whose full wake is only what has been changing and what I keep
    coming back to: Opus's own impact lines and one idea the noticer found."""
    _impacts(rt, 2, OPUS)
    rt._set_meta("ideas_returning", json.dumps([{
        "ids": ["engram_A1", "engram_A2", "engram_A3"], "days": 3,
        "quote": "The render is the only honest judge.",
    }]))


def test_the_new_sections_count_as_carried(runtime):
    from mnemos.interface.context_packet import carried_count

    _changing_and_returning(runtime)
    packet = _packet(runtime)
    assert _headings(packet["prompt"]) == [
        "what's been changing in me", "what i keep coming back to",
    ], packet["prompt"]
    assert carried_count(packet) > 0


def test_a_wake_of_the_new_sections_is_not_an_empty_packet(runtime, monkeypatch):
    monkeypatch.setattr(runtime, "author_model", lambda signed_as="": OPUS)
    _settled(runtime)
    _changing_and_returning(runtime)
    for _ in range(3):
        assert "### what's been changing in me" in runtime.context()
    signals = runtime.continuity_signals()
    assert signals["empty_context_streak"] == 0
    assert not [w for w in signals["warnings"] if _EMPTY_WARNING in w], signals["warnings"]


def test_an_empty_scope_still_counts_as_empty(runtime):
    _settled(runtime)
    for _ in range(3):
        assert runtime.context().startswith("Nothing has carried over yet")
    signals = runtime.continuity_signals()
    assert signals["empty_context_streak"] == 3
    assert [w for w in signals["warnings"] if _EMPTY_WARNING in w], signals["warnings"]


def test_an_honest_empty_wake_is_not_counted_as_amnesia(runtime, monkeypatch):
    """Kept memories with nothing in my own words to wake with (unsigned, each
    already saying what it changed, so no question is asked): the wake says
    they are kept, recall reaches them, and the empty-packet streak doesn't
    grow, so the health card doesn't warn of amnesia."""
    monkeypatch.setattr(runtime, "author_model", lambda signed_as="": "")
    _settled(runtime)
    runtime.capture("Riley moved the harbour survey to Thursday.",
                    impact="Plans with Riley move; I check the day before.")
    for _ in range(3):
        assert runtime.context().startswith("Nothing to wake with yet in my own words")
    signals = runtime.continuity_signals()
    assert signals["empty_context_streak"] == 0
    assert not [w for w in signals["warnings"] if _EMPTY_WARNING in w], signals["warnings"]
    assert "harbour survey" in runtime.recall("harbour survey Thursday")


def test_what_the_new_note_shows_counts_as_shown_for_the_cue():
    """The cue never brings back in a session what the wake showed: the memory
    a question quotes, an impact line shown as changing, and each memory of an
    idea shown as returning count as shown, as a carried note did."""
    from mnemos.interface.context_packet import shown_memories

    packet = {
        "shown": {"questions": ["q1"], "changing": ["engram_C1"],
                  "returning": ["engram_R1,engram_R2"]},
        "reflections": [{"id": "q1", "target_id": "engram_Q1"},
                        {"id": "q2", "target_id": "engram_NOT_SHOWN"}],
        "changing": [{"id": "engram_C1", "text": "The render is where I check the work."},
                     {"id": "engram_C2", "text": "Cut for room."}],
    }

    ids, texts = shown_memories(packet)

    assert {"engram_Q1", "engram_C1", "engram_R1", "engram_R2"} <= ids
    assert "engram_NOT_SHOWN" not in ids and "engram_C2" not in ids
    assert "The render is where I check the work." in texts and "Cut for room." not in texts
