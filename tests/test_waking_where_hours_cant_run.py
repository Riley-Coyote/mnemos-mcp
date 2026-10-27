"""Waking where the quiet hours can't run (Windows).

The hours' runner, ``mnemos.life``, locks with fcntl, which Windows doesn't
have, so there the module can't be imported. To show the newest quiet hour
once, the wake asks that module where an hour keeps its records, and it
imported it one line above the guard that turns any failure there into "no
hour". So an agent waking as itself (a model that signs its memories, from its
second session on) got "Error executing tool mnemos_context" instead of its
wake. The Windows black box never signed, so it never reached that path.
`mnemos life` failed there the same way, with a traceback.

These tests make importing ``mnemos.life`` fail, as it fails on Windows.
"""

from __future__ import annotations

import sys

import mnemos
from mnemos.cli import main
from mnemos.simple_runtime import MnemosRuntime

SCOPE = {"agent_id": "nova", "person_id": "riley", "project_scope": "demo"}
SCOPE_ARGS = ["--agent-id", "nova", "--person-id", "riley", "--project-scope", "demo"]
OPUS = "claude-opus-5-5"
NOTE = "Where I stopped: the ferry timetable changes on the first of May."


def _runtime(db) -> MnemosRuntime:
    return MnemosRuntime(db_path=str(db), use_dedicated_model=False, **SCOPE)


def _as_on_windows(monkeypatch) -> None:
    """Make importing the hours' runner fail, as it fails on Windows: nothing
    in sys.modules, and nothing on the package either, where an earlier
    test's import leaves it and ``from . import life`` would find it."""
    monkeypatch.setitem(sys.modules, "mnemos.life", None)
    monkeypatch.delattr(mnemos, "life", raising=False)


def test_an_agent_waking_as_itself_wakes_where_the_hours_cant_run(tmp_path, monkeypatch):
    db = tmp_path / "m.db"
    monkeypatch.setenv("MNEMOS_AGENT_MODEL", OPUS)
    writer = _runtime(db)
    try:
        writer.introduce(OPUS)
        writer.capture("The ferry office keeps the timetable on the harbour wall.", signed_as=OPUS)
        writer.handoff(NOTE, signed_as=OPUS)
    finally:
        writer.close()

    _as_on_windows(monkeypatch)
    reader = _runtime(db)
    try:
        wake = reader.context()
    finally:
        reader.close()

    # It woke as itself, the wake that looks for the newest hour, with its note.
    assert "### where i was" in wake, wake
    assert NOTE in wake, wake


def test_mnemos_life_says_plainly_where_the_hours_cant_run(tmp_path, monkeypatch, capsys):
    _as_on_windows(monkeypatch)
    db = tmp_path / "m.db"

    code = main(["--db-path", str(db), *SCOPE_ARGS, "life", "--hour", "mine"])

    err = capsys.readouterr().err
    assert code == 1
    assert "The quiet hours can't run on this system" in err, err
    assert "they run on macOS and Linux" in err, err
    assert not db.exists()
