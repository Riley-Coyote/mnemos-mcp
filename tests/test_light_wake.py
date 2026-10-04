from __future__ import annotations

import json
import re
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

from mnemos.simple_runtime import MnemosRuntime


SCOPE = {"agent_id": "nova", "person_id": "riley", "project_scope": "demo"}
SCOPE_ARGS = ["--agent-id", "nova", "--person-id", "riley", "--project-scope", "demo"]
OPUS = "claude-opus-5-5"
EARLIER = "11111111-aaaa-4aaa-8aaa-111111111111"
FRESH = "22222222-bbbb-4bbb-8bbb-222222222222"
STANDING = "Riley prefers plain words and short replies."
FOUNDATIONAL = "Riley works best after midnight."
HANDOFF = "Where I stopped: the harbour ledger balances. Next: the spring timetable. " + "The harbour ledger lists every crossing, one line each. " * 30
JOURNAL = "The harbour ledger balances."
REPLY = "The spring timetable is ready."
PROMPT = 'You keep returning to "vektor" (5 memories). Is that a belief you now hold? If it is, state it in one line with verdict hold; if it is not, decline. Or leave it. [theme:vektor]'


def _store(tmp_path: Path):
    db = tmp_path / "memory.db"
    runtime = MnemosRuntime(db_path=db, use_dedicated_model=False, **SCOPE)
    try:
        runtime.introduce(OPUS)
        said = runtime.capture(STANDING, impact=STANDING)
        standing_id = re.search(r"Memory ID: (engram_\w+)", said).group(1)
        store = runtime._store
        store.set_standing(standing_id, True, by=OPUS)
        store.write_hypomnema_entry(
            FOUNDATIONAL, **SCOPE, authored_by="agent", author_id="nova", author_model=OPUS,
            domain="foundational", foundational=True, confidence=0.9, salience=0.9,
        )
        handoff = store.write_handoff(HANDOFF, **SCOPE, author_model=OPUS, author_session=EARLIER)
        store.write_journal_entry(JOURNAL, **SCOPE, model_id=OPUS, session_id=EARLIER)
        question = store.enqueue_reflection("belief", standing_id, PROMPT, **SCOPE)
        note = store.write_note(JOURNAL, author="agent", kind="noticed", model_id=OPUS, **SCOPE)
        reply = store.write_note(REPLY, author="person", in_reply_to=note, **SCOPE)
    finally:
        runtime.close()
    return db, {"handoff": handoff, "question": question, "reply": reply}


def _hook(db: Path, tmp_path: Path, *, env: dict[str, str] | None = None,
          extra: tuple[str, ...] = ()):
    home = tmp_path / "home"
    (home / ".mnemos").mkdir(parents=True, exist_ok=True)
    folder = tmp_path / "work" / "harbour-app"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / ".git").mkdir(exist_ok=True)
    payload = {
        "hook_event_name": "SessionStart", "source": "startup", "session_id": FRESH,
        "cwd": str(folder), "model": OPUS,
    }
    return subprocess.run(
        [sys.executable, "-m", "mnemos.cli", "hook", "session-start", "--db-path", str(db), *SCOPE_ARGS, *extra],
        input=json.dumps(payload), capture_output=True, text=True, timeout=180,
        env={"HOME": str(home), "PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "MNEMOS_DISABLE_DOTENV": "1", "PYTHONPATH": ":".join(sys.path), **(env or {})},
    )


def _packet(done):
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)["hookSpecificOutput"]["additionalContext"]


def _rows(db, sql, params=()):
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


def test_light_names_who_and_where_but_asks_nothing(tmp_path):
    db, ids = _store(tmp_path)
    packet = _packet(_hook(db, tmp_path, env={"MNEMOS_WAKE": "light"}))
    assert STANDING in packet
    assert FOUNDATIONAL in packet
    assert "### where i left off" in packet
    assert "### a question waiting for me" not in packet
    assert "last time I wrote in my journal" not in packet
    assert REPLY not in packet
    body, tools = packet.split("\n\n### for the memory tools\n", 1)
    handoff = body.split("### where i left off\n", 1)[1].split(":\n", 1)[1]
    assert len(handoff) <= 700
    assert handoff != HANDOFF
    assert handoff.startswith("Where I stopped: the harbour ledger balances.")
    assert ids["handoff"] in tools


def test_light_spends_nothing(tmp_path):
    db, ids = _store(tmp_path)
    delivery = "SELECT key, value FROM meta WHERE key LIKE '%:last_context_delivery_at'"
    before = _rows(db, delivery)
    assert before == []
    _packet(_hook(db, tmp_path, env={"MNEMOS_WAKE": "light"}))
    assert _rows(db, "SELECT surfaced_count FROM reflection_queue WHERE id = ?", (ids["question"],)) == [(0,)]
    assert _rows(db, "SELECT delivered_at FROM notes WHERE id = ?", (ids["reply"],)) == [(None,)]
    assert _rows(db, delivery) == before


def test_off_wakes_with_nothing_and_opens_no_store(tmp_path):
    db = tmp_path / "absent.db"
    done = _hook(db, tmp_path, extra=("--wake", "off"))
    assert done.returncode == 0, done.stderr
    assert done.stdout == ""
    assert not db.exists()


def test_the_flag_wins_over_the_environment(tmp_path):
    db, _ = _store(tmp_path)
    packet = _packet(_hook(db, tmp_path, env={"MNEMOS_WAKE": "off"}, extra=("--wake", "light")))
    assert packet
    assert "### a question waiting for me" not in packet


def test_an_unknown_mode_wakes_fully(tmp_path):
    db, _ = _store(tmp_path)
    done = _hook(db, tmp_path, env={"MNEMOS_WAKE": "sideways"})
    assert "### a question waiting for me" in _packet(done)
    assert "unknown wake mode 'sideways'" in done.stderr


def test_full_is_unchanged(tmp_path):
    db, _ = _store(tmp_path)
    default = tmp_path / "default.db"
    full = tmp_path / "full.db"
    shutil.copy(db, default)
    shutil.copy(db, full)
    a = _packet(_hook(default, tmp_path))
    b = _packet(_hook(full, tmp_path, env={"MNEMOS_WAKE": "full"}))
    def without_clock(packet):
        lines = packet.splitlines()
        lines[lines.index("## waking up") + 1] = "<when>"
        return "\n".join(lines)
    assert without_clock(a) == without_clock(b)
