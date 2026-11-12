"""`mnemos view`: a host app's read-only view of one resident (docs/host-read-view.md).

A host app shows one agent's memory in a tab. Opening or refreshing that tab
must never wake, recall, mark read or write, and must never show a
neighbour. These tests hold the view to that, against one store file that
two residents share (and a third scope of the first agent's, about another
person), built through Mnemos's normal write path in a home of the test's
own:

- the scope is pinned in full by the caller, never by the environment or
  ~/.mnemos/config.json, and a missing part is refused;
- nothing of another resident's (words, ids, names, counts) reaches a reply,
  beliefs included;
- the protocol is checked before the store is opened;
- replies are bounded (items, text, bytes) and page by cursor;
- the store's bytes and its folder's listing are what they were after every
  section; with a live writer the view sees its newest commit and leaves the
  main file alone; no memory is woken or strengthened, no note marked read,
  no trace row written, nothing new appears under the home;
- nothing the view reaches can write: its one connection is the exporter's
  read-only one, and SQLite's own authorizer sees no write attempted.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import sqlite3
import struct
import subprocess
import sys
from pathlib import Path

import pytest

import mnemos
from mnemos import host_view
from mnemos.cli import main
from mnemos.companion.export import open_read_only
from mnemos.core.belief import Belief
from mnemos.simple_runtime import MnemosRuntime
from mnemos.store.sqlite_store import EngramStore

REPO = Path(__file__).resolve().parent.parent
SIGNED = "example-model"
WREN = {"agent_id": "wren", "person_id": "pat-example", "project_scope": "lighthouse"}
QUINN = {"agent_id": "wren", "person_id": "quinn-example", "project_scope": "lighthouse"}
OTTER = {"agent_id": "otter", "person_id": "sam-example", "project_scope": "orchard"}
LISTS = host_view.LIST_SECTIONS
WORDS = {
    "wren": ["The keeper's log lives in the blue binder on the shelf.",
             "The harbour tide table is pinned beside the door."],
    "wren_standing": "Pat likes replies short and plain.",
    "quinn": ["Quinn's spare shed key hangs on the green hook."],
    "otter": ["Otter's orchard ledger counts the plum trees each spring.",
              "The orchard gate sticks after rain."],
    "otter_standing": "Sam wants the orchard numbers in a table.",
}


def _flags(scope: dict[str, str] | None = None, **leave_out: bool) -> list[str]:
    scope = scope or WREN
    out = []
    for key, flag in (("agent_id", "--agent-id"), ("person_id", "--person-id"),
                      ("project_scope", "--project-scope")):
        if not leave_out.get(key):
            out += [flag, scope[key]]
    return out


def _memory_id(said: str) -> str:
    return said.split("Memory ID: ", 1)[1].split()[0]


@pytest.fixture
def home(tmp_path, monkeypatch) -> Path:
    """A home of the test's own, with upkeep run in the writing process so
    no detached process is still writing the store when a test reads it."""
    home = tmp_path / "home"
    (home / ".mnemos").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("MNEMOS_MAINTENANCE", "inline")
    return home


def _write(db: Path, scope: dict[str, str], memories: list[str], *, standing: str = "",
           journal: str = "", note: str = "", reply: str = "", handoff: str = "") -> list[str]:
    runtime = MnemosRuntime(db_path=str(db), use_dedicated_model=False, **scope)
    try:
        kept = [_memory_id(runtime.capture(text, signed_as=SIGNED)) for text in memories]
        if standing:
            kept.append(_memory_id(runtime.capture(standing, signed_as=SIGNED, standing=True)))
        if journal:
            runtime.journal(journal, signed_as=SIGNED)
        if note:
            runtime.note(note, kind="noticed", signed_as=SIGNED)
        if reply:
            runtime.person_note(reply)
        if handoff:
            runtime.handoff(handoff, signed_as=SIGNED)
    finally:
        runtime.close()
    return kept


def _beliefs(db: Path, *beliefs: Belief) -> None:
    store = EngramStore(db)
    try:
        for belief in beliefs:
            store.save_belief(belief)
    finally:
        store.close()


@pytest.fixture
def store(home) -> dict:
    """One file, two residents (wren about pat in lighthouse, otter about sam
    in orchard), and wren's one memory about quinn. Closed: nothing has it
    open, so no -wal is beside it."""
    db = home / ".mnemos" / "residents.db"
    wren = _write(db, WREN, WORDS["wren"], standing=WORDS["wren_standing"],
                  journal="A quiet day. I sorted the blue binder by month.",
                  note="I noticed the blue binder is nearly full.",
                  reply="Thanks, a new binder is on its way.",
                  handoff="Next time: ask whether the new binder arrived.")
    quinn = _write(db, QUINN, WORDS["quinn"])
    otter = _write(db, OTTER, WORDS["otter"], standing=WORDS["otter_standing"],
                   journal="Otter walked the orchard rows and counted forty plums.",
                   note="I noticed the orchard gate needs oil.",
                   reply="Sam will bring the oil can on Friday.",
                   handoff="Next time: check the orchard gate after the oil.")
    _beliefs(
        db,
        Belief(agent_id="wren", content="Pat keeps paper records close at hand.", confidence=0.6,
               supporting_engram_ids=[wren[0]], source="agent"),
        # wren's, but resting on a memory about quinn and one about pat: shown, naming only pat's
        Belief(agent_id="wren", content="Binders and hooks both get used here.", confidence=0.5,
               supporting_engram_ids=[quinn[0], wren[1]], source="agent"),
        # wren's, resting only on a memory about quinn: never shown for pat
        Belief(agent_id="wren", content="Quinn trusts hooks more than drawers.", confidence=0.6,
               supporting_engram_ids=[quinn[0]], source="agent"),
        # wren's, resting on nothing: no scope can claim it
        Belief(agent_id="wren", content="Unattached conviction about lamps.", confidence=0.4,
               supporting_engram_ids=[], source="agent"),
        Belief(agent_id="otter", content="Sam plans the orchard a season ahead.", confidence=0.6,
               supporting_engram_ids=[otter[0]], source="agent"),
    )
    return {"db": db, "wren": wren, "quinn": quinn, "otter": otter}


def _view(db: Path, section: str, **extra) -> dict:
    return host_view.read_view(protocol=1, db_path=str(db), section=section, **{**WREN, **extra})


def _cli(capsys, *argv: str) -> tuple[int, dict]:
    status = main(["view", *argv])
    return status, json.loads(capsys.readouterr().out)


def _env(home: Path, **more: str) -> dict[str, str]:
    return {"HOME": str(home), "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "PYTHONPATH": os.pathsep.join(sys.path), "PYTHONDONTWRITEBYTECODE": "1",
            "MNEMOS_DISABLE_DOTENV": "1", **more}


def _cli_process(home: Path, *argv: str, **env: str) -> tuple[int, dict]:
    done = subprocess.run([sys.executable, "-m", "mnemos.cli", "view", *argv], capture_output=True,
                          text=True, timeout=120, env=_env(home, **env))
    return done.returncode, json.loads(done.stdout)


def _hidden(db: Path) -> set[str]:
    """Every text and id of another scope's, and the other scopes' names:
    what must never appear in a reply for wren / pat / lighthouse."""
    conn = sqlite3.connect(f"{db.resolve().as_uri()}?mode=ro&immutable=1", uri=True)
    found: set[str] = {"otter", "sam-example", "orchard", "quinn-example"}
    try:
        for table, owner, text in (("engrams", "owner_agent_id", "content"), ("journal_entries", "agent_id", "text"),
                                   ("notes", "agent_id", "text"), ("hypomnema_entries", "agent_id", "content")):
            for row in conn.execute(
                    f"SELECT id, {text} FROM {table} WHERE NOT ({owner}=? AND person_id=? AND project_scope=?)",
                    (WREN["agent_id"], WREN["person_id"], WREN["project_scope"])):
                found |= {row[0], row[1].strip()}
        for row in conn.execute("SELECT id, content FROM beliefs WHERE agent_id != 'wren' "
                                "OR content LIKE 'Quinn%' OR content LIKE 'Unattached%'"):
            found |= {row[0], row[1]}
    finally:
        conn.close()
    return found


def _every_reply(db: Path, limit: int = 1) -> list[dict]:
    """Every section, each list section paged to its end at ``limit`` a page."""
    replies = [_view(db, "summary")]
    for section in LISTS:
        cursor = None
        while True:
            reply = _view(db, section, limit=limit, cursor=cursor)
            replies.append(reply)
            if not reply["truncated"]:
                break
            cursor = reply["next_cursor"]
    return replies


def _folder(path: Path) -> dict[str, str]:
    """A folder's listing, each file with the hash of its bytes."""
    return {str(p.relative_to(path)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(path.rglob("*")) if p.is_file()}


def _state(db: Path) -> dict:
    """What a read must never change: every memory's reinforcement fields,
    every note's read_at, the trace table's rows."""
    conn = open_read_only(db)
    try:
        return {
            "engrams": conn.execute(
                "SELECT id, access_count, last_accessed, strength, stability, state, accessibility "
                "FROM engrams ORDER BY id").fetchall(),
            "notes": conn.execute("SELECT id, read_at, delivered_at FROM notes ORDER BY id").fetchall(),
            "trace": conn.execute("SELECT count(*) FROM memory_trace").fetchone()[0],
            "reinforcements": conn.execute("SELECT count(*) FROM session_reinforcements").fetchone()[0],
            "connections": conn.execute("SELECT count(*) FROM connections").fetchone()[0],
        }
    finally:
        conn.close()


# ── The verb, and the scope ──


def test_the_view_has_its_own_verb_and_nothing_it_reaches_can_write(store, monkeypatch, capsys):
    """One connection a call, the exporter's read-only one, and SQLite's
    authorizer sees nothing but reads: no write is even attempted. No
    runtime, store or interface (the code that writes) is made."""
    opened: list[sqlite3.Connection] = []
    attempted: list[tuple] = []
    reads = {sqlite3.SQLITE_READ, sqlite3.SQLITE_SELECT, sqlite3.SQLITE_FUNCTION}

    def guarded(path):
        conn = open_read_only(path)
        opened.append(conn)

        def allow(action, arg1, arg2, database, source):
            if action in reads or (action == sqlite3.SQLITE_PRAGMA and arg1 == "table_info"):
                return sqlite3.SQLITE_OK
            attempted.append((action, arg1, arg2))
            return sqlite3.SQLITE_DENY

        conn.set_authorizer(allow)
        return conn

    def refuse(*args, **kwargs):
        raise AssertionError("the view made something that writes")

    monkeypatch.setattr(host_view, "open_read_only", guarded)
    monkeypatch.setattr(MnemosRuntime, "__init__", refuse)
    monkeypatch.setattr(EngramStore, "__init__", refuse)
    monkeypatch.setattr("mnemos.interface.person.Interface.__init__", refuse)
    connects: list[str] = []
    real_connect = sqlite3.connect
    monkeypatch.setattr(sqlite3, "connect", lambda target, *a, **k: (connects.append(str(target)),
                                                                     real_connect(target, *a, **k))[1])

    replies = _every_reply(store["db"])
    status, cli_reply = _cli(capsys, "--protocol", "1", "--section", "notes", "--db-path", str(store["db"]), *_flags())

    assert status == 0 and cli_reply["items"]
    assert attempted == [], attempted
    assert len(opened) == len(replies) + 1 == len(connects)
    assert all("mode=ro" in target for target in connects), connects
    # its own verb: not one of the person interface's commands, which include writes
    from mnemos.interface.person import COMMANDS

    assert "view" not in COMMANDS and "correct" in COMMANDS


def test_every_part_of_the_scope_is_required(store, capsys):
    for left_out, flag in (("agent_id", "--agent-id"), ("person_id", "--person-id"),
                           ("project_scope", "--project-scope")):
        status, reply = _cli(capsys, "--protocol", "1", "--section", "summary",
                             "--db-path", str(store["db"]), *_flags(**{left_out: True}))
        assert status == 2
        assert reply["error"]["code"] == "scope_required"
        assert reply["error"]["missing"] == [flag]
        assert "scope" not in reply
    status, reply = _cli(capsys, "--protocol", "1", "--section", "summary", *_flags())
    assert status == 2 and reply["error"]["missing"] == ["--db-path"]
    status, reply = _cli(capsys, "--protocol", "1", "--section", "summary")
    assert status == 2
    assert reply["error"]["missing"] == ["--db-path", "--agent-id", "--person-id", "--project-scope"]
    # an id given in a form Mnemos doesn't store is refused, not turned into another scope
    status, reply = _cli(capsys, "--protocol", "1", "--section", "summary", "--db-path", str(store["db"]),
                         "--agent-id", "Wren", "--person-id", "pat-example", "--project-scope", "lighthouse")
    assert status == 2 and reply["error"]["code"] == "scope_not_canonical"


def test_the_environment_and_the_config_file_are_ignored(store, home, monkeypatch, capsys):
    """MNEMOS_* and ~/.mnemos/config.json both name otter; the view answers
    for the flags, and a flag left out is refused, never filled from them."""
    (home / ".mnemos" / "config.json").write_text(json.dumps({
        "agent_id": "otter", "person_id": "sam-example", "project_scope": "orchard",
        "store": {"db_path": str(store["db"])},
    }))
    elsewhere = {"MNEMOS_AGENT_ID": "otter", "MNEMOS_PERSON_ID": "sam-example",
                 "MNEMOS_PROJECT_SCOPE": "orchard", "MNEMOS_DB_PATH": str(store["db"])}
    for name, value in elsewhere.items():
        monkeypatch.setenv(name, value)

    status, reply = _cli(capsys, "--protocol", "1", "--section", "memories", "--db-path", str(store["db"]), *_flags())
    assert status == 0
    assert reply["scope"] == WREN
    assert [m["words"] for m in reply["items"]] == [*WORDS["wren"], WORDS["wren_standing"]]

    status, reply = _cli(capsys, "--protocol", "1", "--section", "memories", "--db-path", str(store["db"]),
                         *_flags(person_id=True))
    assert status == 2 and reply["error"]["missing"] == ["--person-id"]
    status, reply = _cli(capsys, "--protocol", "1", "--section", "memories")
    assert status == 2 and len(reply["error"]["missing"]) == 4

    # and so in a process of its own, as a host runs it
    status, reply = _cli_process(home, "--protocol", "1", "--section", "memories",
                                 "--db-path", str(store["db"]), *_flags(), **elsewhere)
    assert status == 0 and reply["scope"] == WREN
    assert [m["words"] for m in reply["items"]] == [*WORDS["wren"], WORDS["wren_standing"]]
    status, reply = _cli_process(home, "--protocol", "1", "--section", "summary",
                                 "--db-path", str(store["db"]), *_flags(agent_id=True), **elsewhere)
    assert status == 2 and reply["error"]["missing"] == ["--agent-id"]


def test_the_view_never_creates_or_migrates_a_store(tmp_path, home, store, capsys):
    folder = tmp_path / "nothing-here"
    folder.mkdir()
    status, reply = _cli(capsys, "--protocol", "1", "--section", "summary",
                         "--db-path", str(folder / "missing.db"), *_flags())
    assert status == 2 and reply["error"]["code"] == "no_store"
    assert list(folder.iterdir()) == []
    assert str(folder) not in json.dumps(reply)

    empty = folder / "empty.db"
    empty.write_bytes(b"")
    status, reply = _cli(capsys, "--protocol", "1", "--section", "memories", "--db-path", str(empty), *_flags())
    assert status == 2 and reply["error"]["code"] == "not_a_store"
    assert sorted(p.name for p in folder.iterdir()) == ["empty.db"] and empty.read_bytes() == b""

    text = folder / "words.db"
    text.write_text("not a database at all " * 50)
    status, reply = _cli(capsys, "--protocol", "1", "--section", "memories", "--db-path", str(text), *_flags())
    assert status == 2 and reply["error"]["code"] == "unreadable_store"
    assert sorted(p.name for p in folder.iterdir()) == ["empty.db", "words.db"]

    # a store an older Mnemos wrote stays as it was: no migration, no stamp
    db = store["db"]
    conn = sqlite3.connect(db)
    conn.execute("UPDATE meta SET value='18' WHERE key='schema_version'")
    conn.commit()
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.close()
    for name in ("residents.db-wal", "residents.db-shm"):
        (db.parent / name).unlink(missing_ok=True)
    before = _folder(home)
    for reply in _every_reply(db):
        assert reply["schema_version"] == 18
    assert _folder(home) == before


def test_protocol_is_checked_before_the_store_is_opened(store, monkeypatch, capsys):
    def never(path):
        raise AssertionError("the store was opened")

    monkeypatch.setattr(host_view, "open_read_only", never)
    for given in ("2", "0", "abc", None):
        argv = ["--section", "summary", "--db-path", str(store["db"]), *_flags()]
        if given is not None:
            argv = ["--protocol", given, *argv]
        status, reply = _cli(capsys, *argv)
        assert status == 2
        assert reply["error"]["code"] == ("protocol_required" if given in ("abc", None) else "unsupported_protocol")
        assert reply["supported_protocols"] == [1]
        assert "schema_version" not in reply
    # even with nothing else right, the protocol is what's refused first
    status, reply = _cli(capsys, "--protocol", "7")
    assert reply["error"]["code"] == "unsupported_protocol"
    assert mnemos.VIEW_PROTOCOL_VERSION == host_view.VIEW_PROTOCOL_VERSION == 1
    assert mnemos.HOST_MUTATION_PROTOCOL_VERSION == 1


def test_every_reply_says_its_versions_and_scope(store):
    from mnemos.package_version import mnemos_version

    for reply in _every_reply(store["db"], limit=50):
        assert reply["protocol_version"] == 1
        assert reply["mnemos_version"] == mnemos_version()
        assert reply["schema_version"] == 19
        assert reply["scope"] == WREN
        assert str(store["db"]) not in json.dumps(reply) and "residents.db" not in json.dumps(reply)


# ── Only this resident ──


def test_nothing_of_another_resident_appears_in_any_reply(store):
    hidden = _hidden(store["db"])
    replies = _every_reply(store["db"], limit=1)
    for reply in replies:
        text = json.dumps(reply, ensure_ascii=False)
        assert [x for x in hidden if x and x in text] == [], reply["section"]
    summary = replies[0]
    assert summary["counts"] == {
        "memories": {"active": 3, "dormant": 0, "archived": 0}, "standing": 1, "journal": 1,
        "notes": {"all": 2, "unread": 1}, "handoffs": 1, "beliefs": 1,
    }
    seen = {s: [i for r in replies if r["section"] == s for i in r["items"]] for s in LISTS}
    assert [m["words"] for m in seen["memories"]] == [*WORDS["wren"], WORDS["wren_standing"]]
    assert [m["words"] for m in seen["standing"]] == [WORDS["wren_standing"]]
    assert seen["standing"][0]["standing"] is True
    assert [j["text"] for j in seen["journal"]] == ["A quiet day. I sorted the blue binder by month."]
    assert sorted(n["text"] for n in seen["notes"]) == [
        "I noticed the blue binder is nearly full.", "Thanks, a new binder is on its way."]
    assert [h["text"] for h in seen["handoffs"]] == ["Next time: ask whether the new binder arrived."]


def test_beliefs_are_kept_to_the_whole_scope(store):
    """The beliefs table is the agent's alone (no person, no project): a
    belief is this scope's only when every memory it rests on is this
    scope's. One that also rests on another person's memory is shown to
    neither, because its words may carry what the other person said."""
    beliefs = _view(store["db"], "beliefs")["items"]
    assert [b["text"] for b in beliefs] == ["Pat keeps paper records close at hand."]
    assert beliefs[0]["supports"] == [store["wren"][0]] and beliefs[0]["supports_total"] == 1
    assert store["quinn"][0] not in json.dumps(beliefs)
    quinn = host_view.read_view(protocol=1, db_path=str(store["db"]), section="beliefs", **QUINN)["items"]
    assert [b["text"] for b in quinn] == ["Quinn trusts hooks more than drawers."]
    assert quinn[0]["supports"] == [store["quinn"][0]]
    for shown in (beliefs, quinn):
        assert "Binders and hooks both get used here." not in json.dumps(shown)


# ── Bounds ──


def test_limits_cursors_and_the_byte_ceiling(home, capsys):
    db = home / ".mnemos" / "big.db"
    long_words = "🌊" * 30_000  # four bytes each: far past the text limit and the ceiling
    kept = _write(db, WREN, [f"Plain memory number {n:03d}." for n in range(230)] +
                  [f"Long memory {n}. {long_words}" for n in range(20)])
    runtime = MnemosRuntime(db_path=str(db), use_dedicated_model=False, **WREN)
    try:  # the longest an item can be: both its texts cut at the limit
        kept.append(_memory_id(runtime.capture(f"Longest. {long_words}", impact="🔥" * 30_000, signed_as=SIGNED)))
    finally:
        runtime.close()

    for bad in ("0", "201", "-3", "many"):
        status, reply = _cli(capsys, "--protocol", "1", "--section", "memories", "--db-path", str(db),
                             *_flags(), "--limit", bad)
        assert status == 2 and reply["error"]["code"] == "bad_limit" and reply["error"]["most"] == 200
    for bad in ("not-a-cursor", base64.urlsafe_b64encode(b'{"s":"journal","a":["x","y"]}').decode()):
        status, reply = _cli(capsys, "--protocol", "1", "--section", "memories", "--db-path", str(db),
                             *_flags(), "--cursor", bad)
        assert status == 2 and reply["error"]["code"] == "bad_cursor"
    status, reply = _cli(capsys, "--protocol", "1", "--section", "summary", "--db-path", str(db),
                         *_flags(), "--limit", "5")
    assert status == 2

    first = _view(db, "memories")
    assert len(first["items"]) == host_view.DEFAULT_ITEMS == 50 and first["truncated"]

    seen, sizes, cursor, clipped, cut_by_bytes = [], [], None, 0, 0
    while True:
        status = main(["view", "--protocol", "1", "--section", "memories", "--db-path", str(db), *_flags(),
                       "--limit", "200", *(["--cursor", cursor] if cursor else [])])
        printed = capsys.readouterr().out
        assert status == 0
        reply = json.loads(printed)
        sizes.append(len(printed.rstrip("\n").encode("utf-8")))
        assert len(reply["items"]) <= 200
        seen += [m["id"] for m in reply["items"]]
        clipped += sum(1 for m in reply["items"] if m.get("clipped"))
        for m in reply["items"]:
            assert len(m["words"]) <= host_view.MOST_TEXT_CHARS
            assert len(m["impact"]) <= host_view.MOST_TEXT_CHARS
        assert reply["items"], "a reply must always carry at least one item while there are more"
        if not reply["truncated"]:
            assert reply["next_cursor"] is None
            break
        if len(reply["items"]) < 200 and len(seen) < len(kept):
            cut_by_bytes += 1  # stopped by the ceiling, not the limit
        cursor = reply["next_cursor"]
    assert seen == kept, "paging lost, repeated or reordered a memory"
    assert clipped == 21
    assert cut_by_bytes >= 5, "the long memories should have been cut by the byte ceiling"
    assert max(sizes) <= host_view.MOST_REPLY_BYTES
    print(f"largest reply: {max(sizes)} bytes over {len(sizes)} pages")


def test_newest_first_sections_page_to_the_end_once_each(home):
    db = home / ".mnemos" / "paged.db"
    runtime = MnemosRuntime(db_path=str(db), use_dedicated_model=False, **WREN)
    try:
        for n in range(7):
            runtime.journal(f"Journal entry {n}.", signed_as=SIGNED)
            runtime.note(f"Note {n}.", kind="noticed", signed_as=SIGNED)
    finally:
        runtime.close()
    for section, field in (("journal", "Journal entry"), ("notes", "Note")):
        texts, cursor = [], None
        while True:
            reply = _view(db, section, limit=2, cursor=cursor)
            assert len(reply["items"]) <= 2
            texts += [item["text"] for item in reply["items"]]
            if not reply["truncated"]:
                break
            cursor = reply["next_cursor"]
        assert texts == [f"{field} {n}." for n in reversed(range(7))], section


def test_the_summary_token_changes_only_when_the_memory_does(store):
    one = _view(store["db"], "summary")["change_token"]
    assert _view(store["db"], "summary")["change_token"] == one
    _write(store["db"], OTTER, ["Otter adds a line about pears."])
    assert _view(store["db"], "summary")["change_token"] == one, "another resident's write moved it"
    _write(store["db"], WREN, ["Pat asked for a second binder."])
    assert _view(store["db"], "summary")["change_token"] != one


ELSEWHERE = {"agent_id": "wren", "person_id": "pat-example", "project_scope": "harbour-office"}


def _token(db: Path, scope: dict[str, str] | None = None) -> str:
    return host_view.read_view(protocol=1, db_path=str(db), section="summary",
                               **(scope or WREN))["change_token"]


def _run(db: Path, scope: dict[str, str], act) -> object:
    runtime = MnemosRuntime(db_path=str(db), use_dedicated_model=False, **scope)
    try:
        return act(runtime)
    finally:
        runtime.close()


def _in_store(db: Path, act) -> object:
    engrams = EngramStore(db)
    try:
        return act(engrams)
    finally:
        engrams.close()


def _sql(db: Path, statement: str, *params: object) -> None:
    conn = sqlite3.connect(db)
    try:
        conn.execute(statement, params)
        conn.commit()
    finally:
        conn.close()


def _first(db: Path, query: str, *params: object) -> str:
    conn = open_read_only(db)
    try:
        return conn.execute(query, params).fetchone()[0]
    finally:
        conn.close()


def test_the_summary_token_moves_for_every_change_a_section_shows_and_no_other(store):
    """One table: every kind of change a section can show, each made the
    way Mnemos makes it where it has a way, must move the token; every
    change outside the scope (the other resident in the same file, this
    agent's memory of another person, this agent and person in another
    project) must not. Each outside change must move its own scope's token,
    so a write that landed nowhere can't pass for one that was ignored."""
    db = store["db"]
    kept: dict[str, str] = {}
    wren_note = _first(db, "SELECT id FROM notes WHERE agent_id='wren' AND person_id='pat-example' "
                           "AND author='agent'")

    def capture(scope, words, name):
        kept[name] = _run(db, scope, lambda r: _memory_id(r.capture(words, signed_as=SIGNED)))

    def belief(name, supports, agent="wren"):
        made = Belief(agent_id=agent, content=f"A belief: {name}.", confidence=0.5,
                      supporting_engram_ids=supports, source="agent")
        kept[name] = made.id
        _in_store(db, lambda s: s.save_belief(made))

    def rest_on(name, supports):
        def act(s):
            held = s.get_belief(kept[name])
            held.supporting_engram_ids = supports
            s.save_belief(held)
        _in_store(db, act)

    def otter_entries(r):
        r.journal("Otter's journal: the pears are in.", signed_as=SIGNED)
        r.note("I noticed the pear ladder is loose.", kind="noticed", signed_as=SIGNED)
        r.person_note("Sam will fix the ladder.")
        r.handoff("Next time: the ladder.", signed_as=SIGNED)

    in_scope = [
        ("a new memory", lambda: capture(WREN, "Pat keeps the spare lamp wick in the drawer.", "wick")),
        ("a corrected memory", lambda: kept.update(corrected=_run(db, WREN, lambda r: r.correct_memory(
            store["wren"][0], "The keeper's log lives in the red binder now.", person=False,
            signed_as=SIGNED))["id"])),
        ("a forgotten memory", lambda: _run(db, WREN, lambda r: r.forget_memory(
            store["wren"][1], person=False, signed_as=SIGNED))),
        ("standing turned on", lambda: _in_store(db, lambda s: s.set_standing(kept["wick"], True, by=SIGNED))),
        ("standing turned off", lambda: _in_store(db, lambda s: s.set_standing(kept["wick"], False, by=SIGNED))),
        ("a memory fading (how alive it is)", lambda: _sql(
            db, "UPDATE engrams SET accessibility = accessibility / 2 WHERE id = ?", kept["wick"])),
        ("a memory going dormant", lambda: _sql(db, "UPDATE engrams SET state = 'dormant' WHERE id = ?",
                                               kept["wick"])),
        ("a new journal entry", lambda: _run(db, WREN, lambda r: r.journal("The lamp burned all night.",
                                                                           signed_as=SIGNED))),
        ("a new note from the agent", lambda: _run(db, WREN, lambda r: r.note(
            "I noticed the wick is short.", kind="noticed", signed_as=SIGNED))),
        ("a reply to a note", lambda: _run(db, WREN, lambda r: r.reply_to_note(wren_note, "Ordered more."))),
        ("a new note from the person", lambda: _run(db, WREN, lambda r: r.person_note("The lamp is lovely."))),
        ("a note read by the person", lambda: _run(db, WREN, lambda r: r.mark_notes_read([wren_note]))),
        ("a person's note delivered", lambda: _sql(
            db, "UPDATE notes SET delivered_at = '2026-11-12T09:00:00+00:00' WHERE agent_id = 'wren' "
                "AND person_id = 'pat-example' AND project_scope = 'lighthouse' AND author = 'person'")),
        ("a new handoff", lambda: _run(db, WREN, lambda r: r.handoff("Next time: the wick.", signed_as=SIGNED))),
        ("a belief gained", lambda: belief("wick belief", [kept["wick"]])),
        ("a belief revised", lambda: _in_store(db, lambda s: s.revise_belief(kept["wick belief"], 0.8, "seen"))),
        ("a belief lost: it comes to rest on another person's memory too",
         lambda: rest_on("wick belief", [kept["wick"], store["quinn"][0]])),
        ("a belief gained: it rests on this scope's memories alone again",
         lambda: rest_on("wick belief", [kept["wick"]])),
        # the fixture's "Pat keeps paper records" rests on the memory the correction archived
        ("a belief lost: a memory it rests on is deleted", lambda: _in_store(
            db, lambda s: s.delete_engram(store["wren"][0]))),
        ("a belief retired", lambda: _in_store(db, lambda s: s.supersede_belief(kept["wick belief"]))),
    ]
    outside = [
        ("another resident's new memory", OTTER, lambda: capture(OTTER, "Otter counts the pears.", "pears")),
        ("another resident's memory forgotten", OTTER, lambda: _run(db, OTTER, lambda r: r.forget_memory(
            store["otter"][0], person=False, signed_as=SIGNED))),
        ("another resident's standing turned on", OTTER, lambda: _in_store(
            db, lambda s: s.set_standing(kept["pears"], True, by=SIGNED))),
        ("another resident's journal, notes and handoff", OTTER, lambda: _run(db, OTTER, otter_entries)),
        ("another resident's belief", OTTER, lambda: belief("orchard belief", [kept["pears"]], agent="otter")),
        ("another person's new memory", QUINN, lambda: capture(QUINN, "Quinn oils the hinges.", "hinges")),
        ("another person's memory corrected", QUINN, lambda: _run(db, QUINN, lambda r: r.correct_memory(
            store["quinn"][0], "Quinn's spare key hangs on the blue hook.", person=False, signed_as=SIGNED))),
        ("another person's journal entry and note", QUINN, lambda: _run(db, QUINN, lambda r: (
            r.journal("Quinn came by.", signed_as=SIGNED),
            r.note("I noticed Quinn's hinges squeak.", kind="noticed", signed_as=SIGNED)))),
        ("a belief of this agent's resting only on another person's memory", QUINN,
         lambda: belief("hinge belief", [kept["hinges"]])),
        ("a belief of this agent's resting on this person's memory and another's", None,
         lambda: belief("mixed belief", [kept["wick"], kept["hinges"]])),
        ("another project's new memory", ELSEWHERE, lambda: capture(ELSEWHERE, "The office kettle is new.",
                                                                    "kettle")),
        ("another project's journal, note and handoff", ELSEWHERE, lambda: _run(db, ELSEWHERE, lambda r: (
            r.journal("The office was quiet.", signed_as=SIGNED),
            r.note("I noticed the office kettle.", kind="noticed", signed_as=SIGNED),
            r.handoff("Next time: the office.", signed_as=SIGNED)))),
    ]
    still, moved, unseen = [], [], []
    for name, change in in_scope:
        before = _token(db)
        change()
        if _token(db) == before:
            still.append(name)
    for name, theirs, change in outside:
        before, their_before = _token(db), _token(db, theirs) if theirs else None
        change()
        if _token(db) != before:
            moved.append(name)
        if theirs and _token(db, theirs) == their_before:
            unseen.append(name)
    assert len(in_scope) + len(outside) == 32
    assert still == [], f"changes a section shows that left the token as it was: {still}"
    assert moved == [], f"changes outside the scope that moved the token: {moved}"
    assert unseen == [], f"outside changes their own scope's token didn't see: {unseen}"


def test_the_summary_counts_what_the_sections_give(store):
    """Each count is how many items paging that section to its end gives,
    and the standing section is the memories section's standing ones, at
    the same places."""
    db = store["db"]
    _run(db, WREN, lambda r: [r.capture(f"Standing rule {n}.", signed_as=SIGNED, standing=n % 2 == 0)
                              for n in range(9)])
    for scope in (WREN, QUINN, OTTER):
        summary = host_view.read_view(protocol=1, db_path=str(db), section="summary", **scope)["counts"]
        seen: dict[str, list[tuple[dict, str | None]]] = {}
        for section in LISTS:
            cursor, seen[section] = None, []
            while True:
                reply = host_view.read_view(protocol=1, db_path=str(db), section=section, limit=2,
                                            cursor=cursor, **scope)
                seen[section] += [(item, reply["next_cursor"]) for item in reply["items"]]
                if not reply["truncated"]:
                    break
                cursor = reply["next_cursor"]
        notes = [item for item, _ in seen["notes"]]
        assert summary == {
            "memories": {"active": len(seen["memories"]), "dormant": 0, "archived": 0},
            "standing": len(seen["standing"]), "journal": len(seen["journal"]),
            "notes": {"all": len(notes),
                      "unread": sum(1 for n in notes if n["author"] == "agent" and not n["read_at"])},
            "handoffs": len(seen["handoffs"]), "beliefs": len(seen["beliefs"]),
        }, scope
        memories = [item for item, _ in seen["memories"]]
        assert [item for item, _ in seen["standing"]] == [m for m in memories if m["standing"]]
    assert summary["standing"] == 1 and len(memories) == 3  # otter's, the last read
    wren = host_view.read_view(protocol=1, db_path=str(db), section="summary", **WREN)["counts"]
    assert wren["standing"] == 6 and wren["memories"]["active"] == 12
    # a standing page's cursor is a place in the memories order, as it always was
    first = _view(db, "standing", limit=2)
    places = json.loads(base64.urlsafe_b64decode(first["next_cursor"] + "=" * (-len(first["next_cursor"]) % 4)))
    every = [m["id"] for m in _view(db, "memories", limit=200)["items"]]
    assert places == {"s": "standing", "a": every.index(first["items"][-1]["id"]) + 1}


def test_values_of_mixed_kinds_are_still_put_in_one_order(store):
    """A store can hold a value of another kind where text is expected (a
    time or an id kept as bytes). The standing section then falls back to
    SQLite's own order, the memories section's, and the token to a fixed
    order of its own."""
    db = store["db"]
    made = _run(db, WREN, lambda r: [_memory_id(r.capture(f"Rule {n} of the lamp room.", signed_as=SIGNED,
                                                          standing=True)) for n in range(4)])
    _sql(db, "UPDATE engrams SET created_at = CAST(created_at AS BLOB) WHERE id = ?", made[1])
    _run(db, WREN, lambda r: r.journal("A second entry, kept as text.", signed_as=SIGNED))
    _sql(db, "UPDATE journal_entries SET id = CAST(id AS BLOB) WHERE agent_id = 'wren' AND text LIKE 'A quiet day%'")
    every = [m["id"] for m in _view(db, "memories", limit=200)["items"]]
    assert every[-1] == made[1], "SQLite puts a value kept as bytes after every text"
    standing, cursor = [], None
    while True:
        reply = _view(db, "standing", limit=2, cursor=cursor)
        standing += [m["id"] for m in reply["items"]]
        if not reply["truncated"]:
            break
        cursor = reply["next_cursor"]
    assert standing == [i for i in every if i in {*made, store["wren"][2]}]
    one = _token(db)
    assert _token(db) == one
    _sql(db, "UPDATE journal_entries SET text = 'Changed.' WHERE agent_id = 'wren' AND typeof(id) = 'blob'")
    assert _token(db) != one


def test_search_is_not_a_section(store, capsys):
    status, reply = _cli(capsys, "--protocol", "1", "--section", "search", "--db-path", str(store["db"]), *_flags())
    assert status == 2 and reply["error"]["code"] == "unknown_section"
    assert "search" not in reply["error"]["sections"]


def test_why_search_is_left_out_the_search_path_leaves_files_beside_an_idle_store(store, home):
    """`mnemos search` opens the store through a reader of its own, not the
    exporter's, and beside a store nobody has open it leaves a -wal and a
    -shm. The view's proof is that the folder's listing is unchanged, so
    search stays out of the view. If this starts failing, the search path
    has become listing-clean, and search can be weighed again."""
    db = store["db"]
    before = sorted(p.name for p in db.parent.iterdir())
    done = subprocess.run([sys.executable, "-m", "mnemos.cli", "--db-path", str(db), *_flags(),
                           "search", "--json", "binder"], capture_output=True, text=True, timeout=300,
                          env=_env(home, MNEMOS_MAINTENANCE="inline"))
    assert done.returncode == 0, done.stderr
    after = sorted(p.name for p in db.parent.iterdir())
    assert set(after) - set(before) == {"residents.db-wal", "residents.db-shm"}


# ── Writes nothing ──


def test_an_idle_store_is_byte_for_byte_and_file_for_file_as_it_was(store, home):
    db = store["db"]
    folder = db.parent
    assert sorted(p.name for p in folder.iterdir()) == ["residents.db"], "the fixture left the store open"
    before = _folder(folder)
    for section in host_view.SECTIONS:
        _view(db, section)
        assert _folder(folder) == before, section
    _every_reply(db, limit=1)
    assert _folder(folder) == before
    for section in host_view.SECTIONS:  # and from a process of its own, as a host runs it
        status, reply = _cli_process(home, "--protocol", "1", "--section", section,
                                     "--db-path", str(db), *_flags())
        assert status == 0, reply
        assert _folder(folder) == before, section


_WRITER = """
import sys
from mnemos.simple_runtime import MnemosRuntime
runtime = MnemosRuntime(db_path=sys.argv[1], use_dedicated_model=False,
                        agent_id="wren", person_id="pat-example", project_scope="lighthouse")
said = runtime.capture("Written while the writer holds the store open.", signed_as="example-model")
conn = runtime._store._get_conn()
conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('example-last-write', '1')")
conn.commit()
if sys.argv[2] == "read-after":  # else its last act is that bare commit, with no read after it
    conn.execute("SELECT count(*) FROM engrams").fetchone()
print(said.split("Memory ID: ", 1)[1].split()[0], flush=True)
sys.stdin.readline()
runtime.close()
"""


@pytest.fixture(params=["bare-commit", "read-after"])
def last_act(request) -> str:
    return request.param


def test_a_live_writer_is_read_to_its_last_commit_and_its_files_kept(store, home, last_act):
    db = store["db"]
    writer = subprocess.Popen([sys.executable, "-c", _WRITER, str(db), last_act], stdin=subprocess.PIPE,
                              stdout=subprocess.PIPE, text=True, env=_env(home, MNEMOS_MAINTENANCE="inline"))
    try:
        fresh = writer.stdout.readline().strip()
        assert fresh.startswith("engram_")
        wal, shm = Path(f"{db}-wal"), Path(f"{db}-shm")
        assert wal.is_file() and shm.is_file(), "the writer should be holding the WAL open"
        main_before, wal_before, shm_before = db.read_bytes(), wal.read_bytes(), shm.read_bytes()
        listing = sorted(p.name for p in db.parent.iterdir())

        for section in host_view.SECTIONS:
            status, reply = _cli_process(home, "--protocol", "1", "--section", section,
                                         "--db-path", str(db), *_flags())
            assert status == 0, reply
            if section == "memories":
                assert fresh in [m["id"] for m in reply["items"]], "the newest commit wasn't read"
            if section == "summary":
                assert reply["counts"]["memories"]["active"] == 4

        assert db.read_bytes() == main_before, "the reader changed the main file"
        assert wal.read_bytes() == wal_before
        assert sorted(p.name for p in db.parent.iterdir()) == listing
        shm_after = shm.read_bytes()
        assert len(shm_after) == len(shm_before)
        moved = [i for i in range(len(shm_before)) if shm_before[i] != shm_after[i]]
        # What SQLite does to -shm: a reader records the newest frame it reads
        # in one of the WAL index's read-mark slots (bytes 100-119), and
        # changes nothing else.
        assert all(100 <= i < 120 for i in moved), moved
        if last_act == "bare-commit":
            assert moved, "the reader found no read mark at the newest frame, so it should have set one"
        else:
            assert moved == [], "a read mark at the newest frame was there; nothing should move"
        marks = struct.unpack("<5I", shm_after[100:120])
        print(f"{last_act}: -shm bytes changed: {moved}; read marks {struct.unpack('<5I', shm_before[100:120])} -> {marks}")
    finally:
        writer.stdin.write("\n")
        writer.stdin.close()
        writer.wait(timeout=60)


def test_no_memory_is_woken_no_note_read_no_trace_written_nothing_new_at_home(store, home):
    db = store["db"]
    (home / ".mnemos" / "config.json").write_text("{}")
    state, files = _state(db), _folder(home)
    unread = [row for row in state["notes"] if row[1] is None]
    assert unread, "the fixture should hold a note not yet read"
    _every_reply(db, limit=1)
    for section in host_view.SECTIONS:
        _cli_process(home, "--protocol", "1", "--section", section, "--db-path", str(db), *_flags())
    assert _state(db) == state
    assert _folder(home) == files
    assert not list((home / ".mnemos").glob("run/shown-*"))


def test_the_example_runs_and_finds_nothing_of_the_other_resident(tmp_path):
    done = subprocess.run([sys.executable, str(REPO / "examples" / "host_read_view" / "run.py")],
                          capture_output=True, text=True, timeout=300, cwd=str(REPO),
                          env=_env(tmp_path / "unused-home"))
    assert done.returncode == 0, done.stdout + done.stderr
    assert "Nothing of otter's or quinn-example's appeared in any reply" in done.stdout


def test_the_speed_script_runs_at_a_tiny_size(tmp_path):
    """The script behind the "How fast" table, at 100 memories with one
    timed call, so it can't stop working unnoticed."""
    results = tmp_path / "results.json"
    done = subprocess.run([sys.executable, str(REPO / "examples" / "host_read_view" / "measure.py"),
                           "--sizes", "100", "--runs", "1", "--cli", "summary", "--json", str(results)],
                          capture_output=True, text=True, timeout=120, cwd=str(REPO),
                          env={**_env(tmp_path / "unused-home"), "TMPDIR": str(tmp_path)})
    assert done.returncode == 0, done.stdout + done.stderr
    assert "the direct build gives the same summary counts and section lengths as the capture build: yes" \
        in done.stdout
    measured = json.loads(results.read_text())
    assert [(row["size"], row["built_by"]) for row in measured["sizes"]] == [(100, "capture"), (100, "direct")]
    assert set(measured["sizes"][0]["sections"]) == set(host_view.SECTIONS)
    assert measured["live_writer"]["inprocess_ms"]["median"] > 0
    assert [p.name for p in tmp_path.iterdir() if p.name.startswith("mnemos-view-measure-")] == []
