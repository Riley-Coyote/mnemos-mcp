"""Attribution preserves historical evidence and the prompt cue's read path."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from contextlib import closing

import pytest

from mnemos.attribution import bind_origin, register_hook_origin, stored_origin
from mnemos.core.engram import Engram
from mnemos.simple_runtime import MnemosRuntime
from mnemos.store.sqlite_store import EngramStore


THREAD = "origin-thread-123"
WORDS = "The copper lantern keeper closes the storm shutters each evening."


@pytest.mark.parametrize("snapshot", [
    {"thread_id": THREAD},
    {"thread_id": THREAD, "project_id": "original-project"},
])
def test_promotion_does_not_fill_historical_gaps_from_current_registration(
    tmp_path, monkeypatch, snapshot,
):
    monkeypatch.setattr("mnemos.store.embedding_index._check_local_deps", lambda: False)
    runtime = MnemosRuntime(db_path=str(tmp_path / "memory.db"), use_dedicated_model=False)
    try:
        runtime._ensure_init()
        store = runtime._store
        with bind_origin(snapshot):
            note = store.write_hypomnema_entry(WORDS, authored_by="agent", **runtime._scope_args())
        store.revise_hypomnema_entry(
            note, WORDS + " Check before sunset.",
            author_model="gpt-6.1-sol", revised_by="gpt-6.1-sol", reason="Add timing.",
            **runtime._scope_args(),
        )
        for session in ("first-reader-123", "second-reader-123"):
            with bind_origin({"thread_id": session}):
                runtime.recall(note)
        register_hook_origin(store, {
            "session_id": THREAD,
            "cwd": "/later/workspace",
            "mnemos_origin": {
                "project_id": "later-project", "project_name": "Later project",
                "thread_title": "Later title",
            },
        }, runtime.scope)
        with bind_origin({"thread_id": "maintainer-thread-123"}):
            result = runtime._promote_candidates()
        assert result["promoted"] == 1
        promoted = store.get_engram(result["candidates"][0]["memory_id"])
        assert promoted.origin == snapshot
        assert stored_origin(store.get_hypomnema_entry(note, **runtime._scope_args())) == snapshot
    finally:
        runtime.close()


def _prompt(db, home, *, origin=True):
    payload = {
        "session_id": THREAD, "hook_event_name": "UserPromptSubmit", "prompt": WORDS,
    }
    if origin:
        payload["mnemos_origin"] = {"project_id": "current-project"}
    return subprocess.run(
        [sys.executable, "-m", "mnemos.cli", "hook", "prompt", "--db-path", str(db),
         "--agent-id", "default", "--person-id", "user", "--project-scope", "global"],
        input=json.dumps(payload), text=True, capture_output=True, timeout=10,
        env={
            **os.environ, "HOME": str(home), "MNEMOS_DISABLE_DOTENV": "1",
            "MNEMOS_EMBEDDING_PROVIDER": "off", "MNEMOS_CUE_JUDGE": "off",
        },
    )


def test_optional_registration_does_not_block_a_readable_cue(tmp_path):
    path = tmp_path / "memory.db"
    store = EngramStore(path)
    memory = Engram(content=WORDS, kind="semantic", person_id="user", project_scope="global")
    store.save_engram(memory)
    store.close()
    blocker = sqlite3.connect(path)
    blocker.execute("BEGIN IMMEDIATE")
    try:
        baseline = _prompt(path, tmp_path / "baseline-home", origin=False)
        enriched = _prompt(path, tmp_path / "enriched-home")
    finally:
        blocker.rollback()
        blocker.close()
    assert baseline.returncode == enriched.returncode == 0
    assert memory.id in baseline.stdout
    assert memory.id in enriched.stdout


@pytest.mark.parametrize("existing", [False, True])
def test_prompt_registration_never_creates_or_migrates_a_store(tmp_path, existing):
    path = tmp_path / "memory.db"
    if existing:
        with closing(sqlite3.connect(path)) as conn, conn:
            conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
            conn.execute("INSERT INTO meta VALUES ('schema_version', '19')")
    result = _prompt(path, tmp_path / "home")
    assert result.returncode == 0
    assert path.exists() == existing
    if existing:
        with closing(sqlite3.connect(path)) as conn:
            assert conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone() == ("19",)
            assert conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall() == [("meta",)]
            registered = conn.execute("SELECT value FROM meta WHERE key LIKE 'entry_origin:%'").fetchone()
            assert json.loads(registered[0])["project_id"] == "current-project"
