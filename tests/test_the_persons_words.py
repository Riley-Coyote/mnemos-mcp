"""The person's own words, and the first restart (Ready D2).

What a person types with ``mnemos remember`` is theirs: kept unsigned as the
person's (``author_kind`` 'person'), shown once in the next full wake, marked
in recall, and never counted as the agent's own. The first wake that crosses a
restart says so in the agent's own words, through the session-start hook as
well as ``mnemos_context``.

The person's words are written the way a newcomer writes them, with
``MNEMOS_AGENT_MODEL`` set: before this change ``remember`` signed them with
whatever model resolved, and every path below counted them as the agent's.
Hook packets set the model in the payload: the hook reads the launch line with
``ps`` only under ``CLAUDE_PID``, which the build sandbox blocks.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from mnemos.cli import main
from mnemos.interface.context_packet import (
    build_context_packet,
    carried_count,
    resident_model,
    shown_memories,
)
from mnemos.simple_runtime import MnemosRuntime

OPUS = "claude-opus-5-5"
SONNET = "claude-sonnet-5-5"
SCOPE = {"agent_id": "nova", "person_id": "riley", "project_scope": "demo"}
SCOPE_ARGS = ["--agent-id", "nova", "--person-id", "riley", "--project-scope", "demo"]
FIRST = "aaaaaaaa-1111-4111-8111-111111111111"
LATER = "bbbbbbbb-2222-4222-8222-222222222222"
LATEST = "cccccccc-3333-4333-8333-333333333333"
KEPT_BEFORE = "I still have what I kept before:"


@pytest.fixture
def home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / ".mnemos").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    # A person's terminal, not an agent's own shell: `remember` keeps the
    # agent's words when Claude Code (or another agent) runs it.
    monkeypatch.delenv("CLAUDECODE", raising=False)
    monkeypatch.delenv("AI_AGENT", raising=False)
    return home


@pytest.fixture
def db(tmp_path, home):
    return tmp_path / "memory.db"


def _runtime(db: Path) -> MnemosRuntime:
    rt = MnemosRuntime(db_path=str(db), use_dedicated_model=False, **SCOPE)
    rt._ensure_init()
    return rt


def _remember(db: Path, text: str, *extra: str, monkeypatch=None) -> str:
    """``mnemos remember`` as a newcomer runs it (with ``monkeypatch``, a model
    configured); the id of the memory it wrote."""
    if monkeypatch is not None:
        monkeypatch.setenv("MNEMOS_AGENT_MODEL", OPUS)
    try:
        assert main(["remember", text, *extra, "--db-path", str(db), *SCOPE_ARGS]) == 0
    finally:
        if monkeypatch is not None:
            monkeypatch.delenv("MNEMOS_AGENT_MODEL", raising=False)
    return _newest_engram(db)


def _newest_engram(db: Path) -> str:
    rt = _runtime(db)
    try:
        return rt._store._get_conn().execute(
            "SELECT id FROM engrams ORDER BY created_at DESC LIMIT 1").fetchone()[0]
    finally:
        rt.close()


def _id(result: str) -> str:
    return re.search(r"Memory ID: (engram_\w+)", result).group(1)


def _section(text, heading):
    assert f"### {heading}\n" in text, text
    return text.split(f"### {heading}\n", 1)[1].split("\n\n### ", 1)[0]


def _opening(text: str) -> str:
    """The opening paragraph: the line after the packet's heading."""
    lines = text.splitlines()
    assert lines[0] == "## waking up", text
    return lines[1]


# ── D2.1 · `mnemos remember` writes the person's words ──


def test_remember_keeps_the_persons_words_unsigned(db, monkeypatch, capsys):
    monkeypatch.setenv("MNEMOS_AGENT_MODEL", OPUS)
    assert main(["remember", "Sam prefers tabs", "--impact", "Tabs, not spaces.",
                 "--db-path", str(db), *SCOPE_ARGS]) == 0
    out = capsys.readouterr().out
    memory = re.fullmatch(r"Remembered, in your words: (engram_\w+)\n", out)
    assert memory, out

    rt = _runtime(db)
    try:
        conn = rt._store._get_conn()
        row = conn.execute(
            "SELECT author_kind, author_model, impact_source FROM engrams WHERE id = ?",
            (memory.group(1),)).fetchone()
        note = conn.execute(
            "SELECT authored_by, author_model FROM hypomnema_entries "
            "WHERE graduated_to_engram_id = ?", (memory.group(1),)).fetchone()
    finally:
        rt.close()
    assert tuple(row) == ("person", "", "person")
    assert tuple(note) == ("unknown", "")


def test_remember_prints_exactly_one_line(db, capsys):
    assert main(["remember", "Sam prefers tabs", "--db-path", str(db), *SCOPE_ARGS]) == 0
    out = capsys.readouterr().out
    assert re.fullmatch(r"Remembered, in your words: engram_\w+\n", out), out


def test_remember_after_a_near_duplicate_prints_the_warning_then_one_line(db, capsys):
    rt = _runtime(db)
    rt.capture("Sam prefers tabs over spaces and wants terse commit messages.", signed_as=OPUS)
    rt.close()
    assert main(["remember", "Sam prefers tabs", "--db-path", str(db), *SCOPE_ARGS]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 2, lines
    assert lines[0].startswith("A memory already says something close:"), lines
    assert re.fullmatch(r"Remembered, in your words: engram_\w+", lines[1]), lines


def test_remember_with_nothing_to_keep_exits_1(db, capsys):
    assert main(["remember", "   ", "--db-path", str(db), *SCOPE_ARGS]) == 1
    assert capsys.readouterr().out == "Nothing captured: content was empty.\n"


def test_capture_refuses_an_unknown_author_kind(db):
    rt = _runtime(db)
    try:
        with pytest.raises(ValueError):
            rt.capture("Sam prefers tabs", author_kind="bot")
    finally:
        rt.close()


# ── D2.2 · The person's words never count as the agent's own ──


def test_what_has_been_changing_leaves_out_the_persons_words(db, monkeypatch):
    _remember(db, "Riley moved the standup.", "--impact", "Mornings are for the person now.",
              monkeypatch=monkeypatch)
    rt = _runtime(db)
    try:
        rt.capture("The ferry page rendered wrong.", impact="The render is the honest judge.",
                   signed_as=OPUS)
        text = build_context_packet(rt._store, **SCOPE, reader_model=OPUS,
                                    mark_surfaced=False)["prompt"]
    finally:
        rt.close()
    changing = _section(text, "what's been changing in me")
    assert "The render is the honest judge." in changing, text
    assert "Mornings are for the person now." not in text, text


def _idea_store(db, monkeypatch, rt):
    """The waking test's idea store (37 background lines and one idea of the
    agent's on three days) with a stronger idea the person wrote on four days.
    Returns the agent's idea's ids and the person's."""
    from tests.test_waking_in_my_own_words import _idea_store as agents_ideas, _unit
    import random

    group, _background = agents_ideas(rt, monkeypatch)
    rng = random.Random(2002)
    base = _unit([rng.gauss(0.0, 1.0) for _ in range(384)])
    vectors = {}
    persons = []
    for index in range(4):
        _remember(db, f"Riley timed crossing {index} against the table.",
                  "--impact", f"The printed table lies about crossing {index}.",
                  monkeypatch=monkeypatch)
        persons.append(_newest_engram(db))
        vectors[persons[-1]] = _unit([value + rng.gauss(0.0, 0.01) for value in base])
    now = datetime.now(timezone.utc)
    conn = rt._store._get_conn()
    for index, target in enumerate(persons):
        conn.execute("UPDATE engrams SET created_at = ?, author_session = ? WHERE id = ?",
                     ((now - timedelta(days=12 - 3 * index, hours=3)).isoformat(),
                      f"person-{index}", target))
    conn.execute("DELETE FROM meta WHERE key = ?", (rt._meta_key("ideas_noticed_at"),))
    rt._store._commit()
    agents = rt._embedding_index.impact_vectors
    monkeypatch.setattr(rt._embedding_index, "impact_vectors", lambda impacts: {
        **agents(impacts), **{item: vectors[item] for item in impacts if item in vectors}})
    return group, persons


def test_the_noticer_finds_ideas_only_in_the_agents_words(db, monkeypatch):
    rt = _runtime(db)
    try:
        group, persons = _idea_store(db, monkeypatch, rt)
        rt._enqueue_returning_idea()
        saved = json.loads(rt._get_meta("ideas_returning") or "null")
    finally:
        rt.close()
    assert [entry["ids"] for entry in saved] == [group], saved
    assert not set(persons) & {i for entry in saved for i in entry["ids"]}


def test_a_belief_the_noticer_proposes_cites_only_the_agents_words(db, monkeypatch):
    rt = _runtime(db)
    try:
        group, persons = _idea_store(db, monkeypatch, rt)
        assert rt._enqueue_returning_idea() == 1
        question = rt._store._get_conn().execute(
            "SELECT target_id, prompt FROM reflection_queue WHERE kind = 'belief' "
            "AND instr(prompt, '[evidence:') > 0").fetchone()
        evidence = re.search(r"\[evidence:([\w,]+)\]", question["prompt"]).group(1).split(",")
        assert evidence == group, question["prompt"]
        rt.reflect(question["target_id"], "The render is the only honest judge.",
                   verdict="hold", signed_as=OPUS)
        beliefs = rt._store.get_beliefs("nova", active_only=True)
    finally:
        rt.close()
    assert [sorted(belief.supporting_engram_ids) for belief in beliefs] == [sorted(group)]
    assert not set(persons) & set(beliefs[0].supporting_engram_ids)


def test_the_persons_words_dont_make_the_resident(db, monkeypatch):
    for index in range(3):
        _remember(db, f"Riley's fact number {index}.", monkeypatch=monkeypatch)
    rt = _runtime(db)
    try:
        rt.capture("I checked the harbour ledger.", signed_as=SONNET)
        assert resident_model(rt._store, SCOPE) == SONNET
    finally:
        rt.close()


def test_the_person_isnt_asked_what_their_words_changed_in_the_agent(db, monkeypatch):
    person = _remember(db, "Riley moved the standup to ten.", monkeypatch=monkeypatch)
    rt = _runtime(db)
    try:
        agent = _id(rt.capture("The standup now runs at ten.", signed_as=OPUS))
        rt._enqueue_impact_reflections()
        asked = {row[0] for row in rt._store._get_conn().execute(
            "SELECT target_id FROM reflection_queue WHERE kind = 'impact'")}
    finally:
        rt.close()
    assert agent in asked
    assert person not in asked


# ── D2.3 · The next full wake shows it once, under "while i was away" ──


def test_the_next_full_wake_shows_the_persons_words_once(db, monkeypatch):
    _remember(db, "Sam prefers tabs", monkeypatch=monkeypatch)
    monkeypatch.setenv("MNEMOS_PERSON_NAME", "Riley")
    monkeypatch.setenv("MNEMOS_AGENT_MODEL", OPUS)  # the reader, waking as itself
    rt = _runtime(db)
    try:
        first = rt.context()
    finally:
        rt.close()
    away = _section(first, "while i was away")
    assert '- Riley wrote this into my memory: "Sam prefers tabs"' in away.splitlines(), first

    rt = _runtime(db)
    try:
        second = rt.context()
    finally:
        rt.close()
    assert "wrote this into my memory" not in second, second


def test_without_a_name_the_person_wrote_it(db):
    _remember(db, "Sam prefers tabs")
    rt = _runtime(db)
    try:
        text = build_context_packet(rt._store, **SCOPE, reader_model=OPUS,
                                    mark_surfaced=False)["prompt"]
    finally:
        rt.close()
    assert 'The person wrote this into my memory: "Sam prefers tabs"' in text, text


def test_a_light_wake_shows_and_records_nothing_of_the_persons_words(db):
    _remember(db, "Sam prefers tabs")
    rt = _runtime(db)
    try:
        rt.handoff("Where I stopped: the harbour ledger.", signed_as=OPUS)
        light = build_context_packet(rt._store, **SCOPE, reader_model=OPUS, wake="light")
        assert "wrote this into my memory" not in light["prompt"], light["prompt"]
        assert light["person_words"] == []
        assert rt._get_meta("person_words_shown_at") is None
        full = build_context_packet(rt._store, **SCOPE, reader_model=OPUS)["prompt"]
    finally:
        rt.close()
    assert 'The person wrote this into my memory: "Sam prefers tabs"' in full, full


def test_the_persons_words_count_as_carried(db):
    person = _remember(db, "Sam prefers tabs")
    rt = _runtime(db)
    try:
        packet = build_context_packet(rt._store, **SCOPE, reader_model=OPUS, mark_surfaced=False)
    finally:
        rt.close()
    assert packet["shown"]["person_words"] == [person]
    assert carried_count(packet) == 1


# ── D2.4 · Recall marks them ──


def test_recall_marks_the_persons_words(db, monkeypatch):
    person = _remember(db, "Sam prefers tabs for the harbour code")
    rt = _runtime(db)
    try:
        agent = _id(rt.capture("The harbour code uses tabs throughout", signed_as=OPUS))
        monkeypatch.setenv("MNEMOS_PERSON_NAME", "Riley")
        named = rt.recall("harbour tabs")
        monkeypatch.delenv("MNEMOS_PERSON_NAME")
        unnamed = rt.recall("harbour tabs")
    finally:
        rt.close()

    def row(text, engram_id):
        found = [line for line in text.splitlines() if f"id={engram_id} " in line]
        assert len(found) == 1, text
        return found[0]

    assert row(named, person).endswith("; in Riley's words"), named
    assert row(unnamed, person).endswith("; in the person's words"), unnamed
    assert "words" not in row(named, agent), named


# ── D2.5 · The first restart, for the hook and the tool alike ──


def _hook(db: Path, home: Path, session: str) -> str:
    """The real SessionStart hook in another process, in Claude Code session
    ``session``; the packet it injects, or ``""``."""
    payload = {"hook_event_name": "SessionStart", "source": "startup",
               "session_id": session, "model": OPUS}
    done = subprocess.run(
        [sys.executable, "-m", "mnemos.cli", "hook", "session-start",
         "--db-path", str(db), *SCOPE_ARGS],
        input=json.dumps(payload), capture_output=True, text=True, timeout=180,
        env={"HOME": str(home), "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
             "MNEMOS_DISABLE_DOTENV": "1", "PYTHONPATH": ":".join(sys.path)},
    )
    assert done.returncode == 0, done.stderr
    if not done.stdout.strip():
        return ""
    return json.loads(done.stdout)["hookSpecificOutput"]["additionalContext"]


def _first_capture_in(db: Path, monkeypatch, session: str = FIRST) -> None:
    """A first capture made by the agent in Claude Code session ``session``,
    with a handoff so later wakes have something to say."""
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", session)
    rt = _runtime(db)
    try:
        rt.capture("The garden gnome is named Bartholomew.", signed_as=OPUS)
        rt.handoff("Where I stopped: naming the garden.", signed_as=OPUS)
    finally:
        rt.close()
        monkeypatch.delenv("CLAUDE_CODE_SESSION_ID")


def test_the_hook_says_the_first_restart_once(db, home, monkeypatch):
    _first_capture_in(db, monkeypatch)
    later = _hook(db, home, LATER)
    assert _opening(later).endswith(
        f'{KEPT_BEFORE} "The garden gnome is named Bartholomew.".'), later

    latest = _hook(db, home, LATEST)
    assert latest, "premise: the next wake says something"
    assert KEPT_BEFORE not in latest, latest


def test_context_says_the_first_restart_once(db):
    rt = _runtime(db)
    try:
        rt.capture("The garden gnome is named Bartholomew.", signed_as=OPUS)
        same = rt.context()
    finally:
        rt.close()
    assert KEPT_BEFORE not in same, same

    rt = _runtime(db)
    try:
        later = rt.context()
    finally:
        rt.close()
    assert _opening(later).endswith(
        f'{KEPT_BEFORE} "The garden gnome is named Bartholomew.".'), later

    rt = _runtime(db)
    try:
        latest = rt.context()
        verified = rt._get_meta("verified_at")
    finally:
        rt.close()
    assert KEPT_BEFORE not in latest, latest
    assert verified is not None and datetime.fromisoformat(verified)


def test_a_wake_in_the_first_captures_session_doesnt_say_it(db, home, monkeypatch):
    _first_capture_in(db, monkeypatch)
    # A later runtime (a higher session count) in the same Claude Code session.
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", FIRST)
    rt = _runtime(db)
    try:
        through_tool = rt.context()
        assert rt._get_meta("verified_at") is None
    finally:
        rt.close()
        monkeypatch.delenv("CLAUDE_CODE_SESSION_ID")
    assert through_tool, "premise: the wake says something"
    assert KEPT_BEFORE not in through_tool, through_tool

    through_hook = _hook(db, home, FIRST)
    assert through_hook, "premise: the wake says something"
    assert KEPT_BEFORE not in through_hook, through_hook

    # Control: the next Claude Code session does say it.
    assert KEPT_BEFORE in _hook(db, home, LATER)


def test_a_forgotten_first_note_isnt_said(db, home, monkeypatch):
    _first_capture_in(db, monkeypatch)
    rt = _runtime(db)
    try:
        # Control, recording nothing: a later session would say it.
        unforgotten = build_context_packet(rt._store, **SCOPE, reader_model=OPUS,
                                           reader_session=LATER, mark_surfaced=False)
        assert KEPT_BEFORE in unforgotten["prompt"], unforgotten["prompt"]
        rt.correct(correction="", query="garden gnome Bartholomew", action="forget")
    finally:
        rt.close()
    text = _hook(db, home, LATER)
    assert KEPT_BEFORE not in text and "Bartholomew" not in text, text

    rt = _runtime(db)
    try:
        text = rt.context()
    finally:
        rt.close()
    assert KEPT_BEFORE not in text and "Bartholomew" not in text, text


def test_memory_verified_appears_nowhere(db):
    rt = _runtime(db)
    try:
        rt.introduce(OPUS)
        rt.capture("The garden gnome is named Bartholomew.", signed_as=OPUS)
    finally:
        rt.close()
    rt = _runtime(db)
    try:
        text = rt.context()
    finally:
        rt.close()
    assert KEPT_BEFORE in text, "premise: this wake crosses the restart"
    assert "MEMORY VERIFIED" not in text, text
    package = Path(__file__).resolve().parents[1] / "mnemos"
    said = [str(path) for path in package.rglob("*.py") if "MEMORY VERIFIED" in path.read_text()]
    assert said == [], said


# ── Round 2 ──
# 1 · The first capture is the agent's own


def test_a_persons_remember_on_a_fresh_store_records_no_first_capture(db):
    _remember(db, "Sam prefers tabs")
    rt = _runtime(db)
    try:
        assert rt._get_meta("first_capture") is None
    finally:
        rt.close()


def test_the_agents_later_capture_is_the_first_capture_the_restart_says(db):
    _remember(db, "Sam prefers tabs")
    rt = _runtime(db)
    try:
        agent = _id(rt.capture("The garden gnome is named Bartholomew.", signed_as=OPUS))
        recorded = json.loads(rt._get_meta("first_capture"))
    finally:
        rt.close()
    assert recorded["engram_id"] == agent

    rt = _runtime(db)
    try:
        later = rt.context()
    finally:
        rt.close()
    assert _opening(later).endswith(
        f'{KEPT_BEFORE} "The garden gnome is named Bartholomew.".'), later


# 3 · The trace of the person's words is unsigned


def test_the_trace_of_a_persons_remember_is_unsigned(db, monkeypatch):
    person = _remember(db, "Sam prefers tabs", monkeypatch=monkeypatch)
    rt = _runtime(db)
    try:
        rows = rt._store._get_conn().execute(
            "SELECT author_model, written_ids FROM memory_trace WHERE tool = 'capture'"
        ).fetchall()
    finally:
        rt.close()
    traced = [row for row in rows if person in json.loads(row["written_ids"])]
    assert len(traced) == 1, [dict(row) for row in rows]
    assert traced[0]["author_model"] == ""


# 5 · An agent's own shell writes the agent's words


def _engram(db: Path, engram_id: str) -> dict:
    rt = _runtime(db)
    try:
        row = rt._store._get_conn().execute(
            "SELECT author_kind, author_model FROM engrams WHERE id = ?", (engram_id,)
        ).fetchone()
    finally:
        rt.close()
    return dict(row)


def test_remember_in_claude_codes_shell_keeps_the_agents_words(db, monkeypatch, capsys):
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setenv("MNEMOS_AGENT_MODEL", OPUS)
    assert main(["remember", "Sam prefers tabs", "--db-path", str(db), *SCOPE_ARGS]) == 0
    out = capsys.readouterr().out
    said = re.fullmatch(r"Remembered, as the agent's own words: (engram_\w+)\n", out)
    assert said, out
    assert _engram(db, said.group(1)) == {"author_kind": "agent", "author_model": OPUS}


def test_remember_signed_as_keeps_the_agents_words_signed_so(db, monkeypatch, capsys):
    monkeypatch.setenv("MNEMOS_AGENT_MODEL", OPUS)
    assert main(["remember", "Sam prefers tabs", "--signed-as", SONNET,
                 "--db-path", str(db), *SCOPE_ARGS]) == 0
    out = capsys.readouterr().out
    said = re.fullmatch(r"Remembered, as the agent's own words: (engram_\w+)\n", out)
    assert said, out
    assert _engram(db, said.group(1)) == {"author_kind": "agent", "author_model": SONNET}


def test_remember_in_neither_keeps_the_persons_words(db, monkeypatch, capsys):
    monkeypatch.setenv("MNEMOS_AGENT_MODEL", OPUS)
    monkeypatch.setenv("CLAUDECODE", "")
    monkeypatch.setenv("AI_AGENT", "")
    assert main(["remember", "Sam prefers tabs", "--db-path", str(db), *SCOPE_ARGS]) == 0
    out = capsys.readouterr().out
    said = re.fullmatch(r"Remembered, in your words: (engram_\w+)\n", out)
    assert said, out
    assert _engram(db, said.group(1)) == {"author_kind": "person", "author_model": ""}


# 6 · The person's words count as shown


def test_shown_memories_counts_the_persons_words(db):
    person = _remember(db, "Sam prefers tabs. Context: the harbour code.")
    rt = _runtime(db)
    try:
        packet = build_context_packet(rt._store, **SCOPE, reader_model=OPUS,
                                      mark_surfaced=False)
    finally:
        rt.close()
    assert packet["shown"]["person_words"] == [person], "premise: the wake showed them"
    ids, texts = shown_memories(packet)
    assert person in ids
    assert "Sam prefers tabs. Context: the harbour code." in texts


# 7 · The line's dash


def test_the_persons_line_starts_with_a_dash(db):
    _remember(db, "Sam prefers tabs")
    rt = _runtime(db)
    try:
        text = build_context_packet(rt._store, **SCOPE, reader_model=OPUS,
                                    mark_surfaced=False)["prompt"]
    finally:
        rt.close()
    lines = [line for line in _section(text, "while i was away").splitlines()
             if "wrote this into my memory" in line]
    assert lines == ['- The person wrote this into my memory: "Sam prefers tabs"'], text
