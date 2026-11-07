"""Handoffs have their own search and their own rows in recall's list.

The lab replayed recorded searches with no model runs (L20 and L20b,
2026-11-06). On a copy of the real store one ranking gave a 15-row list of about
8 memories and 7 handoffs, 87% of those old drafts a newer handoff had replaced,
and handoffs also took places among the 30 a search by meaning starts from. With
13 rows from a search with no handoffs in it and the best 2 from a search of them
alone, the fact shows on the page for 47 of 118 facts rather than 39 on M4's
searches, and 44 rather than 40 on M5's.

So every list length here follows that mix, and what the lab said to keep stays:
every old draft can still be found. Simply dropping them would make 6 facts that
live only in old drafts unfindable.
"""

from __future__ import annotations

import re

import pytest

import mnemos.store.embedding_index as ei
from mnemos.core.engram import Engram
from mnemos.interface.person import search_view
from mnemos.retrieval.reactive import ReactiveRetriever
from mnemos.simple_mcp import MAX_TOOL_OUTPUT_CHARS, _output
from mnemos.simple_runtime import MnemosRuntime
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


def _fill(rt: MnemosRuntime, memories: int, handoffs: int) -> None:
    """Memories and handoffs that all hold the same words."""
    for n in range(memories):
        rt.capture(f"Tide gauge reading {n}: the harbour tide stood at {n + 1} metres at noon.")
    for n in range(handoffs):
        rt.handoff(f"Harbour tide gauge reading, pass {n}: still checking the noon figures.", signed_as=MODEL)


QUERY = "harbour tide gauge reading"


# ── The mix the lab tested ──


def test_fifteen_rows_are_thirteen_memories_and_two_handoffs(tmp_path):
    rt = _runtime(tmp_path / "memory.db")
    try:
        _fill(rt, memories=20, handoffs=20)
        out = rt.recall(QUERY)
    finally:
        rt.close()

    assert _counted(out) == (13, 2), out


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
    [(1, 0), (2, 1), (4, 1), (10, 1), (11, 2), (15, 2), (20, 2), (21, 3), (30, 3), (45, 5), (50, 5)],
)
def test_handoffs_get_one_row_in_ten_rounded_up(rows, handoffs):
    from mnemos.simple_runtime import _handoff_rows

    assert _handoff_rows(rows) == handoffs


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
    assert _counted(out) == (12, 2), out


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

    assert _counted(one) == (14, 1), one


def test_with_no_handoffs_every_row_goes_to_the_memories(tmp_path):
    rt = _runtime(tmp_path / "memory.db")
    try:
        _fill(rt, memories=20, handoffs=0)
        none = rt.recall(QUERY)
    finally:
        rt.close()

    assert _counted(none) == (15, 0), none


def test_rows_memories_leave_go_to_the_handoffs(tmp_path):
    rt = _runtime(tmp_path / "memory.db")
    try:
        _fill(rt, memories=3, handoffs=20)
        out = rt.recall(QUERY)
    finally:
        rt.close()

    assert _counted(out) == (3, 12), out


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


def test_a_recall_restores_no_more_than_fifteen_from_the_archive(tmp_path):
    """Restoring changes a memory, so what's restored has to be shown, and at
    50 rows with as many from the archive an answer would be cut first."""
    rt = _runtime(tmp_path / "memory.db")
    try:
        faded = [_kept_id(rt.capture(f"Harbour crane note {n}: repainted blue in May.")) for n in range(20)]
        for memory_id in faded:
            rt._store.archive_engram(rt._store.get_engram(memory_id), reason="decay_below_threshold")
        out = rt.recall("harbour crane repainted", max_results=50, include_archived=True)
        restored = [memory_id for memory_id in faded if rt._store.get_engram(memory_id).state == "active"]
    finally:
        rt.close()

    assert _section(out, "From the archive").count("- Harbour crane note") == 15, out
    assert len(restored) == 15


def test_the_longest_answer_with_the_archive_is_never_cut(tmp_path, meaning):  # noqa: F811
    """Every row as long as a row can be: 45 memories, 5 handoffs and 15 from
    the archive, the last of them still on the page after Mnemos's own limit."""
    long = " Then the noon figures came in again and nothing else changed all week." * 40
    rt = _runtime(tmp_path / "memory.db")
    try:
        for n in range(30):
            rt.capture(f"The lighthouse stood beside the ferry pier, year {n}.{long}")
            rt.capture(f"Tonight the beacon lamp needs oil, night {n}.{long}")
        for n in range(10):
            rt.handoff(f"Tonight the beacon lamp needs oil, pass {n}.{long}", signed_as=MODEL)
        faded = [_kept_id(rt.capture(f"The lighthouse crane, note {n}.{long}")) for n in range(20)]
        for memory_id in faded:
            rt._store.archive_engram(rt._store.get_engram(memory_id), reason="decay_below_threshold")
        answer = rt.recall("lighthouse", max_results=50, include_archived=True)
    finally:
        rt.close()

    assert _counted(answer) == (45, 5), answer[:400]
    assert _section(answer, "From the archive").count("- The lighthouse crane") == 15
    assert len(answer) < MAX_TOOL_OUTPUT_CHARS
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
