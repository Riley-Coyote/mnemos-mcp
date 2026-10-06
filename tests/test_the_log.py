"""`mnemos log`: a small page to watch an agent's days, read-only, on this
machine only.

What these tests hold:

1. The export: from a store written with the package's own tools (captures,
   journal entries, a note, a quiet hour and its record), the page's two
   documents carry the right days, named as Mnemos names the mind.
2. It never writes: the store file's hash is the same after an export, nothing
   appears beside it, and with no store it makes none.
3. Whose memory: the scope every other command resolves, defaults included.
4. Whether the hours are scheduled, said plainly either way.
5. The server: the page and both documents, on 127.0.0.1 only, and nothing
   for another host, a request without the run's path, or a path out of the
   studio.
6. The page asks nothing of the network, and ships inside the package with its
   fonts' licenses.

No test reaches a real network, a real scheduler or a real ~/.mnemos.
"""

from __future__ import annotations

import hashlib
import http.client
import json
import os
import plistlib
import re
import signal
import subprocess
import sys
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from mnemos.cli import main
from mnemos.companion import export as log_export
from mnemos.companion import server as log_server
from mnemos.companion.export import Exporter
from mnemos.companion.server import LogServer, page_files
from mnemos.simple_runtime import MnemosRuntime
from mnemos.store.sqlite_store import EngramStore

AGENT = "test-agent"
OPUS = "claude-opus-5-5"
SCOPE = {"agent_id": AGENT, "person_id": "user", "project_scope": "global"}
HOUR = "01K6WQTESTHOUR000000000001"
ENGRAM = re.compile(r"engram_[0-9A-Z]{26}")
# A 1x1 PNG.
PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000d49444154789c6360f8cfc00000030101005d9d7cd30000000049454e44ae426082"
)


@pytest.fixture(autouse=True)
def no_real_scheduler(monkeypatch):
    """No test asks the machine's launchd or crontab anything."""
    monkeypatch.setattr(log_export, "_launchd_loaded", lambda label: True)
    monkeypatch.setattr(log_export, "_crontab", lambda: "")


def interrupted(self, poll_interval=0.5):
    """Serving, then Ctrl-C at once."""
    raise KeyboardInterrupt


def store_path() -> Path:
    """Where the agent's store is by default: ~/.mnemos/<agent>.db, in the test's own home."""
    return Path.home() / ".mnemos" / f"{AGENT}.db"


def runtime(db: Path | None = None) -> MnemosRuntime:
    return MnemosRuntime(db_path=str(db) if db else None, agent_id=AGENT, use_dedicated_model=False)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def mind(monkeypatch):
    """A store with a few days in it, written with Mnemos's own tools: three
    captures, two journal entries, a note, and one quiet hour that wrote in
    the journal, made a picture and left its record."""
    rt = runtime()
    try:
        ids = [ENGRAM.search(rt.capture(text, impact=impact, signed_as=OPUS)).group(0) for text, impact in (
            ("The ferry timetable changed: the 7:40 is now the 7:55.", "Check timetables first."),
            ("Riley prefers plain, everyday words.", "Write for the person."),
            ("The log stays read-only.", ""),
        )]
        rt.journal("I keep noticing how much of the work is deciding what not to build.\n\nThe smallest true "
                   "version first.", signed_as=OPUS, mood="settled")
        rt.journal("Spent the afternoon on the read-only path.", signed_as=OPUS)
        rt.note("The page renders without the network now.", "made", signed_as=OPUS)
    finally:
        rt.close()

    now = datetime.now(timezone.utc)
    start, end = now - timedelta(hours=1), now - timedelta(minutes=20)
    monkeypatch.setenv("MNEMOS_HOUR_ID", HOUR)
    rt = runtime()
    try:
        rt.journal("The hour was quiet. I drew the week as a map.", signed_as=OPUS, mood="quiet")
    finally:
        rt.close()
    monkeypatch.delenv("MNEMOS_HOUR_ID")
    reader = EngramStore(store_path())
    try:
        written = reader.hour_rows(HOUR, **SCOPE)
    finally:
        reader.close()

    hours = Path.home() / ".mnemos" / "hours" / AGENT
    folder = hours / HOUR
    folder.mkdir(parents=True)
    (folder / "prompt.md").write_text(f"Open questions\n- What did it teach? [{ids[0]}]\n")
    events = [
        {"type": "system", "subtype": "hook_response", "output": f"waking [{ids[1]}]"},
        {"type": "assistant", "message": {"model": OPUS, "content": [
            {"type": "tool_use", "id": "t1", "name": "mcp__mnemos__mnemos_recall", "input": {"query": "read-only"}},
            {"type": "tool_use", "id": "t2", "name": "WebFetch", "input": {"url": "https://example.com"}}]}},
        {"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "t1", "content": f"found [{ids[2]}]"},
            {"type": "tool_result", "tool_use_id": "t2", "content": "Permission to use WebFetch was denied."}]}},
        {"type": "result", "result": "A quiet hour; I drew the week."},
    ]
    (folder / "stream.jsonl").write_text("\n".join(json.dumps(e) for e in events) + "\nnot json\n")
    record = {"id": HOUR, "kind": "mine", "started_at": start.isoformat(), "ended_at": end.isoformat(),
              "model": OPUS, "status": "done", "reason": "", "tokens": None, "store": "live",
              "journal_ids": written["journal_ids"], "note_ids": written["note_ids"], "since": "",
              "waiting": {"handoffs": 0, "captures": 0, "questions": 1}, "discarded_ids": []}
    (hours / "hours.jsonl").write_text("not json\n" + json.dumps({"id": "../escape", "kind": "mine"}) + "\n"
                                       + json.dumps(record) + "\n")

    picture = Path.home() / ".mnemos" / "studio" / AGENT / "maps" / "the-week.png"
    picture.parent.mkdir(parents=True)
    picture.write_bytes(PNG)
    made = (start + timedelta(minutes=10)).timestamp()
    os.utime(picture, (made, made))
    return {"ids": ids, "written": written}


# ── 1. The export ──


def test_the_export_carries_the_minds_days(mind):
    life, memories = Exporter.for_scope(agent_id=AGENT, person="Riley").export()

    who = life["identity"]
    assert who["name"] == "Opus 5.5"  # named the way Mnemos names the model that signs its memories
    assert who["agentId"] == AGENT and who["person"] == "Riley"
    assert who["store"] == f"~/.mnemos/{AGENT}.db"

    journal = life["journal"]
    assert [entry["text"] for entry in journal][1:] == [
        "Spent the afternoon on the read-only path.",
        "I keep noticing how much of the work is deciding what not to build.\n\nThe smallest true version first.",
    ]
    assert journal[2]["mood"] == "settled" and journal[2]["written"] == "in_conversation"
    assert journal[0]["hour"] == HOUR and journal[0]["written"] == "between_sessions"
    assert [(n["kind"], n["author"], n["text"]) for n in life["notes"]] == [
        ("made", "agent", "The page renders without the network now.")]

    [hour] = life["hours"]  # the malformed line and the id that would leave the folder are passed over
    assert hour["id"] == HOUR and hour["kind"] == "mine" and not hour["practice"]
    assert hour["minutes"] == 40.0 and hour["modelName"] == "Opus 5.5"
    assert [entry["text"] for entry in hour["journal"]] == ["The hour was quiet. I drew the week as a map."]
    assert hour["said"] == "A quiet hour; I drew the week."
    assert hour["refused"] == ["WebFetch"]
    ids = mind["ids"]
    assert hour["trail"] == {"woke": [ids[1]], "waiting": [ids[0]], "reached": [ids[2]]}
    assert hour["made"] == ["maps/the-week.png"]
    assert life["studio"][0]["picture"] == "../data/studio/maps/the-week.png"

    assert life["schedule"] == []
    assert life["memory"]["count"] == len(memories["memories"]) == 3
    assert {m["content"] for m in memories["memories"]} == {
        "The ferry timetable changed: the 7:40 is now the 7:55.",
        "Riley prefers plain, everyday words.",
        "The log stays read-only.",
    }
    assert life["memory"]["version"] == memories["version"]


def test_the_memories_version_changes_only_with_the_memories(mind):
    exporter = Exporter.for_scope(agent_id=AGENT)
    first = exporter.export()[1]["version"]
    assert exporter.export()[1]["version"] == first
    rt = runtime()
    try:
        rt.capture("A fourth memory.", signed_as=OPUS)
    finally:
        rt.close()
    assert exporter.export()[1]["version"] != first


def test_the_persons_name_comes_from_the_flag_or_the_environment(mind, monkeypatch):
    assert Exporter.for_scope(agent_id=AGENT).export()[0]["identity"]["person"] is None  # the page says "you"
    monkeypatch.setenv("MNEMOS_PERSON_NAME", "  Sam  ")
    assert Exporter.for_scope(agent_id=AGENT).export()[0]["identity"]["person"] == "Sam"
    assert Exporter.for_scope(agent_id=AGENT, person="Riley").export()[0]["identity"]["person"] == "Riley"


def test_a_practice_hour_is_read_from_its_copy(mind, monkeypatch):
    """A practice hour wrote in a copy of the store; its words are read from
    the copy, read-only, and are not in the real memory."""
    hours = Path.home() / ".mnemos" / "hours" / AGENT
    practice = "01K6WQPRACTICEHOUR00000001"
    copy = hours / practice / "store.db"
    copy.parent.mkdir()
    EngramStore(copy).close()
    monkeypatch.setenv("MNEMOS_HOUR_ID", practice)
    rt = runtime(copy)
    try:
        rt.journal("Practice, on a copy.", signed_as=OPUS)
    finally:
        rt.close()
    monkeypatch.delenv("MNEMOS_HOUR_ID")
    before = digest(copy)
    now = datetime.now(timezone.utc).isoformat()
    with (hours / "hours.jsonl").open("a") as records:
        records.write(json.dumps({"id": practice, "kind": "ours", "started_at": now, "ended_at": now,
                                  "status": "done", "store": "copy", "journal_ids": ["x"],
                                  "live_store_untouched": True}) + "\n")

    life = Exporter.for_scope(agent_id=AGENT).export()[0]

    hour = life["hours"][0]
    assert hour["practice"] and hour["untouched"] is True and hour["check"] == "rows"
    assert [entry["text"] for entry in hour["journal"]] == ["Practice, on a copy."]
    assert "Practice, on a copy." not in [entry["text"] for entry in life["journal"]]
    assert digest(copy) == before


# ── 2. It never writes ──


def test_an_export_leaves_the_store_exactly_as_it_was(mind):
    store = store_path()
    beside = sorted(p.name for p in store.parent.iterdir())
    before = digest(store)

    Exporter.for_scope(agent_id=AGENT).export()

    assert digest(store) == before
    # A store no one has open has no -wal or -shm beside it; reading it makes none.
    assert sorted(p.name for p in store.parent.iterdir()) == beside


def test_an_export_through_the_server_leaves_the_store_as_it_was(mind):
    before = digest(store_path())
    with serving(Exporter.for_scope(agent_id=AGENT)) as server:
        for name in ("life.json", "memories.json"):
            assert fetch(server, f"data/{name}")[0] == 200
    assert digest(store_path()) == before


def test_a_store_in_use_is_read_with_its_latest_writes(mind):
    """With a writer holding the store open (its -wal beside it), the export
    still reads every committed write, and writes nothing itself."""
    writer = runtime()
    try:
        writer.capture("Written while the log was reading.", signed_as=OPUS)
        assert Path(f"{store_path()}-wal").exists()
        memories = Exporter.for_scope(agent_id=AGENT).export()[1]["memories"]
        assert "Written while the log was reading." in [m["content"] for m in memories]
    finally:
        writer.close()


def test_no_store_is_said_plainly_and_none_is_made():
    life, memories = Exporter.for_scope(agent_id="nobody").export()
    assert life["missing"] is True
    assert life["identity"]["name"] == "nobody"
    assert life["identity"]["store"] == "~/.mnemos/nobody.db"
    assert memories["memories"] == []
    assert not (Path.home() / ".mnemos" / "nobody.db").exists()


# ── 3. Whose memory ──


def test_the_log_finds_the_memory_the_way_every_command_does(mind, monkeypatch, capsys):
    """With no flags at all: the agent from ~/.mnemos/config.json, and its
    store where Mnemos keeps it by default."""
    (Path.home() / ".mnemos" / "config.json").write_text(json.dumps({"agent_id": AGENT}))
    monkeypatch.setattr(LogServer, "serve_forever", interrupted)
    opened = []
    monkeypatch.setattr(log_server.webbrowser, "open", lambda url: opened.append(url))

    assert main(["log"]) == 0

    out = capsys.readouterr().out
    url = re.search(r"http://127\.0\.0\.1:\d+/[\w-]+/log/", out).group(0)
    assert out.startswith(f"The log of Opus 5.5: {url}")
    assert "Ctrl-C stops it." in out and out.rstrip().endswith("Stopped.")
    assert opened == [url]


def test_no_open_prints_the_address_and_opens_nothing(mind, monkeypatch, capsys):
    monkeypatch.setattr(LogServer, "serve_forever", interrupted)
    monkeypatch.setattr(log_server.webbrowser, "open", lambda url: pytest.fail("opened a browser"))
    assert main(["log", "--no-open", "--agent-id", AGENT, "--db-path", str(store_path())]) == 0
    assert "The log of Opus 5.5: http://127.0.0.1:" in capsys.readouterr().out


def test_an_agent_with_no_memory_yet_is_told_how_to_find_it(monkeypatch, capsys):
    monkeypatch.setattr(LogServer, "serve_forever", interrupted)
    assert main(["log", "--no-open", "--agent-id", "newcomer"]) == 0
    out = capsys.readouterr().out
    assert "There's no memory at ~/.mnemos/newcomer.db for newcomer yet" in out
    assert "--agent-id" in out
    assert not (Path.home() / ".mnemos").exists()


# ── 4. Whether the hours are scheduled ──


def launch_agent(name: str, args: list[str], **extra) -> None:
    folder = Path.home() / "Library" / "LaunchAgents"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{name}.plist").write_bytes(plistlib.dumps({"Label": name, "ProgramArguments": args, **extra}))


def test_a_launch_agent_that_runs_the_hours_is_its_schedule(mind):
    launch_agent("world.test.hours", ["/usr/local/bin/mnemos", "--agent-id", AGENT, "life", "--hour", "mine"],
                 StartCalendarInterval={"Hour": 3, "Minute": 30})
    launch_agent("world.test.other", ["/usr/local/bin/mnemos", "--agent-id", "someone-else", "life", "--hour", "mine"])
    launch_agent("world.test.mentions", ["/bin/sh", "-c", "claude -p 'think about life'"])
    launch_agent("world.test.hourly", ["mnemos", "--agent-id", AGENT, "life", "--hour=ours"],
                 StartCalendarInterval={"Minute": 15})
    (Path.home() / "Library" / "LaunchAgents" / "broken.plist").write_text("not a plist")

    schedule = Exporter.for_scope(agent_id=AGENT).export()[0]["schedule"]

    assert schedule == [
        {"label": "world.test.hourly", "when": None, "kind": "ours", "loaded": True},
        {"label": "world.test.hours", "when": {"Hour": 3, "Minute": 30}, "kind": "mine", "loaded": True},
    ]


def test_a_crontab_line_that_runs_the_hours_is_its_schedule(mind, monkeypatch):
    monkeypatch.setattr(log_export, "_crontab", lambda: (
        "# 0 4 * * * mnemos --agent-id test-agent life --hour mine\n"
        "30 2 * * * /opt/bin/mnemos --agent-id test-agent life --hour mine >> /tmp/x.log 2>&1\n"
        "*/30 * * * * mnemos --agent-id test-agent life --hour ours\n"
        "0 5 * * * mnemos --agent-id another life --hour mine\n"
    ))
    assert Exporter.for_scope(agent_id=AGENT).export()[0]["schedule"] == [
        {"label": "crontab", "when": {"Hour": 2, "Minute": 30}, "kind": "mine", "loaded": True},
        {"label": "crontab", "when": None, "kind": "ours", "loaded": True},
    ]


def test_no_schedule_is_an_empty_list(mind):
    """The page reads an empty schedule as "hours not scheduled"."""
    assert Exporter.for_scope(agent_id=AGENT).export()[0]["schedule"] == []


# ── 5. The server ──


class serving:
    """A LogServer answering on a thread for the length of a with-block."""

    def __init__(self, exporter: Exporter) -> None:
        self.server = LogServer(exporter)

    def __enter__(self) -> LogServer:
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        return self.server

    def __exit__(self, *exc) -> None:
        self.server.shutdown()
        self.server.server_close()


def fetch(server: LogServer, rel: str, *, host: str | None = None, prefix: str | None = None):
    connection = http.client.HTTPConnection("127.0.0.1", server.port, timeout=10)
    try:
        path = f"/{server.token}/{rel}" if prefix is None else f"{prefix}{rel}"
        connection.request("GET", path, headers={"Host": host or f"127.0.0.1:{server.port}"})
        response = connection.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    finally:
        connection.close()


def test_the_server_serves_the_page_and_its_data_on_this_machine_only(mind):
    with serving(Exporter.for_scope(agent_id=AGENT, person="Riley")) as server:
        assert server.server_address[0] == "127.0.0.1"
        assert server.socket.getsockname()[0] == "127.0.0.1"
        assert server.url == f"http://127.0.0.1:{server.port}/{server.token}/log/"

        status, headers, body = fetch(server, "log/")
        assert status == 200 and headers["Content-Type"].startswith("text/html")
        assert b'<script type="module" src="log.js">' in body
        assert "default-src 'none'" in headers["Content-Security-Policy"]
        for rel, kind in (("log/log.js", "text/javascript"), ("shared/room.js", "text/javascript"),
                          ("shared/room.css", "text/css"), ("shared/fonts.css", "text/css"),
                          ("fonts/inter-latin-wght-normal.woff2", "font/woff2")):
            status, headers, _ = fetch(server, rel)
            assert (status, headers["Content-Type"].split(";")[0]) == (200, kind), rel

        status, headers, body = fetch(server, "data/life.json")
        assert status == 200 and headers["Cache-Control"] == "no-store"
        life = json.loads(body)
        assert life["identity"]["name"] == "Opus 5.5" and life["identity"]["person"] == "Riley"
        status, _, body = fetch(server, "data/memories.json")
        assert status == 200 and json.loads(body)["version"] == life["memory"]["version"]

        status, headers, body = fetch(server, "data/studio/maps/the-week.png")
        assert (status, headers["Content-Type"], body) == (200, "image/png", PNG)
        assert "sandbox" in headers["Content-Security-Policy"]

        # The page's own address, by name, works as well.
        assert fetch(server, "log/", host=f"localhost:{server.port}")[0] == 200
        assert fetch(server, "", prefix=f"/{server.token}")[0] == 302


def test_the_server_answers_no_one_else(mind):
    (Path.home() / ".mnemos" / "secret.png").write_bytes(PNG)
    with serving(Exporter.for_scope(agent_id=AGENT)) as server:
        # another site whose name now points here (DNS rebinding)
        assert fetch(server, "data/life.json", host=f"evil.example:{server.port}")[0] == 403
        # without the path this run made
        assert fetch(server, "data/life.json", prefix="/")[0] == 404
        assert fetch(server, "data/life.json", prefix="/not-the-token/")[0] == 404
        # out of the studio, plainly or encoded
        for rel in ("data/studio/../../secret.png", "data/studio/..%2F..%2Fsecret.png",
                    f"data/studio/../../{AGENT}.db", "data/studio/maps/missing.png",
                    "data/studio/.hidden.png", "../../etc/passwd"):
            assert fetch(server, rel)[0] == 404, rel


def test_the_documents_are_kept_a_few_seconds(mind, monkeypatch):
    exporter = Exporter.for_scope(agent_id=AGENT)
    calls = []
    real = exporter.export
    monkeypatch.setattr(exporter, "export", lambda: calls.append(1) or real())
    server = LogServer(exporter)
    try:
        first = server.documents()
        assert server.documents() == first and len(calls) == 1
        server._documents = (server._documents[0] - log_server.CACHE_SECONDS, server._documents[1])
        server.documents()
        assert len(calls) == 2
    finally:
        server.server_close()


@pytest.mark.skipif(sys.platform == "win32", reason="Ctrl-C is a POSIX signal here")
def test_mnemos_log_runs_until_ctrl_c(mind, tmp_path):
    """The command itself, in its own process: it prints the address, serves
    the data there, and Ctrl-C stops it cleanly. Its PATH holds no crontab, so
    it asks the machine's scheduler nothing."""
    (tmp_path / "empty-path").mkdir()
    env = {**os.environ, "PYTHONUNBUFFERED": "1", "PATH": str(tmp_path / "empty-path")}
    proc = subprocess.Popen(
        [sys.executable, "-m", "mnemos.cli", "log", "--no-open", "--agent-id", AGENT],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env,
    )
    timer = threading.Timer(60, proc.kill)
    timer.start()
    try:
        first = proc.stdout.readline()
        url = re.search(r"http://127\.0\.0\.1:\d+/[\w-]+/log/", first).group(0)
        port, token = re.search(r":(\d+)/([\w-]+)/log/", url).groups()
        connection = http.client.HTTPConnection("127.0.0.1", int(port), timeout=10)
        try:
            connection.request("GET", f"/{token}/data/life.json")
            assert json.loads(connection.getresponse().read())["identity"]["name"] == "Opus 5.5"
        finally:
            connection.close()
        proc.send_signal(signal.SIGINT)
        out, err = proc.communicate(timeout=30)
    finally:
        timer.cancel()
        if proc.poll() is None:
            proc.kill()
    assert proc.returncode == 0, err
    assert out.rstrip().endswith("Stopped.")


# ── 6. The page ──


def test_the_page_asks_nothing_of_the_network():
    files = page_files()
    for name in ("log/index.html", "log/log.js", "shared/room.js", "shared/room.css", "shared/words.js",
                 "shared/fonts.css"):
        assert name in files
    for name, content in files.items():
        if name.endswith((".html", ".js", ".css")):
            text = content.decode("utf-8")
            assert not re.search(r"https?://|//fonts\.|@import", text), name
            assert "../warm/" not in text and "open-mind" not in text, name  # Still warm doesn't ship


def test_every_font_ships_with_its_license():
    files = page_files()
    css = files["shared/fonts.css"].decode("utf-8")
    fonts = re.findall(r"url\(\.\./fonts/([\w.-]+)\)", css)
    assert len(fonts) == 6
    for font in fonts:
        assert f"fonts/{font}" in files, font
    for family in ("Inter", "InterTight", "CormorantGaramond", "Silkscreen"):
        license_text = files[f"fonts/OFL-{family}.txt"].decode("utf-8")
        assert "SIL Open Font License" in license_text or "SIL OPEN FONT LICENSE" in license_text, family
    for family in ("Inter", "Inter Tight", "Cormorant Garamond", "Silkscreen"):
        assert f'font-family:"{family}"' in css
