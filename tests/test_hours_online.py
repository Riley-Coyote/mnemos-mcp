"""Online only when chosen, and what an hour read (QH-2, November 2026).

An own hour and our hour get the web (WebSearch, WebFetch) only when the
person turned it on for that hour (``state.hour_online``); a dream never. An
own hour set up before the setting existed, and still scheduled, keeps the web
it had. The hour is told which it is in one line after its own words, and its
record says whether it had the web and lists the searches and pages it read.

Inside Hermes the truth about an hour is its job: ``scheduled_in_hermes``
reads it from Hermes's own jobs file.

Every hour here runs the suite's fake claude (tests/fake_claude.py), and every
scheduler is the suite's fake (tests/conftest.py).
"""

from __future__ import annotations

import io
import json
import os
from pathlib import Path
import sys

import pytest

from mnemos.setup import scheduler, state
from mnemos.store.sqlite_store import EngramStore

AGENT = "claude-code"
SCOPE = {"agent_id": AGENT, "person_id": "user", "project_scope": "global"}
ROOT = Path(__file__).resolve().parents[1]
WEB = {"WebSearch", "WebFetch"}


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    folder = tmp_path / "home"
    (folder / ".mnemos").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(folder))
    monkeypatch.setenv("MNEMOS_LIFE_MNEMOS_BIN", "/opt/fake/mnemos")
    monkeypatch.setenv("MNEMOS_CLAUDE_BIN", str(ROOT / "tests/fake_claude.py"))
    monkeypatch.setenv("FAKE_CLAUDE_LOG", str(tmp_path / "fake.json"))
    monkeypatch.setenv("FAKE_CLAUDE_SCENARIO", "ok")
    monkeypatch.setenv("PATH", str(Path(sys.executable).parent) + os.pathsep + os.environ["PATH"])
    return folder


@pytest.fixture
def db(home):
    path = home / ".mnemos" / f"{AGENT}.db"
    EngramStore(path).close()
    return path


@pytest.fixture
def launchd(monkeypatch, os_scheduler):
    monkeypatch.setattr(scheduler, "detect_backend", lambda system=None: "launchd")
    return os_scheduler


def _work(db):
    from mnemos.simple_runtime import MnemosRuntime

    runtime = MnemosRuntime(db_path=str(db), use_dedicated_model=False, **SCOPE)
    try:
        runtime.capture("The ferry timetable changed.", signed_as="claude-opus-5-5",
                        impact="Read the new timetable.")
        runtime.handoff("Check the ferry timetable next session.", signed_as="claude-opus-5-5")
    finally:
        runtime.close()


def _run(db, kind="mine", **kwargs):
    from mnemos.life import run_hour

    return run_hour(kind, db_path=str(db), **SCOPE, **kwargs)


def _ran(tmp_path, home, record) -> tuple[set[str], set[str], str]:
    """What the hour was given: its --tools, what its settings allow, and the
    prompt it read."""
    argv = json.loads((tmp_path / "fake.json").read_text())["argv"]
    folder = home / ".mnemos" / "hours" / AGENT / record["id"]
    settings = json.loads((folder / "settings.json").read_text())
    tools = argv[argv.index("--tools") + 1]
    return set(filter(None, tools.split(","))), set(settings["permissions"]["allow"]), \
        (folder / "prompt.md").read_text()


def _schedule_own_hour(launchd) -> None:
    """The own hour scheduled the way the old `daemon install --hours` left it."""
    blueprint = scheduler.plan(agent_id=AGENT, mnemos_command="mnemos", has_model=False, backend="launchd")
    for entry in blueprint["hours"]:
        if entry["job"].name == "hour-mine":
            entry["path"].parent.mkdir(parents=True, exist_ok=True)
            entry["path"].write_bytes(entry["content"])
            launchd.loaded.add(entry["path"].stem)


# ── The tools an hour has ──


def test_an_own_hour_nobody_chose_the_web_for_is_offline(db, home, tmp_path):
    from mnemos.life import OFFLINE_LINE, ONLINE_LINE

    record = _run(db)
    tools, allowed, prompt = _ran(tmp_path, home, record)
    assert record["status"] == "done"
    assert tools == {"Read", "Write", "Edit", "Glob", "Grep", "Bash"}
    assert not WEB & allowed
    assert allowed == {"mcp__mnemos", "Bash"}
    assert record["online"] is False
    assert OFFLINE_LINE in prompt and ONLINE_LINE not in prompt
    assert "web" not in record


def test_an_own_hour_the_person_put_online_has_the_web(db, home, tmp_path):
    state.record_hour(AGENT, "mine", online=True)
    record = _run(db)
    tools, allowed, _prompt = _ran(tmp_path, home, record)
    assert WEB <= tools and WEB <= allowed
    assert tools == {"Read", "Write", "Edit", "Glob", "Grep", "Bash", "WebSearch", "WebFetch"}
    # Every tool it has beyond the five Claude Code allows is allowed, or
    # --permission-prompts none would deny it.
    assert allowed == {"mcp__mnemos"} | (tools - {"Read", "Write", "Edit", "Glob", "Grep"})
    assert record["online"] is True


def test_a_change_applies_at_the_next_hour(db, home, tmp_path):
    state.record_hour(AGENT, "mine", online=True)
    assert WEB <= _ran(tmp_path, home, _run(db))[0]
    state.record_hour(AGENT, "mine", online=False)
    assert not WEB & _ran(tmp_path, home, _run(db))[0]


def test_a_legacy_own_hour_keeps_its_web(db, home, tmp_path, launchd):
    _schedule_own_hour(launchd)
    folder = state.hours_dir(AGENT)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / state.CHOICE_FILE).write_text('{"choice": "yes"}\n')
    record = _run(db)
    tools, allowed, _prompt = _ran(tmp_path, home, record)
    assert WEB <= tools and WEB <= allowed
    assert record["online"] is True


@pytest.mark.parametrize("online", [False, True])
def test_our_hour_is_online_only_when_chosen(db, home, tmp_path, online):
    from mnemos.life import OFFLINE_LINE, ONLINE_LINE

    _work(db)
    state.record_hour(AGENT, "ours", online=online)
    record = _run(db, "ours")
    tools, allowed, prompt = _ran(tmp_path, home, record)
    base = {"Read", "Write", "Edit", "Glob", "Grep"}
    assert tools == (base | WEB if online else base)
    assert allowed == ({"mcp__mnemos"} | WEB if online else {"mcp__mnemos"})
    assert "Bash" not in tools
    assert record["online"] is online
    assert (ONLINE_LINE if online else OFFLINE_LINE) in prompt
    assert (OFFLINE_LINE if online else ONLINE_LINE) not in prompt


def test_our_hour_nobody_chose_for_is_offline_even_beside_a_legacy_own_hour(db, home, tmp_path, launchd):
    _schedule_own_hour(launchd)
    _work(db)
    record = _run(db, "ours")
    assert not WEB & _ran(tmp_path, home, record)[0]
    assert record["online"] is False


def test_a_dream_never_goes_online(db, home, launchd):
    from mnemos import life

    # Even a record that says otherwise, written by hand.
    folder = state.hours_dir(AGENT)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / state.CHOICE_FILE).write_text(json.dumps({"hours": {"dream": {"online": True}}}))
    assert life.hour_online(AGENT, "dream") is False
    _mcp, settings, cmd = life._files_and_command(
        "dream", "hour-1", home, db, SCOPE, "claude", "mnemos", online=True,
    )
    assert cmd[cmd.index("--tools") + 1] == ""
    assert settings["permissions"]["allow"] == ["mcp__mnemos"]
    out = io.StringIO()
    record = _run(db, "dream", dry_run=True, out=out)
    assert record["online"] is False
    assert "Online: never" in out.getvalue()
    assert "Tools: only its memory's own" in out.getvalue()
    assert life.ONLINE_LINE not in record["prompt"] and life.OFFLINE_LINE not in record["prompt"]


def test_an_hour_that_cant_tell_is_offline(db, home, tmp_path, monkeypatch):
    from mnemos import life

    def broken(agent_id, kind):
        raise OSError("launchctl isn't answering")

    monkeypatch.setattr(state, "hour_online", broken)
    assert life.hour_online(AGENT, "mine") is False
    record = _run(db)
    assert not WEB & _ran(tmp_path, home, record)[0]


# ── The prompt's line ──


def test_the_line_comes_after_the_hours_own_words(db, home):
    from mnemos import life

    words = life.studio_dir(AGENT) / "words"
    words.mkdir(parents=True)
    (words / "my-hour.md").write_text("My own words.\n")
    offline = _run(db, dry_run=True, out=io.StringIO())["prompt"]
    assert offline.startswith("My own words.\n\n" + life.OFFLINE_LINE + "\n\n---\n\nWhat's waiting")
    state.record_hour(AGENT, "mine", online=True)
    online = _run(db, dry_run=True, out=io.StringIO())["prompt"]
    assert online.startswith("My own words.\n\n" + life.ONLINE_LINE + "\n\n---\n\nWhat's waiting")
    assert life.ONLINE_LINE == "In this hour you can search and read the web. The person sees every page you read."
    assert life.OFFLINE_LINE == "You can't go online in this hour: the person has the internet off for it."


def test_a_hand_off_is_unchanged(db, home):
    from mnemos import life

    state.record_hour(AGENT, "mine", online=True)
    out = io.StringIO()
    record = _run(db, handoff=True, out=out)
    assert record["status"] == "done"
    assert "online" not in record and "web" not in record
    assert life.ONLINE_LINE not in out.getvalue() and life.OFFLINE_LINE not in out.getvalue()


# ── The dry run ──


@pytest.mark.parametrize("online", [False, True])
def test_the_dry_run_says_whether_it_would_be_online(db, home, online):
    if online:
        state.record_hour(AGENT, "mine", online=True)
    out = io.StringIO()
    record = _run(db, dry_run=True, out=out)
    printed = out.getvalue()
    assert record["online"] is online
    if online:
        assert "Online: yes: it can search and read the web" in printed
        assert "Tools: Read, Write, Edit, Glob, Grep, Bash, WebSearch, WebFetch, and its memory's own" in printed
        assert "--tools Read,Write,Edit,Glob,Grep,Bash,WebSearch,WebFetch" in printed
    else:
        assert "Online: no: the internet is off for this hour" in printed
        assert "Tools: Read, Write, Edit, Glob, Grep, Bash, and its memory's own" in printed
        assert "WebSearch" not in printed and "WebFetch" not in printed


def test_the_cli_dry_run_reads_the_persons_choice(db, home):
    import subprocess

    # The person's choice is recorded, so nothing asks the machine's scheduler.
    state.record_hour(AGENT, "mine", online=True)
    done = subprocess.run(
        [sys.executable, "-m", "mnemos.cli", "life", "--hour", "mine", "--dry-run",
         "--db-path", str(db), "--agent-id", AGENT],
        env=dict(os.environ), capture_output=True, text=True, timeout=60,
    )
    assert done.returncode == 0, done.stderr
    assert "Online: yes: it can search and read the web" in done.stdout


# ── An hour's minutes ──


def test_an_hours_minutes_come_first_from_what_is_passed_then_down(db, home, monkeypatch):
    from mnemos.life import budget

    def minutes(**passed):
        seconds, _tokens, wrong = budget("mine", agent_id=AGENT, **passed)
        assert wrong == ""
        return seconds / 60

    assert minutes() == state.DEFAULT_MINUTES["mine"] == 60
    (home / ".mnemos" / "config.json").write_text(json.dumps({"life": {"minutes": {"mine": 45}}}))
    assert minutes() == 45
    state.record_hour(AGENT, "mine", minutes=25)
    assert minutes() == 25, "the person's own setting comes before the config"
    monkeypatch.setenv("MNEMOS_HOUR_MINUTES", "15")
    assert minutes() == 15, "a host app's budget for the hour it runs comes before the person's setting"
    assert minutes(max_minutes=7) == 7, "what is passed comes first"
    # Another agent's setting is its own.
    monkeypatch.delenv("MNEMOS_HOUR_MINUTES")
    assert budget("mine", agent_id="someone-else")[0] / 60 == 45
    # A setting the person never made is not taken from the defaults table:
    # the config still decides another hour.
    assert budget("ours", agent_id=AGENT)[0] / 60 == state.DEFAULT_MINUTES["ours"]


def test_the_minutes_the_person_chose_are_read_in_one_place(home, monkeypatch):
    from mnemos import life

    assert state.chosen_minutes(AGENT, "mine") is None
    assert state.hour_settings(AGENT)["mine"]["minutes"] == state.DEFAULT_MINUTES["mine"]
    state.record_hour(AGENT, "mine", minutes=25)
    assert state.chosen_minutes(AGENT, "mine") == 25
    assert state.chosen_minutes(AGENT, "ours") is None
    assert state.hour_settings(AGENT)["mine"]["minutes"] == 25
    # A length no hour can have, written by hand, is no choice.
    for bad in (500, 0, "25", 25.0, True, None):
        (state.hours_dir(AGENT) / state.CHOICE_FILE).write_text(
            json.dumps({"hours": {"mine": {"minutes": bad}}}))
        assert state.chosen_minutes(AGENT, "mine") is None, bad
        assert state.hour_settings(AGENT)["mine"]["minutes"] == state.DEFAULT_MINUTES["mine"], bad
    # And the budget asks the public reader, nothing else.
    asked = []
    monkeypatch.setattr(state, "chosen_minutes", lambda agent_id, kind: asked.append((agent_id, kind)) or 12)
    assert life.budget("ours", agent_id=AGENT)[0] / 60 == 12
    assert asked == [(AGENT, "ours")]


def test_the_persons_minutes_reach_the_hour_that_runs(db, monkeypatch):
    from mnemos import life

    state.record_hour(AGENT, "mine", minutes=5)
    seen = {}
    real = life._watch

    def watch(cmd, studio, env, folder, prompt, max_seconds, max_tokens, hour=life.HOUR_MODEL):
        seen["minutes"] = max_seconds / 60
        return real(cmd, studio, env, folder, prompt, max_seconds, max_tokens, hour)

    monkeypatch.setattr(life, "_watch", watch)
    assert _run(db)["status"] == "done"
    assert seen["minutes"] == 5


# ── What an hour read ──


def test_the_record_lists_the_searches_and_pages(db, home, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_SCENARIO", "web")
    state.record_hour(AGENT, "mine", online=True)
    record = _run(db)
    assert record["status"] == "done"
    assert record["online"] is True
    assert record["web"] == {
        "searched": ["tide tables Lisbon", "moon phase November 2026"],
        "read": ["https://example.org/tides", "https://example.org/moon",
                 ("https://example.net/" + "x" * 400)[:300]],
    }
    kept = json.loads((state.hours_dir(AGENT) / "hours.jsonl").read_text().splitlines()[-1])
    assert kept["web"] == record["web"] and kept["online"] is True


def test_the_record_keeps_at_most_fifty_of_each():
    from mnemos.life import _web_used

    web, seen = {"searched": [], "read": []}, set()
    blocks = [{"type": "tool_use", "id": f"s{n}", "name": "WebSearch", "input": {"query": f"q{n}"}}
              for n in range(60)]
    blocks += [{"type": "tool_use", "id": f"r{n}", "name": "WebFetch", "input": {"url": "u" * 900}}
               for n in range(70)]
    blocks += [{"type": "tool_use", "name": "WebSearch", "input": "not a dict"}, "not a block", None]
    _web_used(blocks, web, seen)
    _web_used("not a list", web, seen)
    assert web["searched"] == [f"q{n}" for n in range(50)]
    assert len(web["read"]) == 50 and all(len(url) == 300 for url in web["read"])


# ── The page ──


def test_the_page_gets_the_hours_web_as_recorded(db, home):
    from mnemos.companion.export import Exporter
    from mnemos.core.engram import _gen_ulid

    folder = state.hours_dir(AGENT)
    folder.mkdir(parents=True, exist_ok=True)
    web = {"searched": ["tide tables Lisbon"], "read": ["https://example.org/tides"]}
    base = {"kind": "mine", "started_at": "2026-11-20T08:00:00+00:00", "ended_at": "2026-11-20T08:40:00+00:00",
            "model": "claude-opus-5-5", "status": "done", "reason": "", "tokens": None, "store": "live",
            "journal_ids": [], "note_ids": [], "since": "", "waiting": {}, "discarded_ids": []}
    older, offline, online = _gen_ulid(), _gen_ulid(), _gen_ulid()
    (folder / "hours.jsonl").write_text("\n".join(json.dumps(r) for r in (
        {"id": older, **base},
        {"id": offline, **base, "online": False},
        {"id": online, **base, "online": True, "web": web},
    )) + "\n")
    life, _memories = Exporter.for_scope(agent_id=AGENT, db_path=str(db), person="Riley").export()
    by_id = {hour["id"]: hour for hour in life["hours"]}
    assert (by_id[online]["online"], by_id[online]["web"]) == (True, web)
    assert (by_id[offline]["online"], by_id[offline]["web"]) == (False, None)
    assert (by_id[older]["online"], by_id[older]["web"]) == (None, None)


# ── What Hermes has scheduled ──


def _hermes_job(kind, *, prompt=None, toolsets=None, schedule=None, **more) -> dict:
    """A job as Hermes's own ``create_job`` stores it (cron/jobs.py, 3b42157858)."""
    from mnemos.integrations.hermes.hours import JOB_PROMPT
    from mnemos.setup.agent_hours import cron

    expr = cron(kind)
    job = {
        "id": f"{kind}0123abcd"[:12], "name": f"mnemos-hour-{kind}",
        "prompt": JOB_PROMPT.format(kind=kind) if prompt is None else prompt,
        "skills": None, "skill": None, "model": None, "provider": None, "base_url": None,
        "script": None, "no_agent": False, "monitor_script": None, "monitor_url": None,
        "monitor_state": None, "context_from": None,
        "schedule": schedule or {"kind": "cron", "expr": expr, "display": expr},
        "schedule_display": expr, "repeat": {"times": None, "completed": 0},
        "enabled": True, "state": "scheduled", "paused_at": None, "paused_reason": None,
        "created_at": "2026-11-21T08:00:00+00:00", "next_run_at": "2026-11-22T08:00:00+00:00",
        "last_run_at": None, "last_status": None, "last_error": None, "last_delivery_error": None,
        "last_delivery_unverified": None, "last_failure": None, "failure_streak": 0,
        "deliver": "local", "origin": None, "enabled_toolsets": toolsets, "workdir": None,
    }
    job.update(more)
    return job


@pytest.fixture
def hermes(tmp_path, monkeypatch):
    folder = tmp_path / "hermes-home"
    (folder / "cron").mkdir(parents=True)
    monkeypatch.setenv("HERMES_HOME", str(folder))

    def jobs(*made, bare=False):
        made = list(made)
        (folder / "cron" / "jobs.json").write_text(json.dumps(
            made if bare else {"jobs": made, "updated_at": "2026-11-21T08:00:00+00:00"}))

    jobs.file = folder / "cron" / "jobs.json"
    return jobs


def test_hermes_jobs_the_agent_made(hermes):
    from mnemos.integrations.hermes.hours import scheduled_in_hermes

    hermes(
        _hermes_job("mine", toolsets=["memory", "web", "file", "no_mcp"]),
        _hermes_job("dream", toolsets=["memory", "no_mcp"]),
        {"name": "someone-elses-job", "prompt": "water the plants"},
    )
    assert scheduled_in_hermes() == {
        "mine": {"at": "08:00", "on": True, "online": True, "limited": True, "made_by": "agent"},
        "ours": None,
        "dream": {"at": "03:30", "on": True, "online": False, "limited": True, "made_by": "agent"},
    }


def test_a_hermes_job_made_in_a_terminal(hermes):
    from mnemos.integrations.hermes.hours import scheduled_in_hermes
    from mnemos.setup.agent_hours import message

    # What `mnemos connect hermes --hours` makes with `hermes cron create`:
    # its own words, and no toolsets of its own.
    hermes(_hermes_job("ours", prompt=message("ours", "mnemos", [], "hermes"),
                       schedule={"kind": "cron", "expr": "15 21 * * *", "display": "15 21 * * *"}))
    assert scheduled_in_hermes()["ours"] == {
        "at": "21:15", "on": True, "online": True, "limited": False, "made_by": "terminal",
    }


@pytest.mark.parametrize("paused", [
    {"enabled": False, "state": "paused", "paused_at": "2026-11-21T09:00:00+00:00"},
    {"state": "paused"},
    {"paused_at": "2026-11-21T09:00:00+00:00"},
    {"enabled": False},
])
def test_a_paused_hermes_job_is_off(hermes, paused):
    from mnemos.integrations.hermes.hours import scheduled_in_hermes

    hermes(_hermes_job("mine", toolsets=["memory"], **paused))
    assert scheduled_in_hermes()["mine"]["on"] is False


def test_of_two_hermes_jobs_of_one_name_the_one_that_runs(hermes):
    from mnemos.integrations.hermes.hours import scheduled_in_hermes

    hermes(_hermes_job("mine", toolsets=["memory"], enabled=False, state="paused"),
           _hermes_job("mine", toolsets=["memory", "web"]), bare=True)
    assert scheduled_in_hermes()["mine"]["on"] is True
    assert scheduled_in_hermes()["mine"]["online"] is True


def test_a_hermes_job_not_at_a_daily_time_says_its_schedule(hermes):
    from mnemos.integrations.hermes.hours import scheduled_in_hermes

    hermes(_hermes_job("mine", toolsets=[], schedule={"kind": "cron", "expr": "0 8 * * 1-5"}),
           _hermes_job("ours", toolsets=[], schedule={"kind": "interval", "minutes": 90,
                                                      "display": "every 90m"}))
    found = scheduled_in_hermes()
    assert found["mine"]["at"] == "0 8 * * 1-5"
    assert found["ours"]["at"] == "every 90m"
    # An empty list is no tools at all: not online, and not its memory's.
    assert (found["mine"]["online"], found["mine"]["limited"]) == (False, False)


def test_hermes_jobs_that_cant_be_read_say_so(hermes):
    from mnemos.integrations.hermes.hours import scheduled_in_hermes
    from mnemos.setup import agent_hours

    assert not hermes.file.exists()
    assert scheduled_in_hermes() is None
    hermes.file.write_text("{not json")
    assert scheduled_in_hermes() is None
    hermes.file.write_text(json.dumps({"jobs": "nothing"}))
    assert scheduled_in_hermes() is None
    # And the reader the jobs' words come from still says nothing, as before.
    assert agent_hours._hermes_prompts() == {}
    hermes()
    assert scheduled_in_hermes() == {"mine": None, "ours": None, "dream": None}
