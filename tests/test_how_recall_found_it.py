"""Recall says how it found something.

A recalled row's bracket was its score relative to the best seed, so the top
row always read 1.00, whether it shared one word with the query or everything:
a newcomer asked "what is my dog called" and recall returned "The human wants
to be called Sam." at [1.00], which the agent read as certainty. The bracket
now says how the row was found: by meaning and how close, by which of the
query's words, or through a link. What recall finds, and its order, are as
they were.
"""

from __future__ import annotations

import math

import pytest

import mnemos.mcp_server as mcp_server
import mnemos.store.embedding_index as ei
from mnemos.cli import main
from mnemos.core.engram import Connection, Engram
from mnemos.core.types import ConnectionRelation
from mnemos.retrieval.reactive import ReactiveRetriever
from mnemos.simple_runtime import MnemosRuntime
from mnemos.store.sqlite_store import EngramStore

from tests.test_recall_by_meaning import concept_vector, meaning  # noqa: F401  (a fixture)

SCOPE = {"agent_id": "nova", "person_id": "riley", "project_scope": "demo"}
SCOPE_ARGS = ["--agent-id", "nova", "--person-id", "riley", "--project-scope", "demo"]
SAM = "The human wants to be called Sam."


@pytest.fixture
def words_only(monkeypatch):
    """No embedding backend: recall finds by words alone."""
    monkeypatch.setattr(ei, "_check_local_deps", lambda: False)


def _runtime(db) -> MnemosRuntime:
    return MnemosRuntime(db_path=str(db), use_dedicated_model=False, **SCOPE)


def _memory_id(said: str) -> str:
    return said.split("Memory ID: ", 1)[1].splitlines()[0]


def _closeness(cue: str, text: str) -> str:
    """The fake model's similarity of ``cue`` and ``text``, as the bracket prints it."""
    a, b = concept_vector(cue), concept_vector(text)
    return f"{sum(x * y for x, y in zip(a, b)) / math.hypot(*a) / math.hypot(*b):.2f}"


def test_a_newcomers_dog_question_says_which_word_found_sam(tmp_path, words_only):
    rt = _runtime(tmp_path / "memory.db")
    rt.capture(SAM)

    out = rt.recall("what is my dog called")

    assert f"- [words: called] {SAM}" in out, out
    assert "[1.00]" not in out, out


def test_a_row_found_by_words_and_meaning_says_both(tmp_path, meaning):
    rt = _runtime(tmp_path / "memory.db")
    content = "The lighthouse stands by the ferry pier."
    rt.capture(content)

    out = rt.recall("lighthouse")

    assert f"- [meaning {_closeness('lighthouse', content)}; words: lighthouse] {content}" in out, out


def test_a_row_found_by_meaning_alone_says_how_close(tmp_path, meaning):
    rt = _runtime(tmp_path / "memory.db")
    content = "The beacon guides the ferry."
    rt.capture(content)

    out = rt.recall("lighthouse")

    assert f"- [meaning {_closeness('lighthouse', content)}] {content}" in out, out


def test_a_row_reached_through_a_connection_says_linked(tmp_path, words_only):
    rt = _runtime(tmp_path / "memory.db")
    seed = _memory_id(rt.capture("Sam keeps a sourdough starter named Gerald."))
    linked = _memory_id(rt.capture("The kitchen window faces east."))
    rt._store.save_connection(
        seed, Connection(target_id=linked, relation=ConnectionRelation.SUPPORTS, strength=1.0),
    )

    out = rt.recall("sourdough")

    assert "- [linked] The kitchen window faces east." in out, out


def test_matched_words_are_at_most_three_in_the_cues_order(store):
    """Four of the cue's words are in the memory, one only in its lesson: the
    first three of the cue's are named, in its order, not the memory's."""
    store.save_engram(Engram(
        content="Ferry timetable for the harbour pier", impact="Check the lighthouse first.",
        impact_source="agent", kind="semantic", owner_agent_id="nova", person_id="riley",
        project_scope="demo",
    ))

    [result] = ReactiveRetriever(store, reconsolidation_enabled=False).retrieve(
        "lighthouse pier harbour ferry", **SCOPE)

    assert result.score_breakdown["matched_words"] == ["lighthouse", "pier", "harbour"]


def test_the_advanced_recall_prints_a_whole_id_and_how_it_was_found(tmp_path, monkeypatch):
    store = EngramStore(str(tmp_path / "memory.db"))
    engram = Engram(content=SAM, kind="semantic", owner_agent_id="nova", person_id="riley",
                    project_scope="demo")
    store.save_engram(engram)
    monkeypatch.setattr(mcp_server, "_setup_gate", lambda: None)
    monkeypatch.setattr(mcp_server, "_store", store)
    monkeypatch.setattr(mcp_server, "_retriever", ReactiveRetriever(store))

    out = mcp_server.mnemos_recall("what is my dog called", **SCOPE)

    assert f"[words: called] {SAM}" in out, out
    assert f"id={engram.id} kind=" in out, out


def test_search_says_which_word_found_it_and_no_path(tmp_path, capsys, words_only):
    db = tmp_path / "memory.db"
    rt = _runtime(db)
    rt.capture(SAM)
    rt.close()

    assert main(["--db-path", str(db), *SCOPE_ARGS, "search", "called"]) == 0
    out = capsys.readouterr().out

    assert f"[words: called] {SAM}" in out, out
    assert "path=" not in out, out


def test_a_row_found_only_by_meaning_or_a_link_names_no_words(tmp_path, meaning):
    """Matched words belong to a row found by words: one found by meaning, or
    reached through a link, names none, whatever its text holds."""
    rt = _runtime(tmp_path / "memory.db")
    rt.capture("The beacon guides the ferry.")
    rt.capture("The lighthouse stands by the ferry pier.")

    results = rt._retrieve("lighthouse beacon", max_results=10)

    assert results, "something was found"
    for result in results:
        detail = result.score_breakdown
        if "words_rank" not in detail:
            assert detail["matched_words"] == [], detail
        else:
            assert detail["matched_words"], detail


def test_the_context_querys_notes_say_which_words_found_them():
    """The query section after the packet brackets its notes as recall's rows
    are bracketed: the query's words a note holds, never a relative score."""
    from mnemos.simple_runtime import _format_continuity

    entry = {"id": "n1", "content": "Sam wants to be called Sam, never Samuel.",
             "domain": "general", "confidence": 0.9, "score": 1.0}

    line = _format_continuity(entry, "what is my dog called")

    assert line.startswith("- [words: called] Sam wants"), line
    assert "[1.00]" not in line
    assert _format_continuity({**entry, "content": "Nothing in common here."},
                              "what is my dog called").startswith("- [words] ")
