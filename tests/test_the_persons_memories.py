"""`mnemos memories`: every memory, for the person's own app (M07a).

An app that shows a person their agent's memory (Ghost's home) had no way to
read it: `journal --json` and `notes --json` existed, the memories didn't.
`mnemos memories --json` lists the active and dormant ones, oldest first, in
the shape the app codes against: its words, when its first version was kept
and when this one corrected it, how alive it is (its accessibility, the value
its states follow), the session it was kept in, what it changed, and whose
words it holds. It pages (``--state``, ``--limit``, ``--offset``) for stores of
thousands, and counts the whole scope every time. It reads through the log's
own reading of the same rows, and it never writes or makes a store.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest

from mnemos.cli import main
from mnemos.companion.export import Exporter
from mnemos.core.engram import Engram
from mnemos.simple_runtime import MnemosRuntime

OPUS = "claude-opus-5-5"
SESSION = "aaaaaaaa-1111-4111-8111-111111111111"
SCOPE = {"agent_id": "nova", "person_id": "riley", "project_scope": "demo"}
SCOPE_ARGS = ["--agent-id", "nova", "--person-id", "riley", "--project-scope", "demo"]
FIELDS = ["id", "words", "kept", "state", "alive", "conversation", "corrected", "impact", "author"]


def _runtime(db: Path) -> MnemosRuntime:
    return MnemosRuntime(db_path=str(db), use_dedicated_model=False, **SCOPE)


def _kept(rt: MnemosRuntime, text: str, **options) -> str:
    said = rt.capture(text, signed_as=OPUS, **options)
    return said.split("Memory ID: ", 1)[1].split()[0]


def _set(db: Path, memory_id: str, **values) -> None:
    rt = _runtime(db)
    rt._ensure_init()
    try:
        conn = rt._store._get_conn()
        for column, value in values.items():
            conn.execute(f"UPDATE engrams SET {column} = ? WHERE id = ?", (value, memory_id))
        rt._store._commit()
    finally:
        rt.close()


def _memories(db: Path, capsys, *argv: str) -> dict:
    assert main(["memories", "--json", *argv, "--db-path", str(db), *SCOPE_ARGS]) == 0
    return json.loads(capsys.readouterr().out)


def _ids(view: dict) -> list[str]:
    return [memory["id"] for memory in view["memories"]]


def test_memories_json_gives_every_memory_in_the_contracts_shape(tmp_path, capsys, monkeypatch):
    db = tmp_path / "memory.db"
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", SESSION)
    rt = _runtime(db)
    agent = _kept(rt, "The garden gnome is named Bartholomew.", impact="Names matter to Riley.")
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID")
    quiet = _kept(rt, "The ferry timetable moved to the kitchen drawer.")
    gone = _kept(rt, "The old harbour password was swordfish.")
    rt.correct(correction="", target_id=gone, action="forget", signed_as=OPUS)
    tool = Engram(content="Indexed: a line from a transcript.", author_kind="tool",
                  owner_agent_id="nova", person_id="riley", project_scope="demo")
    rt._store.save_engram(tool)
    rt.close()
    assert main(["remember", "Sam prefers tabs", "--db-path", str(db), *SCOPE_ARGS]) == 0
    person = re.fullmatch(r"Remembered, in your words: (engram_\w+)\n",
                          capsys.readouterr().out).group(1)
    for order, (memory_id, values) in enumerate([
        (agent, {"accessibility": 0.8}),
        (quiet, {"state": "dormant", "accessibility": 0.0312}),
        (tool.id, {}),
        (person, {}),
    ]):
        _set(db, memory_id, created_at=f"2026-10-0{order + 1}T10:00:00+00:00", **values)

    view = _memories(db, capsys)

    assert list(view) == ["memories", "counts"]
    assert view["counts"] == {"active": 3, "dormant": 1, "archived": 1}
    assert _ids(view) == [agent, quiet, tool.id, person], "oldest first, and never the archived"
    for memory in view["memories"]:
        assert list(memory) == FIELDS
    by_id = {memory["id"]: memory for memory in view["memories"]}
    assert by_id[agent] == {
        "id": agent, "words": "The garden gnome is named Bartholomew.",
        "kept": "2026-10-01T10:00:00+00:00", "state": "active", "alive": 0.8,
        "conversation": {"id": SESSION, "title": None}, "corrected": None,
        "impact": "Names matter to Riley.", "author": "agent",
    }
    assert by_id[quiet]["state"] == "dormant"
    assert by_id[quiet]["alive"] == 0.031
    assert by_id[quiet]["conversation"] is None
    assert by_id[tool.id]["author"] == "tool"
    assert by_id[person]["author"] == "person"
    assert by_id[person]["words"] == "Sam prefers tabs"


def test_author_is_the_agent_the_person_a_tool_or_unknown(tmp_path, capsys):
    db = tmp_path / "memory.db"
    rt = _runtime(db)
    kinds = ["agent", "person", "tool", "system", "import", "unknown", "", "a-kind-from-later"]
    ids = [_kept(rt, f"Harbour ledger line {n}.") for n in range(len(kinds))]
    conn = rt._store._get_conn()
    for memory_id, kind in zip(ids, kinds):
        conn.execute("UPDATE engrams SET author_kind = ? WHERE id = ?", (kind, memory_id))
    rt._store._commit()
    rt.close()

    authors = {memory["id"]: memory["author"] for memory in _memories(db, capsys)["memories"]}

    assert [authors[memory_id] for memory_id in ids] == [
        "agent", "person", "tool", "tool", "tool", "unknown", "unknown", "unknown"]


def test_kept_is_the_first_versions_day_and_corrected_this_ones(tmp_path, capsys):
    db = tmp_path / "memory.db"
    rt = _runtime(db)
    first = _kept(rt, "Riley's reading is in November.")
    plain = _kept(rt, "The garden gnome is named Bartholomew.")
    rt.close()
    _set(db, first, created_at="2026-10-04T10:00:00+00:00")
    _set(db, plain, created_at="2026-10-05T08:00:00+00:00")
    rt = _runtime(db)
    rt.correct(correction="Riley's reading moved to December.", target_id=first, signed_as=OPUS)
    second = rt._latest(first)
    rt.close()
    _set(db, second, created_at="2026-10-14T09:30:00+00:00")
    assert main(["correct", "--json", second, "Riley's reading is on December 3.",
                 "--db-path", str(db), *SCOPE_ARGS]) == 0
    third = json.loads(capsys.readouterr().out)

    view = _memories(db, capsys)

    by_id = {memory["id"]: memory for memory in view["memories"]}
    assert set(by_id) == {third["id"], plain}
    assert by_id[third["id"]]["kept"] == "2026-10-04T10:00:00+00:00", "kept is the first version's"
    assert by_id[third["id"]]["corrected"] == third["corrected"]
    assert by_id[plain]["kept"] == "2026-10-05T08:00:00+00:00"
    assert by_id[plain]["corrected"] is None


def test_state_limit_and_offset_page_it_oldest_first_and_count_the_whole_scope(tmp_path, capsys):
    db = tmp_path / "memory.db"
    rt = _runtime(db)
    ids = [_kept(rt, f"Harbour note number {n} about the tides.") for n in range(6)]
    rt.close()
    times = ["2026-10-01T00:00:00+00:00"] * 2 + [f"2026-10-0{n}T00:00:00+00:00" for n in range(2, 6)]
    for memory_id, moment in zip(ids, times):
        _set(db, memory_id, created_at=moment)
    for memory_id in (ids[1], ids[4]):
        _set(db, memory_id, state="dormant", accessibility=0.02)

    whole = _memories(db, capsys)
    oldest = sorted(ids[:2]) + ids[2:]  # the same moment: then by id, every time

    assert _ids(whole) == oldest
    counts = {"active": 4, "dormant": 2, "archived": 0}
    assert whole["counts"] == counts
    dormant = _memories(db, capsys, "--state", "dormant")
    assert _ids(dormant) == [i for i in oldest if i in (ids[1], ids[4])]
    assert dormant["counts"] == counts, "counts are always the whole scope's"
    assert _ids(_memories(db, capsys, "--state", "active", "--limit", "2")) == [
        i for i in oldest if i not in (ids[1], ids[4])][:2]
    assert _ids(_memories(db, capsys, "--limit", "2", "--offset", "1")) == oldest[1:3]
    assert _memories(db, capsys, "--limit", "0") == {"memories": [], "counts": counts}
    assert _ids(_memories(db, capsys, "--offset", "40")) == []
    pages = [_ids(_memories(db, capsys, "--limit", "4", "--offset", str(at))) for at in (0, 4)]
    assert pages[0] + pages[1] == oldest


def test_the_log_and_the_command_read_the_same_rows(tmp_path, capsys):
    db = tmp_path / "memory.db"
    rt = _runtime(db)
    for n in range(4):
        _kept(rt, f"Ledger line {n}: the east pier needs measuring.")
    rt.close()

    _life, log = Exporter.for_scope(db_path=str(db), **SCOPE).export()

    assert _ids(_memories(db, capsys)) == [memory["id"] for memory in log["memories"]]


def test_memories_reads_without_writing_and_never_makes_a_store(tmp_path, capsys):
    db = tmp_path / "memory.db"
    rt = _runtime(db)
    _kept(rt, "The ferry timetable moved to the kitchen drawer.")
    rt.close()
    beside = sorted(path.name for path in tmp_path.iterdir())
    digest = hashlib.sha256(db.read_bytes()).hexdigest()

    assert len(_memories(db, capsys)["memories"]) == 1

    assert hashlib.sha256(db.read_bytes()).hexdigest() == digest
    assert sorted(path.name for path in tmp_path.iterdir()) == beside
    nowhere = tmp_path / "nothing-here.db"
    assert _memories(nowhere, capsys) == {
        "memories": [], "counts": {"active": 0, "dormant": 0, "archived": 0}}
    assert not nowhere.exists()


@pytest.mark.parametrize("argv, said", [
    (["--limit", "-1"], "--limit takes a number of memories, 0 or more.\n"),
    (["--offset", "-2"], "--offset takes a number of memories, 0 or more.\n"),
    (["--state", "archived"], "--state is one of: active, dormant.\n"),
])
def test_a_bad_page_is_one_plain_sentence(tmp_path, capsys, argv, said):
    assert main(["memories", "--json", *argv, "--db-path", str(tmp_path / "m.db"), *SCOPE_ARGS]) == 2
    out = capsys.readouterr()
    assert out.out == ""
    assert out.err == said
