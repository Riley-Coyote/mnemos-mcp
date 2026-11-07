"""Two things every agent's memory leans on, from outside its own process: how long
opening a store waits for someone in its way, and what code its background upkeep
runs.
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import time

import pytest

from mnemos import simple_runtime
from mnemos.simple_scope import resolve_scope
from mnemos.store.sqlite_store import EngramStore

_HOLD = """
import sqlite3, sys, time
conn = sqlite3.connect(sys.argv[1], isolation_level=None)
conn.execute("PRAGMA locking_mode=EXCLUSIVE")
conn.execute("BEGIN IMMEDIATE")
conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('held', 'yes')")
print("held", flush=True)
time.sleep(60)
"""


def test_a_held_store_is_given_up_on_inside_what_a_hook_has(tmp_path):
    # A session-start hook has fifteen seconds. Waiting out each step of opening in
    # turn, it sat for more than thirty and was killed, and the session woke with
    # nothing and no reason why.
    db = tmp_path / "memory.db"
    EngramStore(db).close()
    holder = subprocess.Popen([sys.executable, "-c", _HOLD, str(db)], stdout=subprocess.PIPE, text=True)
    try:
        assert holder.stdout.readline().strip() == "held"
        began = time.monotonic()
        with pytest.raises(sqlite3.OperationalError, match="locked"):
            EngramStore(db)
        assert time.monotonic() - began < 12
    finally:
        holder.kill()
        holder.wait()
        holder.stdout.close()
    EngramStore(db).close()


def _fake_mnemos(folder, says: str) -> None:
    package = folder / "mnemos"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("")
    (package / "simple_runtime.py").write_text(
        f"def run_background_upkeep(argv):\n    print({says!r})\n    return 0\n"
    )


def test_upkeep_imports_from_where_its_parent_does(tmp_path):
    # A checkout run beside an older install: the parent runs the checkout, and the
    # child, with the install on its own path first, ran the old code on the store.
    _fake_mnemos(tmp_path / "checkout", "the checkout")
    _fake_mnemos(tmp_path / "installed", "the old install")
    parents_path = [str(tmp_path / "checkout"), str(tmp_path / "installed"), *sys.path]
    done = subprocess.run(
        [sys.executable, "-c", simple_runtime._UPKEEP_CHILD, json.dumps(parents_path)],
        env={**os.environ, "PYTHONPATH": str(tmp_path / "installed")},
        cwd=tmp_path, capture_output=True, text=True, timeout=60,
    )
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == "the checkout"


def test_upkeep_is_told_the_folder_its_parent_runs_in(tmp_path, monkeypatch):
    # The child runs somewhere else, so an empty entry would mean somewhere else.
    started = []

    class Child:
        def poll(self):
            return 0

    def popen(command, **options):
        started.append(command)
        return Child()

    monkeypatch.setattr(simple_runtime.subprocess, "Popen", popen)
    monkeypatch.setattr(simple_runtime, "_UPKEEP_CHILDREN", [])
    monkeypatch.setattr(sys, "path", ["", *sys.path])
    monkeypatch.chdir(tmp_path)
    scope = resolve_scope(agent_id="a", db_path=str(tmp_path / "a.db"))
    assert simple_runtime._spawn_upkeep(scope, "token")
    paths = json.loads(started[0][3])
    assert paths[0] == os.getcwd() and "" not in paths
