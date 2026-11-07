"""Handoffs have their own search and their own rows in recall's list.

The lab replayed recorded searches with no model runs (L20 and L20b,
2026-11-06). On a copy of the real store one ranking gave a 15-row list of about
8 memories and 7 handoffs, 87% of those old drafts a newer handoff had replaced,
and handoffs also took places among the 30 a search by meaning starts from. With
13 rows from a search with no handoffs in it and the best 2 from a search of them
alone, the fact shows on the page for 47 of 118 facts rather than 39 on M4's
searches, and 44 rather than 40 on M5's.

What the lab said to keep stays: every old draft can still be found. Simply
dropping them would make 6 facts that live only in old drafts unfindable.

But the best two matches are often old drafts, so asked to pick up work (L20c, 12
questions on a copy of the real store) that list held where the work had got to
for about 6, against about 10 for today's one long list. So handoffs get 3 rows of
the 16: the best match as it is, that session's newest draft, and the newest of
the ten closest from another session. Then about 10 land there, and the fact still
shows for 47 on M4's searches.
"""

from __future__ import annotations

import re

import pytest

import mnemos.store.embedding_index as ei
from mnemos.core.engram import Engram
from mnemos.interface.person import search_view
from mnemos.retrieval.reactive import ReactiveRetriever
from mnemos.simple_mcp import MAX_QUERY_CHARS, MAX_TOOL_OUTPUT_CHARS, _output
from mnemos.simple_runtime import MnemosRuntime, RECALL_RESULTS, _handoff_rows
from mnemos.store.fts import COMMON_MIN_MEMORIES
from mnemos.store.sqlite_store import HANDOFF_SESSIONS_KEPT
from tests.test_recall_by_meaning import meaning  # noqa: F401  (a fixture)

SCOPE = {"agent_id": "nova", "person_id": "riley", "project_scope": "demo"}
MODEL = "claude-opus-5-5"


def _runtime(db) -> MnemosRuntime:
    return MnemosRuntime(db_path=str(db), use_dedicated_model=False, **SCOPE)


def _section(out: str, heading: str) -> str:
    """The rows under one heading of a recall's answer."""
    if f"{heading}:\n" not in out:
        return ""
    return out.split(f"{heading}:\n", 1)[1].split("\n\n", 1)[0]


def _counted(out: str) -> tuple[int, int]:
    """How many memory rows and handoff rows a recall's answer has."""
    return tuple(
        _section(out, heading).count("- [") for heading in ("Durable memories", "Handoffs")
    )


def _rows(out: str, heading: str = "Handoffs") -> list[str]:
    """Each row under one heading, its two lines together."""
    return [f"- {row}" for row in _section(out, heading).removeprefix("- ").split("\n- ") if row]


def _leave(rt: MnemosRuntime, session: int, words: str, **scope) -> str:
    """A handoff left by one numbered session; its id."""
    rt._ensure_init()
    return rt._store.write_handoff(
        words, author_session=f"{session:08d}-4444-4444-8444-444444444444", **{**SCOPE, **scope},
    )


# Twelve sessions, each matching fewer of these words and left later than the one
# before: the closest match is the oldest, and the newest is ranked last.
SHIP_WORDS = "lantern anchor compass sextant barometer tiller rudder keel mast sail halyard winch".split()


def _twelve_sessions(rt: MnemosRuntime) -> None:
    for n in range(12):
        _leave(rt, n, f"Session {n} checked the {' '.join(SHIP_WORDS[:12 - n])}.")


def _sessions_listed(out: str) -> list[str]:
    return [re.search(r"Session (\d+) checked", row).group(1) for row in _rows(out)]


def _fill(rt: MnemosRuntime, memories: int, handoffs: int) -> None:
    """Memories and handoffs that all hold the same words."""
    for n in range(memories):
        rt.capture(f"Tide gauge reading {n}: the harbour tide stood at {n + 1} metres at noon.")
    for n in range(handoffs):
        rt.handoff(f"Harbour tide gauge reading, pass {n}: still checking the noon figures.", signed_as=MODEL)


QUERY = "harbour tide gauge reading"


# ── The mix the lab tested ──


def test_the_default_is_thirteen_memories_and_three_handoffs(tmp_path):
    rt = _runtime(tmp_path / "memory.db")
    try:
        _fill(rt, memories=20, handoffs=20)
        out = rt.recall(QUERY)
    finally:
        rt.close()

    assert RECALL_RESULTS == 16
    assert _counted(out) == (13, 3), out


def test_fifty_rows_are_forty_five_memories_and_five_handoffs(tmp_path, meaning):  # noqa: F811
    """Each list reaches 30 at most, so 45 memories take two lists that differ:
    30 found by their words, and 30 closer in meaning that don't hold them."""
    rt = _runtime(tmp_path / "memory.db")
    try:
        for n in range(30):
            rt.capture(f"The lighthouse stood beside the ferry pier, year {n}.")
            rt.capture(f"Tonight the beacon lamp needs oil, night {n}.")
        for n in range(10):
            rt.handoff(f"Tonight the beacon lamp needs oil, pass {n}.", signed_as=MODEL)
        out = rt.recall("lighthouse", max_results=50)
    finally:
        rt.close()

    assert _counted(out) == (45, 5), out


@pytest.mark.parametrize(
    ("rows", "handoffs"),
    [
        (1, 0), (2, 1), (3, 1), (4, 1), (5, 2), (8, 2), (10, 2), (11, 3), (15, 3), (16, 3),
        (30, 3), (31, 4), (40, 4), (41, 5), (45, 5), (50, 5),
    ],
)
def test_how_many_rows_go_to_handoffs_at_each_length(rows, handoffs):
    assert _handoff_rows(rows) == handoffs


def test_a_list_has_that_mix_at_every_length_and_never_runs_past_its_rows(tmp_path):
    rt = _runtime(tmp_path / "memory.db")
    try:
        _fill(rt, memories=40, handoffs=8)
        for n in range(4):
            _leave(rt, n, f"Harbour tide gauge reading, session {n}: still checking the noon figures.")
        mixes = {rows: _counted(rt.recall(QUERY, max_results=rows)) for rows in range(1, 51)}
    finally:
        rt.close()

    for rows, (memories, handoffs) in mixes.items():
        assert memories + handoffs <= rows, (rows, memories, handoffs)
    for rows in range(1, 31):
        assert mixes[rows] == (rows - _handoff_rows(rows), _handoff_rows(rows)), rows


def test_the_added_row_counts_against_the_list(tmp_path):
    """The search found one handoff and the list shows two, so the memories get
    what's left after the two, not after the one."""
    rt = _runtime(tmp_path / "memory.db")
    try:
        _fill(rt, memories=20, handoffs=0)
        _leave(rt, 1, "Harbour tide gauge reading: still checking the noon figures.")
        _leave(rt, 1, "Everything on the boat is finished.")
        out = rt.recall(QUERY)
    finally:
        rt.close()

    assert _counted(out) == (14, 2), out


# ── Which handoffs get the rows ──


def test_an_old_draft_keeps_its_row_and_its_sessions_newest_follows_it(tmp_path):
    """The words live only in the old draft, so it has to stay listed. Where the
    work got to doesn't match at all, and its row says what it is instead."""
    rt = _runtime(tmp_path / "memory.db")
    try:
        _leave(rt, 1, "Where I was: the lantern still needs checking.")
        _leave(rt, 1, "Where I was: everything on the boat is finished.")
        out = rt.recall("lantern")
    finally:
        rt.close()

    old, newest = _rows(out)
    assert old.startswith("- [words: lantern] Where I was: the lantern still needs checking"), out
    assert "kind=older handoff, replaced by a newer one from its session" in old
    assert newest.startswith("- [newest from the session above] Where I was: everything on the boat is finished"), out
    assert "kind=handoff;" in newest


def test_the_added_row_was_never_reached_and_says_so_to_the_code_too(tmp_path):
    rt = _runtime(tmp_path / "memory.db")
    try:
        _leave(rt, 1, "Where I was: the lantern still needs checking.")
        newest = _leave(rt, 1, "Where I was: everything on the boat is finished.")
        rows = rt._recall_rows("lantern", 16)
    finally:
        rt.close()

    assert [(row.retrieval_path, row.score) for row in rows if row.item_id == newest] == [("session", 0.0)]


def test_a_newest_draft_that_matched_says_how_as_well(tmp_path):
    rt = _runtime(tmp_path / "memory.db")
    try:
        _leave(rt, 1, "Where I was: the lantern and the anchor still need checking.")
        _leave(rt, 1, "Where I was: the lantern is done.")
        out = rt.recall("lantern anchor")
    finally:
        rt.close()

    old, newest = _rows(out)
    assert old.startswith("- [words: lantern, anchor] "), out
    assert newest.startswith("- [words: lantern; newest from the session above] "), out


def test_a_best_match_that_is_its_sessions_newest_is_listed_once(tmp_path):
    rt = _runtime(tmp_path / "memory.db")
    try:
        _leave(rt, 1, "Where I was: everything on the boat is finished.")
        _leave(rt, 1, "Where I was: the lantern still needs checking.")
        out = rt.recall("lantern")
    finally:
        rt.close()

    assert [row.split("\n")[0] for row in _rows(out)] == ["- [words: lantern] Where I was: the lantern still needs checking."]


def test_the_newest_close_match_from_another_session_comes_before_a_closer_one(tmp_path):
    rt = _runtime(tmp_path / "memory.db")
    try:
        _leave(rt, 1, "The lantern, the anchor and the compass still need checking.")
        _leave(rt, 2, "The lantern and the anchor still need checking.")
        _leave(rt, 3, "The lantern still needs checking.")
        out = rt.recall("lantern anchor compass")
    finally:
        rt.close()

    assert [row.split("] ")[1].split(" still")[0] for row in _rows(out)] == [
        "The lantern, the anchor and the compass",
        "The lantern",
        "The lantern and the anchor",
    ], out


def test_another_session_gets_its_row_ahead_of_more_of_the_same_session(tmp_path):
    rt = _runtime(tmp_path / "memory.db")
    try:
        _leave(rt, 1, "The lantern, the anchor and the compass still need checking.")
        _leave(rt, 1, "The lantern and the anchor still need checking.")
        _leave(rt, 2, "The lantern still needs checking.")
        _leave(rt, 1, "Everything on the boat is finished.")
        out = rt.recall("lantern anchor compass")
    finally:
        rt.close()

    words = [row.split("] ")[1].split("\n")[0] for row in _rows(out)]
    assert words == [
        "The lantern, the anchor and the compass still need checking.",
        "Everything on the boat is finished.",
        "The lantern still needs checking.",
        "The lantern and the anchor still need checking.",
    ], out


def test_the_third_row_looks_no_further_than_the_ten_closest(tmp_path):
    rt = _runtime(tmp_path / "memory.db")
    try:
        _twelve_sessions(rt)
        out = rt.recall(" ".join(SHIP_WORDS))
    finally:
        rt.close()

    assert _sessions_listed(out)[:3] == ["0", "9", "1"], out


def test_a_short_list_still_looks_at_the_ten_closest(tmp_path):
    rt = _runtime(tmp_path / "memory.db")
    try:
        _twelve_sessions(rt)
        out = rt.recall(" ".join(SHIP_WORDS), max_results=5)
        rows = _rows(out)
    finally:
        rt.close()

    assert _sessions_listed(out)[:2] == ["0", "9"], out
    assert len(rows) <= 5


def test_a_long_list_adds_the_next_best_after_the_chosen_three(tmp_path):
    rt = _runtime(tmp_path / "memory.db")
    try:
        _twelve_sessions(rt)
        out = rt.recall(" ".join(SHIP_WORDS), max_results=50)
    finally:
        rt.close()

    assert _sessions_listed(out) == ["0", "9", "1", "2", "3", "4", "5", "6", "7", "8", "10", "11"], out


def test_a_short_list_keeps_the_best_match_and_then_its_newest(tmp_path):
    rt = _runtime(tmp_path / "memory.db")
    try:
        for n in range(8):
            rt.capture(f"The lantern room note {n} is in the log.")
        _leave(rt, 1, "Where I was: the lantern still needs checking, the lantern most of all.")
        _leave(rt, 1, "Where I was: everything on the boat is finished.")
        _leave(rt, 2, "The lantern came up in passing.")
        eight, four = (rt.recall("lantern", max_results=rows) for rows in (8, 4))
    finally:
        rt.close()

    assert _counted(eight) == (6, 2), eight
    assert "still needs checking" in _rows(eight)[0]
    assert "everything on the boat is finished" in _rows(eight)[1]
    assert _counted(four) == (3, 1), four
    assert "still needs checking" in _rows(four)[0]


def test_the_handoff_in_use_is_its_sessions_newest_whatever_the_clock_says(tmp_path):
    """As the store says, and as a wake reads it, even after a clock moved back."""
    rt = _runtime(tmp_path / "memory.db")
    try:
        old = _leave(rt, 1, "Where I was: the lantern still needs checking.")
        _leave(rt, 1, "Where I was: the sails are mended.")
        _leave(rt, 1, "Where I was: everything on the boat is finished.")
        rt._store._get_conn().execute(
            "UPDATE hypomnema_entries SET created_at = '2999-01-01T00:00:00+00:00' WHERE id = ?", (old,),
        )
        rt._store._get_conn().commit()
        out = rt.recall("lantern")
    finally:
        rt.close()

    assert "everything on the boat is finished" in _rows(out)[1], out
    assert "kind=handoff;" in _rows(out)[1]


@pytest.mark.parametrize("rows", [1, 2, 3, 4])
def test_a_list_with_one_row_for_handoffs_adds_none_that_didnt_match(tmp_path, rows):
    """Even when there are rows free: only a row of its own holds one of these."""
    rt = _runtime(tmp_path / "memory.db")
    try:
        _leave(rt, 1, "Where I was: the lantern and the anchor still need checking.")
        _leave(rt, 1, "Where I was: everything on the boat is finished.")
        _leave(rt, 2, "The lantern came up in passing.")
        out = rt.recall("lantern anchor", max_results=rows)
    finally:
        rt.close()

    assert "everything on the boat" not in out, out
    assert "newest from the session above" not in out
    assert "still need checking" in _rows(out)[0], out
    assert len(_rows(out)) == min(rows, 2)


def test_a_handoff_with_no_session_has_no_newer_one_added(tmp_path):
    """Writers that can't say which session they are share the empty session and
    replace each other, so nothing says two of them are one thread of work."""
    rt = _runtime(tmp_path / "memory.db")
    try:
        rt._ensure_init()
        rt._store.write_handoff("Where I was: the lantern still needs checking.", **SCOPE)
        rt._store.write_handoff("Where I was: everything on the boat is finished.", **SCOPE)
        out = rt.recall("lantern")
    finally:
        rt.close()

    assert len(_rows(out)) == 1, out
    assert "everything on the boat" not in out


def test_a_handoff_with_no_session_counts_as_another_session(tmp_path):
    rt = _runtime(tmp_path / "memory.db")
    try:
        _leave(rt, 1, "Where I was: the lantern and the anchor still need checking.")
        _leave(rt, 1, "Where I was: the lantern and the anchor are nearly done.")
        rt._store.write_handoff("Where I was: the lantern came up in passing.", **SCOPE)
        out = rt.recall("lantern anchor")
    finally:
        rt.close()

    assert "the lantern and the anchor are nearly done" in _rows(out)[0], out
    assert "the lantern came up in passing" in _rows(out)[1], out
    assert "the lantern and the anchor still need checking" in _rows(out)[2], out


def test_a_forgotten_draft_is_never_its_sessions_newest(tmp_path):
    rt = _runtime(tmp_path / "memory.db")
    try:
        _leave(rt, 1, "Where I was: the lantern still needs checking.")
        _leave(rt, 1, "Where I was: the sails are mended.")
        secret = _leave(rt, 1, "Where I was: the harbour master owes me money.")
        rt.correct(correction="", target_id=secret, action="forget")
        out = rt.recall("lantern")
    finally:
        rt.close()

    assert "harbour master" not in out
    first, second = _rows(out)
    assert "replaced by a newer one from its session" in first, out
    assert second.startswith("- [newest from the session above] Where I was: the sails are mended"), out
    assert "kind=older handoff, the newest its session still has" in second, out


def test_a_sessions_newest_from_another_scope_is_never_added(tmp_path):
    rt = _runtime(tmp_path / "memory.db")
    try:
        _leave(rt, 1, "Where I was: the lantern still needs checking.")
        _leave(rt, 1, "Everything in the other project is finished.", project_scope="elsewhere")
        out = rt.recall("lantern")
    finally:
        rt.close()

    assert "the other project" not in out, out
    assert len(_rows(out)) == 1


def test_an_added_draft_is_never_strengthened(tmp_path, monkeypatch):
    """A handoff is never a memory: a recall reinforces only the memories it shows."""
    rt = _runtime(tmp_path / "memory.db")
    try:
        rt.capture("The lantern room note is in the log.")
        _leave(rt, 1, "Where I was: the lantern still needs checking.")
        _leave(rt, 1, "Where I was: everything on the boat is finished.")
        reinforced: list[list[object]] = []
        monkeypatch.setattr(rt, "_reinforce_returned", lambda query, memories: reinforced.append(memories))
        out = rt.recall("lantern")
    finally:
        rt.close()

    assert "everything on the boat is finished" in out
    assert [[row.engram.content for row in memories] for memories in reinforced] == [["The lantern room note is in the log."]]


# ── A search of notes alone ──


def test_a_search_of_notes_alone_returns_no_memory(tmp_path, meaning):  # noqa: F811
    """Not one found by its words, by its lesson's words, by its meaning or
    from a shared store, each of which would take a handoff's row."""

    class Shared:
        def search_fts_ranked(self, query, limit):
            return [(Engram(content="The ferry timetable, shared.", kind="semantic",
                            owner_agent_id="vega", visibility="shared"), -1.0)]

        def get_connections(self, memory_id):
            return []

    rt = _runtime(tmp_path / "memory.db")
    try:
        rt.capture("The ferry timetable is in the kitchen drawer.")
        rt.capture("The marigolds came up late this year.", impact="Check the ferry timetable first.")
        rt.capture("The boat leaves from the far pier.")
        rt.handoff("Still looking for the ferry timetable.", signed_as=MODEL)
        retriever = ReactiveRetriever(rt._store, embedding_index=rt._embedding_index, shared_store=Shared())
        everything = retriever.retrieve(
            "ferry timetable", notes=rt._recallable_notes(), reconsolidate_results=False, **SCOPE,
        )
        alone = retriever.retrieve(
            "ferry timetable", notes=rt._recallable_notes(), reconsolidate_results=False,
            only_notes=True, **SCOPE,
        )
    finally:
        rt.close()

    assert len([found for found in everything if found.engram is not None]) >= 4, everything
    assert [found.note["content"] for found in alone] == ["Still looking for the ferry timetable."]
    assert all(found.engram is None for found in alone)


def test_a_search_of_notes_alone_returns_no_memory_when_meaning_fails(tmp_path, meaning, monkeypatch):  # noqa: F811
    """A failed search by meaning puts back the words it had cut, and looks for
    them among the memories too, unless it was only the notes it was asked for."""

    def fails(self, *args, **kwargs):
        raise RuntimeError("the search failed")

    rt = _runtime(tmp_path / "memory.db")
    try:
        for n in range(COMMON_MIN_MEMORIES):
            rt.capture(f"The ferry ran late on day {n}.")
        rt.handoff("Still looking for the ferry timetable.", signed_as=MODEL)
        monkeypatch.setattr(ei.EmbeddingIndex, "search_candidates", fails)
        alone = rt._retriever.retrieve(
            "ferry timetable", notes=rt._recallable_notes(), reconsolidate_results=False,
            only_notes=True, **SCOPE,
        )
    finally:
        rt.close()

    assert [found.note["content"] for found in alone] == ["Still looking for the ferry timetable."]


# ── Neither takes the places a search by meaning starts from ──


def test_handoffs_closer_in_meaning_leave_a_memory_its_place(tmp_path, meaning):  # noqa: F811
    """More handoffs than meaning's top 30, all closer than the memory: in one
    search it never came back, whatever the list's length."""
    rt = _runtime(tmp_path / "memory.db")
    try:
        rt.capture("The beacon stood beside the ferry pier.")
        for n in range(35):
            rt.handoff(f"Tonight the beacon lamp needs oil, pass {n}.", signed_as=MODEL)
        out = rt.recall("lighthouse")
    finally:
        rt.close()

    assert "The beacon stood beside the ferry pier." in _section(out, "Durable memories"), out


def test_memories_closer_in_meaning_leave_a_handoff_its_place(tmp_path, meaning):  # noqa: F811
    rt = _runtime(tmp_path / "memory.db")
    try:
        for n in range(35):
            rt.capture(f"Tonight the beacon lamp needs oil, night {n}.")
        rt.handoff("The beacon stood beside the ferry pier.", signed_as=MODEL)
        out = rt.recall("lighthouse")
    finally:
        rt.close()

    assert "The beacon stood beside the ferry pier." in _section(out, "Handoffs"), out


def test_a_journal_entry_takes_its_row_from_the_memories_not_the_handoffs(tmp_path):
    """L20b's mix: handoffs alone are searched apart, and the journal stays in
    the search with the memories."""
    rt = _runtime(tmp_path / "memory.db")
    try:
        _fill(rt, memories=20, handoffs=5)
        rt.journal("Harbour tide gauge reading tonight: I stayed up to watch it.", signed_as=MODEL)
        out = rt.recall(QUERY)
    finally:
        rt.close()

    assert _section(out, "Journal").count("- [") == 1, out
    assert _counted(out) == (12, 3), out


# ── Every old draft stays searchable ──


def test_every_old_draft_can_still_be_found_by_its_words(tmp_path):
    words = ["lantern", "anchor", "compass", "sextant", "barometer", "tiller"]
    rt = _runtime(tmp_path / "memory.db")
    try:
        for word in words:
            rt.handoff(f"Where I was: the {word} still needs checking.", signed_as=MODEL)
        found = {word: rt.recall(word) for word in words}
    finally:
        rt.close()

    for word in words:
        assert f"the {word} still needs checking" in found[word], found[word]
    for word in words[:-1]:
        assert "kind=older handoff, replaced by a newer one from its session" in found[word]


def test_a_handoff_retired_as_newer_sessions_left_theirs_can_still_be_found(tmp_path):
    rt = _runtime(tmp_path / "memory.db")
    try:
        rt._ensure_init()
        for n in range(HANDOFF_SESSIONS_KEPT + 1):
            words = "the lantern still needs checking" if n == 0 else f"thread {n} goes on"
            rt._store.write_handoff(
                f"Where I was: {words}.", author_session=f"{n:08d}-4444-4444-8444-444444444444", **SCOPE,
            )
        out = rt.recall("lantern")
    finally:
        rt.close()

    assert "the lantern still needs checking" in out, out
    assert "kind=older handoff, retired as newer sessions left theirs" in out


def test_an_old_draft_can_still_be_found_by_its_meaning(tmp_path, meaning):  # noqa: F811
    rt = _runtime(tmp_path / "memory.db")
    try:
        rt.handoff("Where I was: the beacon still needs a new lamp.", signed_as=MODEL)
        rt.handoff("Where I was: the marigolds in the greenhouse need water.", signed_as=MODEL)
        out = rt.recall("lighthouse")
    finally:
        rt.close()

    assert "the beacon still needs a new lamp" in _section(out, "Handoffs"), out
    assert "kind=older handoff, replaced by a newer one from its session" in out


def test_every_old_draft_comes_back_when_nothing_else_fills_the_list(tmp_path):
    rt = _runtime(tmp_path / "memory.db")
    try:
        _fill(rt, memories=0, handoffs=12)
        out = rt.recall(QUERY, max_results=50)
    finally:
        rt.close()

    assert _counted(out) == (0, 12), out
    for n in range(12):
        assert f"pass {n}:" in out


# ── A list comes back short only when the searches find no more ──


def test_rows_handoffs_leave_go_to_the_memories(tmp_path):
    rt = _runtime(tmp_path / "memory.db")
    try:
        _fill(rt, memories=20, handoffs=1)
        one = rt.recall(QUERY)
    finally:
        rt.close()

    assert _counted(one) == (15, 1), one


def test_two_handoffs_leave_their_third_row_to_the_memories(tmp_path):
    rt = _runtime(tmp_path / "memory.db")
    try:
        _fill(rt, memories=20, handoffs=2)
        out = rt.recall(QUERY)
    finally:
        rt.close()

    assert _counted(out) == (14, 2), out


def test_with_no_handoffs_every_row_goes_to_the_memories(tmp_path):
    rt = _runtime(tmp_path / "memory.db")
    try:
        _fill(rt, memories=20, handoffs=0)
        none = rt.recall(QUERY)
    finally:
        rt.close()

    assert _counted(none) == (16, 0), none


def test_rows_memories_leave_go_to_the_handoffs(tmp_path):
    rt = _runtime(tmp_path / "memory.db")
    try:
        _fill(rt, memories=3, handoffs=20)
        out = rt.recall(QUERY)
    finally:
        rt.close()

    assert _counted(out) == (3, 13), out


def test_a_single_row_goes_to_the_best_memory(tmp_path):
    rt = _runtime(tmp_path / "memory.db")
    try:
        _fill(rt, memories=2, handoffs=2)
        out = rt.recall(QUERY, max_results=1)
    finally:
        rt.close()

    assert _counted(out) == (1, 0), out


@pytest.mark.parametrize("rows", [0, 1])
def test_a_single_row_goes_to_a_handoff_when_it_is_all_there_is(tmp_path, rows):
    """No number under one means none: the tool refuses it, and a caller inside
    Mnemos gets one row, as ``_retrieve`` gives."""
    rt = _runtime(tmp_path / "memory.db")
    try:
        _fill(rt, memories=0, handoffs=2)
        out = rt.recall(QUERY, max_results=rows)
    finally:
        rt.close()

    assert _counted(out) == (0, 1), out


# ── Two searches, one embedding ──


def _count_embeddings(monkeypatch, answer=None) -> list[str]:
    """Each text ``embed_query`` is asked for. ``answer`` stands in for the
    backend: a function of the index and the text."""
    asked: list[str] = []
    real = answer or ei.EmbeddingIndex.embed_query

    def embed_query(self, text):
        asked.append(text)
        return real(self, text)

    monkeypatch.setattr(ei.EmbeddingIndex, "embed_query", embed_query)
    return asked


def test_a_recall_embeds_its_query_once(tmp_path, meaning, monkeypatch):  # noqa: F811
    rt = _runtime(tmp_path / "memory.db")
    try:
        rt.capture("The beacon stood beside the ferry pier.")
        rt.handoff("Tonight the beacon lamp needs oil.", signed_as=MODEL)
        asked = _count_embeddings(monkeypatch)
        out = rt.recall("lighthouse")
    finally:
        rt.close()

    assert asked == ["lighthouse"]
    assert _counted(out) == (1, 1), out


def test_a_backend_that_fails_is_asked_once_and_words_still_answer(tmp_path, meaning, monkeypatch):  # noqa: F811
    """Each try on a network backend can wait for its whole timeout, so a
    backend that's down holds the two searches for one of them. (Shared memory
    is a store of its own, with its own search and its own try.)"""
    rt = _runtime(tmp_path / "memory.db")
    try:
        rt.capture("The ferry timetable is in the kitchen drawer.")
        rt.handoff("Still looking for the ferry timetable.", signed_as=MODEL)
        asked = _count_embeddings(monkeypatch, answer=lambda index, text: None)
        out = rt.recall("ferry timetable")
    finally:
        rt.close()

    assert asked == ["ferry timetable"]
    assert _counted(out) == (1, 1), out


# ── The archive at the longest list ──


def _kept_id(said: str) -> str:
    return re.search(r"Memory ID: (\S+)", said).group(1)


@pytest.mark.parametrize(("rows", "restores"), [(1, 1), (16, 16), (30, 16), (39, 16), (45, 10), (50, 5)])
def test_a_recall_restores_only_what_its_answer_can_show(tmp_path, rows, restores):
    """Restoring changes a memory, so what's restored has to be shown, and at
    50 rows with as many from the archive an answer would be cut first."""
    rt = _runtime(tmp_path / "memory.db")
    try:
        faded = [_kept_id(rt.capture(f"Harbour crane note {n}: repainted blue in May.")) for n in range(20)]
        for memory_id in faded:
            rt._store.archive_engram(rt._store.get_engram(memory_id), reason="decay_below_threshold")
        out = rt.recall("harbour crane repainted", max_results=rows, include_archived=True)
        restored = [memory_id for memory_id in faded if rt._store.get_engram(memory_id).state == "active"]
    finally:
        rt.close()

    assert _section(out, "From the archive").count("- Harbour crane note") == restores, out
    assert len(restored) == restores


def test_a_list_past_what_an_answer_can_show_restores_nothing(tmp_path):
    rt = _runtime(tmp_path / "memory.db")
    try:
        faded = _kept_id(rt.capture("Harbour crane note: repainted blue in May."))
        rt._store.archive_engram(rt._store.get_engram(faded), reason="decay_below_threshold")
        out = rt.recall("harbour crane repainted", max_results=60, include_archived=True)
        state = rt._store.get_engram(faded).state
    finally:
        rt.close()

    assert state != "active", out


@pytest.mark.parametrize(("rows", "mix", "restores"), [(50, (50, 0), 5), (39, (39, 0), 16)])
def test_the_longest_answer_with_the_archive_is_never_cut(tmp_path, meaning, rows, mix, restores):  # noqa: F811
    """Every row as long as a row can be, and no handoffs, whose rows are short.
    The last row restored is still on the page after Mnemos's own limit, with
    the longest query there can be at the top of it."""
    long = " Then the noon figures came in again and nothing else changed all week." * 40
    rt = _runtime(tmp_path / "memory.db")
    try:
        for n in range(30):
            rt.capture(f"The lighthouse stood beside the ferry pier, year {n}.{long}")
            rt.capture(f"Tonight the beacon lamp needs oil, night {n}.{long}")
        faded = [_kept_id(rt.capture(f"The lighthouse crane, note {n}.{long}")) for n in range(20)]
        for memory_id in faded:
            rt._store.archive_engram(rt._store.get_engram(memory_id), reason="decay_below_threshold")
        answer = rt.recall("lighthouse", max_results=rows, include_archived=True)
    finally:
        rt.close()

    assert _counted(answer) == mix, answer[:400]
    assert _section(answer, "From the archive").count("- The lighthouse crane") == restores
    assert len(answer) + MAX_QUERY_CHARS < MAX_TOOL_OUTPUT_CHARS, len(answer)
    assert _output(answer) == answer


# ── What stays as it was ──


def test_a_persons_search_stays_at_ten(tmp_path):
    """A person looking through the memory isn't an agent reading rows it pays
    for, and nothing tested it longer. It searches memories alone, as it did."""
    rt = _runtime(tmp_path / "memory.db")
    try:
        _fill(rt, memories=12, handoffs=3)
        view = search_view(rt, QUERY)
        memories = rt.search_memories(QUERY)
    finally:
        rt.close()

    assert len(view["results"]) == 10
    assert len(memories) == 10
    assert all("pass" not in result["words"] for result in view["results"])
