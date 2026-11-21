"""An hour's job runs the same mnemos as the agent's upkeep (QH-6, November 2026).

A person may have more than one Mnemos installed: on the maintainer's Mac,
every background job runs a copy kept for launchd (~/.mnemos/runtime/bin),
while the sessions' hooks run an editable checkout from ~/Documents, which a
background job can't read. Changing an hour from a session (`mnemos hours on
mine --at 09:00 --write`, which the onboarding gives the agent) rewrote that
hour's job to run the session's copy. Now an hour's job runs the program this
agent's upkeep job (`maintain`) runs, when that job is scheduled and its
program can run (``scheduler.background_mnemos``); otherwise the mnemos that
ran the command, as before.

Every scheduler here is the suite's fake (tests/conftest.py).
"""

from __future__ import annotations

import plistlib
from pathlib import Path

import pytest

from mnemos import cli
from mnemos.cli import main
from mnemos.setup import scheduler

SCOPE = ["--agent-id", "nova", "--person-id", "riley", "--project-scope", "demo"]
MAINTAIN = "com.mnemos.nova.maintain"
MINE = "com.mnemos.nova.hour-mine"


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


def _program(tmp_path: Path, name: str) -> str:
    """A mnemos command at its own path: a stand-in for one install."""
    folder = tmp_path / name / "bin"
    folder.mkdir(parents=True)
    binary = folder / "mnemos"
    binary.write_text("#!/bin/sh\nexit 0\n")
    binary.chmod(0o755)
    return str(binary)


@pytest.fixture
def installs(tmp_path, monkeypatch):
    """Two installs of Mnemos: the one kept for the scheduler, and the one a
    session runs. ``use(path)`` makes the next command run that one."""
    kept = _program(tmp_path, "runtime")
    session = _program(tmp_path, "checkout")

    def use(path: str) -> None:
        monkeypatch.setattr(cli, "_mnemos_command", lambda: path)

    return kept, session, use


@pytest.fixture(params=["launchd", "systemd", "crontab"])
def backend(request, monkeypatch, os_scheduler):
    monkeypatch.setattr(scheduler, "detect_backend", lambda system=None: request.param)
    os_scheduler.crontab = "0 9 * * * /usr/bin/backup.sh\n"
    return request.param


def _runs(backend: str, os_scheduler, name: str) -> tuple[str, dict]:
    """The program a job runs, and the environment it sets, as installed."""
    blueprint = scheduler.plan(agent_id="nova", mnemos_command="mnemos", has_model=False,
                               backend=backend)
    entry = next(e for e in [*blueprint["entries"], *blueprint["hours"]] if e["job"].name == name)
    found = scheduler.installed_command(blueprint, entry, os_scheduler.crontab)
    assert found, f"{name} isn't installed"
    argv, environment = found
    return argv[0], environment


def test_an_hour_changed_from_a_session_runs_what_the_upkeep_runs(backend, os_scheduler, claude, installs):
    kept, session, use = installs
    use(kept)
    assert main(["daemon", "install", *SCOPE, "--write"]) == 0
    upkeep_before = _runs(backend, os_scheduler, "maintain")

    use(session)
    assert main(["hours", "on", "mine", "--at", "09:00", *SCOPE, "--write"]) == 0

    program, environment = _runs(backend, os_scheduler, "hour-mine")
    assert program == kept
    assert environment["MNEMOS_LIFE_MNEMOS_BIN"] == kept, "the hour and its dry run agree"
    assert _runs(backend, os_scheduler, "maintain") == upkeep_before, "the upkeep is left as it was"
    if backend == "crontab":
        assert "/usr/bin/backup.sh" in os_scheduler.crontab


def test_with_no_upkeep_an_hour_runs_the_mnemos_that_set_it(backend, os_scheduler, claude, installs):
    _kept, session, use = installs
    use(session)
    assert main(["hours", "on", "mine", "--at", "09:00", *SCOPE, "--write"]) == 0
    program, environment = _runs(backend, os_scheduler, "hour-mine")
    assert program == session and environment["MNEMOS_LIFE_MNEMOS_BIN"] == session


def test_an_upkeep_program_that_is_gone_is_not_followed(backend, os_scheduler, claude, installs):
    kept, session, use = installs
    use(kept)
    assert main(["daemon", "install", *SCOPE, "--write"]) == 0
    Path(kept).unlink()

    use(session)
    assert main(["hours", "on", "mine", *SCOPE, "--write"]) == 0
    assert _runs(backend, os_scheduler, "hour-mine")[0] == session


def test_an_upkeep_program_that_cannot_run_is_not_followed(backend, os_scheduler, claude, installs):
    kept, session, use = installs
    use(kept)
    assert main(["daemon", "install", *SCOPE, "--write"]) == 0
    Path(kept).chmod(0o644)

    use(session)
    assert main(["hours", "on", "mine", *SCOPE, "--write"]) == 0
    assert _runs(backend, os_scheduler, "hour-mine")[0] == session


def test_an_upkeep_that_is_not_loaded_is_not_followed(monkeypatch, os_scheduler, claude, installs):
    """A plist left on disk that launchd doesn't have loaded isn't a job
    that runs: nothing says its program still works."""
    monkeypatch.setattr(scheduler, "detect_backend", lambda system=None: "launchd")
    kept, session, use = installs
    use(kept)
    assert main(["daemon", "install", *SCOPE, "--write"]) == 0
    os_scheduler.loaded.discard(MAINTAIN)

    use(session)
    assert main(["hours", "on", "mine", *SCOPE, "--write"]) == 0
    assert _runs("launchd", os_scheduler, "hour-mine")[0] == session


def test_daemon_install_hours_keeps_the_upkeep_and_the_hours_together(backend, os_scheduler, claude, installs):
    """`daemon install` schedules the upkeep again with the mnemos running
    it, as it always has; the hours go with it, not with the copy before."""
    kept, session, use = installs
    use(kept)
    assert main(["daemon", "install", *SCOPE, "--hours", "--write"]) == 0
    use(session)
    assert main(["daemon", "install", *SCOPE, "--hours", "--write"]) == 0
    assert _runs(backend, os_scheduler, "maintain")[0] == session
    assert _runs(backend, os_scheduler, "hour-mine")[0] == session
    assert _runs(backend, os_scheduler, "hour-dream")[0] == session


def test_the_pages_save_follows_the_upkeep_too(monkeypatch, os_scheduler, claude, installs):
    from mnemos.companion.server import quiet_hours
    from mnemos.simple_scope import resolve_scope

    monkeypatch.setattr(scheduler, "detect_backend", lambda system=None: "launchd")
    kept, session, use = installs
    use(kept)
    assert main(["daemon", "install", *SCOPE, "--write"]) == 0
    use(session)
    scope = resolve_scope(agent_id="nova", person_id="riley", project_scope="demo")
    said = quiet_hours(scope, {"hours": {"ours": {"on": True, "at": "20:15"}}})
    assert "error" not in said, said
    assert _runs("launchd", os_scheduler, "hour-ours")[0] == kept


def test_the_path_the_upkeep_runs_with_goes_with_the_hour(monkeypatch, os_scheduler, claude, installs):
    monkeypatch.setattr(scheduler, "detect_backend", lambda system=None: "launchd")
    kept, session, use = installs
    use(kept)
    assert main(["daemon", "install", *SCOPE, "--write"]) == 0
    plist = Path.home() / "Library" / "LaunchAgents" / f"{MAINTAIN}.plist"
    job = plistlib.loads(plist.read_bytes())
    job["EnvironmentVariables"] = {"PATH": "/opt/kept/bin:/usr/bin"}
    plist.write_bytes(plistlib.dumps(job))

    use(session)
    assert main(["hours", "on", "mine", *SCOPE, "--write"]) == 0
    path = _runs("launchd", os_scheduler, "hour-mine")[1]["PATH"].split(":")
    assert path[:2] == [str(claude.parent), "/opt/kept/bin"]
    assert path.count("/usr/bin") == 1


def test_a_crontab_line_is_read_back_as_it_was_written(monkeypatch, os_scheduler):
    monkeypatch.setattr(scheduler, "detect_backend", lambda system=None: "crontab")
    job = next(j for j in scheduler.JOBS if j.name == "maintain")
    line = scheduler.cron_line(
        job, agent_id="nova", mnemos_command="/opt/My Mnemos/bin/mnemos",
        scope_args=("--agent-id", "nova"), environment={"HOME": "/home/it's", "PATH": "/a:/b"},
        working_dir="/home/it's/.mnemos",
    )
    blueprint = scheduler.plan(agent_id="nova", mnemos_command="x", has_model=False, backend="crontab")
    entry = next(e for e in blueprint["entries"] if e["job"].name == "maintain")
    argv, environment = scheduler.installed_command(blueprint, entry, line + "\n")
    assert argv == ["/opt/My Mnemos/bin/mnemos", "--agent-id", "nova", "consolidate"]
    assert environment == {"HOME": "/home/it's", "PATH": "/a:/b"}


def test_a_systemd_unit_is_read_back_as_it_was_written(tmp_path):
    job = next(j for j in scheduler.JOBS if j.name == "maintain")
    service, _timer = scheduler.systemd_units(
        job, agent_id="nova", mnemos_command="/opt/My Mnemos/bin/mnemos",
        environment={"HOME": "/home/100%", "PATH": '/a:/"b"'},
    )
    path = tmp_path / "mnemos-nova-maintain.service"
    path.write_text(service)
    blueprint = {"backend": "systemd", "agent_id": "nova"}
    argv, environment = scheduler.installed_command(blueprint, {"units": [path], "job": job})
    assert argv[0] == "/opt/My Mnemos/bin/mnemos"
    assert environment == {"HOME": "/home/100%", "PATH": '/a:/"b"'}
