"""The transcript indexer is retired (0.4.0).

`mnemos index` had a model pull "facts" out of old conversations and file
them as the agent's memories: on one install about 7,000 of them against 13
the agent kept itself. Only the agent writes its memory. The indexer, its
console script (`mnemos-index-session`) and what the wheel shipped of it are
gone; `mnemos index` stays only to say so, and exits non-zero. The first
`mnemos daemon install` scheduled it every 30 minutes when a provider was
configured, so installing the background jobs takes that job off a machine an
earlier install left it on, as it does the substrate's tick.

What it wrote stays where it is, a tool's words, which the quarantine repair
still moves out of recall.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

from mnemos import cli
from mnemos.setup import scheduler
from tests.test_the_substrate_is_retired import ROOT, _wheel_files


@pytest.mark.parametrize("argv", [
    ["index"],
    ["index", "--backfill"],
    ["--agent-id", "nova", "--db-path", "/tmp/nowhere/nova.db", "index"],
])
def test_the_command_says_plainly_it_is_retired_and_why(capsys, argv):
    assert cli.main(argv) == 1
    said = capsys.readouterr()
    assert said.out == ""
    assert said.err.startswith("mnemos index is retired.\n")
    assert "a model pull \"facts\" out of old conversations" in said.err
    assert "Only the agent writes its memory" in said.err
    assert "mnemos repair quarantine-tool-written" in said.err


def test_it_writes_nothing(tmp_path, capsys):
    db = tmp_path / "memory.db"
    assert cli.main(["--db-path", str(db), "index"]) == 1
    assert not db.exists()
    assert not (Path.home() / ".mnemos").exists()


def test_the_package_is_gone(monkeypatch):
    for name in [n for n in sys.modules if n == "mnemos.indexer" or n.startswith("mnemos.indexer.")]:
        monkeypatch.delitem(sys.modules, name)
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("mnemos.indexer")


def test_the_wheel_ships_nothing_of_it_and_no_script_for_it():
    files = _wheel_files()
    assert "mnemos/cli.py" in files, "premise: the list holds the package's files"
    assert [f for f in files if f.startswith("mnemos/indexer/")] == []

    try:
        import tomllib
    except ModuleNotFoundError:  # Python 3.10
        tomllib = pytest.importorskip("tomli")
    with (ROOT / "pyproject.toml").open("rb") as handle:
        scripts = tomllib.load(handle)["project"]["scripts"]
    assert scripts == {"mnemos": "mnemos.cli:main"}


def test_installing_takes_off_the_indexer_job_an_earlier_install_left(monkeypatch, os_scheduler, capsys):
    monkeypatch.setattr(scheduler, "detect_backend", lambda system=None: "launchd")
    agents = Path.home() / "Library" / "LaunchAgents"
    agents.mkdir(parents=True)
    old = agents / "com.mnemos.nova.index.plist"
    old.write_bytes(b"<plist/>")
    os_scheduler.loaded.add("com.mnemos.nova.index")

    assert cli.main(["daemon", "status", "--agent-id", "nova"]) == 0
    assert "index            retired" in capsys.readouterr().out

    assert cli.main(["daemon", "install", "--agent-id", "nova"]) == 0
    preview = capsys.readouterr().out
    assert old.exists(), "a preview removed something"
    assert "index — an earlier install scheduled it; it is removed" in preview

    assert cli.main(["daemon", "install", "--agent-id", "nova", "--write"]) == 0
    assert not old.exists()
    assert "com.mnemos.nova.index" not in os_scheduler.loaded
    assert ("launchctl", "bootstrap", "com.mnemos.nova.index") not in os_scheduler.calls
    assert {path.stem for path in agents.glob("*.plist")} == {
        "com.mnemos.nova.maintain", "com.mnemos.nova.maintain-deep",
    }


def test_setup_takes_it_off_a_crontab_too(monkeypatch, os_scheduler, tmp_path, capsys):
    monkeypatch.setattr(scheduler, "detect_backend", lambda system=None: "crontab")
    [index] = [job for job in scheduler.RETIRED_JOBS if job.name == "index"]
    old = scheduler.cron_line(index, agent_id="nova", mnemos_command="/usr/local/bin/mnemos")
    theirs = scheduler.cron_line(index, agent_id="vega", mnemos_command="/usr/local/bin/mnemos")
    os_scheduler.crontab = f"0 9 * * * /usr/bin/backup.sh\n{old}\n{theirs}\n"

    assert cli.main(["hooks", "install", "claude-code", "--settings", str(tmp_path / "s.json"),
                     "--agent-id", "nova", "--write"]) == 0

    assert not scheduler.cron_has(os_scheduler.crontab, "nova", "index")
    assert scheduler.cron_has(os_scheduler.crontab, "nova", "maintain")
    assert scheduler.cron_has(os_scheduler.crontab, "vega", "index"), "another agent's line is theirs"
    assert "/usr/bin/backup.sh" in os_scheduler.crontab
