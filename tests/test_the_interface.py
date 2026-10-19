"""`mnemos interface`: the person's commands for an app, from one process (M07a).

A one-shot command pays for the meaning model on every call (4.4 s on the
maintainer's Mac, then about 14 ms a query), which an app searching as the
person types can't. `mnemos interface` answers the same commands, in the same
shapes, from one process that loads the model once, in the background as it
starts: one JSON request a line on stdin, one JSON line an answer on stdout,
each with the request's id, and an error as one plain sentence.
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

import mnemos.store.embedding_index as ei
from mnemos.cli import main
from mnemos.simple_runtime import MnemosRuntime
from tests.test_recall_by_meaning import _ConceptEmbedder

OPUS = "claude-opus-5-5"
SCOPE = {"agent_id": "nova", "person_id": "riley", "project_scope": "demo"}
SCOPE_ARGS = ["--agent-id", "nova", "--person-id", "riley", "--project-scope", "demo"]
COMMANDS = ("memories", "search", "correct", "forget", "journal", "notes", "reply")


def _here(db: Path):
    """The interface, in this process, for the test scope."""
    from mnemos.interface.person import Interface

    return Interface(db_path=str(db), **SCOPE)


def _runtime(db: Path) -> MnemosRuntime:
    return MnemosRuntime(db_path=str(db), use_dedicated_model=False, **SCOPE)


def _kept(rt: MnemosRuntime, text: str) -> str:
    said = rt.capture(text, signed_as=OPUS)
    return said.split("Memory ID: ", 1)[1].split()[0]


def _one_shot(db: Path, capsys, *argv: str):
    assert main([*argv, "--db-path", str(db), *SCOPE_ARGS]) == 0
    return json.loads(capsys.readouterr().out)


def _interface(db: Path, home: Path, requests: list[dict], **env: str) -> list[dict]:
    """``mnemos interface`` in a process of its own: every request on its
    stdin, then stdin closed; its answers, one a line."""
    done = subprocess.run(
        [sys.executable, "-m", "mnemos.cli", "interface", "--db-path", str(db), *SCOPE_ARGS],
        input="".join(json.dumps(request) + "\n" for request in requests),
        capture_output=True, text=True, timeout=180,
        env={"HOME": str(home), "PATH": "/usr/bin:/bin", "MNEMOS_DISABLE_DOTENV": "1",
             "PYTHONPATH": ":".join(sys.path), **env},
    )
    assert done.returncode == 0, done.stderr
    lines = done.stdout.splitlines()
    assert len(lines) == len(requests), done.stdout
    return [json.loads(line) for line in lines]


def _seeded(db: Path) -> dict[str, str]:
    rt = _runtime(db)
    try:
        ids = {
            "ferry": _kept(rt, "The ferry timetable moved to the kitchen drawer."),
            "pier": _kept(rt, "The ferry leaves the east pier at nine on weekdays."),
            "gnome": _kept(rt, "The garden gnome is named Bartholomew."),
        }
        rt.journal("Tonight I thought about the ferry and the gnome.", signed_as=OPUS)
        rt.note("Should the ferry note move to the shared board?", kind="question", signed_as=OPUS)
        ids["note"] = rt.notes()[0]["id"]
    finally:
        rt.close()
    return ids


def test_the_interface_answers_each_command_as_its_one_shot_json_does(tmp_path, capsys):
    db = tmp_path / "memory.db"
    ids = _seeded(db)
    asked = [
        ({"command": "memories"}, ["memories", "--json"]),
        ({"command": "memories", "state": "active", "limit": 1, "offset": 1},
         ["memories", "--json", "--state", "active", "--limit", "1", "--offset", "1"]),
        ({"command": "search", "query": "ferry pier", "max_results": 5},
         ["search", "--json", "-n", "5", "ferry pier"]),
        ({"command": "journal", "last": 3}, ["journal", "--json", "--last", "3"]),
        ({"command": "notes"}, ["notes", "--json"]),
        ({"command": "notes", "unread": True}, ["notes", "--json", "--unread"]),
    ]
    one_shot = [_one_shot(db, capsys, *argv) for _request, argv in asked]

    answers = _interface(db, tmp_path, [
        {"id": n, **request} for n, (request, _argv) in enumerate(asked, start=1)
    ])

    for n, (answer, expected) in enumerate(zip(answers, one_shot), start=1):
        assert answer == {"id": n, "result": expected}, (asked[n - 1], answer)

    writes = _interface(db, tmp_path, [
        {"id": "c", "command": "correct", "memory_id": ids["ferry"],
         "text": "The ferry timetable is in the hall drawer now."},
        {"id": "f", "command": "forget", "memory_id": ids["gnome"]},
        {"id": "r", "command": "reply", "note_id": ids["note"], "text": "Yes, move it."},
    ])

    corrected, forgotten, replied = (answer["result"] for answer in writes)
    assert [answer["id"] for answer in writes] == ["c", "f", "r"]
    assert list(corrected) == ["id", "replaces", "corrected"] and corrected["replaces"] == ids["ferry"]
    assert list(forgotten) == ["id", "state", "forgotten"] and forgotten["id"] == ids["gnome"]
    listed = {memory["id"]: memory for memory in _one_shot(db, capsys, "memories", "--json")["memories"]}
    assert set(listed) == {corrected["id"], ids["pier"]}
    assert listed[corrected["id"]]["author"] == "person"
    assert listed[corrected["id"]]["corrected"] == corrected["corrected"]
    assert replied in _one_shot(db, capsys, "notes", "--json")


def test_a_persons_reply_is_listed_with_no_kind_their_name_and_the_note_it_answers(
    tmp_path, capsys,
):
    """The dash shows a reply under the note it answers by these three fields
    of `notes --json`, which already said so before the interface; the
    interface's reply and notes must give exactly the same."""
    db = tmp_path / "memory.db"
    note = _seeded(db)["note"]
    assert main(["notes", "reply", note, "Yes,", "move", "it.", "--db-path", str(db), *SCOPE_ARGS]) == 0
    capsys.readouterr()

    listed = _one_shot(db, capsys, "notes", "--json")
    answers = _interface(db, tmp_path, [
        {"id": 1, "command": "reply", "note_id": note, "text": "And the gnome's too."},
        {"id": 2, "command": "notes"},
    ])

    replies = [entry for entry in listed if entry["author"] == "person"]
    assert len(replies) == 1
    assert replies[0]["kind"] is None
    assert replies[0]["in_reply_to"] == note
    assert replies[0]["model"] is None
    assert answers[0]["result"]["kind"] is None
    assert answers[0]["result"]["author"] == "person"
    assert answers[0]["result"]["in_reply_to"] == note
    assert answers[1]["result"] == [answers[0]["result"], *listed]


def test_reading_notes_through_the_interface_marks_nothing_read(tmp_path):
    db = tmp_path / "memory.db"
    note = _seeded(db)["note"]

    answers = _interface(db, tmp_path, [{"id": 1, "command": "notes"}])

    assert [entry["id"] for entry in answers[0]["result"]] == [note]
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        assert conn.execute("SELECT read_at FROM notes WHERE id = ?", (note,)).fetchone()[0] is None
    finally:
        conn.close()


def test_every_refusal_is_one_plain_sentence_with_the_requests_id(tmp_path):
    db = tmp_path / "memory.db"
    ids = _seeded(db)
    interface = _here(db)
    try:
        answers = [interface.answer(line) for line in (
            "not json at all",
            "[1, 2]",
            json.dumps({"id": 1, "command": "drop-everything"}),
            json.dumps({"id": 2, "command": "memories", "limit": -1}),
            json.dumps({"id": 3, "command": "memories", "state": "archived"}),
            json.dumps({"id": 4, "command": "search", "query": 7}),
            json.dumps({"id": 5, "command": "forget", "memory_id": "engram_01NOSUCHMEMORY0000000000"}),
            json.dumps({"id": 6, "command": "correct", "memory_id": ids["pier"], "text": " "}),
            json.dumps({"id": 7, "command": "notes", "unread": "yes"}),
            json.dumps({"id": 8, "command": "reply", "note_id": ids["note"], "text": ""}),
        )]
    finally:
        interface.close()

    assert answers == [
        {"id": None, "error": "A request is one JSON object on one line."},
        {"id": None, "error": "A request is one JSON object on one line."},
        {"id": 1, "error": 'There is no command "drop-everything" here; the commands are '
                           f"{', '.join(COMMANDS)}."},
        {"id": 2, "error": '"limit" takes a whole number, 0 or more.'},
        {"id": 3, "error": '"state" is "active" or "dormant".'},
        {"id": 4, "error": '"query" takes text.'},
        {"id": 5, "error": "No memory engram_01NOSUCHMEMORY0000000000 is held here."},
        {"id": 6, "error": "A correction needs the memory's new words."},
        {"id": 7, "error": '"unread" is true or false.'},
        {"id": 8, "error": "Nothing saved: The note was empty."},
    ]


def test_without_a_store_the_interface_reads_nothing_and_makes_nothing(tmp_path):
    db = tmp_path / "nothing-here.db"
    interface = _here(db)
    try:
        answers = [interface.answer(json.dumps({"id": n, **request})) for n, request in enumerate([
            {"command": "memories"},
            {"command": "search", "query": "ferry"},
            {"command": "journal"},
            {"command": "notes"},
            {"command": "correct", "memory_id": "engram_01ABC0000000000000000000", "text": "words"},
            {"command": "forget", "memory_id": "engram_01ABC0000000000000000000"},
            {"command": "reply", "note_id": "x", "text": "hello"},
        ])]
    finally:
        interface.close()

    assert [answer.get("result", answer.get("error")) for answer in answers] == [
        {"memories": [], "counts": {"active": 0, "dormant": 0, "archived": 0}},
        {"query": "ferry", "results": []},
        [],
        [],
        "No memory engram_01ABC0000000000000000000 is held here.",
        "No memory engram_01ABC0000000000000000000 is held here.",
        "Nothing saved: there are no notes here yet.",
    ]
    assert not db.exists()


class _CountedEmbedder(_ConceptEmbedder):
    loads = 0

    def _get_model(self):
        if self._model is None:
            type(self).loads += 1
        return super()._get_model()


def test_the_model_loads_once_and_every_runtime_embeds_with_it(tmp_path, monkeypatch):
    monkeypatch.setattr(ei, "_check_local_deps", lambda: True)
    monkeypatch.setattr(ei, "_LocalEmbedder", _ConceptEmbedder)
    db = tmp_path / "memory.db"
    rt = _runtime(db)
    try:
        beacon = _kept(rt, "The beacon on the point burns all night.")
        _kept(rt, "Marigolds bloom beside the greenhouse door every June.")
    finally:
        rt.close()
    monkeypatch.setattr(ei, "_LocalEmbedder", _CountedEmbedder)
    _CountedEmbedder.loads = 0

    interface = _here(db)
    try:
        interface.warm()
        first = interface.answer(json.dumps({"id": 1, "command": "search", "query": "lighthouse"}))
        interface.answer(json.dumps({"id": 2, "command": "correct", "memory_id": beacon,
                                     "text": "The beacon on the point burns until dawn."}))
        again = interface.answer(json.dumps({"id": 3, "command": "search", "query": "lighthouse"}))
    finally:
        interface.close()

    assert first["result"]["results"][0] == {**first["result"]["results"][0], "id": beacon,
                                             "found": "meaning", "closeness": 1.0}
    assert again["result"]["results"][0]["words"] == "The beacon on the point burns until dawn."
    assert _CountedEmbedder.loads == 1


def test_in_an_agents_shell_the_interface_writes_as_the_agent(tmp_path, monkeypatch):
    db = tmp_path / "memory.db"
    ids = _seeded(db)
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setenv("MNEMOS_AGENT_MODEL", OPUS)
    interface = _here(db)
    try:
        corrected = interface.answer(json.dumps({
            "id": 1, "command": "correct", "memory_id": ids["pier"], "text": "The ferry leaves at ten."}))
        interface.answer(json.dumps({"id": 2, "command": "forget", "memory_id": ids["gnome"]}))
    finally:
        interface.close()

    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        assert conn.execute("SELECT author_kind, author_model FROM engrams WHERE id = ?",
                            (corrected["result"]["id"],)).fetchone() == ("agent", OPUS)
        assert conn.execute("SELECT archive_reason FROM archive WHERE id = ?",
                            (ids["gnome"],)).fetchone() == ("simple_correction_forget",)
    finally:
        conn.close()


def test_the_interface_ends_when_stdin_closes_having_answered_nothing(tmp_path):
    assert _interface(tmp_path / "memory.db", tmp_path, []) == []
    assert not (tmp_path / "memory.db").exists()


@pytest.mark.parametrize("command", COMMANDS)
def test_every_command_the_interface_answers_has_a_one_shot_beside_it(command):
    from mnemos.interface.person import COMMANDS as answered

    assert command in answered
    one_shot = {"reply": ["notes", "reply"]}.get(command, [command])
    with pytest.raises(SystemExit) as helped:
        main([*one_shot, "--help"])
    assert helped.value.code == 0
