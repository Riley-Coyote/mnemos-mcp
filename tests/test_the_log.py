"""`mnemos log`: a small page to watch an agent's days, on this machine only. It
reads the memory, and writes only the person's own words left on it, and which
of the agent's notes they read there.

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
7. What it writes: a reply or a note in the person's own words, and that a
   note was read, from the page itself only, and nothing else.
8. An agent opens it for the person in one call (``mnemos_page``): the same
   page all session, for the server's own memory, with nothing on stdout.

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
    """No test asks the machine's launchd, systemd or crontab anything."""
    monkeypatch.setattr(log_export, "_launchd_loaded", lambda label: True)
    monkeypatch.setattr(log_export, "_systemd_active", lambda timer: True)
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
        home = server.mind()
        home.documents = (home.documents[0] - log_server.CACHE_SECONDS, home.documents[1])
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
                 "shared/theme.js", "shared/fonts.css", "mind/index.html", "mind/mind.js", "mind/build.js", "engine/tissue.js"):
        assert name in files
    for name, content in files.items():
        if name.endswith((".html", ".js", ".css")):
            # the SVG namespace is a name, never fetched
            text = content.decode("utf-8").replace("http://www.w3.org/2000/svg", "")
            assert not re.search(r"https?://|//fonts\.|@import", text), name
            assert "../warm/" not in text and "open-mind" not in text, name  # Still warm doesn't ship


def test_the_log_has_two_looks_and_the_mind_stays_dark():
    """The look is set before the page draws, so it never flashes the wrong one, and only where it's asked for: the
    stylesheet the mind shares has no light of its own to fall into, whatever the system says."""
    files = page_files()
    log, css = files["log/index.html"].decode("utf-8"), files["shared/room.css"].decode("utf-8")
    assert log.index('src="../shared/theme.js"') < log.index('rel="stylesheet"')
    assert ':root[data-theme="light"]' in css and "prefers-color-scheme" not in css
    assert "theme.js" not in files["mind/index.html"].decode("utf-8")
    assert "theme.js" not in files["mind/mind.js"].decode("utf-8")


def test_every_font_ships_with_its_license():
    files = page_files()
    css = files["shared/fonts.css"].decode("utf-8")
    fonts = re.findall(r"url\(\.\./fonts/([\w.-]+)\)", css)
    assert len(fonts) == 10
    for font in fonts:
        assert f"fonts/{font}" in files, font
    # the mind's light is set in JetBrains Mono, loaded by its script; the stylesheet names it too, for the readings
    # the frame takes off the mind
    assert "fonts/jetbrains-mono-nl.woff" in files and "../fonts/jetbrains-mono-nl.woff" in files["mind/mind.js"].decode("utf-8")
    for family in ("Inter", "InterTight", "Silkscreen", "Newsreader", "JetBrainsMono"):
        license_text = files[f"fonts/OFL-{family}.txt"].decode("utf-8")
        assert "SIL Open Font License" in license_text or "SIL OPEN FONT LICENSE" in license_text, family
    for family in ("Inter", "Inter Tight", "Silkscreen", "Newsreader", "JetBrains Mono"):
        assert f'font-family:"{family}"' in css


# ---------- 7. It writes the person's own words, and what they read ----------
# A reply to one of the agent's notes, or a note of their own, is kept as theirs, and the agent wakes with it
# (`mnemos notes` writes the same); a note of the agent's they read there is marked read. Only the page itself can
# send either, and nothing else can be written through it.

def post(server, body, *, origin="page", kind="application/json", path=None, host=None):
    connection = http.client.HTTPConnection("127.0.0.1", server.port, timeout=10)
    data = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
    headers = {"Host": host or f"127.0.0.1:{server.port}", "Content-Type": kind}
    if origin == "page":
        headers["Origin"] = f"http://127.0.0.1:{server.port}"
    elif origin:
        headers["Origin"] = origin
    try:
        connection.request("POST", path or f"/{server.token}/act", body=data, headers=headers)
        response = connection.getresponse()
        return response.status, json.loads(response.read() or b"null")
    finally:
        connection.close()


def agents_note(server):
    life = json.loads(server.documents()[0])
    [note] = [n for n in life["notes"] if n["author"] == "agent"]
    return note


def test_a_reply_from_the_page_is_kept_as_the_persons_and_shows_at_once(mind):
    with serving(Exporter.for_scope(agent_id=AGENT, person="Riley")) as server:
        note = agents_note(server)
        status, answer = post(server, {"command": "reply", "note_id": note["id"], "text": "Yes, keep it that way."})
        assert status == 200, answer
        assert answer["result"]["text"] == "Yes, keep it that way."
        assert answer["result"]["author"] == "person"
        assert answer["result"]["in_reply_to"] == note["id"]

        life = json.loads(server.documents()[0])        # read again, not the copy from before the reply
        [reply] = [n for n in life["notes"] if n["author"] == "person"]
        assert (reply["text"], reply["replyTo"]) == ("Yes, keep it that way.", note["id"])
        assert agents_note(server)["read"]              # answering a note is reading it


def test_a_note_of_the_persons_own_is_kept_too(mind):
    with serving(Exporter.for_scope(agent_id=AGENT, person="Riley")) as server:
        status, answer = post(server, {"command": "note", "text": "Take tomorrow slowly."})
        assert status == 200, answer
        assert (answer["result"]["author"], answer["result"]["text"]) == ("person", "Take tomorrow slowly.")


def test_nothing_but_the_page_itself_can_write(mind):
    with serving(Exporter.for_scope(agent_id=AGENT, person="Riley")) as server:
        note = agents_note(server)
        reply = {"command": "reply", "note_id": note["id"], "text": "From somewhere else."}
        read = {"command": "read", "note_ids": [note["id"]]}
        for origin in ("", "https://example.com", "http://127.0.0.1:1", "null"):
            assert post(server, reply, origin=origin)[0] == 403, origin
            assert post(server, read, origin=origin)[0] == 403, origin
        assert post(server, reply, host="example.com")[0] == 403                          # another site's name
        assert post(server, reply, path="/not-the-token/act")[0] == 404                  # not this run's page
        assert post(server, reply, kind="text/plain")[0] == 415                          # a plain form can't send it
        assert post(server, b"x" * (33 * 1024))[0] == 413
        assert post(server, b"not json")[0] == 400
        life = json.loads(server.documents()[0])
        assert [n for n in life["notes"] if n["author"] == "person"] == []
        assert not agents_note(server)["read"]


def test_the_page_can_write_nothing_but_what_the_person_does(mind):
    with serving(Exporter.for_scope(agent_id=AGENT, person="Riley")) as server:
        memories = json.loads(server.documents()[1])["memories"]
        target = memories[0]["id"]
        for request in ({"command": "search", "query": "ferry"}, {"command": "memories"}, {"text": "no command"}):
            status, answer = post(server, request)
            assert status == 400 and "nothing else" in answer["error"], request
        # letting a memory go is asked twice: once by the page, and the request says so
        status, answer = post(server, {"command": "forget", "memory_id": target})
        assert status == 400 and "asked for twice" in answer["error"]
        assert [m["id"] for m in json.loads(server.documents()[1])["memories"]] == [m["id"] for m in memories]


def test_a_reply_says_why_when_it_cant_be_kept(mind):
    with serving(Exporter.for_scope(agent_id=AGENT, person="Riley")) as server:
        status, answer = post(server, {"command": "reply", "note_id": "no-such-note", "text": "Hello?"})
        assert status == 400 and answer["error"].startswith("Nothing saved"), answer
        status, answer = post(server, {"command": "note", "text": "   "})
        assert status == 400 and answer["error"], answer


def test_a_note_read_on_the_page_is_marked_read_once(mind):
    """The page says which of its notes the person has read, once they've had
    it on their screen a moment, as `mnemos notes` marks what it shows. Only
    the agent's notes are marked, each once."""
    with serving(Exporter.for_scope(agent_id=AGENT, person="Riley")) as server:
        note = agents_note(server)
        assert not note["read"]
        status, answer = post(server, {"command": "read", "note_ids": [note["id"]]})
        assert (status, answer["result"]) == (200, [note["id"]]), answer
        assert agents_note(server)["read"]                              # read again, at once
        first = agents_note(server)["read"]
        status, answer = post(server, {"command": "read", "note_ids": [note["id"]]})
        assert (status, answer["result"]) == (200, []), answer         # it keeps the time it was first read
        assert agents_note(server)["read"] == first

        status, answer = post(server, {"command": "note", "text": "My own note."})
        mine = answer["result"]["id"]
        assert post(server, {"command": "read", "note_ids": [mine, "no-such-note"]}) == (200, {"result": []})
        for bad in ({"command": "read"}, {"command": "read", "note_ids": []}, {"command": "read", "note_ids": "x"},
                    {"command": "read", "note_ids": [3]}, {"command": "read", "note_ids": ["x"] * 201}):
            status, answer = post(server, bad)
            assert status == 400 and answer["error"], bad


# ---------- 8. An agent opens it for the person ----------
# `mnemos_page` starts the same page from the agent's own MCP server, for that server's memory, so an agent with no
# shell can open it too. Its stdout is the protocol, so it must never write a word there.

def test_an_agent_opens_its_page_in_one_call(mind, capsys):
    from mnemos import simple_mcp

    simple_mcp.configure_runtime(db_path=str(store_path()), agent_id=AGENT)
    try:
        page = simple_mcp.simple_mcp._tool_manager.get_tool("mnemos_page").fn
        first, again = page(), page()
        assert capsys.readouterr().out == ""
        address = first.splitlines()[0]
        assert address == again.splitlines()[0]                       # one page for the session
        assert re.fullmatch(r"Your page is open: http://127\.0\.0\.1:\d+/[\w-]+/log/", address), address
        assert "Nothing is kept here yet" not in first
        url = address.removeprefix("Your page is open: ")
        port, token = re.match(r"http://127\.0\.0\.1:(\d+)/([\w-]+)/", url).groups()
        connection = http.client.HTTPConnection("127.0.0.1", int(port), timeout=10)
        try:
            connection.request("GET", f"/{token}/data/life.json", headers={"Host": f"127.0.0.1:{port}"})
            life = json.loads(connection.getresponse().read())
        finally:
            connection.close()
        assert [n["text"] for n in life["notes"]] == ["The page renders without the network now."]
    finally:
        simple_mcp.configure_runtime()                                 # another memory: the page stops
    with pytest.raises(OSError):
        http.client.HTTPConnection("127.0.0.1", int(port), timeout=2).request("GET", "/")


def test_an_agents_page_says_when_there_is_nothing_yet(capsys):
    from mnemos import simple_mcp

    simple_mcp.configure_runtime(db_path=str(store_path()), agent_id="newcomer")
    try:
        answer = simple_mcp.simple_mcp._tool_manager.get_tool("mnemos_page").fn()
    finally:
        simple_mcp.configure_runtime()
    assert answer.startswith("Your page is open: ") and "Nothing is kept here yet" in answer, answer
    assert not store_path().exists()                                   # opening it made no store
    assert capsys.readouterr().out == ""


# ---------- 8. The quiet hours, on or off, and when ----------
# The one setting that's the person's: whether the agent's quiet hours run, and when. The page asks for exactly what
# `mnemos daemon install --hours --write` (or `uninstall --hours --write`) does for this scope; here the scheduler is
# stood in for, so no test touches the machine's own jobs.

def test_the_page_turns_the_quiet_hours_on_at_its_times_and_off(mind, monkeypatch):
    from mnemos import cli

    asked = []
    monkeypatch.setattr(cli, "_cmd_daemon", lambda args: asked.append(vars(args).copy()) or print("Scheduled.") or 0)
    with serving(Exporter.for_scope(agent_id=AGENT, person="Riley")) as server:
        status, answer = post(server, {"command": "hours", "on": True, "mine": "07:15", "ours": "", "dream": "3:05"})
        assert status == 200, answer
        assert answer["result"] == "Scheduled."
        status, answer = post(server, {"command": "hours", "on": False})
        assert status == 200, answer
    on, off = asked
    assert (on["daemon_command"], on["hours"], on["write"]) == ("install", True, True)
    assert (on["mine_at"], on["ours_at"], on["dream_at"]) == ((7, 15), None, (3, 5))   # an empty time keeps its default
    assert on["agent_id"] == AGENT
    assert (off["daemon_command"], off["hours"], off["write"]) == ("uninstall", True, True)


def test_the_quiet_hours_take_only_a_yes_or_no_and_times_of_day(mind, monkeypatch):
    from mnemos import cli

    asked = []
    monkeypatch.setattr(cli, "_cmd_daemon", lambda args: asked.append(args) or 0)
    with serving(Exporter.for_scope(agent_id=AGENT, person="Riley")) as server:
        for request in ({"command": "hours", "on": "yes"}, {"command": "hours"},
                        {"command": "hours", "on": True, "mine": "25:00"}, {"command": "hours", "on": True, "dream": "8am"},
                        {"command": "hours", "on": True, "ours": 1900}):
            status, answer = post(server, request)
            assert status == 400 and "error" in answer, request
        assert post(server, {"command": "hours", "on": True}, origin="https://example.com")[0] == 403
    assert asked == []


KEY = "ts_live_9f2Q7xK3mP0wZ8yV"


@pytest.fixture
def jev_unset(monkeypatch):
    """Jev as a person finds it: no switch in the environment, its own key file."""
    monkeypatch.delenv("MNEMOS_CUE_JUDGE", raising=False)
    monkeypatch.delenv("MNEMOS_JEV_KEY_FILE", raising=False)
    return Path.home() / ".config" / "jev" / "api_key", Path.home() / ".mnemos" / "config.json"


def test_jev_is_off_until_the_person_saves_a_key_and_turns_it_on(mind, jev_unset, caplog):
    """0.6.0: Jev, the cue's judge, is set in the page's Settings. The key is
    kept private (folder 0700, file 0600) and never said back; the switch is
    "cue_judge" in the config, set and removed with the rest kept."""
    import logging

    from mnemos import jev

    key_path, config = jev_unset
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(json.dumps({"server": {"mode": "simple"}}))
    caplog.set_level(logging.DEBUG)
    with serving(Exporter.for_scope(agent_id=AGENT, person="Riley")) as server:
        assert json.loads(server.documents()[0])["jev"]["on"] is False
        assert post(server, {"command": "jev", "on": True}) == (400, {"error": "Save a key first: without one, Jev can't run."})

        status, answer = post(server, {"command": "jev", "key": f"  {KEY}\n"})
        assert status == 200, answer
        assert KEY not in json.dumps(answer)
        assert key_path.read_text() == KEY + "\n"
        assert oct(key_path.stat().st_mode & 0o777) == "0o600"
        assert oct(key_path.parent.stat().st_mode & 0o777) == "0o700"
        life = json.loads(server.documents()[0])
        assert (life["jev"]["key"], life["jev"]["on"]) == (True, False)
        assert KEY.encode() not in server.documents()[0]
        assert jev.in_use() is False, "a saved key alone turns nothing on"

        assert post(server, {"command": "jev", "on": True}) == (200, {"result": "Jev is on."})
        assert json.loads(config.read_text()) == {"server": {"mode": "simple"}, "cue_judge": "jev"}
        assert jev.in_use() is True
        assert post(server, {"command": "jev", "on": False}) == (200, {"result": "Jev is off."})
        assert json.loads(config.read_text()) == {"server": {"mode": "simple"}}

        post(server, {"command": "jev", "on": True})
        assert post(server, {"command": "jev", "remove_key": True}) == (200, {"result": "The key is removed, and Jev is off."})
        assert not key_path.exists()
        assert json.loads(config.read_text()) == {"server": {"mode": "simple"}}
    assert KEY not in caplog.text


def test_jev_takes_only_a_key_a_removal_or_a_yes_or_no_and_only_from_its_page(mind, jev_unset):
    key_path, config = jev_unset
    with serving(Exporter.for_scope(agent_id=AGENT, person="Riley")) as server:
        for request in ({"command": "jev"}, {"command": "jev", "on": "yes"}, {"command": "jev", "key": ""},
                        {"command": "jev", "key": "two words"}, {"command": "jev", "key": 12345},
                        {"command": "jev", "key": "x" * 513}):
            status, answer = post(server, request)
            assert status == 400 and "error" in answer, request
            assert "two words" not in answer["error"]
        assert post(server, {"command": "jev", "key": KEY}, origin="https://example.com")[0] == 403
    assert not key_path.exists() and not config.exists()


def test_a_config_jev_cant_read_is_left_as_it_is(mind, jev_unset):
    key_path, config = jev_unset
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text("{not json")
    key_path.parent.mkdir(parents=True)
    key_path.write_text(KEY)
    with serving(Exporter.for_scope(agent_id=AGENT, person="Riley")) as server:
        status, answer = post(server, {"command": "jev", "on": True})
    assert status == 400 and "left as it is" in answer["error"], answer
    assert config.read_text() == "{not json"


def test_inside_hermes_the_page_changes_nothing_that_is_claude_codes(mind, jev_unset, monkeypatch):
    """Hermes's plugin rules: a plugin uses no other program's sign-in and keeps
    no key of its own outside Hermes. The quiet hours run `claude -p` on the
    person's own Claude account from the system's scheduler, and Jev's key is a
    file, so the page an agent opens inside Hermes changes neither: both are
    Claude Code's, and set there."""
    from mnemos import cli, llm

    asked = []
    monkeypatch.setattr(cli, "_cmd_daemon", lambda args: asked.append(args.daemon_command) or 0)
    monkeypatch.setattr(llm, "_host_secrets", lambda name, default=None: default)  # Hermes hands out the keys
    key_path, config = jev_unset
    key_path.parent.mkdir(parents=True)
    key_path.write_text(KEY)
    with serving(Exporter.for_scope(agent_id=AGENT, person="Riley")) as server:
        for request in ({"command": "hours", "on": True, "mine": "07:15"}, {"command": "hours", "on": False}):
            status, answer = post(server, request)
            assert status == 400 and "Claude Code" in answer["error"], (request, answer)
        for request in ({"command": "jev", "key": "ts_other_key"}, {"command": "jev", "on": True},
                        {"command": "jev", "on": False}, {"command": "jev", "remove_key": True}):
            status, answer = post(server, request)
            assert status == 400 and "Hermes" in answer["error"], (request, answer)
    assert asked == []
    assert key_path.read_text() == KEY and not config.exists()


@pytest.mark.parametrize("hung_up", [BrokenPipeError, ConnectionResetError])
def test_a_browser_that_hangs_up_mid_answer_ends_quietly(hung_up):
    """A page closed or reloaded while an answer was on its way raised
    BrokenPipeError out of _send, and the server printed a traceback for it."""

    class Gone:
        def write(self, data):
            raise hung_up()

    handler = log_server._Handler.__new__(log_server._Handler)
    handler.wfile, handler.request_version, handler.requestline = Gone(), "HTTP/1.1", "GET / HTTP/1.1"
    handler.command, handler.client_address, handler.close_connection = "GET", ("127.0.0.1", 0), False
    handler._send(200, b"x" * 100_000, "text/plain", True)
    assert handler.close_connection is True
    handler.close_connection = False
    handler._redirect("/elsewhere/")
    assert handler.close_connection is True


def test_a_schedule_that_cant_be_made_says_why(mind, monkeypatch):
    from mnemos import cli

    def refuse(args):
        print("No supported scheduler found on this system.", file=sys.stderr)
        return 1

    monkeypatch.setattr(cli, "_cmd_daemon", refuse)
    with serving(Exporter.for_scope(agent_id=AGENT, person="Riley")) as server:
        status, answer = post(server, {"command": "hours", "on": True})
    assert status == 400
    assert answer["error"] == "No supported scheduler found on this system."


# ---------- 9. Every mind on this machine ----------
# Beside the mind it was started for, the page shows the others that keep their memory in the same folder, one store
# each named for its agent (<agent>.db, as Mnemos makes them), each read from the person and project that hold most of
# its memories, and named by its own name. A store that pools several agents names no one, and is left out.

def other_mind(agent: str, person_id: str, texts: list[str]) -> Path:
    db = Path.home() / ".mnemos" / f"{agent}.db"
    rt = MnemosRuntime(db_path=str(db), agent_id=agent, person_id=person_id, use_dedicated_model=False)
    try:
        for text in texts:
            rt.capture(text, signed_as=OPUS)
    finally:
        rt.close()
    return db


def get(server, path):
    connection = http.client.HTTPConnection("127.0.0.1", server.port, timeout=10)
    try:
        connection.request("GET", f"/{server.token}/{path}", headers={"Host": f"127.0.0.1:{server.port}"})
        response = connection.getresponse()
        return response.status, json.loads(response.read() or b"null")
    finally:
        connection.close()


def test_the_page_finds_every_mind_beside_its_own_and_reads_each(mind):
    other_mind("anima", "riley", ["The garden needs the north light.", "Sonnet's last question is still open."])
    pooled = Path.home() / ".mnemos" / "shared.db"
    rt = MnemosRuntime(db_path=str(pooled), agent_id="someone-else", use_dedicated_model=False)
    try:
        rt.capture("A pool of many agents, under no one's name.", signed_as=OPUS)
    finally:
        rt.close()
    with serving(Exporter.for_scope(agent_id=AGENT, person="Riley")) as server:
        status, listed = get(server, "data/minds.json")
        assert status == 200
        minds = {m["agentId"]: m for m in listed["minds"]}
        assert list(minds) == [AGENT, "anima"]                       # its own first; the pool names no one
        assert minds[AGENT]["home"] and not minds["anima"]["home"]
        assert minds[AGENT]["name"] == "Opus 5.5"                     # its own: named by the model that signs it
        assert minds["anima"]["name"] == "Anima"                      # another: by its own name
        assert minds["anima"]["memories"] == 2                        # read from the person who holds its memories

        status, memories = get(server, "data/memories.json?agent=anima")
        assert status == 200
        assert {m["content"] for m in memories["memories"]} == {"The garden needs the north light.",
                                                                 "Sonnet's last question is still open."}
        assert get(server, "data/life.json?agent=no-such-mind")[0] == 404
        assert get(server, "data/life.json?agent=shared")[0] == 404


def test_a_note_left_for_another_mind_goes_to_that_mind(mind):
    db = other_mind("anima", "riley", ["The garden needs the north light."])
    with serving(Exporter.for_scope(agent_id=AGENT, person="Riley")) as server:
        status, answer = post(server, {"command": "note", "text": "For Anima."}, path=f"/{server.token}/act?agent=anima")
        assert status == 200, answer
        status, answer = post(server, {"command": "note", "text": "For no one."}, path=f"/{server.token}/act?agent=nobody")
        assert status == 400 and "no such mind" in answer["error"]
        anima = json.loads(server.documents("anima")[0])
        assert [n["text"] for n in anima["notes"] if n["author"] == "person"] == ["For Anima."]
        own = json.loads(server.documents()[0])
        assert [n for n in own["notes"] if n["author"] == "person"] == []
    assert db.is_file()


# ---------- 10. What comes to mind, as it comes, and what a question finds ----------
# The mind page asks every second or so what came to the mind since it last looked: what a recall brought back or a
# capture kept (memory_trace, one row a call) and what the cue offered with a message (its session files under
# ~/.mnemos/run). And it asks the memory by meaning and by words, as `mnemos search` does. Both only read.

def test_the_pulse_says_what_a_recall_brought_back_and_what_the_cue_offered(mind):
    from mnemos.cue import run_dir, scope_key

    before = datetime.now(timezone.utc).isoformat()
    rt = runtime()
    try:
        rt.recall("the ferry timetable")
    finally:
        rt.close()
    exporter = Exporter.for_scope(agent_id=AGENT, person="Riley")
    memories = json.loads(LogServer(exporter).documents()[1])["memories"]
    ferry = next(m["id"] for m in memories if "ferry" in m["content"])
    scope = exporter.scope
    folder = run_dir()
    folder.mkdir(parents=True, exist_ok=True)
    offered_at = datetime.now(timezone.utc).isoformat()
    (folder / f"shown-sess1-{scope_key(scope.db_path, scope.agent_id, scope.person_id, scope.project_scope)}.json").write_text(
        json.dumps({"session": "sess1", "offers": [{"at": offered_at, "ids": [ferry], "via": "words"}]}))
    sealed = digest(store_path())
    with serving(exporter) as server:
        status, pulse = get(server, f"data/pulse.json?since={before}")
        assert status == 200
        kinds = {(e["kind"], tuple(e["ids"])) for e in pulse["events"]}
        assert any(kind == "recall" and ferry in ids for kind, ids in kinds), pulse
        assert ("cue", (ferry,)) in kinds
        assert pulse["now"] >= offered_at
        keys = [e["key"] for e in pulse["events"]]
        assert len(keys) == len(set(keys))
        # asked again from later on, nothing that came before is said again
        status, later = get(server, f"data/pulse.json?since={pulse['now']}")
        assert status == 200 and later["events"] == []
        assert get(server, "data/pulse.json?agent=nobody")[0] == 404
    assert digest(store_path()) == sealed                         # it only read


def test_a_question_finds_memories_and_changes_nothing(mind):
    sealed = digest(store_path())
    with serving(Exporter.for_scope(agent_id=AGENT, person="Riley")) as server:
        status, found = get(server, "data/search.json?q=ferry%20timetable")
        assert status == 200
        assert found["results"] and "ferry" in found["results"][0]["words"]
        assert {"id", "words", "kept", "closeness", "found"} <= set(found["results"][0])
        status, empty = get(server, "data/search.json?q=")
        assert status == 200 and empty["results"] == []
        assert get(server, "data/search.json?q=x&agent=nobody")[0] == 404
    assert digest(store_path()) == sealed



# ---------- 11. A memory corrected in the person's words, or let go ----------
# From the page, a correction or a forget is always the person's: their words unsigned, the memory archived as theirs
# to let go, and the agent told once. That holds when an agent's own server serves the page (its process carries
# CLAUDECODE), which is exactly when the command line would call it the agent's.

def test_a_memory_corrected_on_the_page_is_the_persons_even_from_an_agents_server(mind, monkeypatch):
    monkeypatch.setenv("CLAUDECODE", "1")                     # an agent's shell, as mnemos_page serves from
    with serving(Exporter.for_scope(agent_id=AGENT, person="Riley")) as server:
        memories = json.loads(server.documents()[1])["memories"]
        ferry = next(m for m in memories if "ferry" in m["content"])
        status, answer = post(server, {"command": "correct", "memory_id": ferry["id"], "text": "The 7:55 is the 8:05 now."})
        assert status == 200, answer
        after = json.loads(server.documents()[1])["memories"]
        corrected = next(m for m in after if m["content"] == "The 7:55 is the 8:05 now.")
        assert corrected["author"] == "person" and not corrected["model"]
        assert ferry["id"] not in {m["id"] for m in after}


def test_a_memory_let_go_on_the_page_is_archived_as_the_persons(mind, monkeypatch):
    monkeypatch.setenv("CLAUDECODE", "1")
    with serving(Exporter.for_scope(agent_id=AGENT, person="Riley")) as server:
        memories = json.loads(server.documents()[1])["memories"]
        target = next(m for m in memories if "read-only" in m["content"])
        status, answer = post(server, {"command": "forget", "memory_id": target["id"], "confirmed": True})
        assert status == 200, answer
        assert answer["result"]["state"] == "archived"
        assert target["id"] not in {m["id"] for m in json.loads(server.documents()[1])["memories"]}
    import sqlite3

    conn = sqlite3.connect(f"file:{store_path()}?mode=ro", uri=True)
    try:
        row = conn.execute("SELECT state FROM engrams WHERE id = ?", (target["id"],)).fetchone()
        reason = conn.execute("SELECT archive_reason FROM archive WHERE id = ?", (target["id"],)).fetchone()
    finally:
        conn.close()
    assert row[0] == "archived"
    assert reason and reason[0] == "forgotten_by_person"      # the person's, not the agent's, though an agent served it


def test_shared_acts_have_the_pages_guards_and_export_separate_rows(mind, monkeypatch):
    from mnemos import shared_memory as sm
    monkeypatch.setenv("MNEMOS_SHARED_MEMORY_DB", str(Path.home() / "shared-memory.db"))
    monkeypatch.delenv("MNEMOS_SHARED_MEMORY", raising=False)
    with serving(Exporter.for_scope(**SCOPE)) as server:
        request = {"command": "shared", "action": "add", "text": "Words for every agent."}
        assert post(server, request, origin="https://elsewhere.example")[0] == 403
        assert post(server, request, kind="text/plain")[0] == 415
        assert not sm.path().exists()
        status, answer = post(server, request)
        assert status == 200 and "result" in answer
        life, memories = map(json.loads, server.documents())
        assert life["shared"]["rows"][0]["content"] == request["text"]
        assert life["shared"]["rows"][0]["person"]
        assert all(m["content"] != request["text"] for m in memories["memories"])
