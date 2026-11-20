"""The whole notebook through `mnemos interface`, for a host (WP-46).

An app that keeps one `mnemos interface` process (Polyphonic, Ghost) gets, beside
the person's commands, everything the notebook's own page shows and does:

1. ``hello``: what this Mnemos answers, asked once.
2. ``notebook``: each part of the page (``life``, ``memories``, ``pulse``)
   exactly as the page is given it, by the page's own code; each picture as a
   file inside this mind's studio, never bytes in a line.
3. ``summary``: what each part counts, what waits on the person, and a token
   that changes only when something shown changes.
4. The rest of the person's acts on the page: ``read``, ``hours``, ``shared``,
   through the page's own functions, with its limits and its sentences. Jev
   stays on the page: it takes a key, and nothing here takes one.
5. ``--as-person`` and ``--strict-scope``.
6. Reading changes nothing, any read: every table the same after as before.

No test reaches a real scheduler, a real network or a real ~/.mnemos.
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from mnemos.companion import export as log_export
from mnemos.companion.export import MOST_BYTES, Exporter, open_read_only
from mnemos.companion.server import LogServer
from mnemos.interface import person
from mnemos.interface.person import COMMANDS, PARTS, Interface
from mnemos.simple_runtime import MnemosRuntime

OPUS = "claude-opus-5-5"
AGENT = "nova"
SCOPE = {"agent_id": AGENT, "person_id": "riley", "project_scope": "demo"}
SCOPE_ARGS = ["--agent-id", AGENT, "--person-id", "riley", "--project-scope", "demo"]
OLD = ("memories", "search", "correct", "forget", "journal", "notes", "reply", "note")
HOUR = "01K6WQTESTHOUR000000000009"
PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000d49444154789c6360f8cfc00000030101005d9d7cd30000000049454e44ae426082"
)
KEY = "ts_live_9f2Q7xK3mP0wZ8yV"


@pytest.fixture(autouse=True)
def no_real_scheduler(monkeypatch):
    """The page's own read of the schedulers, answered here (as test_the_log does)."""
    monkeypatch.setattr(log_export, "_launchd_loaded", lambda label: True)
    monkeypatch.setattr(log_export, "_systemd_active", lambda timer: True)
    monkeypatch.setattr(log_export, "_crontab", lambda: "")


def _runtime(db: Path) -> MnemosRuntime:
    return MnemosRuntime(db_path=str(db), use_dedicated_model=False, **SCOPE)


def _id(said: str) -> str:
    return said.split("Memory ID: ", 1)[1].split()[0]


@pytest.fixture
def notebook(tmp_path):
    """A mind with something in every part of the notebook: memories, a journal,
    a question waiting on the person and a note they haven't read, a note it
    left itself, one quiet hour with its record, and pictures in its studio."""
    db = tmp_path / "nova.db"
    rt = _runtime(db)
    try:
        ids = {
            "ferry": _id(rt.capture("The ferry timetable moved to the kitchen drawer.", signed_as=OPUS)),
            "pier": _id(rt.capture("The ferry leaves the east pier at nine on weekdays.", signed_as=OPUS)),
            "gnome": _id(rt.capture("The garden gnome is named Bartholomew.", signed_as="claude-fable-1")),
        }
        rt.journal("Tonight I thought about the ferry and the gnome.", signed_as=OPUS)
        rt.note("Should the ferry note move to the shared board?", "question", signed_as=OPUS)
        rt.note("I kept the timetable where you can find it.", "made", signed_as=OPUS)
        rt.handoff("Where I was: the ferry. Next: the gnome's name.", signed_as=OPUS)
        notes = rt.notes()
        ids["question"] = next(n["id"] for n in notes if n["kind"] == "question")
        ids["made"] = next(n["id"] for n in notes if n["kind"] == "made")
    finally:
        rt.close()
    studio = Path.home() / ".mnemos" / "studio" / AGENT
    (studio / "maps").mkdir(parents=True)
    (studio / "week.png").write_bytes(PNG)
    (studio / "maps" / "pier.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg"/>')
    (studio / "notes.txt").write_text("not a picture")
    (studio / ".hidden.png").write_bytes(PNG)
    (studio / "huge.png").write_bytes(b"\0" * (MOST_BYTES + 1))
    outside = tmp_path / "outside.png"
    outside.write_bytes(PNG)
    (studio / "away.png").symlink_to(outside)
    hours = Path.home() / ".mnemos" / "hours" / AGENT
    (hours / HOUR).mkdir(parents=True)
    (hours / HOUR / "stream.jsonl").write_text(json.dumps({"type": "result", "result": "A quiet hour."}) + "\n")
    now = datetime.now(timezone.utc)
    (hours / "hours.jsonl").write_text(json.dumps({
        "id": HOUR, "kind": "mine", "started_at": (now - timedelta(hours=1)).isoformat(),
        "ended_at": (now - timedelta(minutes=30)).isoformat(), "model": OPUS, "status": "done",
        "store": "live", "live_store_untouched": True}) + "\n")
    return db, ids


def _here(db: Path, **more) -> Interface:
    return Interface(db_path=str(db), **SCOPE, **more)


def _ask(interface: Interface, command: str, **request):
    return interface.answer(json.dumps({"id": 1, "command": command, **request}))


def _result(interface: Interface, command: str, **request):
    answer = _ask(interface, command, **request)
    assert "result" in answer, answer
    return answer["result"]


def _interface(db: Path, home: Path, requests: list[dict], *flags: str, scope: list[str] | None = None,
               **env: str) -> subprocess.CompletedProcess:
    """``mnemos interface`` in a process of its own, in ``home``."""
    return subprocess.run(
        [sys.executable, "-m", "mnemos.cli", "interface", *(scope if scope is not None else
                                                             ["--db-path", str(db), *SCOPE_ARGS]), *flags],
        input="".join(json.dumps(request) + "\n" for request in requests),
        capture_output=True, text=True, timeout=180,
        env={"HOME": str(home), "PATH": "/usr/bin:/bin", "MNEMOS_DISABLE_DOTENV": "1",
             "PYTHONPATH": ":".join(sys.path), **env},
    )


def _without(document: dict, *keys: str) -> dict:
    return {k: v for k, v in document.items() if k not in keys}


# ---------- 1. hello ----------

def test_hello_says_what_this_mnemos_answers(notebook):
    from mnemos.package_version import mnemos_version
    from mnemos.store.sqlite_store import SCHEMA_VERSION

    db, _ = notebook
    interface = _here(db)
    try:
        said = _result(interface, "hello")
    finally:
        interface.close()
    assert said == {
        "protocol": 1, "mnemos": mnemos_version(), "schema": SCHEMA_VERSION, "commands": list(COMMANDS),
        "parts": ["life", "memories", "pulse"], "writes_as": "person", "strict_scope": False,
        "scope": {**SCOPE, "db_path": str(db), "held": True},
    }
    assert list(COMMANDS[:len(OLD)]) == list(OLD), "the person's commands keep their place"


# ---------- 2. Each part, as the page is given it ----------

def test_each_part_is_exactly_what_the_page_is_given(notebook):
    db, _ = notebook
    server = LogServer(Exporter.for_scope(db_path=str(db), **SCOPE))
    interface = _here(db)
    try:
        page_life, page_memories = (json.loads(document) for document in server.documents())
        since = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        page_pulse = json.loads(server.pulse(None, since))
        life = _result(interface, "notebook", part="life")
        memories = _result(interface, "notebook", part="memories")
        pulse = _result(interface, "notebook", part="pulse", since=since)
    finally:
        interface.close()
        server.server_close()
    assert (life["part"], memories["part"], pulse["part"]) == PARTS
    assert _without(life["document"], "made") == _without(page_life, "made")
    assert _without(memories["document"], "made") == _without(page_memories, "made")
    assert _without(pulse["document"], "now") == _without(page_pulse, "now")
    assert pulse["document"]["events"], "the captures came to mind"
    # every part of the page is there: who, the hours and their schedule, the settings, the shared notebook, the
    # journal, the notes, what it made, what its memory asks, its memory, beliefs, what it carries forward
    assert set(life["document"]) == {"made", "identity", "hours", "schedule", "jev", "shared", "journal", "notes",
                                     "studio", "questions", "memory", "beliefs", "handoffs"}
    assert life["document"]["hours"][0]["id"] == HOUR and life["document"]["handoffs"]


def test_the_parts_are_made_by_the_pages_own_code(notebook, monkeypatch):
    """Not a second way to make them: ``Exporter.export`` for life and
    memories, the very ``pulse`` function the page's server calls."""
    db, _ = notebook
    made = []
    real = Exporter.export
    monkeypatch.setattr(Exporter, "export", lambda self, now=None: made.append(self.scope) or real(self, now))
    interface = _here(db)
    try:
        _result(interface, "notebook", part="life")
        _result(interface, "notebook", part="memories")
        _result(interface, "summary")
    finally:
        interface.close()
    assert made == [interface.scope] * 3
    assert person.pulse is log_export.pulse


def test_a_part_is_asked_for_by_name(notebook):
    db, _ = notebook
    interface = _here(db)
    try:
        answers = [_ask(interface, "notebook"), _ask(interface, "notebook", part="minds"),
                   _ask(interface, "notebook", part="pulse", since=7)]
    finally:
        interface.close()
    assert [answer["error"] for answer in answers] == [
        '"part" is "life", "memories" or "pulse".', '"part" is "life", "memories" or "pulse".',
        '"since" takes a time, in ISO 8601.']


def test_without_a_store_each_part_says_so_and_makes_nothing(tmp_path):
    db = tmp_path / "nothing.db"
    interface = _here(db)
    try:
        life = _result(interface, "notebook", part="life")
        memories = _result(interface, "notebook", part="memories")
        summary = _result(interface, "summary")
        hello = _result(interface, "hello")
    finally:
        interface.close()
    assert life["document"]["missing"] is True and life["pictures"] == {}
    assert memories["document"]["memories"] == []
    assert summary["missing"] is True and summary["counts"]["memories"] == 0
    assert hello["scope"]["held"] is False
    assert not db.exists()


# ---------- Pictures ----------

def test_each_picture_is_a_file_inside_its_own_studio_and_nothing_else(notebook):
    db, _ = notebook
    interface = _here(db)
    try:
        life = _result(interface, "notebook", part="life")
    finally:
        interface.close()
    studio = os.path.realpath(Path.home() / ".mnemos" / "studio" / AGENT)
    assert life["pictures"] == {
        "week.png": os.path.join(studio, "week.png"),
        "maps/pier.svg": os.path.join(studio, "maps", "pier.svg"),
    }
    # the page lists the text file and the huge picture (as files it made), and offers neither as a picture
    listed = {item["path"]: item["picture"] for item in life["document"]["studio"]}
    assert listed["notes.txt"] is None and listed["huge.png"] is None
    assert ".hidden.png" not in listed and "away.png" not in listed
    for path in life["pictures"].values():
        assert path.startswith(studio + os.sep) and Path(path).read_bytes()


# ---------- 3. summary ----------

def test_the_summary_counts_what_the_page_shows(notebook):
    db, ids = notebook
    interface = _here(db)
    try:
        life = _result(interface, "notebook", part="life")["document"]
        summary = _result(interface, "summary")
    finally:
        interface.close()
    counts = summary["counts"]
    assert counts["memories"] == life["memory"]["count"] == 3
    assert counts["states"] == {"active": 3, "dormant": 0, "archived": 0}
    assert counts["journal"] == len(life["journal"])
    assert counts["notes"] == 2 and counts["replies"] == 0
    assert counts["hours"] == 1 and counts["made"] == len(life["studio"]) and counts["carrying"] == 1
    assert counts["beliefs"] == len(life["beliefs"]) and counts["questions"] == life["questions"]["open"]
    assert summary["unread"] == 2
    assert summary["waiting"] == 1, "the agent's question waits on the person"
    assert summary["missing"] is False


def test_waiting_is_the_newest_note_of_each_thread_when_it_is_the_agents_question():
    notes = [
        {"id": "r1", "at": "2026-11-03T10:00:00+00:00", "author": "person", "text": "Yes.", "replyTo": "q1"},
        {"id": "q2", "at": "2026-11-02T10:00:00+00:00", "author": "agent", "text": "Tea or coffee?  ", "replyTo": ""},
        {"id": "q1", "at": "2026-11-01T10:00:00+00:00", "author": "agent", "text": "Move it?", "replyTo": ""},
        {"id": "m1", "at": "2026-11-01T09:00:00+00:00", "author": "agent", "text": "I made a map.", "replyTo": ""},
    ]
    assert [note["id"] for note in person.waiting(notes)] == ["q2"]


def test_the_change_token_holds_still_and_moves_with_what_is_shown(notebook):
    db, ids = notebook
    interface = _here(db)
    try:
        token = lambda: _result(interface, "summary")["change_token"]  # noqa: E731
        first = token()
        assert token() == first == token(), "nothing changed, so neither did the token"
        seen = [first]

        def moved(what: str) -> None:
            now = token()
            assert now not in seen, what
            assert token() == now, f"after {what}, still again"
            seen.append(now)

        _result(interface, "read", note_ids=[ids["made"]])
        moved("a note read")
        _result(interface, "note", text="Back on Thursday.")
        moved("the person's note")
        _result(interface, "correct", memory_id=ids["pier"], text="The ferry leaves at ten now.")
        moved("a correction")
        rt = _runtime(db)
        try:
            rt.capture("The kettle is new.", signed_as=OPUS)
        finally:
            rt.close()
        moved("a memory the agent kept, in another process")
        (Path.home() / ".mnemos" / "studio" / AGENT / "new.png").write_bytes(PNG)
        moved("a picture made")
        _result(interface, "shared", action="add", text="Every agent: the kettle is new.")
        moved("a shared memory added")
    finally:
        interface.close()


# ---------- 4. The person's acts ----------

PAGE_REFUSALS = [
    {"command": "read"}, {"command": "read", "note_ids": []}, {"command": "read", "note_ids": "x"},
    {"command": "read", "note_ids": [" "]}, {"command": "read", "note_ids": ["n"] * 201},
    {"command": "hours", "on": "yes"}, {"command": "hours"}, {"command": "hours", "on": True, "mine": "25:00"},
    {"command": "hours", "on": True, "dream": "8am"}, {"command": "hours", "on": True, "ours": 1900},
    {"command": "shared"}, {"command": "shared", "action": "add", "text": " "},
    {"command": "shared", "action": "add", "text": 7}, {"command": "shared", "action": "forget", "memory_id": "x"},
    {"command": "shared", "action": "forget", "memory_id": "engram_x", "confirmed": True},
    {"command": "shared", "action": "correct", "memory_id": "shared_engram_none", "text": ""},
]


@pytest.mark.parametrize("request_", PAGE_REFUSALS, ids=lambda r: json.dumps(r)[:60])
def test_each_act_is_refused_in_the_pages_own_sentence(notebook, monkeypatch, request_):
    from mnemos import cli

    asked = []
    monkeypatch.setattr(cli, "_cmd_daemon", lambda args: asked.append(args) or 0)
    db, _ = notebook
    server = LogServer(Exporter.for_scope(db_path=str(db), **SCOPE))
    interface = _here(db)
    try:
        on_the_page = server.act(dict(request_))
        here = interface.answer(json.dumps({"id": "x", **request_}))
    finally:
        interface.close()
        server.server_close()
    assert "error" in on_the_page, on_the_page
    assert here == {"id": "x", "error": on_the_page["error"]}
    assert asked == []


def test_read_marks_the_agents_notes_read_once_as_the_page_does(notebook):
    db, ids = notebook
    interface = _here(db)
    try:
        first = _result(interface, "read", note_ids=[ids["made"], ids["question"], "no-such-note"])
        again = _result(interface, "read", note_ids=[ids["made"]])
        notes = _result(interface, "notes")
        summary = _result(interface, "summary")
    finally:
        interface.close()
    assert sorted(first) == sorted([ids["made"], ids["question"]]) and again == []
    assert all(note["read_at"] for note in notes if note["author"] == "agent")
    assert summary["unread"] == 0


def test_read_without_a_store_marks_nothing_and_makes_nothing(tmp_path):
    db = tmp_path / "nothing.db"
    interface = _here(db)
    try:
        assert _result(interface, "read", note_ids=["n1"]) == []
    finally:
        interface.close()
    assert not db.exists()


def test_hours_asks_the_scheduler_exactly_what_the_page_asks(notebook, monkeypatch):
    from mnemos import cli

    asked = []

    def daemon(args):
        asked.append(vars(args).copy())
        print("Scheduled.")
        print("a line for stderr", file=sys.stderr)
        return 0

    monkeypatch.setattr(cli, "_cmd_daemon", daemon)
    db, _ = notebook
    server = LogServer(Exporter.for_scope(db_path=str(db), **SCOPE))
    interface = _here(db)
    try:
        requests = ({"command": "hours", "on": True, "mine": "07:15", "ours": "", "dream": "3:05"},
                    {"command": "hours", "on": False})
        page = [server.act(dict(request)) for request in requests]
        here = [interface.answer(json.dumps(request)) for request in requests]
    finally:
        interface.close()
        server.server_close()
    assert here == [{"id": None, **answer} for answer in page] == [
        {"id": None, "result": "Scheduled."}, {"id": None, "result": "Scheduled."}]
    by_page, by_host = asked[:2], asked[2:]
    assert by_page == by_host
    on, off = by_host
    assert (on["daemon_command"], on["hours"], on["write"]) == ("install", True, True)
    assert (on["mine_at"], on["ours_at"], on["dream_at"]) == ((7, 15), None, (3, 5))
    assert (on["agent_id"], on["person_id"], on["project_scope"], on["db_path"]) == (*SCOPE.values(), str(db))
    assert off["daemon_command"] == "uninstall"


def test_hours_that_cant_be_scheduled_say_why_and_print_nothing(notebook, monkeypatch, capsys):
    from mnemos import cli

    def refuse(args):
        print("No supported scheduler found on this system.", file=sys.stderr)
        return 1

    monkeypatch.setattr(cli, "_cmd_daemon", refuse)
    db, _ = notebook
    interface = _here(db)
    try:
        answer = _ask(interface, "hours", on=True)
    finally:
        interface.close()
    assert answer == {"id": 1, "error": "No supported scheduler found on this system."}
    assert capsys.readouterr() == ("", ""), "what the scheduler said stays off the host's line"


def test_inside_hermes_the_hours_are_left_to_claude_code(notebook, monkeypatch):
    from mnemos import cli, llm

    asked = []
    monkeypatch.setattr(cli, "_cmd_daemon", lambda args: asked.append(args) or 0)
    monkeypatch.setattr(llm, "_host_secrets", lambda name, default=None: default)
    db, _ = notebook
    interface = _here(db)
    try:
        answer = _ask(interface, "hours", on=False)
    finally:
        interface.close()
    assert "Claude Code" in answer["error"] and asked == []


def test_the_shared_notebook_is_added_to_corrected_and_let_go_as_the_person(notebook):
    db, _ = notebook
    interface = _here(db)
    try:
        added = _result(interface, "shared", action="add", text="Every agent: the kettle is new.")
        memory_id = added.split("Shared memory ID: ", 1)[1].split()[0]
        corrected = _result(interface, "shared", action="correct", memory_id=memory_id, text="The kettle is red.")
        rows = _result(interface, "notebook", part="life")["document"]["shared"]["rows"]
        unasked = _ask(interface, "shared", action="forget", memory_id=rows[0]["id"])
        gone = _result(interface, "shared", action="forget", memory_id=rows[0]["id"], confirmed=True)
        after = _result(interface, "notebook", part="life")["document"]["shared"]["rows"]
    finally:
        interface.close()
    assert added.startswith("Saved") and corrected.startswith("Corrected") and gone.startswith("Withdrawn")
    assert [(row["content"], row["person"], row["editable"]) for row in rows] == [("The kettle is red.", True, True)]
    assert unasked["error"] == "Letting a memory go is asked for twice: the page asks first."
    assert after == []


def test_jev_stays_on_the_page_and_no_key_reaches_a_host(notebook, monkeypatch, caplog):
    """Jev's setting takes a key. The interface takes none, says none and
    logs none: a request carrying one is refused as no command, and the key
    saved by the page shows to a host only as "a key is saved"."""
    import logging

    from mnemos import jev

    monkeypatch.delenv("MNEMOS_JEV_KEY_FILE", raising=False)
    caplog.set_level(logging.DEBUG)
    db, _ = notebook
    key_file = Path.home() / ".config" / "jev" / "api_key"
    interface = _here(db)
    try:
        refused = _ask(interface, "jev", key=KEY)
        assert not key_file.exists()
        jev.save_key(KEY)  # as the page's Settings saves it
        answers = [_ask(interface, command, **request) for command, request in (
            ("hello", {}), ("summary", {}), ("notebook", {"part": "life"}), ("notebook", {"part": "memories"}),
            ("notebook", {"part": "pulse"}), ("hours", {"on": "yes", "key": KEY}),
            ("shared", {"action": "add", "text": " ", "key": KEY}))]
    finally:
        interface.close()
    assert refused["error"].startswith('There is no command "jev" here') and KEY not in refused["error"]
    assert "jev" not in COMMANDS
    life = answers[2]["result"]["document"]
    assert life["jev"]["key"] is True
    for answer in [refused, *answers]:
        assert KEY not in json.dumps(answer)
    assert KEY not in caplog.text


# ---------- 5. The two flags ----------

def test_as_person_makes_every_write_the_persons_even_in_an_agents_shell(notebook, tmp_path):
    db, ids = notebook

    def corrected(memory_id: str, *flags: str) -> tuple:
        done = _interface(db, tmp_path, [
            {"id": 1, "command": "hello"},
            {"id": 2, "command": "correct", "memory_id": memory_id, "text": f"New words for {memory_id}."}],
            *flags, CLAUDECODE="1", MNEMOS_AGENT_MODEL=OPUS)
        assert done.returncode == 0, done.stderr
        hello, answer = (json.loads(line) for line in done.stdout.splitlines())
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            row = conn.execute("SELECT author_kind, author_model FROM engrams WHERE id = ?",
                               (answer["result"]["id"],)).fetchone()
        finally:
            conn.close()
        return hello["result"]["writes_as"], tuple(row)

    assert corrected(ids["pier"]) == ("agent", ("agent", OPUS))
    assert corrected(ids["ferry"], "--as-person") == ("person", ("person", ""))


@pytest.mark.parametrize("missing", ["--db-path", "--agent-id", "--person-id", "--project-scope"])
def test_strict_scope_with_a_flag_missing_ends_at_once_with_one_sentence(notebook, tmp_path, missing):
    db, _ = notebook
    given = {"--db-path": str(db), "--agent-id": AGENT, "--person-id": "riley", "--project-scope": "demo"}
    scope = [part for flag, value in given.items() if flag != missing for part in (flag, value)]
    # the environment has every one of them, and is not asked
    done = _interface(db, tmp_path, [{"id": 1, "command": "hello"}], "--strict-scope", scope=scope,
                      MNEMOS_DB_PATH=str(db), MNEMOS_AGENT_ID=AGENT, MNEMOS_PERSON_ID="riley",
                      MNEMOS_PROJECT_SCOPE="demo")
    assert done.returncode == 2
    assert done.stdout == ""
    lines = done.stderr.strip().splitlines()
    assert len(lines) == 1 and lines[0].endswith(f"this is missing {missing}."), done.stderr
    assert lines[0].startswith("--strict-scope takes the memory's scope from all four of")


def test_strict_scope_takes_the_four_flags_over_the_environment_and_the_config(notebook, tmp_path):
    db, _ = notebook
    home = tmp_path / "home"
    (home / ".mnemos").mkdir(parents=True)
    (home / ".mnemos" / "config.json").write_text(json.dumps({
        "agent_id": "elsewhere", "person_id": "someone", "project_scope": "other",
        "store": {"db_path": str(tmp_path / "other.db")}}))
    elsewhere = {"MNEMOS_DB_PATH": str(tmp_path / "env.db"), "MNEMOS_AGENT_ID": "env-agent",
                 "MNEMOS_PERSON_ID": "env-person", "MNEMOS_PROJECT_SCOPE": "env-project"}
    done = _interface(db, home, [{"id": 1, "command": "hello"}, {"id": 2, "command": "memories"}],
                      "--strict-scope", **elsewhere)
    assert done.returncode == 0, done.stderr
    hello, memories = (json.loads(line)["result"] for line in done.stdout.splitlines())
    assert hello["strict_scope"] is True
    assert hello["scope"] == {**SCOPE, "db_path": str(db), "held": True}
    assert memories["counts"]["active"] == 3
    # without the flag, the same flags still win over the environment, as they always have
    done = _interface(db, home, [{"id": 1, "command": "hello"}], **elsewhere)
    assert json.loads(done.stdout)["result"]["scope"]["agent_id"] == AGENT


def test_strict_scope_in_this_process_refuses_to_start_without_all_four(tmp_path):
    from mnemos.interface.person import Refused, serve

    with pytest.raises(Refused, match="missing --person-id, --project-scope"):
        Interface(db_path=str(tmp_path / "m.db"), agent_id=AGENT, strict_scope=True)
    import io

    out, err = io.StringIO(), io.StringIO()
    code = serve(io.StringIO('{"id": 1, "command": "hello"}\n'), out, stderr=err, strict_scope=True,
                 db_path=str(tmp_path / "m.db"), agent_id=AGENT, person_id=" ", project_scope="demo")
    assert (code, out.getvalue()) == (2, "")
    assert err.getvalue().strip().endswith("this is missing --person-id.")


# ---------- One host session ----------

def test_one_process_answers_twenty_mixed_commands_in_order(notebook, tmp_path):
    db, ids = notebook
    requests = [
        {"id": 1, "command": "hello"},
        {"id": 2, "command": "summary"},
        {"id": 3, "command": "notebook", "part": "life"},
        {"id": 4, "command": "memories", "limit": 2},
        {"id": 5, "command": "search", "query": "ferry pier"},
        {"id": "six", "command": "journal"},
        {"id": 7, "command": "notes", "unread": True},
        {"id": 8, "command": "read", "note_ids": [ids["made"]]},
        {"id": 9, "command": "notebook", "part": "memories"},
        {"id": 10, "command": "reply", "note_id": ids["question"], "text": "Yes, move it."},
        {"id": 11, "command": "note", "text": "Back Thursday."},
        {"id": 12, "command": "notebook", "part": "pulse"},
        {"id": 13, "command": "correct", "memory_id": ids["pier"], "text": "The ferry leaves at ten."},
        {"id": 14, "command": "shared", "action": "add", "text": "Every agent: the kettle is new."},
        {"id": 15, "command": "summary"},
        {"id": 16, "command": "jev", "on": True},
        {"id": 17, "command": "forget", "memory_id": ids["gnome"]},
        {"id": 18, "command": "notebook", "part": "nope"},
        {"id": 19, "command": "notes"},
        {"id": 20, "command": "summary"},
    ]
    done = _interface(db, tmp_path, requests)
    assert done.returncode == 0, done.stderr
    answers = [json.loads(line) for line in done.stdout.splitlines()]
    assert [answer["id"] for answer in answers] == [request["id"] for request in requests]
    failed = {answer["id"] for answer in answers if "error" in answer}
    assert failed == {16, 18}, [answers[i - 1] for i in (16, 18)]
    by_id = {answer["id"]: answer.get("result") for answer in answers}
    assert by_id[2]["unread"] == 2 and by_id[15]["unread"] == 0, "read, then answered"
    assert by_id[15]["waiting"] == 0, "the person answered the question"
    assert by_id[20]["counts"]["memories"] == 2 and by_id[20]["change_token"] != by_id[15]["change_token"]
    assert by_id[2]["change_token"] != by_id[15]["change_token"]


# ---------- 6. Reading changes nothing ----------

def _everything(db: Path) -> dict:
    """Every row of every table of the store and of the shared store, and
    every file under ~/.mnemos (but the -wal and -shm beside a store), with
    its size and time."""
    seen: dict = {}
    for name, path in (("store", db), ("shared", Path.home() / ".mnemos" / "shared-memory.db")):
        if not path.exists():
            seen[name] = None
            continue
        conn = open_read_only(path)
        try:
            tables = [row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name")]
            seen[name] = {table: [tuple(row) for row in conn.execute(f'SELECT * FROM "{table}"')]
                          for table in tables}
        finally:
            conn.close()
    files = {}
    for root in (Path.home() / ".mnemos", db.parent):
        for path in sorted(root.rglob("*")) if root.is_dir() else []:
            if path.name.endswith(("-wal", "-shm")) or path.is_dir():
                continue
            stat = path.lstat()
            files[str(path)] = (stat.st_size, stat.st_mtime_ns)
    seen["files"] = files
    return seen


READS = [
    ("memories", {}), ("memories", {"state": "active", "limit": 1}), ("search", {"query": "ferry pier"}),
    ("journal", {}), ("notes", {}), ("notes", {"unread": True}), ("hello", {}),
    ("notebook", {"part": "life"}), ("notebook", {"part": "memories"}), ("notebook", {"part": "pulse"}),
    ("summary", {}),
]


def test_no_read_wakes_marks_or_writes_anything(notebook, tmp_path):
    db, ids = notebook
    interface = _here(db)
    try:
        _result(interface, "shared", action="add", text="Every agent: the kettle is new.")
        rt = _runtime(db)
        try:
            rt.recall("ferry")  # something already came to mind, so a pulse has a trail to read
        finally:
            rt.close()
        for command, request in READS:
            before = _everything(db)
            _result(interface, command, **request)
            assert _everything(db) == before, command
    finally:
        interface.close()
    # and in a process of its own, every read at once
    before = _everything(db)
    done = _interface(db, Path.home(), [{"id": n, "command": c, **r} for n, (c, r) in enumerate(READS)])
    assert done.returncode == 0, done.stderr
    assert all("result" in json.loads(line) for line in done.stdout.splitlines())
    assert _everything(db) == before
