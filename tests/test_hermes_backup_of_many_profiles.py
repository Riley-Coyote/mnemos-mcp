"""A backup of many profiles doesn't run out of open files.

``hermes backup`` is a short process with the shell's limit on open files,
256 on a Mac. ``backup_paths()`` keeps a read open on every profile's memory
until the copy is done, each one three files (the memory, its log, its shared
index), and never asked for more room, as a conversation's start does. With a
hundred profiles the reads took every file the process had: the last memories
couldn't be held still, and Hermes, writing the archive next, couldn't open
the files it had just been named.

Now ``backup_paths()`` makes room first, as a start does
(``_make_room_for_files``).
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

resource = pytest.importorskip("resource")

_BACKUP = """
import resource, sys, zipfile
resource.setrlimit(resource.RLIMIT_NOFILE, (256, resource.getrlimit(resource.RLIMIT_NOFILE)[1]))
from mnemos.integrations.hermes import MnemosMemoryProviderCore
named = MnemosMemoryProviderCore().backup_paths()
with zipfile.ZipFile(sys.argv[1], "w") as archive:  # what Hermes does next: read each one
    for path in named:
        archive.write(path, path.replace("/", "_"))
print(len(named), resource.getrlimit(resource.RLIMIT_NOFILE)[0])
"""

_PROFILES = 100


def test_a_backup_of_a_hundred_profiles_names_and_reads_every_memory(tmp_path):
    hard = resource.getrlimit(resource.RLIMIT_NOFILE)[1]
    if hard != resource.RLIM_INFINITY and hard < 1024:
        pytest.skip("this machine's ceiling leaves no room to make")
    home = tmp_path / "home"
    root = home / ".hermes"
    memories = home / ".mnemos"
    memories.mkdir(parents=True)
    for i in range(_PROFILES):
        store = memories / f"hermes-p{i}.db"
        conn = sqlite3.connect(store)
        conn.execute("PRAGMA journal_mode=WAL")
        for table in ("engrams", "connections", "versions", "meta"):  # Mnemos's own tables
            conn.execute(f"CREATE TABLE {table} (x)")
        conn.commit()
        conn.close()
        profile = root / "profiles" / f"p{i}"
        profile.mkdir(parents=True)
        (profile / "mnemos.json").write_text(json.dumps({"db_path": str(store), "agent_id": f"hermes-p{i}"}))
    env = {**os.environ, "HOME": str(home), "HERMES_HOME": str(root)}
    env.pop("PYTHONPATH", None)

    done = subprocess.run(
        [sys.executable, "-c", _BACKUP, str(tmp_path / "backup.zip")],
        env=env, capture_output=True, text=True, timeout=120,
        cwd=str(Path(__file__).resolve().parents[1]),
    )

    assert done.returncode == 0, done.stderr[-2000:]
    named, soft = (int(word) for word in done.stdout.split())
    assert named == 2 * _PROFILES, "a memory or its log was left out"
    assert soft > 256
