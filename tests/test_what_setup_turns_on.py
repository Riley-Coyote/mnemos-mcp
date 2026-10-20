"""What setup turns on for a newcomer (0.4.0).

Setup is `mnemos hooks install claude-code --write` for Claude Code (after
`mnemos mcp install claude-code --write`), `mnemos hooks install codex
--write` for Codex, and `mnemos mcp install claude --write` for Claude
Desktop. Unless told not to, it now:

- installs the cue, for Claude Code (tests/test_the_cue.py);
- schedules upkeep between sessions (`--no-upkeep` leaves it out), which with
  no model chosen for Mnemos runs local passes only;
- asks once, at a terminal, whether to schedule the quiet hours, yes by
  default. Without a terminal it schedules nothing and says how; without a
  claude command it says that, and schedules nothing.

`mnemos daemon install --hours` schedules the quiet hours by hand, and
`mnemos daemon uninstall --hours` takes only them off.

Every scheduler here is the suite's fake (tests/conftest.py): nothing reaches
the machine running the tests.
"""

from __future__ import annotations

import json
import os
import plistlib
import socket
import sqlite3
import urllib.request
from pathlib import Path

import pytest

from mnemos import cli
from mnemos.cli import main
from mnemos.setup import scheduler

SCOPE = ["--agent-id", "nova", "--person-id", "riley", "--project-scope", "demo"]
LABELS = {f"com.mnemos.nova.{name}" for name in ("maintain", "maintain-deep")}
HOURS = {f"com.mnemos.nova.{name}" for name in ("hour-mine", "hour-ours")}


@pytest.fixture
def launchd(monkeypatch, os_scheduler):
    monkeypatch.setattr(scheduler, "detect_backend", lambda system=None: "launchd")
    return os_scheduler


@pytest.fixture
def claude(tmp_path, monkeypatch) -> Path:
    """A claude command on PATH, where Claude Code's installer leaves one."""
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


def _plists() -> set[str]:
    """The labels of the jobs launchd would load from LaunchAgents."""
    return {path.stem for path in _agents().glob("*.plist")}


def _plist(label: str) -> dict:
    return plistlib.loads((_agents() / f"{label}.plist").read_bytes())


def _claude_code(tmp_path, *extra: str) -> int:
    return main(["hooks", "install", "claude-code", "--settings", str(tmp_path / "settings.json"),
                 *SCOPE, "--write", *extra])


def _answers(monkeypatch, *replies: str) -> list[str]:
    """Someone at the terminal, giving ``replies`` in turn. Returns the
    questions asked."""
    asked: list[str] = []
    queue = list(replies)

    def answer(question: str = "") -> str:
        asked.append(question)
        return queue.pop(0)

    monkeypatch.setattr(cli, "_can_ask", lambda: True)
    monkeypatch.setattr("builtins.input", answer)
    return asked


def _nobody_asked(monkeypatch) -> None:
    """Someone at the terminal, who must never be asked."""
    monkeypatch.setattr(cli, "_can_ask", lambda: True)

    def never(question: str = "") -> str:
        raise AssertionError(f"asked: {question}")

    monkeypatch.setattr("builtins.input", never)


# ── Upkeep, on by default ──


def test_claude_codes_setup_schedules_upkeep_by_default(tmp_path, launchd, no_claude, capsys):
    assert _claude_code(tmp_path) == 0
    out = capsys.readouterr().out

    assert _plists() == LABELS
    assert launchd.loaded == LABELS
    upkeep = _plist("com.mnemos.nova.maintain")
    assert upkeep["ProgramArguments"][1:] == [
        "--agent-id", "nova", "--person-id", "riley", "--project-scope", "demo",
        "--db-path", str(Path.home() / ".mnemos" / "nova.db"), "consolidate",
    ]
    assert upkeep["WorkingDirectory"] == str(Path.home() / ".mnemos")
    assert (Path.home() / ".mnemos").is_dir(), "the folder every job runs in"
    assert "Upkeep between sessions is on (launchd)" in out
    assert "local passes only: nothing leaves this machine" in out
    assert "Turn it off: mnemos daemon uninstall --write" in out


def test_no_upkeep_leaves_the_schedule_as_it_is(tmp_path, launchd, no_claude, capsys):
    assert _claude_code(tmp_path, "--no-upkeep") == 0

    assert not _agents().exists()
    assert launchd.calls == []
    assert "not scheduled (--no-upkeep)" in capsys.readouterr().out
    assert "SessionStart" in json.loads((tmp_path / "settings.json").read_text())["hooks"]


def test_setup_again_replaces_upkeep_rather_than_stacking_it(tmp_path, launchd, no_claude, capsys):
    assert _claude_code(tmp_path) == 0
    assert _claude_code(tmp_path) == 0

    assert _plists() == LABELS
    assert launchd.loaded == LABELS
    bootstraps = [call for call in launchd.calls if call[1] == "bootstrap"]
    assert len(bootstraps) == 4, "each install loads each job once"


def test_codex_setup_schedules_upkeep_and_never_asks_about_hours(tmp_path, launchd, claude, monkeypatch, capsys):
    _nobody_asked(monkeypatch)
    settings = tmp_path / "hooks.json"

    assert main(["hooks", "install", "codex", "--settings", str(settings), *SCOPE, "--write"]) == 0

    assert launchd.loaded == LABELS
    assert "Quiet hours" not in capsys.readouterr().out

    _agents_before = {path.name for path in _agents().iterdir()}
    assert main(["hooks", "install", "codex", "--settings", str(settings), *SCOPE, "--write",
                 "--no-upkeep"]) == 0
    assert {path.name for path in _agents().iterdir()} == _agents_before


def test_claude_desktops_setup_schedules_upkeep_too(launchd, no_claude, monkeypatch, capsys):
    """For Claude Desktop, `mnemos mcp install claude --write` is all of setup."""
    monkeypatch.setattr(cli.sys, "platform", "darwin")
    assert main(["mcp", "install", "claude", "--agent-id", "nova", "--write"]) == 0

    config = Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    assert "mnemos" in json.loads(config.read_text())["mcpServers"]
    assert launchd.loaded == LABELS
    out = capsys.readouterr().out
    assert "Upkeep between sessions is on" in out and "Quiet hours: off" in out

    launchd.loaded.clear()
    for path in _agents().iterdir():
        path.unlink()
    assert main(["mcp", "install", "claude", "--agent-id", "nova", "--write", "--no-upkeep"]) == 0
    assert launchd.loaded == set() and not any(_agents().iterdir())


@pytest.mark.parametrize("backend", ["systemd", "crontab"])
def test_upkeep_on_linux_schedulers(tmp_path, monkeypatch, os_scheduler, no_claude, backend, capsys):
    monkeypatch.setattr(scheduler, "detect_backend", lambda system=None: backend)
    os_scheduler.crontab = "0 9 * * * /usr/bin/backup.sh\n"

    assert _claude_code(tmp_path) == 0

    if backend == "systemd":
        units = Path.home() / ".config" / "systemd" / "user"
        assert {path.name for path in units.iterdir()} == {
            f"mnemos-nova-{name}.{kind}" for name in ("maintain", "maintain-deep")
            for kind in ("service", "timer")
        }
        assert "WorkingDirectory=" in (units / "mnemos-nova-maintain.service").read_text()
        assert os_scheduler.enabled == {"mnemos-nova-maintain.timer", "mnemos-nova-maintain-deep.timer"}
    else:
        assert scheduler.cron_has(os_scheduler.crontab, "nova", "maintain")
        assert scheduler.cron_has(os_scheduler.crontab, "nova", "maintain-deep")
        assert os_scheduler.crontab.startswith("0 9 * * * /usr/bin/backup.sh\n"), "theirs stays"
    assert f"Upkeep between sessions is on ({backend})" in capsys.readouterr().out


def test_with_no_scheduler_setup_says_so_and_succeeds(tmp_path, monkeypatch, os_scheduler, capsys):
    monkeypatch.setattr(scheduler, "detect_backend", lambda system=None: "unsupported")
    assert _claude_code(tmp_path) == 0
    assert "only while a session is open" in capsys.readouterr().out
    assert os_scheduler.calls == []


def test_a_scheduler_that_refuses_fails_setup_out_loud(tmp_path, launchd, no_claude, monkeypatch, capsys):
    def refuse(action, plist, *, allow_missing=False):
        if action == "bootstrap":
            raise RuntimeError("Bootstrap failed: 5: Input/output error")

    monkeypatch.setattr(cli, "_launchctl", refuse)
    assert _claude_code(tmp_path) == 1
    out = capsys.readouterr().out
    assert "Upkeep between sessions: not scheduled (Bootstrap failed" in out
    assert "mnemos daemon install --write" in out


# ── With no model chosen, upkeep is local ──


def _offline(monkeypatch) -> list:
    """Every way out of the machine, caught and counted."""
    tried: list = []

    def connect(self, address):
        if isinstance(address, tuple) and address[0] in {"127.0.0.1", "::1", "localhost"}:
            return real_connect(self, address)
        tried.append(address)
        raise OSError("the network is off for this test")

    def urlopen(request, *args, **kwargs):
        tried.append(getattr(request, "full_url", request))
        raise OSError("the network is off for this test")

    real_connect = socket.socket.connect
    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    return tried


def test_upkeep_runs_local_passes_only_with_no_model_chosen(tmp_path, monkeypatch, capsys):
    """The jobs setup schedules, run as scheduled, with provider keys around
    for other tools and no model chosen for Mnemos: every pass runs, nothing
    tries to leave the machine, and the cycle records that no model did
    any of it."""
    from mnemos.simple_runtime import MnemosRuntime

    db = Path.home() / ".mnemos" / "nova.db"
    runtime = MnemosRuntime(db_path=str(db), agent_id="nova", person_id="riley",
                            project_scope="demo", use_dedicated_model=False)
    try:
        for words in (
            "Riley keeps the lighthouse logbook in pencil, because ink runs in the damp.",
            "The lighthouse logbook is copied before every autumn inspection.",
            "Riley prefers short replies in the morning and longer ones at night.",
        ):
            runtime.capture(words, signed_as="claude-opus-5-5")
    finally:
        runtime.close()
    for key in ("OPENROUTER_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.setenv(key, "test-key-for-another-tool")
    tried = _offline(monkeypatch)

    blueprint = scheduler.plan(agent_id="nova", mnemos_command="mnemos", backend="launchd",
                               scope_args=cli._scope_args(_scope_namespace(db)))
    assert blueprint["has_model"] is False
    for entry in blueprint["entries"]:
        argv = plistlib.loads(entry["content"])["ProgramArguments"]
        assert main(argv[1:]) == 0, entry["job"].name

    assert tried == [], "upkeep tried to reach the network with no model chosen"
    conn = sqlite3.connect(db)
    try:
        cycles = [json.loads(row[0]) for row in conn.execute(
            "SELECT stats FROM consolidation_log WHERE pass_name = 'cycle' ORDER BY started_at"
        )]
    finally:
        conn.close()
    assert [cycle["cycle_type"] for cycle in cycles][-2:] == ["shallow", "deep"]
    for cycle in cycles[-2:]:
        assert cycle["substrate"] == {
            "model": None, "provider": None,
            "note": "local deterministic passes; judgement left to the agent",
        }
        assert {"connection_discovery", "decay", "softening"} <= set(cycle["passes_run"])
        assert not [key for key in cycle if key.endswith("_error")], cycle
    assert "reflection" in cycles[-1]["passes_run"]

    # The catch sees a send: with a model chosen, the same jobs reach it.
    monkeypatch.setenv("MNEMOS_LLM_PROVIDER", "openrouter")
    for entry in blueprint["entries"]:
        main(plistlib.loads(entry["content"])["ProgramArguments"][1:])
    assert tried and all(str(url).startswith("https://openrouter.ai/") for url in tried), tried


def _scope_namespace(db: Path):
    import argparse

    return argparse.Namespace(db_path=str(db), agent_id="nova", person_id="riley",
                              project_scope="demo")


# ── Quiet hours: asked once, yes by default ──


def test_at_a_terminal_setup_asks_once_and_yes_is_the_default(tmp_path, launchd, claude, monkeypatch, capsys):
    asked = _answers(monkeypatch, "")

    assert _claude_code(tmp_path) == 0

    assert asked == [cli.QUIET_HOURS_QUESTION]
    # In plain words, what they cost: up to an hour and a half a day of Claude,
    # on the person's own plan.
    assert "up to an hour a day that's its own, and half an hour for the day's work" in asked[0]
    assert "they run Claude on its own and use your Claude plan" in asked[0]
    assert asked[0].endswith("[Y/n] ")
    assert launchd.loaded == LABELS | HOURS

    mnemos = cli._mnemos_command()
    for name, kind, at in (("hour-mine", "mine", (8, 0)), ("hour-ours", "ours", (19, 0))):
        job = _plist(f"com.mnemos.nova.{name}")
        assert job["ProgramArguments"] == [
            mnemos, "--agent-id", "nova", "--person-id", "riley", "--project-scope", "demo",
            "--db-path", str(Path.home() / ".mnemos" / "nova.db"), "life", "--hour", kind,
        ]
        assert job["StartCalendarInterval"] == {"Hour": at[0], "Minute": at[1]}
        assert job["WorkingDirectory"] == str(Path.home() / ".mnemos")
        env = job["EnvironmentVariables"]
        assert env["MNEMOS_CLAUDE_BIN"] == str(claude)
        assert env["MNEMOS_LIFE_MNEMOS_BIN"] == mnemos
        assert env["PATH"].split(os.pathsep)[0] == str(claude.parent)
    out = capsys.readouterr().out
    assert "Quiet hours are on: the agent's own hour daily at 08:00, and the day's work at 19:00" in out
    assert "Turn them off: mnemos daemon uninstall --hours --write" in out

    # Setup again: they are on, and nobody is asked twice.
    _nobody_asked(monkeypatch)
    assert _claude_code(tmp_path) == 0
    assert "Quiet hours: on." in capsys.readouterr().out
    assert launchd.loaded == LABELS | HOURS


@pytest.mark.parametrize("reply", ["n", "no", "N", "nope"])
def test_no_leaves_them_off_and_says_how_to_turn_them_on(tmp_path, launchd, claude, monkeypatch, capsys, reply):
    asked = _answers(monkeypatch, reply)
    assert _claude_code(tmp_path) == 0
    assert len(asked) == 1
    assert launchd.loaded == LABELS
    assert "To turn them on later: mnemos daemon install --hours --write" in capsys.readouterr().out


def test_closing_the_input_is_a_no(tmp_path, launchd, claude, monkeypatch, capsys):
    monkeypatch.setattr(cli, "_can_ask", lambda: True)

    def closed(question: str = "") -> str:
        raise EOFError

    monkeypatch.setattr("builtins.input", closed)
    assert _claude_code(tmp_path) == 0
    assert launchd.loaded == LABELS


def test_without_a_terminal_nothing_is_asked_or_scheduled(tmp_path, launchd, claude, capsys):
    """An agent setting Mnemos up for someone runs without a terminal: the
    hours are left for the person to choose, and how is said."""
    assert _claude_code(tmp_path) == 0

    assert launchd.loaded == LABELS
    out = capsys.readouterr().out
    assert "Quiet hours: off. They give the agent up to an hour a day that's its own" in out
    assert "To turn them on: mnemos daemon install --hours --write" in out


def test_without_claude_setup_says_so_and_does_not_ask(tmp_path, launchd, no_claude, monkeypatch, capsys):
    _nobody_asked(monkeypatch)
    assert _claude_code(tmp_path) == 0
    assert launchd.loaded == LABELS
    out = capsys.readouterr().out
    assert "Quiet hours: off, because they run Claude Code's claude command, and none was found" in out


def test_the_claude_login_the_person_set_goes_with_the_hours(tmp_path, launchd, claude, monkeypatch, capsys):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "second-login"))
    _answers(monkeypatch, "y")
    assert _claude_code(tmp_path) == 0
    env = _plist("com.mnemos.nova.hour-mine")["EnvironmentVariables"]
    assert env["CLAUDE_CONFIG_DIR"] == str(tmp_path / "second-login")
    assert "CLAUDE_CONFIG_DIR" not in _plist("com.mnemos.nova.maintain").get("EnvironmentVariables", {})


def test_no_upkeep_still_asks_about_the_hours_and_schedules_only_them(tmp_path, launchd, claude, monkeypatch):
    _answers(monkeypatch, "")
    assert _claude_code(tmp_path, "--no-upkeep") == 0
    assert launchd.loaded == HOURS


# ── mnemos daemon install --hours, by hand ──


def test_daemon_install_hours_previews_then_schedules(launchd, claude, capsys):
    assert main(["daemon", "install", *SCOPE, "--hours"]) == 0
    preview = capsys.readouterr().out
    assert not _agents().exists() and launchd.calls == []
    assert "hour-mine — The agent's own hour" in preview
    assert f"env:      MNEMOS_CLAUDE_BIN={claude}" in preview
    assert "they run Claude on its own and use your Claude plan" in preview

    assert main(["daemon", "install", *SCOPE, "--hours", "--mine-at", "07:30",
                 "--ours-at", "21:15", "--write"]) == 0
    assert launchd.loaded == LABELS | HOURS
    assert _plist("com.mnemos.nova.hour-mine")["StartCalendarInterval"] == {"Hour": 7, "Minute": 30}
    capsys.readouterr()

    assert main(["daemon", "status", *SCOPE]) == 0
    status = capsys.readouterr().out
    assert "hour-mine        scheduled       daily at 07:30" in status
    assert "hour-ours        scheduled       daily at 21:15" in status


def test_daemon_install_without_hours_keeps_hours_already_on(launchd, claude, capsys):
    assert main(["daemon", "install", *SCOPE, "--hours", "--write"]) == 0
    assert main(["daemon", "install", *SCOPE, "--write"]) == 0
    assert launchd.loaded == LABELS | HOURS
    assert _plists() == LABELS | HOURS


def test_daemon_install_hours_without_claude_schedules_upkeep_and_fails(launchd, no_claude, capsys):
    assert main(["daemon", "install", *SCOPE, "--hours", "--write"]) == 1
    assert launchd.loaded == LABELS
    assert "The quiet hours are not scheduled: they run Claude Code's claude command" in capsys.readouterr().out


def test_the_times_need_hours_and_must_be_times(launchd, claude, capsys):
    assert main(["daemon", "install", *SCOPE, "--mine-at", "09:00"]) == 1
    assert "add --hours" in capsys.readouterr().err
    for bad in ("25:00", "9", "07:5", "noon"):
        with pytest.raises(SystemExit) as exited:
            main(["daemon", "install", *SCOPE, "--hours", "--mine-at", bad])
        assert exited.value.code == 2
        assert "is not a time like 08:00" in capsys.readouterr().err


def test_uninstall_hours_takes_off_only_the_hours(launchd, claude, capsys):
    assert main(["daemon", "install", *SCOPE, "--hours", "--write"]) == 0

    assert main(["daemon", "uninstall", *SCOPE, "--hours"]) == 0
    assert "Would remove 2 scheduled job(s)" in capsys.readouterr().out
    assert launchd.loaded == LABELS | HOURS, "a preview removed something"

    assert main(["daemon", "uninstall", *SCOPE, "--hours", "--write"]) == 0
    assert launchd.loaded == LABELS
    assert _plists() == LABELS
    capsys.readouterr()
    assert main(["daemon", "status", *SCOPE]) == 0
    assert "quiet hours      off" in capsys.readouterr().out

    assert main(["daemon", "uninstall", *SCOPE, "--hours", "--write"]) == 0
    assert "The quiet hours aren't scheduled." in capsys.readouterr().out

    assert main(["daemon", "install", *SCOPE, "--hours", "--write"]) == 0
    assert main(["daemon", "uninstall", *SCOPE, "--write"]) == 0
    assert launchd.loaded == set() and not any(_agents().iterdir())
    capsys.readouterr()
    assert main(["daemon", "uninstall", *SCOPE, "--write"]) == 0
    assert "Nothing is scheduled for nova" in capsys.readouterr().out


@pytest.mark.parametrize("backend", ["systemd", "crontab"])
def test_hours_on_and_off_on_linux_schedulers(monkeypatch, os_scheduler, claude, backend, capsys):
    monkeypatch.setattr(scheduler, "detect_backend", lambda system=None: backend)
    os_scheduler.crontab = "0 9 * * * /usr/bin/backup.sh\n"

    assert main(["daemon", "install", *SCOPE, "--hours", "--write"]) == 0
    assert main(["daemon", "install", *SCOPE, "--write"]) == 0, "upkeep again, hours kept"
    if backend == "systemd":
        service = (Path.home() / ".config" / "systemd" / "user" / "mnemos-nova-hour-mine.service").read_text()
        assert f"MNEMOS_CLAUDE_BIN={claude}" in service and "WorkingDirectory=" in service
        assert os_scheduler.enabled >= {"mnemos-nova-hour-mine.timer", "mnemos-nova-hour-ours.timer"}
    else:
        assert scheduler.cron_has(os_scheduler.crontab, "nova", "hour-mine")
        assert scheduler.cron_has(os_scheduler.crontab, "nova", "hour-ours")
    capsys.readouterr()
    assert main(["daemon", "status", *SCOPE]) == 0
    assert "hour-ours        scheduled       daily at 19:00" in capsys.readouterr().out

    assert main(["daemon", "uninstall", *SCOPE, "--hours", "--write"]) == 0
    if backend == "systemd":
        assert not (Path.home() / ".config" / "systemd" / "user" / "mnemos-nova-hour-mine.timer").exists()
        assert "mnemos-nova-hour-mine.timer" not in os_scheduler.enabled
        assert "mnemos-nova-maintain.timer" in os_scheduler.enabled
    else:
        assert not scheduler.cron_has(os_scheduler.crontab, "nova", "hour-mine")
        assert scheduler.cron_has(os_scheduler.crontab, "nova", "maintain")
        assert "/usr/bin/backup.sh" in os_scheduler.crontab


# ── The macOS warning, wherever jobs are scheduled ──


def test_a_mnemos_in_documents_is_warned_about_at_setup(tmp_path, launchd, no_claude, monkeypatch, capsys):
    checkout = Path.home() / "Documents" / "Repositories" / "mnemos" / "mnemos"
    checkout.mkdir(parents=True)
    monkeypatch.setattr(scheduler, "package_folder", lambda: checkout)

    assert _claude_code(tmp_path) == 0
    out = capsys.readouterr().out
    assert "Warning: background jobs will fail on this Mac." in out
    assert "~/Documents/Repositories/mnemos/mnemos" in out

    assert main(["daemon", "install", *SCOPE]) == 0
    assert "background jobs will fail" in capsys.readouterr().out


def test_a_quiet_hour_that_cannot_look_in_documents_still_runs(tmp_path, monkeypatch):
    """A launchd job may not look inside ~/Documents; the hour's folders there
    are left out rather than ending the hour with an error."""
    from mnemos import life

    (Path.home() / "Documents" / "Repositories").mkdir(parents=True)
    real_exists = Path.exists

    def exists(self, *args, **kwargs):
        if "Documents" in self.parts:
            raise PermissionError(1, "Operation not permitted", str(self))
        return real_exists(self, *args, **kwargs)

    monkeypatch.setattr(Path, "exists", exists)
    scope = {"agent_id": "nova", "person_id": "riley", "project_scope": "demo"}
    _mcp, settings, command = life._files_and_command(
        "mine", "hour-1", tmp_path, tmp_path / "store.db", scope, "/usr/bin/true", "mnemos",
    )
    assert "--add-dir" not in command
    assert command[0] == "/usr/bin/true"


@pytest.mark.parametrize("backend", ["launchd", "systemd", "crontab"])
def test_mnemos_log_sees_the_hours_setup_schedules(monkeypatch, os_scheduler, claude, backend, capsys):
    """`mnemos log` reads the quiet hours' schedule from what is installed: the
    jobs scheduled here are the ones it reports, at their times and loaded."""
    from mnemos.companion import export as log_export
    from mnemos.simple_runtime import MnemosRuntime

    monkeypatch.setattr(scheduler, "detect_backend", lambda system=None: backend)
    monkeypatch.setattr(log_export, "_launchd_loaded", lambda label: label in os_scheduler.loaded)
    monkeypatch.setattr(log_export, "_systemd_active", lambda timer: timer in os_scheduler.enabled)
    monkeypatch.setattr(log_export, "_crontab", lambda: os_scheduler.crontab)
    runtime = MnemosRuntime(agent_id="nova", person_id="riley", project_scope="demo",
                            use_dedicated_model=False)
    try:
        runtime.capture("Riley likes the quiet hours early.", signed_as="claude-opus-5-5")
    finally:
        runtime.close()
    exporter = log_export.Exporter.for_scope(agent_id="nova", person_id="riley", project_scope="demo")
    assert exporter.export()[0]["schedule"] == [], "premise: nothing scheduled yet"

    assert main(["daemon", "install", *SCOPE, "--hours", "--mine-at", "07:30", "--write"]) == 0

    found = sorted(exporter.export()[0]["schedule"], key=lambda hour: hour["kind"])
    assert [(hour["kind"], hour["when"], hour["loaded"]) for hour in found] == [
        ("mine", {"Hour": 7, "Minute": 30}, True),
        ("ours", {"Hour": 19, "Minute": 0}, True),
    ]
