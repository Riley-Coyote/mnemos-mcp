"""The onboarding, for new agents and existing ones (QH-3).

Riley, Nov 21 2026: "someone who isnt starting fresh with a new agent gets the
same onboarding treatment". Three cases, one treatment, where the person can
choose quiet hours (Claude Code, and Hermes through its provider):

* (A) a fresh memory for someone new, and (B) a fresh memory for an agent that
  already knows them: the ritual ends with a tour, the quiet hours one at a
  time (each as it is now, in the agent's own voice, the choice theirs), then
  the page.
* (C) an agent that already had Mnemos, whose person hasn't answered about the
  hours since each became theirs to choose (``answered_at`` empty): what's new,
  the hours one at a time, then the page, in ``mnemos_context`` (so Hermes's
  system prompt too) and in Claude Code's automatic wake, until they answer or
  it has been shown in three sessions.

Inside Hermes the agent makes each hour with ``cronjob_manage``, limited by
Hermes to the memory (and the web where chosen), and keeps the answer with
``mnemos_hour``'s ``chosen``. Every other agent's words are as they were.

Temporary homes and the suite's fake scheduler only (tests/conftest.py).
"""

from __future__ import annotations

import json
import os
import shlex
import sys
import types
from pathlib import Path

import pytest

from mnemos import cli
from mnemos.cli import main
from mnemos.integrations.hermes import HermesMnemosConfig, MnemosMemoryProviderCore
from mnemos.integrations.hermes import hours as hermes_hours
from mnemos.setup import agent_hours, connect, scheduler, state
from mnemos.setup import harnesses as hs
from mnemos.simple_runtime import MnemosRuntime

SCOPE = {"agent_id": "nova", "person_id": "riley", "project_scope": "demo"}
SCOPE_ARGS = ["--agent-id", "nova", "--person-id", "riley", "--project-scope", "demo"]
MNEMOS = "/opt/mnemos/bin/mnemos"
OPUS = "claude-opus-5-5"
TOUR = "6. Then give them a short tour, in plain words, even if you knew them before"
HOURS = "Then the quiet hours, one at a time."
NEW = "NEW SINCE LAST TIME - tell them once"
# Claude Code's session ids, as its hook and its servers are given them.
S1, S2, S3, S4 = (f"{n}{n}{n}{n}{n}{n}{n}{n}-{n}{n}{n}{n}-4{n}{n}{n}-8{n}{n}{n}-{str(n) * 12}" for n in range(1, 5))
LEGACY_MINE = (
    "Your own hour, now on, daily at 08:00, up to an hour, and it can go online "
    "(as it was set up before)."
)
# How the agent speaks of wanting the time: it says so only if it does.
VOICE = (
    "In your own voice: if you'd like the time, say so honestly (it would be your own), and "
    "make clear it's entirely their call."
)
CAN_GO_ONLINE = "They can keep it online or take it offline; your page lists every page you read in it."


@pytest.fixture
def claude_code(monkeypatch, tmp_path):
    """A Claude Code session on a Mac with launchd (the suite's fake) and a
    claude command, served the Mnemos at MNEMOS."""
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setattr(state, "mnemos_command", lambda: MNEMOS)
    monkeypatch.setattr(cli, "_mnemos_command", lambda: MNEMOS)
    monkeypatch.setattr(scheduler, "detect_backend", lambda system=None: "launchd")
    folder = tmp_path / "local-bin"
    folder.mkdir()
    (folder / "claude").write_text("#!/bin/sh\nexit 0\n")
    (folder / "claude").chmod(0o755)
    monkeypatch.delenv("MNEMOS_CLAUDE_BIN", raising=False)
    monkeypatch.setenv("PATH", str(folder))


def _db() -> Path:
    return Path.home() / ".mnemos" / "nova.db"


def _runtime() -> MnemosRuntime:
    return MnemosRuntime(db_path=str(_db()), use_dedicated_model=False, **SCOPE)


def _context(monkeypatch, session: str) -> str:
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", session)
    runtime = _runtime()
    try:
        return runtime.context()
    finally:
        runtime.close()


def _command(*parts: str) -> str:
    return state.command_line("nova", _db(), *parts, mnemos=MNEMOS)


def _hook(monkeypatch, capsys, session: str) -> str:
    """Claude Code's automatic wake, run as the installed hook runs it, with
    the session's payload on stdin. Returns what it gives the model."""
    capsys.readouterr()
    read, write = os.pipe()
    os.write(write, json.dumps({"session_id": session, "cwd": "/tmp"}).encode())
    os.close(write)
    stdin = os.fdopen(read)
    monkeypatch.setattr(sys, "stdin", stdin)
    try:
        assert main(["hook", "session-start", "--db-path", str(_db()), *SCOPE_ARGS]) == 0
    finally:
        stdin.close()
    out = capsys.readouterr().out
    return json.loads(out)["hookSpecificOutput"]["additionalContext"] if out.strip() else ""


def _an_agent_from_before(capsys) -> None:
    """A store with memories, all three hours scheduled the old way, and
    ``{"choice": "yes"}`` only, as a release before this one left it."""
    runtime = _runtime()
    try:
        runtime.capture("Riley keeps bees on the roof.", signed_as=OPUS)
        runtime.introduce(agent_model=OPUS)
        runtime.handoff("Was fixing the hive scale; next: calibrate it.", signed_as=OPUS)
    finally:
        runtime.close()
    assert main(["--db-path", str(_db()), *SCOPE_ARGS, "daemon", "install", "--hours", "--write"]) == 0
    (state.hours_dir("nova") / state.CHOICE_FILE).write_text(
        json.dumps({"choice": "yes", "at": "2026-10-01T08:00:00+00:00"}) + "\n"
    )
    capsys.readouterr()
    assert all(hour["on"] for hour in state.hours_now("nova").values())
    assert state.answered_at("nova") is None


def _as_the_agent_runs(command: str) -> int:
    executable, *arguments = shlex.split(command)
    assert executable == MNEMOS
    return main(arguments)


# ── A and B: a fresh memory, in Claude Code ──


def test_a_fresh_memory_ends_with_the_tour_the_hours_and_the_page(claude_code, os_scheduler, monkeypatch):
    packet = _context(monkeypatch, S1)

    assert TOUR in packet
    tour = packet.split(TOUR, 1)[1].split("\n", 1)[0]
    assert "what isn't used fades with time unless they ask you to always remember it" in tour
    assert "on a page you'll open for them whenever they ask" in tour
    assert "correct anything, or let it go" in tour
    assert "its Settings is where they choose your quiet hours" in tour
    walk = packet.split("7. " + HOURS, 1)[1].split("\n8. ", 1)[0]
    assert VOICE in walk and "say honestly that you'd like the time" not in walk
    assert "They're all off now." in walk
    assert "- Your own hour, now off (it would start at 08:00, up to an hour)." in walk
    assert "- Our hour, now off (it would start at 19:00, up to half an hour)." in walk
    assert "- The dream, now off (it would start at 03:30, up to 20 minutes)." in walk
    assert "your page lists every page you read" in walk and "It never goes online." in walk
    assert "on their Claude plan" in walk and "goes to Anthropic" in walk
    assert f"on: {_command('hours', 'on', 'mine', '--at', '08:00', '--write')}" in walk
    assert "all as they are" not in walk, "a fresh memory has nothing to keep"
    assert "If they say no, run the line for none, and don't ask again." in walk
    assert CAN_GO_ONLINE not in walk, "nothing can go online in a fresh memory"
    assert "\n8. Then open your page for them and show them its Settings" in packet
    assert not os_scheduler.loaded, "nothing is scheduled by reading"


def test_an_agent_that_already_knows_them_gets_the_same_tour_and_hours(claude_code, monkeypatch):
    """B: the memory is new to them even if the agent isn't."""
    packet = _context(monkeypatch, S1)
    assert ("the memory is new to them even if you aren't, so knowing them is no reason to skip "
            "the tour or the quiet hours") in packet
    assert "7. " + HOURS in packet


def test_the_wake_leaves_a_fresh_memory_to_mnemos_context(claude_code, monkeypatch, capsys):
    """The automatic wake carries no onboarding for A or B, as before: the
    server's instructions send the agent to mnemos_context, which has it."""
    runtime = _runtime()
    runtime._ensure_init()
    runtime.close()
    woke = _hook(monkeypatch, capsys, S1)
    assert HOURS not in woke and NEW not in woke and "ONBOARDING" not in woke


def test_after_an_unanswered_ritual_the_hours_alone_carry_on(claude_code, monkeypatch):
    """When the first session's ritual completes and nobody answered, C's rule
    takes over, without a second tour."""
    first = _context(monkeypatch, S1)
    assert "7. " + HOURS in first
    runtime = _runtime()
    try:
        runtime.introduce(agent_model=OPUS)
        runtime.capture("Riley keeps bees on the roof.", signed_as=OPUS)
    finally:
        runtime.close()
    later = _context(monkeypatch, S2)
    assert "ONBOARDING" not in later
    assert "QUIET HOURS - still to ask them" in later and NEW not in later
    assert "short tour" not in later and "1. " + HOURS[5:].capitalize() in later


# ── C: an agent that already had Mnemos, in Claude Code ──


def test_an_existing_agent_is_told_whats_new_in_mnemos_context(claude_code, monkeypatch, capsys):
    _an_agent_from_before(capsys)

    packet = _context(monkeypatch, S1)

    assert NEW in packet and "ONBOARDING" not in packet
    block = packet.split(NEW, 1)[1]
    assert ("each quiet hour is now theirs to choose on its own: when it runs, how long, and "
            "whether it can go online. They haven't been asked about it yet.") in packet
    assert "none goes online unless they choose it" not in packet, "untrue of a legacy own hour"
    assert VOICE in block
    assert "its Settings is where they choose your quiet hours" in block
    assert LEGACY_MINE in block
    mine = next(line for line in block.splitlines() if line.strip().startswith("- Your own hour"))
    assert mine.endswith(f"you read, write in your studio and think. {CAN_GO_ONLINE}"), mine
    assert "goes online only if they want it to" not in mine
    ours = next(line for line in block.splitlines() if line.strip().startswith("- Our hour"))
    assert ours.endswith("It's skipped on a day with no work, and goes online only if they want it to."), ours
    assert ("If they'd rather have none, run the line for none. Once they've answered, don't ask "
            "again.") in block
    assert "If they say no" not in block
    assert "- Our hour, now on, daily at 19:00, up to half an hour, offline." in block
    assert "- The dream, now on, daily at 03:30, up to 20 minutes." in block
    assert f"all as they are: {_command('hours', 'keep', '--write')}" in block
    assert f"off: {_command('hours', 'off', 'mine', '--write')}" in block
    assert "3. Then open your page for them and show them its Settings" in block
    assert "never mention tools, databases, scopes or model ids" in block


def test_an_existing_agent_is_told_in_its_automatic_wake(claude_code, monkeypatch, capsys):
    _an_agent_from_before(capsys)

    woke = _hook(monkeypatch, capsys, S1)

    assert woke.startswith("## waking up"), woke
    assert NEW in woke and LEGACY_MINE in woke
    assert woke.index("### where i was") < woke.index(NEW)


def test_once_they_answer_it_stops_in_both(claude_code, monkeypatch, capsys):
    _an_agent_from_before(capsys)
    packet = _context(monkeypatch, S1)
    keep = next(line.split("all as they are: ", 1)[1] for line in packet.splitlines()
                if "all as they are: " in line)

    assert _as_the_agent_runs(keep) == 0
    assert state.answered_at("nova")
    assert all(hour["on"] for hour in state.hours_now("nova").values()), "keep keeps them"
    assert state.hour_online("nova", "mine"), "and the own hour keeps the web it had"

    assert NEW not in _context(monkeypatch, S2)
    assert NEW not in _hook(monkeypatch, capsys, S3)


def test_it_stops_after_three_sessions_counted_by_session(claude_code, monkeypatch, capsys):
    _an_agent_from_before(capsys)

    # One session seen by the wake and by mnemos_context, and again after a
    # compaction, counts once.
    assert NEW in _hook(monkeypatch, capsys, S1)
    assert NEW in _context(monkeypatch, S1)
    assert NEW in _hook(monkeypatch, capsys, S1)
    assert NEW in _context(monkeypatch, S2)
    assert NEW in _hook(monkeypatch, capsys, S3)
    # Three sessions: it stops, and the page and `mnemos hours` remain.
    assert NEW not in _hook(monkeypatch, capsys, S4)
    assert NEW not in _context(monkeypatch, S4)
    # A session it was shown in still has it.
    assert NEW in _context(monkeypatch, S2)
    assert state.answered_at("nova") is None, "stopping is not an answer"


def test_a_no_from_before_this_release_is_not_asked_again(claude_code, monkeypatch, capsys):
    """The old onboarding promised a no wouldn't be asked again: a recorded
    no with no answer since counts as answered, and reading it writes nothing."""
    _an_agent_from_before(capsys)
    choice = state.hours_dir("nova") / state.CHOICE_FILE
    choice.write_text(json.dumps({"choice": "no", "at": "2026-10-01T08:00:00+00:00"}) + "\n")
    before = choice.read_bytes()

    assert NEW not in _context(monkeypatch, S1)
    assert NEW not in _hook(monkeypatch, capsys, S2)
    assert choice.read_bytes() == before


def test_a_no_from_before_is_not_asked_inside_hermes_either():
    _hermes_from_before([])
    choice = state.hours_dir("leo") / state.CHOICE_FILE
    choice.parent.mkdir(parents=True, exist_ok=True)
    choice.write_text(json.dumps({"choice": "no", "at": "2026-11-10T08:00:00+00:00"}) + "\n")
    assert NEW not in _system_prompt()
    assert json.loads(choice.read_text()) == {"choice": "no", "at": "2026-11-10T08:00:00+00:00"}


def test_without_a_session_id_the_runtime_counts_its_own_sessions(claude_code, monkeypatch, capsys):
    _an_agent_from_before(capsys)
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    shown = []
    for _ in range(4):
        runtime = _runtime()
        try:
            shown.append(NEW in runtime.context())
        finally:
            runtime.close()
    assert shown == [True, True, True, False]


def test_the_wake_never_fails_over_it(claude_code, monkeypatch, capsys):
    _an_agent_from_before(capsys)

    def broken(agent_id):
        raise RuntimeError("the scheduler can't be read")

    monkeypatch.setattr(state, "hours_now", broken)
    woke = _hook(monkeypatch, capsys, S1)
    assert woke.startswith("## waking up") and "### where i was" in woke
    assert NEW not in woke
    assert capsys.readouterr().err == ""


def test_the_wake_creates_no_store(claude_code, monkeypatch, capsys):
    assert _hook(monkeypatch, capsys, S1) == ""
    assert not _db().exists()


def test_where_hours_cant_run_an_existing_agent_is_told_nothing(claude_code, monkeypatch, capsys):
    _an_agent_from_before(capsys)
    empty = Path.home() / "empty-bin"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    assert NEW not in _context(monkeypatch, S1)


# ── Hermes, through its provider ──


class FromCatalog(MnemosMemoryProviderCore):
    _from_catalog = True


def _hermes_home() -> Path:
    home = Path.home() / ".hermes"
    home.mkdir(parents=True, exist_ok=True)
    return home


def _provider(cls=FromCatalog) -> MnemosMemoryProviderCore:
    provider = cls(HermesMnemosConfig(db_path=str(Path.home() / "leo.db"), agent_id="leo",
                                      person_id="user", project_scope="global", deep_maintenance=False))
    provider.initialize("20261121_080000_s", platform="cli", hermes_home=str(_hermes_home()),
                        agent_context="primary")
    return provider


def _system_prompt(cls=FromCatalog) -> str:
    provider = _provider(cls)
    try:
        return provider.system_prompt_block()
    finally:
        provider.shutdown()


def _call(name: str, **args) -> dict:
    provider = _provider()
    try:
        return json.loads(provider.handle_tool_call(name, args))
    finally:
        provider.shutdown()


def _hermes_from_before(jobs: list[dict] | None) -> None:
    provider = _provider()
    try:
        provider.handle_tool_call("mnemos_introduce", {"agent_model": OPUS})
        provider.handle_tool_call("mnemos_capture", {"content": "Leo keeps the ferry timetable.",
                                                     "signed_as": OPUS})
    finally:
        provider.shutdown()
    if jobs is not None:
        (_hermes_home() / "cron").mkdir(exist_ok=True)
        (_hermes_home() / "cron" / "jobs.json").write_text(json.dumps({"jobs": jobs}))


def _agent_job(kind: str, schedule: str, *, online: bool = False) -> dict:
    return {"id": f"a-{kind}", "name": f"mnemos-hour-{kind}", "enabled": True,
            "prompt": hermes_hours.JOB_PROMPT.format(kind=kind),
            "schedule": {"kind": "cron", "expr": schedule},
            "enabled_toolsets": hermes_hours.toolsets(kind, online)}


def _terminal_job(kind: str) -> dict:
    return {"id": f"t-{kind}", "name": f"mnemos-hour-{kind}", "enabled": True,
            "prompt": agent_hours.message(kind, "mnemos", [], "hermes"),
            "schedule": {"kind": "cron", "expr": agent_hours.cron(kind)}}


@pytest.mark.parametrize("cls", [FromCatalog, MnemosMemoryProviderCore], ids=["catalog", "connect"])
def test_hermes_fresh_offers_each_hour_with_its_own_toolsets(cls):
    wake = _system_prompt(cls)
    assert TOUR in wake and "its Settings shows your quiet hours; to change one, they ask you" in wake
    walk = wake.split("7. " + HOURS, 1)[1].split("\n8. ", 1)[0]
    assert 'enabled_toolsets ["memory", "no_mcp"], or ["memory", "no_mcp", "web"] if they want it online' in walk
    assert ('enabled_toolsets ["memory", "session_search", "no_mcp"], or '
            '["memory", "session_search", "no_mcp", "web"] if they want it online') in walk
    dream = walk.split("name mnemos-hour-dream", 1)[1].split("\n  Hermes itself", 1)[0]
    assert dream.rstrip().endswith('enabled_toolsets ["memory", "no_mcp"]'), dream
    assert "Hermes itself then limits each hour to your memory's tools, and the web only where they chose it" in walk
    assert "connect hermes --hours" not in wake and "--no-hours" not in wake


def test_hermes_existing_with_jobs_the_agent_made_says_them_as_they_are():
    _hermes_from_before([_agent_job("mine", "15 7 * * *", online=True), _agent_job("dream", "30 3 * * *")])

    wake = _system_prompt()

    assert NEW in wake
    block = wake.split(NEW, 1)[1]
    assert ("each quiet hour is now theirs to choose on its own: when it runs, and whether it "
            "can go online. They haven't been asked about it yet.") in wake
    assert "how long" not in wake.split(NEW, 1)[1].split("\n2. ", 1)[0]
    assert ("- Your own hour, now on, daily at 07:15, and it can go online. It's time with nothing "
            "asked of you, each morning: you go back over your memory, think and write in your "
            "journal. They can keep it online or take it offline.") in block
    assert "If they'd rather have none, keep []. Once they've answered, don't ask again." in block
    assert "If they say no, keep []" not in block
    assert "- Our hour, now off (no job for it)." in block
    assert "- The dream, now on, daily at 03:30. It's a short dream" in block
    assert "isn't limited to your memory" not in block.split("Do exactly what they said", 1)[0]
    assert "3. If they ask to see it, open your page for them" in block


def test_hermes_existing_with_jobs_made_in_a_terminal_is_offered_a_limited_remake():
    _hermes_from_before([_terminal_job(kind) for kind in ("mine", "ours", "dream")])

    wake = _system_prompt()

    block = wake.split(NEW, 1)[1].split("Do exactly what they said", 1)[0]
    for name in ("Your own hour", "Our hour", "The dream"):
        line = next(line for line in block.splitlines() if line.strip().startswith(f"- {name}, now on"))
        assert "Its job isn't limited to your memory: it was made without a list of tools" in line
        assert "Offer to remake it limited to your memory" in line
    assert "It never goes online" not in block, "not true of a job that isn't limited"
    assert "Remade limited, it never goes online." in block
    assert "A job that isn't limited to your memory is remade the same way" in wake


def test_hermes_existing_where_it_cant_tell_says_nothing_of_the_jobs():
    _hermes_from_before(None)
    block = _system_prompt().split(NEW, 1)[1]
    assert "now on" not in block and "now off" not in block and "They're all off now" not in block
    assert "- Your own hour. It's time with nothing asked of you" in block


def test_hermes_stops_once_the_person_answers():
    _hermes_from_before([])
    assert NEW in _system_prompt()
    assert _call("mnemos_hour", chosen=[{"kind": "ours", "at": "20:00", "online": False}])["ok"]
    assert NEW not in _system_prompt()


# ── mnemos_hour with chosen ──


def test_chosen_is_kept_through_the_same_writers():
    said = _call("mnemos_hour", chosen=[{"kind": "mine", "at": "08:00", "online": True},
                                        {"kind": "dream", "at": "03:30"}])
    assert said == {"ok": True, "result": (
        "Kept what they chose: your own hour at 08:00 (online) and the dream at 03:30; "
        "our hour is off."
    )}
    kept = json.loads((state.hours_dir("leo") / state.CHOICE_FILE).read_text())
    assert kept["hours"] == {"mine": {"at": "08:00", "online": True}, "dream": {"at": "03:30"}}
    assert state.hours_choice("leo") == "yes" and state.answered_at("leo")
    assert state.hour_settings("leo")["mine"] == {"at": "08:00", "minutes": 60, "online": True}


def test_none_chosen_is_a_no_that_is_kept():
    said = _call("mnemos_hour", chosen=[])
    assert said["result"] == "Kept: they want no quiet hours, and you won't be asked to offer them again."
    assert state.hours_choice("leo") == "no" and state.answered_at("leo")


@pytest.mark.parametrize("chosen,sentence", [
    ([{"kind": "dream", "at": "03:30", "online": True}], "A dream never goes online."),
    ([{"kind": "mine", "at": "8am"}], "'8am' isn't a time like 08:00, for your own hour."),
    ([{"kind": "nap", "at": "13:00"}], "There's no hour called 'nap': they're mine, ours and dream."),
    ([{"kind": "ours", "at": "19:00"}, {"kind": "ours", "at": "20:00"}], "Our hour is in chosen twice."),
    ([{"kind": "mine", "at": "08:00", "online": "yes"}], "online is true or false, for your own hour."),
    ("mine at eight", 'chosen is a list of the hours they chose, like [{"kind": "mine", "at": "08:00", '
                      '"online": false}], or [] for none.'),
])
def test_chosen_refuses_what_no_hour_can_have_in_one_sentence(chosen, sentence):
    said = _call("mnemos_hour", chosen=chosen)
    assert said["ok"] is False and said["error"] == sentence
    assert not (state.hours_dir("leo") / state.CHOICE_FILE).exists(), "nothing is kept"


def test_kind_and_chosen_together_are_refused():
    said = _call("mnemos_hour", kind="mine", chosen=[])
    assert said["error"] == "Give kind to take an hour, or chosen to keep what they chose, not both."
    assert state.answered_at("leo") is None


def test_chosen_may_come_as_json_words():
    assert _call("mnemos_hour", chosen='[{"kind": "ours", "at": "19:30"}]')["ok"]
    assert state.hour_settings("leo")["ours"]["at"] == "19:30"


# ── mnemos connect hermes leaves the agent's own jobs alone ──


def test_out_of_date_spares_jobs_the_agent_made(monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(_hermes_home()))
    (_hermes_home() / "cron").mkdir(exist_ok=True)
    older = _terminal_job("ours")
    older["prompt"] = "It is time for your quiet hour (ours). Run this: mnemos life --hour ours --handoff"
    (_hermes_home() / "cron" / "jobs.json").write_text(json.dumps({"jobs": [
        _agent_job("mine", "0 9 * * *", online=True), older, _agent_job("dream", "30 3 * * *"),
    ]}))

    assert agent_hours.out_of_date("hermes", "mnemos", []) == ["mnemos-hour-ours"]


def test_connect_hermes_hours_says_its_jobs_arent_limited(monkeypatch):
    from mnemos import connect_cmd

    monkeypatch.setattr(connect_cmd.ah, "install", lambda *a, **k: (True, "mnemos-hour-mine: scheduled"))
    scope = types.SimpleNamespace(agent_id="leo", db_path=str(Path.home() / "leo.db"))
    ok, said = connect_cmd._hours_on(hs.get("hermes"), scope)
    assert ok
    assert ("Jobs made this way aren't limited to the memory: they run with every tool Hermes gives "
            "its scheduled jobs. The agent can make limited ones itself in its next session.") in said


# ── Every other agent: the same tour, and its quiet-hours words as they were ──


_STEP_SIX = (
    "6. Then give them a short tour, in plain words, even if you knew them before: the memory is "
    "new to them even if you aren't, so knowing them is no reason to skip the tour. Tell them what "
    "you will now remember, in your own words, and that what isn't used fades with time unless "
    "they ask you to always remember it, and that they can see all of it, and answer your notes, "
    "on a page you'll open for them whenever they ask. There they can correct anything, or let it "
    "go. If you knew them before, say plainly that from now on you remember across sessions too.\n"
    "When you talk to the human, never mention tools"
)


@pytest.mark.parametrize("key", ["codex", "grok", "gemini", "openclaw"])
def test_other_agents_keep_their_words(key, monkeypatch, tmp_path):
    monkeypatch.setenv("MNEMOS_HARNESS", key)
    monkeypatch.setattr(connect, "status", lambda *a, **k: types.SimpleNamespace(wake="set", cue="set", upkeep=True))
    runtime = MnemosRuntime(db_path=str(tmp_path / f"{key}.db"), agent_id=key, use_dedicated_model=False)
    try:
        fresh = runtime.context()
        runtime.introduce(agent_model=OPUS)
        runtime.capture("Sam keeps the boat at the east pier.", signed_as=OPUS)
    finally:
        runtime.close()
    assert _STEP_SIX in fresh and HOURS not in fresh
    assert "Settings" not in fresh and "Finish by telling them" not in fresh
    if key != "openclaw":
        assert "life --hour mine --handoff" in fresh
    else:
        assert "connect openclaw --hours --write" in fresh
    again = MnemosRuntime(db_path=str(tmp_path / f"{key}.db"), agent_id=key, use_dedicated_model=False)
    try:
        later = again.context()
    finally:
        again.close()
    assert NEW not in later and "QUIET HOURS" not in later and HOURS not in later



@pytest.mark.parametrize("key", ["codex", "grok", "gemini", "openclaw", "hermes"])
def test_other_agents_hours_words_are_exactly_as_they_were(key, monkeypatch, tmp_path):
    """What is settled first, the quiet hours' words among it, is unchanged:
    only the ritual's step 6 became the tour. (Hermes here is Hermes over MCP,
    which has no mnemos_hour.)"""
    monkeypatch.setenv("MNEMOS_HARNESS", key)
    runtime = MnemosRuntime(db_path=str(tmp_path / f"{key}.db"), agent_id=key, use_dedicated_model=False)
    try:
        fresh = runtime.context()
    finally:
        runtime.close()
    from mnemos.simple_runtime import _ONBOARDING_HEAD, _RITUAL_INTRO

    before_ritual = fresh.split("1. Ask what they would like you to call them.", 1)[0]
    assert before_ritual.startswith(_ONBOARDING_HEAD)
    assert _RITUAL_INTRO in before_ritual
    assert "short tour" not in before_ritual and "one at a time" not in before_ritual


def test_an_unknown_agent_gets_the_tour_too(tmp_path):
    runtime = MnemosRuntime(db_path=str(tmp_path / "x.db"), agent_id="x", use_dedicated_model=False)
    try:
        runtime.introduce(agent_model=OPUS)
        almost = runtime.context()
    finally:
        runtime.close()
    assert almost.startswith("ONBOARDING - almost done")
    assert "Then give them a short tour" in almost and "Settings" not in almost


# ── QH-7: words the checker found untrue ──


def test_the_dream_in_hermes_is_said_plainly():
    walk = "\n".join(hermes_hours.walk_through(None))
    assert "It's a short dream over your memory, on the nights there's something for it: inward only." in walk
    assert "each night something waits for it" not in walk


def test_connect_hermes_hours_preview_says_where_replies_go_and_the_limit(monkeypatch):
    from mnemos import connect_cmd

    args = types.SimpleNamespace(hours=True, no_hours=False)
    scope = types.SimpleNamespace(agent_id="leo", db_path=str(Path.home() / "leo.db"))
    monkeypatch.setattr(connect_cmd.ah, "out_of_date", lambda *a, **k: [])
    ((said, _),) = connect_cmd._hours_steps(hs.get("hermes"), scope, args)
    assert "replies go nowhere" not in said
    assert "each reply is kept on this machine and sent to no one" in said
    assert ("Jobs made this way aren't limited to the memory: they run with every tool Hermes gives "
            "its scheduled jobs. The agent can make limited ones itself in its next session.") in said
    ((openclaw, _),) = connect_cmd._hours_steps(hs.get("openclaw"), scope, args)
    assert "each reply is sent to no chat or channel" in openclaw and "limited" not in openclaw


def test_the_page_says_no_hour_has_run_rather_than_none_scheduled():
    log = (Path(__file__).resolve().parent.parent / "mnemos" / "companion" / "page" / "log" / "log.js").read_text()
    assert "· no quiet hour has run yet`" in log
    assert "no quiet hours yet" not in log


@pytest.mark.parametrize("declared,place", [("claude-code", "claude-code"), ("hermes", "hermes"), ("codex", None)])
def test_a_declared_harness_gets_its_own_place(declared, place, monkeypatch, tmp_path):
    """Only a runtime declared "hermes" is Hermes's own provider; one declared
    "claude-code" is Claude Code's, never Hermes's (it was, on 09e6aa4)."""
    monkeypatch.delenv("CLAUDECODE", raising=False)
    monkeypatch.delenv("MNEMOS_HARNESS", raising=False)
    runtime = MnemosRuntime(db_path=str(tmp_path / "p.db"), agent_id="p", harness=declared,
                            use_dedicated_model=False)
    try:
        assert runtime._hours_place() == place
    finally:
        runtime.close()


def test_connect_hermes_hours_preview_hint_keeps_every_flag(capsys, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(_hermes_home()))
    db = str(Path.home() / "leo.db")
    assert main(["connect", "hermes", "--hours", "--agent-id", "leo", "--db-path", db]) == 0
    out = capsys.readouterr().out
    hint = next(line for line in out.splitlines() if line.startswith("Re-run with --write"))
    assert hint == f"Re-run with --write to do it: mnemos connect hermes --db-path {db} --agent-id leo --hours --write"
