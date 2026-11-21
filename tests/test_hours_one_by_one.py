"""The quiet hours, chosen one by one (QH-1, November 2026).

Each hour is off until the person turns it on, and each has its own
settings: when it starts, how long it may last, and for its own hour and our
hour whether it may go online. They are kept in one record,
``~/.mnemos/hours/<agent>/choice.json`` (``mnemos.setup.state``), and one
function answers what an hour gets (``state.hour_settings``). ``mnemos
hours`` shows them and changes them, an hour at a time; ``mnemos daemon
install|uninstall --hours`` changes all three, through the same way.

An hour set up before this release has no ``online`` kept: it is offline,
except an own hour that is scheduled right now, which keeps the web it had.

Every scheduler here is the suite's fake (tests/conftest.py).
"""

from __future__ import annotations

import json
import plistlib
from pathlib import Path

import pytest

from mnemos import cli, connect_cmd
from mnemos.cli import main
from mnemos.setup import harnesses, scheduler, state

SCOPE = ["--agent-id", "nova", "--person-id", "riley", "--project-scope", "demo"]
UPKEEP = {f"com.mnemos.nova.{name}" for name in ("maintain", "maintain-deep")}
MINE, OURS, DREAM = (f"com.mnemos.nova.hour-{kind}" for kind in ("mine", "ours", "dream"))


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
def no_claude(tmp_path, monkeypatch):
    empty = tmp_path / "empty-bin"
    empty.mkdir()
    monkeypatch.delenv("MNEMOS_CLAUDE_BIN", raising=False)
    monkeypatch.setenv("PATH", str(empty))


def _agents() -> Path:
    return Path.home() / "Library" / "LaunchAgents"


def _plist(label: str) -> dict:
    return plistlib.loads((_agents() / f"{label}.plist").read_bytes())


def _at(label: str) -> tuple[int, int]:
    when = _plist(label)["StartCalendarInterval"]
    return when["Hour"], when["Minute"]


def _hours(*words: str) -> int:
    return main(["hours", *words, *SCOPE])


def _kept() -> dict:
    return json.loads((state.hours_dir("nova") / state.CHOICE_FILE).read_text())


def _legacy(launchd) -> None:
    """A store set up before this release: all three hours scheduled by the
    old `daemon install --hours`, and only ``{"choice": "yes"}`` kept."""
    blueprint = scheduler.plan(agent_id="nova", mnemos_command="mnemos", has_model=False,
                               backend="launchd")
    for entry in blueprint["hours"]:
        entry["path"].parent.mkdir(parents=True, exist_ok=True)
        entry["path"].write_bytes(entry["content"])
        launchd.loaded.add(entry["path"].stem)
    folder = state.hours_dir("nova")
    folder.mkdir(parents=True, exist_ok=True)
    (folder / state.CHOICE_FILE).write_text('{"choice": "yes"}\n')


# ── The one record ──


def test_the_defaults_live_in_one_place():
    from mnemos import life

    assert state.DEFAULT_AT == {"mine": (8, 0), "ours": (19, 0), "dream": (3, 30)}
    assert state.DEFAULT_MINUTES == {"mine": 60, "ours": 30, "dream": 20}
    assert [job.daily_at for job in scheduler.HOUR_JOBS] == [state.DEFAULT_AT[k] for k in state.HOUR_KINDS]
    assert life.DEFAULT_MINUTES is state.DEFAULT_MINUTES
    assert life.HOUR_KINDS == state.HOUR_KINDS


def test_hour_settings_with_nothing_kept_are_the_defaults(launchd):
    assert state.hour_settings("nova") == {
        "mine": {"at": "08:00", "minutes": 60, "online": False},
        "ours": {"at": "19:00", "minutes": 30, "online": False},
        "dream": {"at": "03:30", "minutes": 20, "online": False},
    }


def test_a_choice_kept_later_keeps_the_hours_settings(launchd):
    assert state.record_hour("nova", "mine", at="09:15", minutes=45, online=True)
    state.record_hours_choice("nova", "no")
    kept = _kept()
    assert kept["choice"] == "no"
    assert kept["hours"]["mine"] == {"at": "09:15", "minutes": 45, "online": True}
    state.record_hour("nova", "mine", minutes=30)
    assert _kept()["hours"]["mine"] == {"at": "09:15", "minutes": 30, "online": True}
    assert _kept()["choice"] == "no"
    assert state.record_answered("nova")
    assert state.answered_at("nova") == _kept()["answered_at"]
    assert state.hour_settings("nova")["mine"] == {"at": "09:15", "minutes": 30, "online": True}


def test_no_hour_can_be_given_what_none_can_have(launchd):
    for kind, options in (
        ("noon", {}), ("mine", {"at": "25:00"}), ("mine", {"minutes": 4}),
        ("mine", {"minutes": 121}), ("dream", {"online": True}),
    ):
        with pytest.raises(ValueError):
            state.record_hour("nova", kind, **options)
    assert not (state.hours_dir("nova") / state.CHOICE_FILE).exists()


# ── The legacy rule ──


def test_a_legacy_own_hour_keeps_the_web_it_had(launchd):
    _legacy(launchd)
    assert state.hour_online("nova", "mine") is True
    assert state.hour_online("nova", "ours") is False
    assert state.hour_online("nova", "dream") is False
    now = state.hours_now("nova")
    assert [(k, h["on"], h["at"], h["online"]) for k, h in now.items()] == [
        ("mine", True, "08:00", True), ("ours", True, "19:00", False), ("dream", True, "03:30", False),
    ]

    # Taken off, it has nothing left to keep; turned on again, it is offline.
    launchd.loaded.discard(MINE)
    assert state.hour_online("nova", "mine") is False


def test_rescheduling_an_hour_already_on_keeps_its_web(launchd, claude):
    _legacy(launchd)
    assert main(["daemon", "install", *SCOPE, "--hours", "--write"]) == 0
    assert "online" not in state._recorded(_kept(), "mine")
    assert state.hour_online("nova", "mine") is True
    assert _hours("on", "mine", "--at", "06:45", "--write") == 0
    assert state.hour_online("nova", "mine") is True, "a new time doesn't take the web away"


def test_an_hour_turned_on_now_is_offline(launchd, claude):
    assert _hours("on", "mine", "--write") == 0
    assert launchd.loaded == {MINE}
    assert _kept()["hours"]["mine"]["online"] is False
    assert state.hour_online("nova", "mine") is False

    assert main(["daemon", "uninstall", *SCOPE, "--hours", "--write"]) == 0
    assert main(["daemon", "install", *SCOPE, "--hours", "--write"]) == 0
    assert state.hour_online("nova", "mine") is False
    assert state.hour_online("nova", "ours") is False


# ── mnemos hours on and off, one at a time ──


def test_hours_on_and_off_one_at_a_time_leave_the_others_untouched(launchd, claude, capsys):
    assert _hours("on", "mine", "--at", "09:00", "--write") == 0
    assert launchd.loaded == {MINE}, "only its own hour, and no upkeep either"
    assert _at(MINE) == (9, 0)

    assert _hours("on", "dream", "--write") == 0
    assert launchd.loaded == {MINE, DREAM}
    mine_before = (_agents() / f"{MINE}.plist").read_bytes()
    launchd.calls.clear()

    assert _hours("off", "mine", "--write") == 0
    assert launchd.loaded == {DREAM}
    assert not (_agents() / f"{MINE}.plist").exists()
    assert launchd.calls == [("launchctl", "bootout", MINE)], "nothing else was touched"
    assert _at(DREAM) == (3, 30)

    assert _hours("on", "mine", "--write") == 0
    assert (_agents() / f"{MINE}.plist").read_bytes() == mine_before, "the time it had was remembered"
    kept = _kept()
    assert kept["choice"] == "yes" and kept["answered_at"]


def test_changing_an_hour_that_is_on_changes_only_that(launchd, claude, capsys):
    assert _hours("on", "all", "--write") == 0
    launchd.calls.clear()
    capsys.readouterr()

    assert _hours("on", "ours", "--minutes", "20", "--online", "--write") == 0
    assert launchd.calls == [], "nothing to reschedule"
    assert state.hour_settings("nova")["ours"] == {"at": "19:00", "minutes": 20, "online": True}
    assert "our hour: now up to 20 minutes (was 30); now online" in capsys.readouterr().out

    assert _hours("on", "ours", "--at", "21:30", "--write") == 0
    assert launchd.calls == [("launchctl", "bootout", OURS), ("launchctl", "bootstrap", OURS)]
    assert _at(OURS) == (21, 30) and _at(MINE) == (8, 0) and _at(DREAM) == (3, 30)


@pytest.mark.parametrize("backend", ["systemd", "crontab"])
def test_one_at_a_time_on_linux_schedulers(monkeypatch, os_scheduler, claude, backend, capsys):
    monkeypatch.setattr(scheduler, "detect_backend", lambda system=None: backend)
    os_scheduler.crontab = "0 9 * * * /usr/bin/backup.sh\n"
    units = Path.home() / ".config" / "systemd" / "user"

    assert _hours("on", "ours", "--write") == 0
    assert _hours("on", "dream", "--at", "04:10", "--write") == 0
    assert _hours("off", "ours", "--write") == 0
    if backend == "systemd":
        assert os_scheduler.enabled == {"mnemos-nova-hour-dream.timer"}
        assert not (units / "mnemos-nova-hour-ours.timer").exists()
        assert "OnCalendar=*-*-* 04:10:00" in (units / "mnemos-nova-hour-dream.timer").read_text()
    else:
        assert not scheduler.cron_has(os_scheduler.crontab, "nova", "hour-ours")
        assert scheduler.cron_has(os_scheduler.crontab, "nova", "hour-dream")
        assert "10 4 * * *" in os_scheduler.crontab
        assert "/usr/bin/backup.sh" in os_scheduler.crontab
    assert [(k, h["on"], h["at"]) for k, h in state.hours_now("nova").items()] == [
        ("mine", False, "08:00"), ("ours", False, "19:00"), ("dream", True, "04:10"),
    ]


def test_online_with_all_covers_mine_and_ours_and_says_the_dream_stays_offline(launchd, claude, capsys):
    assert _hours("on", "all", "--online", "--write") == 0
    out = capsys.readouterr().out
    assert "The dream stays offline: a dream never goes online." in out
    settings = state.hour_settings("nova")
    assert [settings[k]["online"] for k in state.HOUR_KINDS] == [True, True, False]
    assert "dream" not in _kept()["hours"] or "online" not in _kept()["hours"]["dream"]


def test_a_preview_changes_nothing(launchd, claude, capsys):
    for words in (("on", "mine", "--at", "09:00"), ("on", "all", "--online"), ("off", "all"), ("keep",)):
        assert _hours(*words) == 0
        assert "nothing has changed" in capsys.readouterr().out or words == ("keep",)
    assert launchd.calls == [] and launchd.loaded == set()
    assert not _agents().exists()
    assert not state.hours_dir("nova").exists()


def test_the_preview_says_exactly_what_would_change(launchd, claude, capsys):
    assert _hours("on", "mine", "--at", "09:00", "--minutes", "45") == 0
    assert capsys.readouterr().out == (
        "This would change:\n"
        "  its own hour: on, daily at 09:00, up to 45 minutes, offline\n"
        "This is a preview: nothing has changed. To do it, add --write.\n"
    )


def test_keep_records_the_answer_and_changes_nothing(launchd, claude, capsys):
    _legacy(launchd)
    before = {label: (_agents() / f"{label}.plist").read_bytes() for label in (MINE, OURS, DREAM)}
    assert _hours("keep", "--write") == 0
    assert launchd.calls == []
    assert {label: (_agents() / f"{label}.plist").read_bytes() for label in before} == before
    kept = _kept()
    assert kept["answered_at"] and kept["choice"] == "yes"
    assert kept["hours"]["mine"] == {"at": "08:00", "online": True}, "the web it had, now kept"
    assert "Kept as they are." in capsys.readouterr().out


@pytest.mark.parametrize(("words", "said"), [
    ((), "Name an hour: mine, ours, dream or all."),
    (("noon",), "There's no hour called 'noon': they're mine, ours and dream (or all)."),
    (("mine", "--at", "25:00"), "'25:00' isn't a time like 08:00 or 19:30."),
    (("mine", "ours", "--at", "09:00"), "--at sets one hour's time, so name just one: "
                                         "mnemos hours on mine --at 09:00 --write."),
    (("all", "--at", "09:00"), "--at sets one hour's time, so name just one: "
                                "mnemos hours on mine --at 09:00 --write."),
    (("mine", "--minutes", "4"), "--minutes is a whole number from 5 to 120."),
    (("mine", "--minutes", "half"), "--minutes is a whole number from 5 to 120."),
    (("dream", "--online"), "A dream never goes online."),
])
def test_each_refusal_is_one_plain_sentence(launchd, claude, capsys, words, said):
    assert _hours("on", *words, "--write") == 1
    captured = capsys.readouterr()
    assert captured.err == said + "\n" and captured.out == ""
    assert launchd.calls == [] and not state.hours_dir("nova").exists()


def test_without_claude_or_a_scheduler_turning_one_on_is_refused(launchd, no_claude, monkeypatch, capsys):
    assert _hours("on", "mine", "--write") == 1
    err = capsys.readouterr().err
    assert err.startswith("No hour can be turned on here: they run Claude Code's claude command")
    assert err.count("\n") == 1
    assert _hours("off", "mine", "--write") == 0, "turning one off needs no claude"

    monkeypatch.setattr(scheduler, "detect_backend", lambda system=None: "unsupported")
    capsys.readouterr()
    assert _hours("on", "mine", "--write") == 1
    assert capsys.readouterr().err == (
        "This system has no scheduler Mnemos can use (launchd, systemd or crontab), so the "
        "quiet hours can't run here.\n"
    )


def test_hours_shows_each_hour_and_how_to_change_them(launchd, claude, capsys):
    assert _hours("on", "mine", "--at", "09:00", "--write") == 0
    capsys.readouterr()
    assert _hours() == 0
    out = capsys.readouterr().out
    assert "  its own hour  on   daily at 09:00, up to 60 minutes, offline\n" in out
    assert "  our hour      off  would start at 19:00, up to 30 minutes, offline\n" in out
    assert "  the dream     off  would start at 03:30, up to 20 minutes, never online\n" in out
    assert "They run Claude Code on its own, on your Claude plan" in out
    assert "To change them: the Settings on the agent's page (mnemos log), or" in out
    assert "mnemos --agent-id nova hours on mine --at 09:00 --write" in out

    assert _hours("--json") == 0
    report = json.loads(capsys.readouterr().out)
    assert report["hours"]["mine"] == {"on": True, "at": "09:00", "minutes": 60, "online": False}
    assert report["hours"]["dream"]["on"] is False
    assert report["choice"] == "yes" and report["answered_at"]
    assert report["claude"] == str(claude)


# ── daemon install --hours keeps working, and remembers times ──


def test_times_are_remembered_across_daemon_install(launchd, claude):
    assert _hours("on", "mine", "--at", "09:00", "--write") == 0
    assert _hours("off", "mine", "--write") == 0
    assert main(["daemon", "install", *SCOPE, "--hours", "--write"]) == 0
    assert _at(MINE) == (9, 0), "the time remembered, not reset to 08:00"
    assert launchd.loaded == UPKEEP | {MINE, OURS, DREAM}

    assert main(["daemon", "install", *SCOPE, "--hours", "--dream-at", "04:00", "--write"]) == 0
    assert _at(MINE) == (9, 0) and _at(DREAM) == (4, 0) and _at(OURS) == (19, 0)
    assert main(["daemon", "uninstall", *SCOPE, "--hours", "--write"]) == 0
    assert main(["daemon", "install", *SCOPE, "--hours", "--write"]) == 0
    assert _at(DREAM) == (4, 0)


def test_daemon_install_records_the_choice_not_an_answer(launchd, claude):
    assert main(["daemon", "install", *SCOPE, "--hours", "--write"]) == 0
    kept = _kept()
    assert kept["choice"] == "yes" and "answered_at" not in kept
    assert main(["daemon", "uninstall", *SCOPE, "--hours", "--write"]) == 0
    kept = _kept()
    assert kept["choice"] == "no" and "answered_at" not in kept
    assert kept["hours"]["mine"]["at"] == "08:00", "what it had is still remembered"


def test_the_page_turns_them_on_and_off_through_the_same_way(launchd, claude):
    from mnemos.companion.server import quiet_hours
    from mnemos.simple_scope import resolve_scope

    scope = resolve_scope(agent_id="nova", person_id="riley", project_scope="demo")
    assert _hours("on", "mine", "--at", "06:30", "--write") == 0
    assert "result" in quiet_hours(scope, {"on": True})
    assert _at(MINE) == (6, 30), "the page no longer resets a time it didn't name"
    assert "result" in quiet_hours(scope, {"on": False})
    assert not {MINE, OURS, DREAM} & launchd.loaded


# ── What connect says ──


def test_connect_says_each_claude_code_hour_and_no_contradiction(launchd, claude):
    h = harnesses.get("claude-code")
    assert connect_cmd._hours_gaps(h) == []
    assert not any("quiet hours" in note.lower() for note in h.notes)

    class _Status:
        agent_id = "nova"

    assert connect_cmd._hours_status(h, _Status()) == "off; never asked"
    state.record_hours_choice("nova", "no")
    assert connect_cmd._hours_status(h, _Status()) == "off; you said no"
    assert _hours("on", "mine", "--write") == 0
    assert _hours("on", "dream", "--write") == 0
    assert connect_cmd._hours_status(h, _Status()) == "own hour 08:00, our hour off, dream 03:30"


def test_the_other_agents_still_say_their_hours(launchd):
    for key in ("hermes", "openclaw", "codex"):
        assert connect_cmd._hours_gaps(harnesses.get(key)), key


def test_doctor_says_each_hour(launchd, claude, capsys):
    assert main([*SCOPE[:2], "doctor"]) in (0, 1)
    assert "Quiet hours:  off ('mnemos hours' shows them, and turns each one on)" in capsys.readouterr().out
    assert _hours("on", "ours", "--write") == 0
    capsys.readouterr()
    assert main([*SCOPE[:2], "doctor"]) in (0, 1)
    assert "Quiet hours:  on: our hour at 19:00" in capsys.readouterr().out


def test_setup_cli_has_no_question_left():
    assert not hasattr(cli, "QUIET_HOURS_QUESTION")
