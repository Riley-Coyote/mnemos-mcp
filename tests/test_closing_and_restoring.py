"""Closing a runtime folds the store back into its file, and a restore either
holds or says it didn't."""

from __future__ import annotations

import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

from mnemos.cli import main
from mnemos.simple_runtime import MnemosRuntime

SCOPE = {"agent_id": "nova", "person_id": "riley", "project_scope": "mnemos"}


class _FakeEmbedder:
    model_name = "fake-model"
    dims = 4

    def embed(self, text):
        return [1.0, 0.0, 0.0, 0.0]

    def batch_embed(self, texts):
        return [self.embed(text) for text in texts]


def _live_index(rt, embedder=None):
    index = rt._embedding_index
    index._available = True
    index._embedder = embedder or _FakeEmbedder()
    index._init_table()
    return index


def test_closing_folds_the_store_back_into_its_file(tmp_path):
    db = tmp_path / "memory.db"
    rt = MnemosRuntime(db_path=str(db), use_dedicated_model=False, **SCOPE)
    rt._ensure_init()
    _live_index(rt)
    rt.capture("Riley keeps the release notes in docs/releases.")
    rt.close()

    copy = tmp_path / "copy" / "memory.db"
    copy.parent.mkdir()
    shutil.copyfile(db, copy)
    conn = sqlite3.connect(str(copy))
    try:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert "engrams" in tables, "the copy of memory.db alone holds no store"
        contents = [r[0] for r in conn.execute("SELECT content FROM engrams")]
    finally:
        conn.close()
    assert "Riley keeps the release notes in docs/releases." in contents


_PRE = (
    "import os, sys; from mnemos.store import embedding_index as ei; ei._check_local_deps = lambda: False\n"
    "from mnemos.simple_runtime import MnemosRuntime\n"
    "r = MnemosRuntime(db_path={db!r}, use_dedicated_model=False, agent_id='nova', person_id='riley', project_scope='mnemos')\n"
)


def _child(db: Path, body: str) -> str:
    done = subprocess.run(
        [sys.executable, "-c", _PRE.format(db=str(db)) + body],
        capture_output=True, text=True, timeout=120,
    )
    assert done.returncode == 0, done.stderr
    return done.stdout.strip()


def _latest(db: Path) -> str:
    return _child(
        db,
        "r._ensure_init(); h = r._store.get_latest_handoff(agent_id='nova', person_id='riley', "
        "project_scope='mnemos'); print(None if h is None else h['content']); r.close()",
    )


def _cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "mnemos.cli", *args], capture_output=True, text=True, timeout=120,
    )


def test_a_restore_holds_while_another_process_has_the_store_open(tmp_path):
    db = tmp_path / "h.db"
    hid = _child(db, "print(r.handoff('I fixed the parser.').split('Handoff ID: ',1)[1].splitlines()[0]); r.close()")
    made = _cli("backup", "create", "--db-path", str(db))
    assert made.returncode == 0, made.stderr
    backup = made.stdout.split("Backup verified: ", 1)[1].splitlines()[0]

    holder = subprocess.Popen(
        [sys.executable, "-c", _PRE.format(db=str(db))
         + f"r.correct('', target_id={hid!r}, action='forget'); print('forgot', flush=True); "
           "sys.stdin.readline(); r.close()"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
    )
    try:
        assert holder.stdout.readline().strip() == "forgot"
        assert _latest(db) == "None"

        restored = _cli("backup", "restore", backup, "--db-path", str(db), "--force")
        assert restored.returncode == 0, restored.stdout + restored.stderr
        assert "Restore verified" in restored.stdout

        assert _latest(db) == "I fixed the parser."
    finally:
        holder.stdin.write("\n")
        holder.stdin.flush()
        holder.wait(timeout=120)
    assert _latest(db) == "I fixed the parser."


class _Conn:
    """A connection whose backup writes nothing into one chosen file."""

    def __init__(self, conn, path, skip):
        self._conn, self._path, self._skip = conn, path, skip

    def backup(self, target, *args, **kwargs):
        if target._path == self._skip:
            return None
        return self._conn.backup(target._conn, *args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._conn, name)


def test_a_restore_that_cannot_hold_says_so(tmp_path, monkeypatch, capsys):
    import mnemos.store.embedding_index as ei

    monkeypatch.setattr(ei, "_check_local_deps", lambda: False)
    db = tmp_path / "memory.db"
    rt = MnemosRuntime(db_path=str(db), use_dedicated_model=False, **SCOPE)
    rt.capture("Riley keeps the release notes in docs/releases.")
    rt.close()
    assert main(["backup", "create", "--db-path", str(db)]) == 0
    backup = capsys.readouterr().out.split("Backup verified: ", 1)[1].splitlines()[0]
    rt = MnemosRuntime(db_path=str(db), use_dedicated_model=False, **SCOPE)
    rt.capture("The staging server restarts every Sunday night.")
    rt.close()

    real_connect = sqlite3.connect
    skip = str(db.resolve())

    def connect(target, *args, **kwargs):
        return _Conn(real_connect(target, *args, **kwargs), str(target), skip)

    monkeypatch.setattr(sqlite3, "connect", connect)
    code = main(["backup", "restore", backup, "--db-path", str(db), "--force"])
    out = capsys.readouterr()
    assert code == 1, out.out + out.err
    assert "The restore didn't hold" in out.out + out.err
    assert "Restore verified" not in out.out


def test_the_restore_check_sees_a_changed_row_not_only_a_lost_one(tmp_path):
    """A forget that only archived a row leaves every count as it was: the
    check compares each row, so a restore that undid it is still caught."""
    import shutil
    import sqlite3

    from mnemos.backup import _restore_marks
    from mnemos.simple_runtime import MnemosRuntime

    db = tmp_path / "memory.db"
    runtime = MnemosRuntime(db_path=str(db), agent_id="demo", person_id="riley", project_scope="demo")
    runtime.capture("Riley plans every trip around the ferry timetable.", signed_as="claude-opus-5-5")
    runtime.close()
    copy = tmp_path / "copy.db"
    shutil.copy(db, copy)
    conn = sqlite3.connect(copy)
    conn.execute("UPDATE engrams SET state = 'archived'")
    conn.commit()
    conn.close()
    before, after = _restore_marks(db), _restore_marks(copy)
    assert before["engrams"].split(",")[0] == after["engrams"].split(",")[0]  # the same number of rows
    assert before["engrams"] != after["engrams"]
