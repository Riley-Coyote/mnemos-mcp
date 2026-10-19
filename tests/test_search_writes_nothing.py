"""`mnemos search` looks, and changes nothing (M07a).

The command called recall's retriever with reconsolidation on, so a person's
search counted as a return: every memory it found was woken, strengthened and
linked with the others found beside it, and the agent's memory moved because
someone looked through it. It also opened the store for writing, which makes
a store that isn't there, and it searched by words alone: it built its
retriever with no meaning index.

Now it is the agent's own recall over the memories (by meaning and by words),
with nothing written, and with ``--json`` it gives an app each result's words,
when it was kept, how close it is (relative within the search) and how recall
found it, decided where recall's own rows decide it.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from mnemos.cli import main
from mnemos.retrieval.reactive import RetrievalResult
from mnemos.simple_runtime import MnemosRuntime, how_found
from tests.test_recall_by_meaning import _ConceptEmbedder

OPUS = "claude-opus-5-5"
SCOPE = {"agent_id": "nova", "person_id": "riley", "project_scope": "demo"}
SCOPE_ARGS = ["--agent-id", "nova", "--person-id", "riley", "--project-scope", "demo"]


@pytest.fixture
def meaning(monkeypatch):
    """A local model whose meaning is controlled ("beacon" is near
    "lighthouse"), for every index made while the test runs."""
    import mnemos.store.embedding_index as ei

    monkeypatch.setattr(ei, "_check_local_deps", lambda: True)
    monkeypatch.setattr(ei, "_LocalEmbedder", _ConceptEmbedder)


def _runtime(db: Path) -> MnemosRuntime:
    return MnemosRuntime(db_path=str(db), use_dedicated_model=False, **SCOPE)


def _kept(rt: MnemosRuntime, text: str) -> str:
    said = rt.capture(text, signed_as=OPUS)
    return said.split("Memory ID: ", 1)[1].split()[0]


def _search(db: Path, capsys, *argv: str) -> str:
    """`mnemos search`, its store and scope named before the command, as an
    app runs it."""
    assert main(["--db-path", str(db), *SCOPE_ARGS, "search", *argv]) == 0
    return capsys.readouterr().out


def _everything(db: Path) -> dict[str, list[tuple]]:
    """Every row a return writes, and every meta value, in a stable order."""
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        return {
            table: sorted(tuple(row) for row in conn.execute(f"SELECT * FROM {table}"))
            for table in ("engrams", "connections", "session_reinforcements", "meta", "archive")
        }
    finally:
        conn.close()


def _digest(db: Path) -> str:
    return hashlib.sha256(db.read_bytes()).hexdigest()


def _with_a_dormant_memory(db: Path) -> str:
    """A store of three memories, one gone quiet that "ferry timetable"
    finds, linked to an active one. Closed, so the file holds every write."""
    rt = _runtime(db)
    try:
        quiet = _kept(rt, "The ferry timetable moved to the kitchen drawer.")
        _kept(rt, "The ferry leaves the east pier at nine on weekdays.")
        _kept(rt, "Marigolds bloom beside the greenhouse door every June.")
        conn = rt._store._get_conn()
        conn.execute(
            "UPDATE engrams SET state = 'dormant', accessibility = 0.03 WHERE id = ?", (quiet,))
        rt._store._commit()
    finally:
        rt.close()
    return quiet


def test_a_search_that_finds_a_dormant_memory_changes_nothing(tmp_path, capsys):
    db = tmp_path / "memory.db"
    quiet = _with_a_dormant_memory(db)
    rows, digest = _everything(db), _digest(db)

    text = _search(db, capsys, "ferry timetable")

    assert f"id={quiet} " in text, text
    assert _everything(db) == rows, "a search changed the store"
    assert _digest(db) == digest, "the store's file is not byte for byte what it was"

    found = json.loads(_search(db, capsys, "--json", "ferry timetable"))

    assert quiet in [result["id"] for result in found["results"]], found
    assert _everything(db) == rows, "a search changed the store"
    assert _digest(db) == digest, "the store's file is not byte for byte what it was"


def test_a_search_in_another_process_changes_nothing(tmp_path):
    import subprocess
    import sys

    db = tmp_path / "memory.db"
    quiet = _with_a_dormant_memory(db)
    rows, digest = _everything(db), _digest(db)

    done = subprocess.run(
        [sys.executable, "-m", "mnemos.cli", "--db-path", str(db), *SCOPE_ARGS,
         "search", "--json", "ferry timetable"],
        capture_output=True, text=True, timeout=180,
        env={"HOME": str(tmp_path), "PATH": "/usr/bin:/bin", "MNEMOS_DISABLE_DOTENV": "1",
             "PYTHONPATH": ":".join(sys.path)},
    )

    assert done.returncode == 0, done.stderr
    assert quiet in [result["id"] for result in json.loads(done.stdout)["results"]]
    assert _everything(db) == rows
    assert _digest(db) == digest


def test_a_search_never_makes_a_store(tmp_path, capsys):
    db = tmp_path / "nothing-here.db"

    assert _search(db, capsys, "ferry") == "No memories found.\n"
    assert not db.exists()
    assert json.loads(_search(db, capsys, "--json", "ferry")) == {"query": "ferry", "results": []}
    assert not db.exists()


def test_search_finds_by_meaning_as_the_agents_recall_does(tmp_path, capsys, meaning):
    db = tmp_path / "memory.db"
    rt = _runtime(db)
    try:
        beacon = _kept(rt, "The beacon on the point burns all night.")
        _kept(rt, "Marigolds bloom beside the greenhouse door every June.")
    finally:
        rt.close()

    text = _search(db, capsys, "lighthouse")

    assert "The beacon on the point burns all night." in text, text
    assert "Marigolds" not in text, text

    found = json.loads(_search(db, capsys, "--json", "lighthouse"))

    assert found["results"][0]["id"] == beacon, found
    assert found["results"][0]["found"] == "meaning"


def test_search_json_gives_the_contracts_shape(tmp_path, capsys, meaning, monkeypatch):
    db = tmp_path / "memory.db"
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "aaaaaaaa-1111-4111-8111-111111111111")
    rt = _runtime(db)
    try:
        beacon = _kept(rt, "The beacon on the point burns all night.")
        tabs = _kept(rt, "Sam keeps tabs on the greenhouse heater.")
        rt.handoff("The beacon needs a new lamp; tabs on the heater too.", signed_as=OPUS)
        rt.journal("Tonight I thought about the beacon and the heater tabs.", signed_as=OPUS)
        created = {
            row[0]: row[1] for row in rt._store._get_conn().execute(
                "SELECT id, created_at FROM engrams WHERE id IN (?, ?)", (beacon, tabs))
        }
    finally:
        rt.close()
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID")

    out = _search(db, capsys, "--json", "-n", "5", "beacon tabs")
    found = json.loads(out)

    assert list(found) == ["query", "results"]
    assert found["query"] == "beacon tabs"
    # Memories only: the handoff and the journal entry hold the words too.
    assert {result["id"] for result in found["results"]} == {beacon, tabs}, found
    for result in found["results"]:
        assert list(result) == ["id", "words", "kept", "closeness", "found"]
        assert result["kept"] == created[result["id"]]
        assert result["found"] in {"meaning", "words", "link"}
        assert 0.0 <= result["closeness"] <= 1.0
    assert found["results"][0]["closeness"] == 1.0
    near = [result["closeness"] for result in found["results"]]
    assert near == sorted(near, reverse=True), "closeness must fall with the order"
    words = {result["id"]: result["words"] for result in found["results"]}
    assert words[beacon] == "The beacon on the point burns all night."


def test_found_and_closeness_are_decided_where_how_found_decides():
    from mnemos.core.engram import Engram
    from mnemos.simple_runtime import closeness, found_by

    def result(score, **detail):
        return RetrievalResult(engram=Engram(content="x"), score=score, score_breakdown=detail)

    both = result(0.9, similarity=0.62, words_rank=1, matched_words=["ferry"])
    meaning_only = result(0.6, similarity=0.41)
    words_only = result(0.45, words_rank=2, matched_words=["pier"])
    linked = result(0.3)

    assert [found_by(r) for r in (both, meaning_only, words_only, linked)] == [
        "meaning", "meaning", "words", "link"]
    assert [how_found(r) for r in (both, meaning_only, words_only, linked)] == [
        "[meaning 0.62; words: ferry]", "[meaning 0.41]", "[words: pier]", "[linked]"]
    assert closeness([both, meaning_only, words_only, linked]) == [1.0, 0.6667, 0.5, 0.3333]
    assert closeness([]) == []
