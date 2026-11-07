"""Quiet hours for the agents that have a scheduler of their own.

Hermes and OpenClaw each have a cron that wakes the agent itself, so
``mnemos connect <agent> --hours --write`` puts three jobs in it whose message
tells the agent to run ``mnemos life --hour H --handoff`` and take what it
prints. What these tests hold:

1. Nothing is scheduled unless asked for: not by a preview, not by a plain
   ``connect --write``.
2. A job's reply goes nowhere (Hermes ``--deliver local``, OpenClaw
   ``--no-deliver``), and its message runs the hand-off for this memory.
3. Asking twice makes no second job; ``--no-hours`` removes them and keeps the
   choice; the agents with no scheduler of their own schedule nothing.
4. The first session asks in words true for that agent: what it costs and who
   sees the thoughts, off unless the person says yes.

Every agent here is a fake command on PATH under the test's own home; the real
Hermes, OpenClaw, scheduler and gateway are never touched.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import sys

import pytest

from mnemos.cli import main
from mnemos.setup import harnesses as hs
from mnemos.setup import state

FAKE_AGENT = r'''#!{python}
import json, os, sys

jobs_file, log = os.environ["FAKE_JOBS"], os.environ["FAKE_LOG"]
if os.environ.get("FAKE_JOBS_BY_HOME") and os.path.basename(sys.argv[0]) == "hermes":  # each home has its own
    jobs_file = os.path.join(os.environ["HERMES_HOME"], "fake-jobs.json")
me = os.path.basename(sys.argv[0])
args = sys.argv[1:]
with open(log, "a") as out:
    out.write(json.dumps([me] + args) + "\n")
jobs = json.load(open(jobs_file)) if os.path.exists(jobs_file) else []


def save():
    json.dump(jobs, open(jobs_file, "w"))


def value(flag):
    return args[args.index(flag) + 1] if flag in args else None


if args[:2] == ["cron", "list"]:
    if me == "hermes":
        for job in jobs:
            if job.get("paused") and "--all" not in args:  # as Hermes 0.17 lists them
                continue
            print("  %s [%s]\n    Name:      %s\n    Schedule:  %s\n    Deliver:   %s\n"
                  % (job["id"], "paused" if job.get("paused") else "active",
                     job["name"], job["schedule"], job["deliver"]))
    else:
        print(json.dumps({"jobs": [{"id": j["id"], "name": j["name"]} for j in jobs]}))
elif args[:2] == ["cron", "create"] and me == "hermes":
    rest = [a for a in args[2:]]
    jobs.append({"id": "%012x" % (max([int(j["id"], 16) for j in jobs] + [0]) + 1), "name": value("--name"),
                 "deliver": value("--deliver"), "schedule": rest[-2], "prompt": rest[-1]})
    save()
elif args[:2] == ["cron", "add"] and me == "openclaw":
    jobs.append({"id": "%012x" % (max([int(j["id"], 16) for j in jobs] + [0]) + 1), "name": value("--name"),
                 "schedule": value("--cron"), "prompt": value("--message"),
                 "deliver": "none" if "--no-deliver" in args else "announce"})
    save()
elif args[:2] == ["cron", "edit"] and me == "hermes":
    if os.environ.get("FAKE_EDIT_FAILS"):
        print("no gateway", file=sys.stderr)
        sys.exit(1)
    for job in jobs:
        if job["id"] == args[2]:
            job["prompt"] = value("--prompt")
    save()
elif args[:2] in (["cron", "remove"], ["cron", "rm"]):
    jobs[:] = [j for j in jobs if j["id"] != args[2]]
    save()
sys.exit(0)
'''


@pytest.fixture
def agents(tmp_path, monkeypatch):
    """Fake hermes and openclaw that keep their jobs in a file, and a log of
    every call. Returns (jobs file, call log)."""
    folder = tmp_path / "bin"
    folder.mkdir()
    jobs, log = tmp_path / "jobs.json", tmp_path / "calls.jsonl"
    for command in ("hermes", "openclaw", "codex", "grok", "gemini"):
        script = folder / command
        script.write_text(FAKE_AGENT.replace("{python}", sys.executable))
        script.chmod(script.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{folder}{os.pathsep}{os.environ.get('PATH', '')}")
    monkeypatch.setenv("FAKE_JOBS", str(jobs))
    monkeypatch.setenv("FAKE_LOG", str(log))
    monkeypatch.setenv("HERMES_HOME", str(Path.home() / ".hermes"))
    monkeypatch.setenv("OPENCLAW_STATE_DIR", str(tmp_path / "openclaw"))
    monkeypatch.setenv("OPENCLAW_CONFIG_PATH", str(tmp_path / "openclaw" / "openclaw.json"))
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex"))
    monkeypatch.setenv("GROK_HOME", str(tmp_path / "grok"))
    monkeypatch.setenv("GEMINI_CLI_HOME", str(tmp_path / "gemini"))
    monkeypatch.setattr(state, "mnemos_command", lambda: "/opt/mnemos/bin/mnemos")
    from mnemos import cli

    monkeypatch.setattr(cli, "_mnemos_command", lambda: "/opt/mnemos/bin/mnemos")
    from mnemos.integrations.hermes import installer

    class Done:
        warnings: list = []

        def summary(self):
            return "stub summary"

    monkeypatch.setattr(installer, "install_hermes_plugin", lambda **kw: Done())
    return jobs, log


def calls(log: Path) -> list[list[str]]:
    return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []


def cron_calls(log: Path) -> list[list[str]]:
    return [c for c in calls(log) if c[1] == "cron"]


def held(jobs: Path) -> list[dict]:
    return json.loads(jobs.read_text()) if jobs.exists() else []


# ── 1. Never unless asked for ──


@pytest.mark.parametrize("key", ["hermes", "openclaw"])
def test_a_preview_schedules_nothing_and_asks_nothing_of_the_agent(agents, capsys, key):
    jobs, log = agents

    assert main(["connect", key, "--hours"]) == 0

    text = capsys.readouterr().out
    assert "preview" in text and "schedule the quiet hours" in text
    assert cron_calls(log) == [] and held(jobs) == []


@pytest.mark.parametrize("key", ["hermes", "openclaw"])
def test_connecting_without_hours_schedules_no_hours(agents, key):
    jobs, log = agents

    assert main(["connect", key, "--write", "--no-upkeep"]) == 0

    assert cron_calls(log) == [] and held(jobs) == []
    assert state.hours_choice(key) is None


# ── 2. Where the reply goes, and what the job runs ──


def test_hermes_jobs_run_the_hand_off_and_deliver_nowhere_public(agents, capsys):
    jobs, log = agents

    assert main(["connect", "hermes", "--hours", "--write", "--no-upkeep"]) == 0

    made = held(jobs)
    assert [j["name"] for j in made] == ["mnemos-hour-mine", "mnemos-hour-ours", "mnemos-hour-dream"]
    assert {j["deliver"] for j in made} == {"local"}
    assert [j["schedule"] for j in made] == ["0 8 * * *", "0 19 * * *", "30 3 * * *"]
    for job, kind in zip(made, ("mine", "ours", "dream")):
        assert f"life --hour {kind} --handoff" in job["prompt"]
        assert "--agent-id hermes" in job["prompt"]
        assert "/opt/mnemos/bin/mnemos" in job["prompt"]
        assert "goes nowhere" in job["prompt"]
    assert state.hours_choice("hermes") == "yes"
    assert "gateway" in capsys.readouterr().out


def test_a_hermes_job_can_reach_its_tools_from_its_shell(agents):
    # Hermes from before September 2026 runs a job without its memory provider.
    jobs, log = agents
    assert main(["connect", "hermes", "--hours", "--write", "--no-upkeep"]) == 0
    prompt = held(jobs)[0]["prompt"]
    assert "/opt/mnemos/bin/mnemos hermes tool mnemos_capture" in prompt and "--agent-id hermes" in prompt


def _hermes_job_file(jobs):
    """Hermes' own file for its jobs, as the fake Hermes holds them."""
    hermes_jobs = Path.home() / ".hermes" / "cron" / "jobs.json"
    hermes_jobs.parent.mkdir(parents=True, exist_ok=True)
    hermes_jobs.write_text(json.dumps({"jobs": held(jobs)}))
    return hermes_jobs


def test_jobs_with_older_words_get_the_new_ones_when_connecting_again(agents, capsys):
    jobs, log = agents
    assert main(["connect", "hermes", "--hours", "--write", "--no-upkeep"]) == 0
    older = held(jobs)
    for job in older:
        job["prompt"] = "It is time for your quiet hour, with only the old words."
    jobs.write_text(json.dumps(older))
    _hermes_job_file(jobs)
    capsys.readouterr()

    # Without --hours: someone upgrading, who only runs connect again.
    assert main(["connect", "hermes", "--write", "--no-upkeep"]) == 0

    assert "from an older Mnemos" in capsys.readouterr().out
    renewed = held(jobs)
    assert len(renewed) == 3 and all("hermes tool mnemos_capture" in j["prompt"] for j in renewed)
    assert [j["id"] for j in renewed] == [j["id"] for j in older]
    assert not [c for c in cron_calls(log) if c[2] == "remove"]


def _with_older_words(jobs: Path, paused: bool = False) -> list[dict]:
    older = held(jobs)
    for job in older:
        job["prompt"] = "It is time for your quiet hour, with only the old words."
    older[0]["paused"] = paused
    jobs.write_text(json.dumps(older))
    _hermes_job_file(jobs)
    return older


def test_a_paused_job_stays_paused_when_its_words_change(agents, capsys):
    # Hermes 0.17 lists no paused job but keeps it in its file, which took connect down.
    # Removing and making it again would have started it up, and spent someone's tokens.
    jobs, log = agents
    assert main(["connect", "hermes", "--hours", "--write", "--no-upkeep"]) == 0
    older = _with_older_words(jobs, paused=True)
    log.write_text("")

    assert main(["connect", "hermes", "--write", "--no-upkeep"]) == 0

    renewed = held(jobs)
    assert [j["id"] for j in renewed] == [j["id"] for j in older]
    assert renewed[0]["paused"] and all("hermes tool mnemos_capture" in j["prompt"] for j in renewed)
    assert not [c for c in cron_calls(log) if c[2] in ("remove", "create")]


def test_a_paused_job_is_not_made_a_second_time(agents):
    jobs, log = agents
    assert main(["connect", "hermes", "--hours", "--write", "--no-upkeep"]) == 0
    before = held(jobs)
    before[0]["paused"] = True
    jobs.write_text(json.dumps(before))
    _hermes_job_file(jobs)

    assert main(["connect", "hermes", "--hours", "--write", "--no-upkeep"]) == 0

    assert held(jobs) == before


def test_words_that_cant_be_changed_leave_the_job_and_say_so(agents, capsys, monkeypatch):
    jobs, log = agents
    assert main(["connect", "hermes", "--hours", "--write", "--no-upkeep"]) == 0
    older = _with_older_words(jobs)
    monkeypatch.setenv("FAKE_EDIT_FAILS", "1")
    capsys.readouterr()

    assert main(["connect", "hermes", "--write", "--no-upkeep"]) == 1

    assert "failed" in capsys.readouterr().out
    assert held(jobs) == older


def test_uninstall_takes_the_hours_out_of_every_profile(agents, monkeypatch):
    # A job left in one keeps waking that agent, on its provider, for a command that's gone.
    from mnemos.cli import _hours_taken_out

    default = Path.home() / ".hermes"
    (default / "profiles" / "work").mkdir(parents=True)
    monkeypatch.setenv("FAKE_JOBS_BY_HOME", "1")
    assert main(["connect", "hermes", "--hours", "--write", "--no-upkeep"]) == 0
    assert main(["connect", "hermes", "--profile", "work", "--hours", "--write", "--no-upkeep"]) == 0
    monkeypatch.setenv("HERMES_HOME", str(default))
    files = [default / "fake-jobs.json", default / "profiles" / "work" / "fake-jobs.json"]
    assert [len(held(path)) for path in files] == [3, 3]

    said, problems = _hours_taken_out(write=False)
    assert len(said) == 2 and not problems and [len(held(path)) for path in files] == [3, 3]

    said, problems = _hours_taken_out(write=True)
    assert len(said) == 2 and not problems and [held(path) for path in files] == [[], []]
    assert any("work" in line for line in said)
    assert os.environ["HERMES_HOME"] == str(default)


def test_jobs_with_the_right_words_are_left_alone(agents, capsys):
    jobs, log = agents
    assert main(["connect", "hermes", "--hours", "--write", "--no-upkeep"]) == 0
    _hermes_job_file(jobs)
    before = held(jobs)

    assert main(["connect", "hermes", "--hours", "--write", "--no-upkeep"]) == 0

    assert held(jobs) == before and not [c for c in cron_calls(log) if c[2] == "remove"]
    assert "already scheduled" in capsys.readouterr().out


def test_openclaw_jobs_run_the_hand_off_in_an_isolated_session_and_deliver_nowhere(agents):
    jobs, log = agents

    assert main(["connect", "openclaw", "--hours", "--write", "--no-upkeep"]) == 0

    adds = [c for c in cron_calls(log) if c[2] == "add"]
    assert len(adds) == 3
    for argv, kind in zip(adds, ("mine", "ours", "dream")):
        assert "--no-deliver" in argv and "--announce" not in argv
        assert argv[argv.index("--session") + 1] == "isolated"
        assert argv[argv.index("--declaration-key") + 1] == f"mnemos-hour-{kind}"
        assert f"life --hour {kind} --handoff" in argv[argv.index("--message") + 1]
    assert {j["deliver"] for j in held(jobs)} == {"none"}
    assert state.hours_choice("openclaw") == "yes"


# ── 3. Twice, off, and the agents with no scheduler ──


@pytest.mark.parametrize("key", ["hermes", "openclaw"])
def test_asking_twice_makes_no_second_job(agents, key):
    jobs, log = agents
    assert main(["connect", key, "--hours", "--write", "--no-upkeep"]) == 0
    assert main(["connect", key, "--hours", "--write", "--no-upkeep"]) == 0

    assert len(held(jobs)) == 3


@pytest.mark.parametrize("key", ["hermes", "openclaw"])
def test_no_hours_removes_them_and_keeps_that_choice(agents, key):
    jobs, log = agents
    assert main(["connect", key, "--hours", "--write", "--no-upkeep"]) == 0

    assert main(["connect", key, "--no-hours", "--write", "--no-upkeep"]) == 0

    assert held(jobs) == []
    assert state.hours_choice(key) == "no"


@pytest.mark.parametrize("key", ["codex", "grok", "gemini"])
def test_an_agent_with_no_scheduler_gets_none_and_is_told_to_ask_for_an_hour(agents, capsys, key):
    jobs, log = agents

    assert main(["connect", key, "--hours", "--write", "--no-upkeep"]) == 0

    text = capsys.readouterr().out
    assert cron_calls(log) == [] and held(jobs) == []
    assert "nothing to schedule" in text
    assert "mnemos life --hour mine --handoff" in text
    assert state.hours_choice(key) is None


def test_a_failing_scheduler_stops_and_says_so(agents, tmp_path, capsys):
    jobs, log = agents
    bad = tmp_path / "bin" / "hermes"
    bad.write_text(f"#!/bin/sh\necho \"$@\" >> {log}\ncase \"$2\" in list) exit 0;; *) echo no gateway >&2; exit 1;; esac\n")

    assert main(["connect", "hermes", "--hours", "--write", "--no-upkeep"]) == 1

    assert "failed" in capsys.readouterr().out
    assert state.hours_choice("hermes") is None


def test_hours_are_scheduled_at_claudes_own_times():
    from mnemos.setup import agent_hours, scheduler

    for kind in agent_hours.KINDS:
        job = next(j for j in scheduler.HOUR_JOBS if j.name == f"hour-{kind}")
        assert agent_hours.cron(kind) == f"{job.daily_at[1]} {job.daily_at[0]} * * *"


# ── 4. What the first session says ──


def _first_session(agent_id: str, harness: str, db: Path) -> str:
    from mnemos.simple_runtime import MnemosRuntime

    runtime = MnemosRuntime(db_path=str(db), agent_id=agent_id, harness=harness)
    try:
        settle, lines = runtime._other_setup_part(hs.get(harness))
    finally:
        runtime.close()
    return "\n".join(settle + ([lines] if lines else []))


def test_hermes_is_asked_in_its_own_true_words_and_off_unless_yes(agents, tmp_path):
    text = _first_session("hermes", "hermes", tmp_path / "h.db")

    assert "Quiet hours: no one has asked" in text
    assert "the model and provider Hermes is set to use" in text
    assert "own scheduler" in text
    assert "off unless they say yes" in text.lower() or "unless they say yes" in text
    assert "connect hermes --hours --write" in text and "connect hermes --no-hours --write" in text
    assert "Claude plan" not in text and "Anthropic" not in text


def test_openclaw_is_asked_the_same_in_its_own_words(agents, tmp_path):
    text = _first_session("openclaw", "openclaw", tmp_path / "o.db")

    assert "the model and provider OpenClaw is set to use" in text
    assert "connect openclaw --hours --write" in text
    assert "Anthropic" not in text


@pytest.mark.parametrize("key,vendor", [("codex", "OpenAI"), ("grok", "xAI"), ("gemini", "Google")])
def test_an_agent_that_cannot_schedule_says_who_sees_an_hour_and_offers_the_hand_off(agents, tmp_path, key, vendor):
    text = _first_session(key, key, tmp_path / f"{key}.db")

    assert "Quiet hours are not offered here" not in text
    assert "life --hour mine --handoff" in text
    assert "no hour runs by itself" in text
    assert "Anthropic" not in text and "Claude plan" not in text
    assert hs.get(key).hours.vendor == vendor


def test_once_asked_it_is_not_asked_again(agents, tmp_path):
    state.record_hours_choice("hermes", "no")

    text = _first_session("hermes", "hermes", tmp_path / "h.db")

    assert "no one has asked" not in text
    assert "--hours --write" not in text


def test_claude_codes_words_and_defaults_are_as_they_were():
    from mnemos.simple_runtime import _HOURS_TOLD

    assert "they run Claude Code on its own, on their Claude plan" in _HOURS_TOLD
    assert "goes to Anthropic" in _HOURS_TOLD
    assert hs.get("claude-code").hours.vendor == "Anthropic"


@pytest.mark.parametrize("key", ["hermes", "openclaw"])
def test_uninstall_says_what_it_would_remove_and_removes_the_jobs_only_with_write(agents, key, capsys):
    jobs, log = agents
    assert main(["connect", key, "--hours", "--write", "--no-upkeep"]) == 0
    capsys.readouterr()

    main(["uninstall"])
    assert "the quiet hours (3 jobs) in its scheduler" in capsys.readouterr().out
    assert len(held(jobs)) == 3

    main(["uninstall", "--write"])
    assert "the quiet hours (3 jobs) removed from its scheduler" in capsys.readouterr().out
    assert held(jobs) == []


def test_claude_codes_words_in_the_table_are_the_words_it_always_told():
    from mnemos.simple_runtime import _HOURS_TOLD

    assert hs.get("claude-code").hours.cost == _HOURS_TOLD
