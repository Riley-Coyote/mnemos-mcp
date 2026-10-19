"""The person corrects and forgets, and the agent is told (M07a).

`mnemos correct ID TEXT` and `mnemos forget ID`, run by the person (outside an
agent's shell), are the person's, as `mnemos remember` is:

- a correction writes their words unsigned, as ``author_kind`` 'person', and
  supersedes the memory exactly as the agent's correction does (the link, the
  lineage both ways, the version keeping the old words); the agent wakes once
  to "<name> corrected a memory of mine; it now says: ...";
- a forget is the agent's own forget (the memory and its note archived, never
  deleted, nothing written in their place) with the person as the one who
  forgot (``forgotten_by_person``); the agent's next wake says once that its
  person let a memory go, and on which days, never the words or an id, and
  the memory never comes back by any path.

In an agent's own shell they are the agent's, as before. An id that is unknown,
archived, or replaced by a correction since changes nothing, and says which in
one plain sentence.
"""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

import mnemos.store.embedding_index as ei
from mnemos.cli import main
from mnemos.interface.context_packet import build_context_packet, carried_count
from mnemos.simple_runtime import MnemosRuntime, cue_memories
from mnemos.store.embedding_index import EmbeddingIndex
from mnemos.store.sqlite_store import RECALLABLE_ARCHIVE_REASONS
from tests.test_recall_by_meaning import _ConceptEmbedder

OPUS = "claude-opus-5-5"
SCOPE = {"agent_id": "nova", "person_id": "riley", "project_scope": "demo"}
SCOPE_ARGS = ["--agent-id", "nova", "--person-id", "riley", "--project-scope", "demo"]
SECRET = "CANARY4417"
# The archive reason the contract names for a memory its person let go.
FORGOTTEN_BY_PERSON = "forgotten_by_person"


@pytest.fixture
def meaning(monkeypatch):
    monkeypatch.setattr(ei, "_check_local_deps", lambda: True)
    monkeypatch.setattr(ei, "_LocalEmbedder", _ConceptEmbedder)


@pytest.fixture
def db(tmp_path, monkeypatch):
    # A newcomer's machine: a model is configured, as one would sign the
    # agent's writes. The person's words must never take it.
    monkeypatch.setenv("MNEMOS_AGENT_MODEL", OPUS)
    return tmp_path / "memory.db"


def _runtime(db: Path) -> MnemosRuntime:
    return MnemosRuntime(db_path=str(db), use_dedicated_model=False, **SCOPE)


def _kept(rt: MnemosRuntime, text: str, **options) -> str:
    said = rt.capture(text, signed_as=OPUS, **options)
    return said.split("Memory ID: ", 1)[1].split()[0]


def _run(db: Path, capsys, *argv: str) -> tuple[int, str, str]:
    code = main([*argv, "--db-path", str(db), *SCOPE_ARGS])
    out = capsys.readouterr()
    return code, out.out, out.err


def _row(db: Path, sql: str, *params):
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute(sql, params).fetchone()
    finally:
        conn.close()


def _packet(db: Path, **options) -> dict:
    rt = _runtime(db)
    rt._ensure_init()
    try:
        return build_context_packet(
            rt._store, **SCOPE, reader_model=OPUS, person_name="Riley", **options)
    finally:
        rt.close()


def _away(text: str) -> list[str]:
    assert "### while i was away\n" in text, text
    return text.split("### while i was away\n", 1)[1].split("\n\n", 1)[0].splitlines()


# ── Correct ──


def test_the_persons_correction_is_their_words_unsigned(db, capsys):
    rt = _runtime(db)
    old = _kept(rt, "Riley's reading is in November.", impact="Dates move; check them.")
    rt.close()

    code, out, err = _run(db, capsys, "correct", "--json", old, "Riley's reading is on December 3.")

    assert (code, err) == (0, "")
    done = json.loads(out)
    assert list(done) == ["id", "replaces", "corrected"]
    assert done["replaces"] == old and done["id"] != old
    new = _row(db, "SELECT * FROM engrams WHERE id = ?", done["id"])
    assert (new["author_kind"], new["author_model"], new["state"]) == ("person", "", "active")
    assert new["content"] == "Riley's reading is on December 3."
    assert new["impact"] == "Dates move; check them.", "it keeps what the old one meant"
    assert done["corrected"] == new["created_at"]
    note = _row(db, "SELECT * FROM hypomnema_entries WHERE graduated_to_engram_id = ?", done["id"])
    assert (note["authored_by"], note["author_model"], note["active"]) == ("unknown", "", 1)
    trace = _row(db, "SELECT author_model FROM memory_trace WHERE tool = 'correct'")
    assert trace["author_model"] == "", "the person's correction is never signed as a model's"


def _supersession(db: Path, old: str, new: str) -> dict:
    """Everything that says ``new`` replaced ``old``, without who wrote it."""
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        lineage_new = json.loads(conn.execute(
            "SELECT lineage FROM engrams WHERE id = ?", (new,)).fetchone()[0])
        lineage_old = json.loads(conn.execute(
            "SELECT lineage FROM engrams WHERE id = ?", (old,)).fetchone()[0])
        return {
            "supersedes": lineage_new.get("supersedes") == [old],
            "superseded_by": lineage_old.get("superseded_by") == new,
            "old state": conn.execute("SELECT state FROM engrams WHERE id = ?", (old,)).fetchone()[0],
            "reason": conn.execute("SELECT archive_reason FROM archive WHERE id = ?", (old,)).fetchone()[0],
            "link": conn.execute(
                "SELECT relation FROM connections WHERE source_id = ? AND target_id = ?",
                (new, old)).fetchall(),
            "version": conn.execute(
                "SELECT content_snapshot FROM versions WHERE engram_id = ?", (new,)).fetchall(),
            "old note": conn.execute(
                "SELECT active, superseded_by IS NOT NULL FROM hypomnema_entries "
                "WHERE graduated_to_engram_id = ?", (old,)).fetchall(),
            "standing": conn.execute("SELECT standing FROM engrams WHERE id = ?", (new,)).fetchone()[0],
        }
    finally:
        conn.close()


def test_the_persons_correction_supersedes_exactly_as_the_agents_does(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("MNEMOS_AGENT_MODEL", OPUS)
    found = {}
    for who in ("agent", "person"):
        db = tmp_path / f"{who}.db"
        rt = _runtime(db)
        old = _kept(rt, "The ferry timetable is on the fridge.", standing=True)
        rt.close()
        if who == "agent":
            monkeypatch.setenv("CLAUDECODE", "1")
        code, out, err = _run(db, capsys, "correct", "--json", old, "The ferry timetable is in the drawer.")
        monkeypatch.delenv("CLAUDECODE", raising=False)
        assert code == 0, err
        new = json.loads(out)["id"]
        found[who] = _supersession(db, old, new)
        author = _row(db, "SELECT author_kind, author_model FROM engrams WHERE id = ?", new)
        assert tuple(author) == (("agent", OPUS) if who == "agent" else ("person", ""))

    assert found["person"] == found["agent"]
    assert found["person"]["supersedes"] and found["person"]["superseded_by"]
    assert found["person"]["old state"] == "archived"
    assert found["person"]["link"] == [("supersedes",)]
    assert found["person"]["version"] == [("The ferry timetable is on the fridge.",)]
    assert found["person"]["standing"] == 1, "the replacement carries the standing mark"


def test_the_next_wake_says_the_correction_once(db, capsys):
    rt = _runtime(db)
    old = _kept(rt, "Riley's reading is in November.")
    rt.close()
    assert _run(db, capsys, "correct", old, "Riley's reading is on December 3.")[0] == 0

    first = _packet(db)
    second = _packet(db)

    assert '- Riley corrected a memory of mine; it now says: "Riley\'s reading is on December 3."' \
        in _away(first["prompt"]), first["prompt"]
    assert "corrected a memory of mine" not in second["prompt"], second["prompt"]
    assert "wrote this into my memory" not in first["prompt"] + second["prompt"]


# ── Forget ──


def test_the_persons_forget_archives_the_pair_and_writes_nothing_in_its_place(db, capsys):
    rt = _runtime(db)
    gone = _kept(rt, f"The harbour gate code is {SECRET}.")
    _kept(rt, "The ferry leaves at nine.")
    rt.close()
    before = _row(db, "SELECT (SELECT COUNT(*) FROM engrams) AS e, "
                      "(SELECT COUNT(*) FROM hypomnema_entries) AS h")

    code, out, err = _run(db, capsys, "forget", "--json", gone)

    assert (code, err) == (0, "")
    done = json.loads(out)
    assert list(done) == ["id", "state", "forgotten"]
    archived = _row(db, "SELECT archive_reason, archived_at FROM archive WHERE id = ?", gone)
    assert done == {"id": gone, "state": "archived", "forgotten": archived["archived_at"]}
    assert archived["archive_reason"] == FORGOTTEN_BY_PERSON
    assert FORGOTTEN_BY_PERSON not in RECALLABLE_ARCHIVE_REASONS
    assert _row(db, "SELECT state FROM engrams WHERE id = ?", gone)["state"] == "archived"
    note = _row(db, "SELECT active, revisions_json FROM hypomnema_entries "
                    "WHERE graduated_to_engram_id = ?", gone)
    assert note["active"] == 0
    assert "revised_by" not in json.loads(note["revisions_json"])[-1], "unsigned: the person's"
    after = _row(db, "SELECT (SELECT COUNT(*) FROM engrams) AS e, "
                     "(SELECT COUNT(*) FROM hypomnema_entries) AS h")
    assert tuple(after) == tuple(before), "nothing deleted, nothing written in its place"


def test_the_next_wake_says_once_that_the_person_let_it_go_never_what(db, capsys):
    rt = _runtime(db)
    gone = _kept(rt, f"The harbour gate code is {SECRET}.")
    _kept(rt, "The ferry leaves at nine.")
    note_id = rt._store.notes_for_engram(gone, **SCOPE)[0]["id"]
    rt.close()
    assert _run(db, capsys, "forget", gone)[0] == 0
    conn = sqlite3.connect(db)
    conn.execute("UPDATE archive SET archived_at = ? WHERE id = ?",
                 ("2026-10-18T15:00:00+00:00", gone))
    conn.commit()
    conn.close()
    woke = datetime(2026, 10, 20, 9, 0, tzinfo=timezone.utc)

    first = _packet(db, now=woke)
    second = _packet(db, now=woke)

    assert "- Riley let a memory of mine go on Oct 18; its words went with it." \
        in _away(first["prompt"]), first["prompt"]
    for said in (SECRET, "harbour gate", gone, note_id):
        assert said not in first["prompt"], said
    assert carried_count(first) >= 1
    assert "let a memory of mine go" not in second["prompt"], second["prompt"]


def test_several_let_go_are_one_line_with_their_days(db, capsys):
    rt = _runtime(db)
    gone = [_kept(rt, f"Old harbour note number {n}.") for n in range(3)]
    _kept(rt, "The ferry leaves at nine.")
    rt.close()
    for memory_id in gone:
        assert _run(db, capsys, "forget", memory_id)[0] == 0
    conn = sqlite3.connect(db)
    for memory_id, moment in zip(gone, ["2026-10-18T09:00:00+00:00", "2026-10-18T23:00:00+00:00",
                                        "2026-10-19T08:00:00+00:00"]):
        conn.execute("UPDATE archive SET archived_at = ? WHERE id = ?", (moment, memory_id))
    conn.commit()
    conn.close()

    text = _packet(db, now=datetime(2026, 10, 20, 9, 0, tzinfo=timezone.utc))["prompt"]

    assert ("- Riley let 3 memories of mine go, on Oct 18 and Oct 19; "
            "their words went with them.") in _away(text), text


def test_an_agents_forget_never_counts_as_the_persons(db, capsys):
    rt = _runtime(db)
    agents = _kept(rt, "The agent's own scratch note.")
    persons = _kept(rt, "The person's private note.")
    _kept(rt, "The ferry leaves at nine.")
    rt.correct(correction="", target_id=agents, action="forget", signed_as=OPUS)
    rt.close()
    assert _run(db, capsys, "forget", persons)[0] == 0

    text = _packet(db)["prompt"]

    lines = [line for line in _away(text) if "let" in line]
    assert len(lines) == 1 and "let a memory of mine go on" in lines[0], text
    assert _row(db, "SELECT archive_reason FROM archive WHERE id = ?", agents)[0] == \
        "simple_correction_forget"


def test_the_let_go_line_is_never_left_out_for_room(db, capsys):
    rt = _runtime(db)
    gone = _kept(rt, "Something to let go.")
    for n in range(8):
        rt.handoff(f"Thread {n}: " + "the east pier survey goes on. " * 40, signed_as=OPUS)
    rt.close()
    assert _run(db, capsys, "forget", gone)[0] == 0

    packet = _packet(db, token_budget=60)

    assert "let a memory of mine go on" in packet["prompt"], packet["prompt"]


def test_a_light_wake_says_nothing_and_spends_nothing(db, capsys):
    rt = _runtime(db)
    gone = _kept(rt, "Something to let go.")
    rt.handoff("Where I stopped: the harbour ledger.", signed_as=OPUS)
    rt.close()
    assert _run(db, capsys, "forget", gone)[0] == 0

    light = _packet(db, wake="light")
    full = _packet(db)

    assert "let a memory of mine go" not in light["prompt"]
    assert "let a memory of mine go" in full["prompt"], full["prompt"]


def test_a_memory_the_person_forgot_never_comes_back(db, capsys, meaning):
    rt = _runtime(db)
    gone = _kept(rt, f"The lighthouse keeper's gate code is {SECRET}.")
    _kept(rt, "Marigolds bloom beside the greenhouse door every June.")
    note_id = rt._store.notes_for_engram(gone, **SCOPE)[0]["id"]
    message = "where does the lighthouse keeper leave the spare lamp tonight"
    index = EmbeddingIndex(db_path=str(db))
    try:
        assert gone in [line["id"] for line in cue_memories(rt._store, index, message, **SCOPE)], \
            "premise: the cue would show it"
    finally:
        index.close()
    rt.close()

    assert _run(db, capsys, "forget", gone)[0] == 0

    rt = _runtime(db)
    try:
        said = [
            rt.recall(SECRET),                              # its words
            rt.recall("beacon"),                            # its meaning
            rt.recall(f"lighthouse keeper gate code {SECRET}", include_archived=True),
            rt.recall(gone),                                # its id
            rt.recall(note_id),                             # its note's id
        ]
        index = EmbeddingIndex(db_path=str(db))
        try:
            cued = [line["id"] for line in cue_memories(rt._store, index, message, **SCOPE)]
        finally:
            index.close()
        rt.maintain(deep=True)
        rt.maintain()
        said.append(rt.recall(SECRET, include_archived=True))
        said.append(rt.context())
    finally:
        rt.close()

    for text in said:
        assert SECRET not in text, text
    assert gone not in cued
    assert _row(db, "SELECT archive_reason FROM archive WHERE id = ?", gone)[0] == FORGOTTEN_BY_PERSON
    assert _row(db, "SELECT state FROM engrams WHERE id = ?", gone)[0] == "archived"
    for argv in (["memories", "--json"], ["search", "--json", SECRET], ["search", "--json", "beacon"]):
        code, out, _err = _run(db, capsys, *argv)
        listed = json.loads(out).get("memories") or json.loads(out).get("results")
        assert code == 0 and gone not in out, out
        assert not [item for item in listed if SECRET in item["words"]], out


# ── In an agent's shell, the agent's ──


@pytest.mark.parametrize("how", ["CLAUDECODE", "AI_AGENT", "--signed-as"])
def test_in_an_agents_shell_correct_and_forget_stay_the_agents(db, capsys, monkeypatch, how):
    rt = _runtime(db)
    fixed, gone = _kept(rt, "The ferry leaves at nine."), _kept(rt, "An old scratch note.")
    rt.close()
    signed = []
    if how == "--signed-as":
        signed = ["--signed-as", OPUS]
    else:
        monkeypatch.setenv(how, "1")

    code, out, err = _run(db, capsys, "correct", "--json", *signed, fixed, "The ferry leaves at ten.")
    assert code == 0, err
    new = json.loads(out)["id"]
    assert _run(db, capsys, "forget", *signed, gone)[0] == 0
    monkeypatch.delenv(how, raising=False)

    row = _row(db, "SELECT author_kind, author_model FROM engrams WHERE id = ?", new)
    assert tuple(row) == ("agent", OPUS)
    assert _row(db, "SELECT archive_reason FROM archive WHERE id = ?", gone)[0] == \
        "simple_correction_forget"
    text = _packet(db)["prompt"]
    assert "corrected a memory of mine" not in text and "let a memory of mine go" not in text, text


# ── Refusals: one plain sentence, nothing changed ──


def test_an_archived_or_replaced_id_changes_nothing_and_says_which(db, capsys):
    rt = _runtime(db)
    old, gone = _kept(rt, "The ferry leaves at nine."), _kept(rt, "An old scratch note.")
    rt.close()
    new = json.loads(_run(db, capsys, "correct", "--json", old, "The ferry leaves at ten.")[1])["id"]
    assert _run(db, capsys, "forget", gone)[0] == 0
    count = _row(db, "SELECT COUNT(*) FROM engrams")[0]

    for argv, said in [
        (["correct", old, "The ferry leaves at eleven."],
         f"Memory {old} was replaced by a correction; its current version is {new}.\n"),
        (["forget", old], f"Memory {old} was replaced by a correction; its current version is {new}.\n"),
        (["forget", gone], f"Memory {gone} is already archived.\n"),
        (["correct", gone, "Back again."], f"Memory {gone} is already archived.\n"),
        (["forget", "engram_01NOSUCHMEMORYHERE00000"], "No memory engram_01NOSUCHMEMORYHERE00000 is held here.\n"),
        (["correct", new, "   "], "A correction needs the memory's new words.\n"),
    ]:
        code, out, err = _run(db, capsys, *argv)
        assert (code, out, err) == (1, "", said), argv

    assert _row(db, "SELECT COUNT(*) FROM engrams")[0] == count
    assert _row(db, "SELECT state FROM engrams WHERE id = ?", new)[0] == "active"


def test_without_a_store_nothing_is_made(tmp_path, capsys):
    db = tmp_path / "nothing-here.db"
    for argv in (["correct", "engram_01ABC0000000000000000000", "words"],
                 ["forget", "engram_01ABC0000000000000000000"]):
        code, out, err = _run(db, capsys, *argv)
        assert (code, out) == (1, "")
        assert err == "No memory engram_01ABC0000000000000000000 is held here.\n"
    assert not db.exists()


def test_the_text_answers_say_whose(db, capsys):
    rt = _runtime(db)
    old, gone = _kept(rt, "The ferry leaves at nine."), _kept(rt, "An old scratch note.")
    rt.close()

    _code, corrected, _ = _run(db, capsys, "correct", old, "The ferry leaves at ten.")
    _code, forgotten, _ = _run(db, capsys, "forget", gone)

    assert re.fullmatch(rf"Corrected, in your words: engram_\w+ replaces {old}\.\n", corrected)
    assert forgotten == (
        f"Forgotten: {gone} is archived, never deleted, and recall won't bring it back.\n")
