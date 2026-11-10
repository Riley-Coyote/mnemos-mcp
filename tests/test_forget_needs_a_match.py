"""A correction by query acts only on what the query's words really name.

mnemos_correct can forget or rewrite a note found by a query instead of an ID.
It took whatever came closest, however far that was: on a scratch store,
"forget the zeppelin schedule" archived "The writing group will meet at the
bookshop next Thursday, as a public reading." Nothing there mentions a
zeppelin. Notes were also scored on every word of the query, so sharing "the"
or "her" counted as much as sharing what the query was about.

Now a note, memory or belief is acted on only when it holds the words that mean
something in the query: at least half of them, and two when the query has two
or more. Otherwise a forget archives nothing and says so, and an update is kept
as new continuity instead of overwriting an unrelated note.
"""

from __future__ import annotations

import pytest

from mnemos.core.belief import Belief
from mnemos.core.engram import Engram
from mnemos.simple_runtime import MnemosRuntime

SCOPE = dict(agent_id="t", person_id="p", project_scope="g")

ZEPPELIN = "The zeppelin schedule moved to Tuesdays."
# The last shares "forget", "the" and "schedule" with "forget the zeppelin schedule".
NOTES = [
    "The writing group will meet at the bookshop next Thursday, as a public reading.",
    "A stuck scene can wait for the noon walk.",
    "Her sister Ines lives in Porto and reads every chapter first.",
    "Don't forget: the ferry schedule changes in May.",
]


def _runtime(tmp_path):
    return MnemosRuntime(db_path=str(tmp_path / "forget.db"), **SCOPE)


def _notes(rt):
    return {note["content"] for note in rt._store.search_hypomnema("", limit=50, **SCOPE)}


def _memories(rt):
    return {engram.content for engram in rt._store.get_active_engrams(agent_id="t", limit=50)}


def test_forgetting_what_no_note_mentions_archives_nothing(tmp_path):
    rt = _runtime(tmp_path)
    for note in NOTES:
        rt.capture(content=note)
    notes, memories = _notes(rt), _memories(rt)

    out = rt.correct(correction="", query="forget the zeppelin schedule", action="forget")

    assert out.startswith("Nothing was archived"), out
    assert _notes(rt) == notes
    assert _memories(rt) == memories


def test_a_memory_holding_one_of_two_words_is_not_forgotten(tmp_path):
    """No note in scope, so the query goes to the memories themselves."""
    rt = _runtime(tmp_path)
    rt._ensure_init()
    ferry = Engram(content="The ferry schedule changes in May.", kind="semantic", **{
        "owner_agent_id": "t", "person_id": "p", "project_scope": "g"})
    rt._store.save_engram(ferry)

    out = rt.correct(correction="", query="the zeppelin schedule", action="forget")

    assert out.startswith("Nothing was archived"), out
    assert rt._store.get_engram(ferry.id).state == "active"


def test_forgetting_what_the_words_name_archives_that_note(tmp_path):
    rt = _runtime(tmp_path)
    for note in [ZEPPELIN, *NOTES]:
        rt.capture(content=note)

    out = rt.correct(correction="", query="forget the zeppelin schedule", action="forget")

    assert out.startswith("Archived"), out
    assert _notes(rt) == set(NOTES)
    assert ZEPPELIN not in _memories(rt)


def test_an_update_that_names_no_note_rewrites_none(tmp_path):
    rt = _runtime(tmp_path)
    for note in NOTES:
        rt.capture(content=note)

    out = rt.correct(correction="The zeppelin now flies on Tuesdays.", query="zeppelin schedule")

    assert out.startswith("No continuity note matched"), out
    assert set(NOTES) <= _notes(rt), "a note that never mentioned a zeppelin was rewritten"
    assert "The zeppelin now flies on Tuesdays." in _notes(rt)


def test_a_belief_is_not_retired_over_what_and_she(tmp_path):
    rt = _runtime(tmp_path)
    rt._ensure_init()
    rt._store.save_belief(Belief(agent_id="t", content="She says what she means.",
                                 confidence=0.7, source="agent"))

    out = rt.correct(correction="", query="forget what she said", action="forget")

    assert "Retired" not in out, out
    assert rt._store.get_beliefs("t", active_only=True)


@pytest.fixture
def words_only(monkeypatch):
    # This is about which notes the question's words name, so meaning search is off.
    from mnemos.store import embedding_index as ei

    monkeypatch.setattr(ei, "_check_local_deps", lambda: False)


def test_recall_shows_the_notes_the_question_is_about(tmp_path, words_only):
    about_the_reading = [
        "She asked me to keep every morning clear this week, until the reading.",
        "The writing group will meet at the bookshop next Thursday, as a public reading.",
    ]
    rt = _runtime(tmp_path)
    for note in [
        "A stuck scene can wait for the noon walk.",
        "Jansson's quiet is the tone she's reaching for.",
        "Guard her writing hours this week.",
        *about_the_reading,
    ]:
        rt.capture(content=note)

    out = rt.recall("getting ready for her reading")
    # A capture's note and memory are one object, so recall shows each
    # capture once, as its memory (R08); every row is one.
    shown = {line.split("] ", 1)[1] for line in out.splitlines() if line.startswith("- [")}

    assert shown == set(about_the_reading), shown


@pytest.mark.parametrize("action", ["update", "forget"])
def test_an_id_that_names_nothing_here_changes_nothing(tmp_path, action):
    """The same for an id. One that names nothing here (mistyped, made up, or
    another agent's) fell through to what a call with no id does. A correction
    was captured as a new memory with no word that the id was unknown, so the
    memory it meant to replace stayed in use beside it, saying the old thing;
    and a forget answered "give the ID as target_id", to a call that had."""
    rt = _runtime(tmp_path)
    rt.capture(content=ZEPPELIN)
    notes, memories = _notes(rt), _memories(rt)

    out = rt.correct(
        correction="" if action == "forget" else "The zeppelin schedule moved to Fridays.",
        target_id="engram_01ZZZZZZZZZZZZZZZZZZZZZZZZ", action=action,
    )

    assert out.startswith("Nothing was archived" if action == "forget" else "Nothing was changed"), out
    assert "engram_01ZZZZZZZZZZZZZZZZZZZZZZZZ" in out and "has the id" in out
    assert _notes(rt) == notes and _memories(rt) == memories, "something was written for an id that names nothing"


@pytest.mark.parametrize("no_id", ["none", "None", "null", "NULL", "n/a", "N/A", "nil", "undefined", "-", '""', "``"])
def test_an_id_that_says_there_is_none_is_no_id(tmp_path, no_id):
    """A model asked for an optional id often fills it with a word for none.
    Taken for an id nothing has, that word changed nothing and kept nothing:
    the fact the agent meant to keep was dropped, with a line about an id it
    never had. It is what leaving the id out is."""
    rt = _runtime(tmp_path)
    rt.capture(content=ZEPPELIN)

    out = rt.correct(correction="The bakery on Calle Mayor opens at six.", target_id=no_id)

    assert "Nothing was changed" not in out, out
    (kept,) = _memories(rt) - {ZEPPELIN}
    assert kept.startswith("The bakery on Calle Mayor opens at six."), out
    assert "Prior query" not in kept, "a memory kept with the label of a query nobody gave"
    assert ZEPPELIN in _memories(rt), "a fact that named nothing replaced one"

    # To forget, a word for none names nothing either: nothing is archived.
    out = rt.correct(correction="", target_id=no_id, action="forget")
    assert out.startswith("Nothing was archived"), out
    assert ZEPPELIN in _memories(rt)


@pytest.mark.parametrize("shown", ["`{id}`", '"{id}"', "[{id}]", "id={id}", " id: {id}\n", "<{id}>", "({id})."])
def test_an_id_is_found_however_it_came_wrapped(tmp_path, shown):
    """Recall shows a memory's id as ``id=engram_...``, and a model passes it
    on in backticks, quotes or brackets as often as bare. Each of those named
    nothing, so the correction changed nothing."""
    rt = _runtime(tmp_path)
    rt.capture(content=ZEPPELIN)
    (memory,) = rt._store.get_active_engrams(agent_id="t", limit=5)

    out = rt.correct(correction="The zeppelin schedule moved to Fridays.", target_id=shown.format(id=memory.id))

    assert "Nothing was changed" not in out, out
    assert _memories(rt) == {"The zeppelin schedule moved to Fridays."}, out
