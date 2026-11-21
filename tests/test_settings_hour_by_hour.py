"""The page's Settings, hour by hour (QH-4, November 2026).

Until now the page had one switch for all three quiet hours and their start
times, and saving a time scheduled all three again. Now each hour is its own
row: on or off by itself, and while it's on, when it starts, how long it may
last and (its own hour and our hour) whether it may go online. One Save sends
only what changed, and it goes through the one way the hours change
(``cli._hours_plan`` and ``cli._hours_apply``), keeping that the person
answered. The older request (one ``on`` and three times) still works.

Inside Hermes the hours are Hermes's own scheduled jobs: the page shows them as
Hermes has them, only to read, from the profile it was opened for.

Every scheduler here is the suite's fake (tests/conftest.py).
"""

from __future__ import annotations

import http.client
import json
import threading
from pathlib import Path

import pytest

from mnemos.companion.export import Exporter
from mnemos.companion.server import LogServer
from mnemos.setup import scheduler, state
from mnemos.simple_runtime import MnemosRuntime

AGENT = "nova"
SCOPE = {"agent_id": AGENT, "person_id": "riley", "project_scope": "demo"}
MINE, OURS, DREAM = (f"com.mnemos.{AGENT}.hour-{kind}" for kind in ("mine", "ours", "dream"))


@pytest.fixture
def launchd(monkeypatch, os_scheduler):
    monkeypatch.setattr(scheduler, "detect_backend", lambda system=None: "launchd")
    return os_scheduler


@pytest.fixture
def claude(tmp_path, monkeypatch) -> Path:
    folder = tmp_path / "local-bin"
    folder.mkdir()
    binary = folder / "claude"
    binary.write_text("#!/bin/sh\nexit 0\n")
    binary.chmod(0o755)
    monkeypatch.delenv("MNEMOS_CLAUDE_BIN", raising=False)
    monkeypatch.setenv("PATH", str(folder))
    return binary


@pytest.fixture
def store():
    rt = MnemosRuntime(**SCOPE, use_dedicated_model=False)
    try:
        rt.capture("The ferry timetable changed: the 7:40 is now the 7:55.", signed_as="claude-opus-5-5")
    finally:
        rt.close()


class serving:
    def __init__(self) -> None:
        self.server = LogServer(Exporter.for_scope(**SCOPE, person="Riley"))

    def __enter__(self) -> LogServer:
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        return self.server

    def __exit__(self, *exc) -> None:
        self.server.shutdown()
        self.server.server_close()


def post(server: LogServer, body: dict) -> tuple[int, dict]:
    connection = http.client.HTTPConnection("127.0.0.1", server.port, timeout=10)
    try:
        connection.request("POST", f"/{server.token}/act", body=json.dumps(body).encode(), headers={
            "Host": f"127.0.0.1:{server.port}", "Content-Type": "application/json",
            "Origin": f"http://127.0.0.1:{server.port}"})
        response = connection.getresponse()
        return response.status, json.loads(response.read() or b"null")
    finally:
        connection.close()


def life(server: LogServer) -> dict:
    """The page's life document, read as the page reads it: over HTTP, on one of its own threads."""
    connection = http.client.HTTPConnection("127.0.0.1", server.port, timeout=10)
    try:
        connection.request("GET", f"/{server.token}/data/life.json", headers={"Host": f"127.0.0.1:{server.port}"})
        return json.loads(connection.getresponse().read())
    finally:
        connection.close()


def kept() -> dict:
    return json.loads((state.hours_dir(AGENT) / state.CHOICE_FILE).read_text())


def legacy(launchd) -> None:
    """All three scheduled the old way, and only ``{"choice": "yes"}`` kept."""
    blueprint = scheduler.plan(agent_id=AGENT, mnemos_command="mnemos", has_model=False, backend="launchd")
    for entry in blueprint["hours"]:
        entry["path"].parent.mkdir(parents=True, exist_ok=True)
        entry["path"].write_bytes(entry["content"])
        launchd.loaded.add(entry["path"].stem)
    state.hours_dir(AGENT).mkdir(parents=True, exist_ok=True)
    (state.hours_dir(AGENT) / state.CHOICE_FILE).write_text('{"choice": "yes"}\n')


def touched(launchd) -> set[str]:
    return {label for tool, _action, label in launchd.calls if tool == "launchctl"}


# ── What the page is given ──


def test_settings_are_given_each_hour_as_it_is(launchd, claude, store):
    with serving() as server:
        hours = life(server)["quietHours"]
    assert hours == {"where": "here", "cant": None, "hours": {
        "mine": {"on": False, "at": "08:00", "minutes": 60, "online": False},
        "ours": {"on": False, "at": "19:00", "minutes": 30, "online": False},
        "dream": {"on": False, "at": "03:30", "minutes": 20, "online": False},
    }}


def test_an_older_install_shows_its_own_hour_online(launchd, claude, store):
    legacy(launchd)
    with serving() as server:
        hours = life(server)["quietHours"]["hours"]
    assert {kind: (hour["on"], hour["online"]) for kind, hour in hours.items()} == {
        "mine": (True, True), "ours": (True, False), "dream": (True, False)}


def test_settings_say_why_no_hour_can_be_turned_on(launchd, store, tmp_path, monkeypatch):
    empty = tmp_path / "empty-bin"
    empty.mkdir()
    monkeypatch.delenv("MNEMOS_CLAUDE_BIN", raising=False)
    monkeypatch.setenv("PATH", str(empty))
    with serving() as server:
        cant = life(server)["quietHours"]["cant"]
    assert cant.startswith("None can be turned on here: they run Claude Code's claude command")


# ── Hour by hour ──


def test_each_hour_turns_on_by_itself_and_the_others_stay_off(launchd, claude, store):
    with serving() as server:
        status, answer = post(server, {"command": "hours", "hours": {
            "ours": {"on": True}, "dream": {"on": True, "at": "04:15", "minutes": 10}}})
        assert status == 200, answer
        assert answer["result"] == ("Our hour: on, daily at 19:00, up to 30 minutes, offline. "
                                    "The dream: on, daily at 04:15, up to 10 minutes, never online.")
        hours = life(server)["quietHours"]["hours"]
    assert launchd.loaded == {OURS, DREAM}
    assert MINE not in touched(launchd)
    assert hours["dream"] == {"on": True, "at": "04:15", "minutes": 10, "online": False}
    assert hours["ours"] == {"on": True, "at": "19:00", "minutes": 30, "online": False}
    assert hours["mine"]["on"] is False
    record = kept()
    assert record["choice"] == "yes" and record["answered_at"]          # the person did it themselves
    assert record["hours"]["ours"]["online"] is False                   # turned on offline


def test_a_change_to_one_hour_reschedules_only_that_hour(launchd, claude, store):
    legacy(launchd)
    with serving() as server:
        status, answer = post(server, {"command": "hours", "hours": {"dream": {"on": True, "at": "04:00"}}})
        assert status == 200, answer
        assert answer["result"] == "The dream: now at 04:00 (was 03:30)."
        status, answer = post(server, {"command": "hours", "hours": {"ours": {"on": True, "minutes": 45,
                                                                               "online": True}}})
        assert status == 200, answer
        hours = life(server)["quietHours"]["hours"]
    assert touched(launchd) == {DREAM}                    # length and the web are read when an hour starts
    assert launchd.loaded == {MINE, OURS, DREAM}
    assert hours["ours"] == {"on": True, "at": "19:00", "minutes": 45, "online": True}
    assert hours["dream"]["at"] == "04:00"
    assert hours["mine"] == {"on": True, "at": "08:00", "minutes": 60, "online": True}   # left as it was


def test_an_hour_turned_off_comes_off_alone(launchd, claude, store):
    legacy(launchd)
    with serving() as server:
        status, answer = post(server, {"command": "hours", "hours": {"mine": {"on": False}}})
    assert status == 200 and answer["result"] == "Its own hour: off.", answer
    assert touched(launchd) == {MINE}
    assert launchd.loaded == {OURS, DREAM}
    assert kept()["choice"] == "yes" and kept()["answered_at"]


def test_the_older_request_still_turns_all_three_on_and_off(launchd, claude, store):
    with serving() as server:
        status, answer = post(server, {"command": "hours", "on": True, "mine": "07:15", "ours": "", "dream": ""})
        assert status == 200, answer
        assert {MINE, OURS, DREAM} <= launchd.loaded
        assert life(server)["quietHours"]["hours"]["mine"]["at"] == "07:15"
        assert kept()["answered_at"]
        status, answer = post(server, {"command": "hours", "on": False})
        assert status == 200, answer
    assert not {MINE, OURS, DREAM} & launchd.loaded


@pytest.mark.parametrize("hours, said", [
    (None, '"hours" names the hours to change'),
    ({}, '"hours" names the hours to change'),
    ({"noon": {"on": True}}, "There's no hour called 'noon'"),
    ({"mine": {"on": "yes"}}, '"on" says whether its own hour runs'),
    ({"mine": {"on": True, "at": "25:00"}}, '"at" is the time its own hour starts'),
    ({"ours": {"on": True, "minutes": 4}}, '"minutes" is how long our hour may last: a whole number from 5 to 120.'),
    ({"ours": {"on": True, "minutes": True}}, '"minutes" is how long our hour may last'),
    ({"ours": {"on": True, "online": "yes"}}, '"online" says whether our hour may go online'),
    ({"dream": {"on": True, "online": True}}, "A dream never goes online."),
    ({"dream": {"on": True, "length": 10}}, 'Each hour takes "on", "at", "minutes" or "online"'),
    ({"dream": {"at": "04:00"}}, "The dream is off: turn it on to change it."),
])
def test_what_no_hour_can_have_is_refused_in_one_sentence(launchd, claude, store, hours, said):
    with serving() as server:
        status, answer = post(server, {"command": "hours", "hours": hours})
    assert status == 400 and answer["error"].startswith(said), answer
    assert launchd.calls == [] and not (state.hours_dir(AGENT) / state.CHOICE_FILE).exists()


def test_with_no_claude_command_nothing_is_turned_on(launchd, store, tmp_path, monkeypatch):
    empty = tmp_path / "empty-bin"
    empty.mkdir()
    monkeypatch.delenv("MNEMOS_CLAUDE_BIN", raising=False)
    monkeypatch.setenv("PATH", str(empty))
    with serving() as server:
        status, answer = post(server, {"command": "hours", "hours": {"ours": {"on": True}}})
    assert status == 400 and answer["error"].startswith("No hour can be turned on here:"), answer
    assert launchd.calls == []


# ── Inside Hermes ──


def _jobs(home: Path, *jobs: dict) -> None:
    (home / "cron").mkdir(parents=True, exist_ok=True)
    (home / "cron" / "jobs.json").write_text(json.dumps({"jobs": list(jobs)}))


def _in_hermes(monkeypatch) -> None:
    from mnemos import llm

    monkeypatch.setattr(llm, "_host_secrets", lambda name, default=None: default)  # Hermes hands out the keys


def test_inside_hermes_the_page_shows_hermes_jobs_from_the_profile_it_was_opened_for(store, tmp_path, monkeypatch):
    from mnemos.integrations.hermes.hours import JOB_PROMPT
    from mnemos.integrations.hermes.scope import running_for_home

    root, profile = tmp_path / "hermes", tmp_path / "hermes" / "profiles" / "work"
    _jobs(root, {"name": "mnemos-hour-mine", "schedule": {"kind": "cron", "expr": "0 6 * * *"},
                 "prompt": JOB_PROMPT.format(kind="mine")})
    _jobs(profile,
          {"name": "mnemos-hour-mine", "schedule": {"kind": "cron", "expr": "15 9 * * *"},
           "prompt": JOB_PROMPT.format(kind="mine"), "enabled_toolsets": ["memory", "no_mcp", "web"]},
          {"name": "mnemos-hour-dream", "schedule": {"kind": "cron", "expr": "30 3 * * *"},
           "prompt": "dream now", "state": "paused"})
    monkeypatch.setenv("HERMES_HOME", str(root))   # the root, as recent Hermes can leave it for a profile
    _in_hermes(monkeypatch)
    with running_for_home(profile):                 # the provider's call that opens the page
        page = serving()
    with page as server:
        hours = life(server)["quietHours"]
        status, answer = post(server, {"command": "hours", "hours": {"ours": {"on": True}}})
    assert hours == {"where": "hermes", "hours": {
        "mine": {"at": "09:15", "on": True, "online": True, "limited": True, "made_by": "agent"},
        "ours": None,
        "dream": {"at": "03:30", "on": False, "online": True, "limited": False, "made_by": "terminal"},
    }}
    assert status == 400 and "Hermes's own scheduled jobs" in answer["error"], answer


def test_inside_hermes_jobs_that_cant_be_read_are_not_called_off(store, tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "no-hermes-here"))
    _in_hermes(monkeypatch)
    with serving() as server:
        assert life(server)["quietHours"] == {"where": "hermes", "hours": None}


def test_mnemos_interface_changes_hours_the_same_way(launchd, claude, store):
    from mnemos.interface.person import Interface

    scope = Exporter.for_scope(**SCOPE).scope
    interface = Interface(db_path=scope.db_path, **SCOPE)
    answer = interface.answer(json.dumps({"id": 3, "command": "hours", "hours": {"mine": {"on": True, "online": True}}}))
    assert answer == {"id": 3, "result": "Its own hour: on, daily at 08:00, up to 60 minutes, online."}
    assert launchd.loaded == {MINE}
    assert state.hour_online(AGENT, "mine") is True and kept()["answered_at"]
    answer = interface.answer(json.dumps({"id": 4, "command": "hours", "on": False}))
    assert "result" in answer, answer
    assert launchd.loaded == set()


def test_inside_hermes_the_schedule_is_the_jobs_that_run(store, tmp_path, monkeypatch):
    """The sidebar's "next hour at …" reads ``schedule``; inside Hermes it was
    always empty, so it said "hours not scheduled" under rows that said On.
    Now it is the jobs that run, from the reader the rows come from."""
    from mnemos.integrations.hermes.hours import JOB_PROMPT

    home = tmp_path / "hermes"
    monkeypatch.setenv("HERMES_HOME", str(home))
    _in_hermes(monkeypatch)
    _jobs(home,
          {"name": "mnemos-hour-mine", "schedule": {"kind": "cron", "expr": "0 8 * * *"},
           "prompt": JOB_PROMPT.format(kind="mine"), "enabled_toolsets": ["memory", "no_mcp"]},
          {"name": "mnemos-hour-ours", "schedule": {"kind": "every", "minutes": 90, "display": "every 90m"},
           "prompt": JOB_PROMPT.format(kind="ours")},
          {"name": "mnemos-hour-dream", "schedule": {"kind": "cron", "expr": "30 3 * * *"},
           "prompt": JOB_PROMPT.format(kind="dream"), "paused_at": "2026-11-20T10:00:00Z"})
    with serving() as server:
        assert life(server)["schedule"] == [
            {"label": "mnemos-hour-mine", "when": {"Hour": 8, "Minute": 0}, "kind": "mine", "loaded": True},
            {"label": "mnemos-hour-ours", "when": None, "kind": "ours", "loaded": True},
        ]
    _jobs(home, {"name": "mnemos-hour-dream", "schedule": {"kind": "cron", "expr": "30 3 * * *"},
                 "prompt": JOB_PROMPT.format(kind="dream"), "enabled": False})
    with serving() as server:
        document = life(server)
    assert document["schedule"] == [] and document["quietHours"]["hours"]["dream"]["on"] is False


def test_inside_hermes_jev_says_it_does_not_apply(store, tmp_path, monkeypatch):
    """Jev judges Claude Code's cue and is never set inside Hermes, where the
    page read none of its numbers and showed "cut to 0 characters". The page
    is told it doesn't apply there, and anywhere else it still does."""
    with serving() as server:
        assert "applies" not in life(server)["jev"]
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))
    _in_hermes(monkeypatch)
    with serving() as server:
        assert life(server)["jev"] == {"on": False, "key": False, "env": False, "applies": False}
