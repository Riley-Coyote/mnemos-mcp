"""Provenance labels a task without changing who can recall its memories."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from threading import Barrier

import pytest

from mnemos.attribution import (
    bind_origin,
    current_origin,
    register_hook_origin,
    stored_origin,
)
from mnemos.core.engram import Engram
from mnemos.integrations.codex_origin import enrich_payload
from mnemos.simple_runtime import MnemosRuntime
from mnemos.store.sqlite_store import EngramStore

FIRST = "11111111-1111-7111-8111-111111111111"
SECOND = "22222222-2222-7222-8222-222222222222"
ORIGIN = {
    "thread_id": FIRST,
    "session_id": FIRST,
    "project_id": "project-one",
    "project_name": "Mnemos",
    "thread_title": "Attribution",
}


def test_origin_is_snapshotted_for_captures_handoffs_journals_and_notes(tmp_path):
    runtime = MnemosRuntime(
        db_path=str(tmp_path / "memory.db"), use_dedicated_model=False
    )
    try:
        with bind_origin(ORIGIN):
            runtime.introduce("gpt-6.1-sol")
            runtime.capture("The provenance check uses durable copper lanterns.")
            runtime.handoff("Next: check copper lanterns.")
            runtime.journal("I checked the provenance of copper lanterns.")
            runtime.note("I found the copper lantern origin.", kind="noticed")
        store = runtime._store
        for table in ("engrams", "hypomnema_entries", "journal_entries", "notes"):
            rows = (
                store._get_conn().execute(f"SELECT origin_json FROM {table}").fetchall()
            )
            assert rows and all(json.loads(row[0]) == ORIGIN for row in rows)
        with bind_origin({"thread_id": SECOND, "session_id": FIRST}):
            assert runtime.session_identity() == ("", "")  # no inherited introduction
            found = runtime.recall("copper lanterns")
            assert "project=Mnemos (project-one)" in found
            assert f"task=Attribution ({FIRST})" in found
        # Moving the chat labels future writes, not previously saved entries.
        moved = {**ORIGIN, "project_id": "project-two", "project_name": "Other"}
        with bind_origin(moved):
            memory = (
                store._get_conn()
                .execute("SELECT id FROM engrams LIMIT 1")
                .fetchone()[0]
            )
            engram = store.get_engram(memory)
            engram.content = "An updated copper lantern memory."
            store.save_engram(engram)
            runtime.handoff("Work from the new project.")
        assert store.get_engram(memory).origin == ORIGIN
        assert stored_origin(store.get_latest_handoff(**runtime._scope_args())) == moved
        assert f"task=Attribution ({FIRST})" in runtime.recall(memory)
    finally:
        runtime.close()


@pytest.mark.parametrize("replacement", [{}, {"project_name": "Beta"}])
def test_project_change_does_not_reuse_the_registered_name(tmp_path, replacement):
    with closing(EngramStore(tmp_path / "memory.db")) as store:
        from mnemos.simple_scope import resolve_scope

        scope = resolve_scope(db_path=str(store.db_path))
        register_hook_origin(store, {"session_id": FIRST, "mnemos_origin": ORIGIN}, scope)
        with bind_origin({"thread_id": FIRST, "project_id": "project-two", **replacement}):
            memory = Engram(content="The project moved.", owner_agent_id=scope.agent_id,
                            person_id=scope.person_id, project_scope=scope.project_scope)
            store.save_engram(memory)
        origin = store.get_engram(memory.id).origin
        assert origin["project_id"] == "project-two"
        assert origin.get("project_name") == replacement.get("project_name")


@pytest.mark.parametrize("cold", [False, True])
@pytest.mark.parametrize("operation", ["capture", "correct"])
def test_shared_writes_keep_hook_registered_source_labels(tmp_path, monkeypatch, cold, operation):
    import re

    target = tmp_path / "shared.db"
    monkeypatch.setenv("MNEMOS_SHARED_MEMORY_DB", str(target))
    monkeypatch.setenv("MNEMOS_SHARED_MEMORY", "on")
    runtime = MnemosRuntime(db_path=str(tmp_path / "private.db"), use_dedicated_model=False)
    try:
        runtime._ensure_init()
        register_hook_origin(runtime._store, {"session_id": FIRST, "mnemos_origin": ORIGIN}, runtime.scope)
        if cold:
            runtime.close()
            runtime = MnemosRuntime(db_path=str(tmp_path / "private.db"), use_dedicated_model=False)
        with bind_origin({"thread_id": FIRST, "session_id": FIRST}):
            result = runtime.capture("The copper lantern source stays attached.", shared=True, signed_as="gpt-6.1-sol")
            original_id = re.search(r"shared_engram_\w+", result)[0]
            expected = ORIGIN
            if operation == "correct":
                expected = {
                    **ORIGIN, "project_id": "project-two",
                    "project_name": "Other", "thread_title": "Correction",
                }
                with closing(EngramStore(runtime.db_path)) as source:
                    register_hook_origin(source, {"session_id": FIRST, "mnemos_origin": expected}, runtime.scope)
                result = runtime.correct(
                    "The corrected copper lantern source stays attached.",
                    target_id=original_id, signed_as="gpt-6.1-sol",
                )
        memory_id = re.search(r"shared_engram_\w+", result)[0]
        with closing(EngramStore(target)) as store:
            original = store.get_engram(original_id)
            written = store.get_engram(memory_id)
            assert original.origin == ORIGIN
            assert written.origin == expected
            if operation == "correct":
                assert original.state == "archived"
                assert original.lineage.superseded_by == memory_id
                assert written.state == "active"
                assert written.lineage.supersedes == [original_id]
        recalled = subprocess.check_output(
            [sys.executable, "-c", "import sys; from mnemos.shared_memory import recall; "
             "print(recall(sys.argv[1], agent_id='another-agent'))", memory_id],
            text=True,
        )
        assert written.content in recalled
    finally:
        runtime.close()


def test_request_origin_is_restored_and_does_not_leak_between_workers():
    barrier = Barrier(2)

    def work(thread):
        with bind_origin({"thread_id": thread}):
            barrier.wait(timeout=5)
            return current_origin()["thread_id"]

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(work, [FIRST, SECOND])) == [FIRST, SECOND]
    assert current_origin() == {}
    with pytest.raises(RuntimeError):
        with bind_origin(ORIGIN):
            raise RuntimeError("tool failed")
    assert current_origin() == {}


def test_hook_registration_ranks_project_without_filtering_other_work(tmp_path):
    runtime = MnemosRuntime(
        db_path=str(tmp_path / "memory.db"), use_dedicated_model=False
    )
    try:
        with bind_origin(ORIGIN):
            runtime.handoff("Older handoff from the right project.")
        with bind_origin(
            {**ORIGIN, "thread_id": SECOND, "project_id": "other-project"}
        ):
            runtime.handoff("Newer handoff from elsewhere.")
        register_hook_origin(
            runtime._store,
            {
                "session_id": "33333333-3333-7333-8333-333333333333",
                "mnemos_origin": {
                    "project_id": "project-one",
                    "project_name": "Mnemos",
                },
            },
            runtime.scope,
        )
        with bind_origin({"thread_id": "33333333-3333-7333-8333-333333333333"}):
            packet = runtime.context()
            assert packet.index("Older handoff") < packet.index("Newer handoff")
            runtime.capture("The third task studies copper lanterns.")
        entries = (
            runtime._store._get_conn()
            .execute("SELECT origin_json FROM engrams")
            .fetchall()
        )
        assert json.loads(entries[0][0])["project_id"] == "project-one"
        assert runtime.scope.project_scope == "global"
    finally:
        runtime.close()


def test_schema_upgrade_preserves_old_words_and_leaves_origin_unknown(tmp_path):
    path = tmp_path / "old.db"
    store = EngramStore(path)
    store.write_handoff("Keep this old text verbatim.")
    store.save_engram(Engram(content="Old memory"))
    store.close()
    # Model the prior schema, not a manually supplied origin on both sides.
    with closing(sqlite3.connect(path)) as conn, conn:
        for table in ("engrams", "hypomnema_entries", "journal_entries", "notes"):
            conn.execute(f"ALTER TABLE {table} DROP COLUMN origin_json")
        conn.execute("UPDATE meta SET value='19' WHERE key='schema_version'")
    store = EngramStore(path)
    try:
        assert store.get_latest_handoff()["content"] == "Keep this old text verbatim."
        assert stored_origin(store.get_latest_handoff()) == {}
        with bind_origin(ORIGIN):
            old = store._get_conn().execute("SELECT id FROM engrams").fetchone()[0]
            engram = store.get_engram(old)
            store.save_engram(engram)
        assert (
            store.get_engram(old).origin == {}
        )  # opening/saving is not attribution evidence
    finally:
        store.close()


def test_codex_helper_uses_explicit_assignments_and_never_guesses_from_cwd(tmp_path):
    payload = {
        "session_id": FIRST,
        "cwd": "/work/mnemos",
        "prompt": "Keep the original prompt.",
    }
    state = {
        "local-projects": {"p1": {"name": "Mnemos", "rootPaths": ["/work/mnemos"]}},
        "thread-project-assignments": {
            FIRST: {"projectKind": "local", "projectId": "p1"}
        },
    }
    (tmp_path / ".codex-global-state.json").write_text(json.dumps(state))
    enriched = enrich_payload(payload, tmp_path)
    assert enriched["prompt"] == payload["prompt"]
    assert enriched["mnemos_origin"]["project_id"] == "p1"
    del state["thread-project-assignments"][FIRST]
    (tmp_path / ".codex-global-state.json").write_text(json.dumps(state))
    assert "project_id" not in enrich_payload(payload, tmp_path)["mnemos_origin"]
    (tmp_path / ".codex-global-state.json").write_text("malformed")
    assert "project_id" not in enrich_payload(payload, tmp_path)["mnemos_origin"]
    assert not (tmp_path / "state_5.sqlite").exists()


def test_codex_helper_prefers_canonical_project_and_tracks_explicit_removal(tmp_path):
    with closing(sqlite3.connect(tmp_path / "state_5.sqlite")) as conn, conn:
        conn.executescript(
            "CREATE TABLE threads(id,project_id,name,title); CREATE TABLE projects(id,name);"
        )
        conn.execute(
            "INSERT INTO threads VALUES (?,?,?,?)",
            (FIRST, "canonical", "Task title", "preview"),
        )
        conn.execute(
            "INSERT INTO projects VALUES (?,?)", ("canonical", "Current project")
        )
    payload = {"session_id": FIRST}
    found = enrich_payload(payload, tmp_path)["mnemos_origin"]
    assert found["project_id"] == "canonical" and found["thread_title"] == "Task title"
    with closing(sqlite3.connect(tmp_path / "state_5.sqlite")) as conn, conn:
        conn.execute("UPDATE threads SET project_id=NULL")
    (tmp_path / ".codex-global-state.json").write_text(
        json.dumps({"projectless-thread-ids": [FIRST]})
    )
    assert enrich_payload(payload, tmp_path)["mnemos_origin"]["project_id"] == ""


def test_hook_helper_forwards_to_existing_command_without_a_shell(tmp_path):
    payload = {"session_id": FIRST, "prompt": "literal $(touch forbidden)"}
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "mnemos.integrations.codex_origin",
            "--",
            sys.executable,
            "-c",
            "import sys;sys.stdout.write(sys.stdin.read())",
        ],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        env={**os.environ, "CODEX_HOME": str(tmp_path)},
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["prompt"] == payload["prompt"]
    assert json.loads(result.stdout)["mnemos_origin"]["thread_id"] == FIRST


def test_enriched_hook_registers_origin_and_missing_store_stays_missing(tmp_path):
    """Run the actual hook entry point, not just a manually matched writer/reader."""
    home = tmp_path / "codex"
    home.mkdir()
    (home / ".codex-global-state.json").write_text(
        json.dumps(
            {
                "local-projects": {"p1": {"name": "Mnemos"}},
                "thread-project-assignments": {
                    FIRST: {"projectKind": "local", "projectId": "p1"}
                },
            }
        )
    )
    path = tmp_path / "memory.db"
    command = [
        sys.executable,
        "-m",
        "mnemos.integrations.codex_origin",
        "--",
        sys.executable,
        "-m",
        "mnemos.cli",
        "hook",
        "session-start",
        "--db-path",
        str(path),
        "--agent-id",
        "probe",
        "--person-id",
        "person",
        "--project-scope",
        "global",
    ]
    payload = json.dumps(
        {
            "session_id": FIRST,
            "cwd": "/work/mnemos",
            "model": "gpt-6.1-sol",
            "hook_event_name": "SessionStart",
        }
    )

    def run():
        result = subprocess.run(
            command,
            input=payload,
            text=True,
            capture_output=True,
            env={**os.environ, "CODEX_HOME": str(home)},
            timeout=15,
        )
        assert result.returncode == 0, result.stderr

    run()
    assert not path.exists()
    EngramStore(path).close()
    run()
    runtime = MnemosRuntime(
        db_path=str(path),
        agent_id="probe",
        person_id="person",
        use_dedicated_model=False,
    )
    try:
        with bind_origin({"thread_id": FIRST}):
            runtime.capture("Copper lanterns pass the hook integration check.")
        rows = (
            runtime._store._get_conn()
            .execute("SELECT origin_json FROM engrams")
            .fetchall()
        )
        assert json.loads(rows[0][0])["project_id"] == "p1"
    finally:
        runtime.close()
