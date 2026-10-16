"""Recall shows what it finds, says when, and says when there is more.

The lab's side-by-side (L15) put plain memory files against Mnemos on 118
facts from two years of real work: the files got 48.5, Mnemos 41.5, and the
files got 20 facts Mnemos missed against 14 the other way. Replaying Mnemos's
own 165 recall calls (L18, 2026-10-16) said why, by counts:

- Rows hid what recall found. The right memory came back for 42 of the 118
  facts, but its 300-character row held the fact for 26. Whole rows: 42.
- Lists were short. At the calls' own lengths (7.6 rows on average) the right
  memory came back for 42; at 20, for 59.
- Nothing said when. Of Mnemos's 12 wrong answers, 7 had a newer memory
  holding the fact in the store, shown in one run; rows carried no date, while
  the files kept each memory under a dated heading.
- It asked less: a median of 4 memory calls a question, against the files'
  11 file calls.

So a memory's row now carries its words whole, up to ``MEMORY_ROW_CHARS``,
and the day it was kept; and the recall tool asks for 15 rows on a question
about the past, for more than one search, in other words too, and says the
newer of two memories that disagree usually holds. Replayed on the same 165
calls (L18b), rows showed the fact for 41 of the 42 facts recall reached
(26 before), and at 15 rows the right memory came back for 59 and showed for
57. A call that says no number gets 10. Handoffs, the journal and notes keep
their short rows.
"""

from __future__ import annotations

import asyncio
import inspect
import sqlite3

import pytest

import mnemos.store.embedding_index as ei
from mnemos import simple_runtime
from mnemos.simple_runtime import MEMORY_ROW_CHARS, ROW_CHARS, MnemosRuntime

SCOPE = {"agent_id": "nova", "person_id": "riley", "project_scope": "demo"}

# The opening names the subject; the fact sits past the first 300 characters,
# in words the query doesn't use.
LONG = (
    "Release planning for the harbour app: we went through the store listing, "
    "the screenshots for every phone size, the accessibility pass on the chart "
    "screens, and who signs off on the copy before anything ships. Riley wants "
    "the copy read aloud once before it goes out, because the last listing had "
    "a sentence nobody could say without stumbling. Then the money question "
    "came up and we settled it: the yearly plan costs forty-two dollars, and "
    "the monthly one is gone for good."
)


@pytest.fixture(autouse=True)
def words_only(monkeypatch):
    """No embedding backend: recall finds by words alone, so what it finds
    doesn't wait on a model."""
    monkeypatch.setattr(ei, "_check_local_deps", lambda: False)


def _runtime(db) -> MnemosRuntime:
    return MnemosRuntime(db_path=str(db), use_dedicated_model=False, **SCOPE)


def _memory_id(said: str) -> str:
    return said.split("Memory ID: ", 1)[1].splitlines()[0]


def _row(out: str, words: str) -> str:
    [row] = [row for row in out.split("\n- ") if words in row]
    return row


def test_a_memory_row_carries_its_words_whole(tmp_path):
    assert len(LONG) > ROW_CHARS
    rt = _runtime(tmp_path / "memory.db")
    try:
        rt.capture(LONG)
        out = rt.recall("harbour app release planning")
    finally:
        rt.close()

    assert "forty-two dollars" in out, out
    assert "the monthly one is gone for good." in _row(out, "Release planning for the harbour app")


def test_a_memory_longer_than_its_row_shows_the_passage_that_answers(tmp_path):
    filler = " ".join(
        f"Day {n} of the survey covered the north shore, the tide tables and the boat schedule."
        for n in range(1, 40)
    )
    words = f"Survey notes for the bay. {filler} The lighthouse keeper's name is Ottoline Marsh. {filler}"
    assert len(words) > 2 * MEMORY_ROW_CHARS
    rt = _runtime(tmp_path / "memory.db")
    try:
        rt.capture(words)
        out = rt.recall("lighthouse keeper name")
    finally:
        rt.close()

    row = _row(out, "Survey notes for the bay.")
    assert "Ottoline Marsh" in row, row
    assert len(row.split("\n")[0]) <= MEMORY_ROW_CHARS + 50, len(row)


def test_every_memory_row_says_the_day_it_was_kept(tmp_path):
    db = tmp_path / "memory.db"
    rt = _runtime(db)
    try:
        memory = _memory_id(rt.capture("The ferry to the island leaves at eight."))
    finally:
        rt.close()
    conn = sqlite3.connect(db)
    conn.execute("UPDATE engrams SET created_at = '2026-03-14T09:30:00+00:00' WHERE id = ?", (memory,))
    conn.commit()
    conn.close()

    rt = _runtime(db)
    try:
        out = rt.recall("ferry island")
    finally:
        rt.close()

    assert f"id={memory} " in out
    assert "kept 2026-03-14" in _row(out, "The ferry to the island leaves at eight."), out


def test_a_recall_that_says_no_number_returns_ten(tmp_path):
    rt = _runtime(tmp_path / "memory.db")
    try:
        for n in range(14):
            rt.capture(f"Tide gauge reading {n}: the harbour tide stood at {n + 1} metres at noon.")
        default = rt.recall("harbour tide gauge reading")
        fifteen = rt.recall("harbour tide gauge reading", max_results=15)
    finally:
        rt.close()

    assert default.count("\n- [") == 10, default
    assert fifteen.count("\n- [") == 14, fifteen


def test_the_default_is_ten_at_the_tool_and_in_the_runtime():
    from mnemos import simple_mcp

    assert inspect.signature(MnemosRuntime.recall).parameters["max_results"].default == 10
    tools = {tool.name: tool for tool in asyncio.run(simple_mcp.simple_mcp.list_tools())}
    schema = tools["mnemos_recall"].inputSchema["properties"]["max_results"]
    assert schema["default"] == 10, schema


def test_handoff_rows_stay_short(tmp_path):
    long_handoff = "Where I was on the harbour app: " + " ".join(
        f"step {n} of the release checklist is done and verified." for n in range(60)
    )
    rt = _runtime(tmp_path / "memory.db")
    try:
        rt.handoff(long_handoff, signed_as="claude-opus-5-5")
        out = rt.recall("harbour app release checklist")
    finally:
        rt.close()

    row = _row(out, "Where I was on the harbour app")
    assert len(row.split("\n")[0]) <= ROW_CHARS + 50, len(row)


def test_the_recall_tool_asks_for_more_than_one_search_and_says_newer_usually_holds():
    """In the tool's own description, which a model reads whole before it
    calls the tool: the server's instructions are held to what Claude Code
    shows of them (2,048 characters, advanced mode's included)."""
    from mnemos import simple_mcp

    tools = {tool.name: tool for tool in asyncio.run(simple_mcp.simple_mcp.list_tools())}
    described = " ".join(tools["mnemos_recall"].description.split())
    assert "For a question about the past, ask for 15 (max_results=15)" in described
    assert "search more than once, in other words too" in described
    assert "When two memories disagree, the newer one usually holds." in described
    assert "the day it was kept" in described
    assert simple_runtime.MEMORY_ROW_CHARS == MEMORY_ROW_CHARS >= 1500
