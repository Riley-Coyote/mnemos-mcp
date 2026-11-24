"""Inside Hermes the first session walks the person through the quiet hours, as Hermes jobs.

The agent takes its hour with ``mnemos_hour``, so its first session ends (after
the tour) with the hours one at a time: what each is and costs, and, for each
one the person wants, a Hermes scheduled job the agent makes with Hermes's own
tool (``cronjob_manage``), limited by Hermes to the memory's tools (and the web
where chosen), or the ``hermes cron create`` lines when it can't reach that
tool. Each job names no path, no command and no version. Mnemos makes no job
itself. Since QH-3 a Mnemos that ``mnemos connect hermes`` connected is walked
through the same way, and the person's answer is kept (``mnemos_hour`` with
``chosen``), so the walk-through is offered until they answer.

Temporary homes only.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys
import types

import pytest

import mnemos
from mnemos.integrations.hermes import HermesMnemosConfig, MnemosMemoryProviderCore
from mnemos.setup import connect
from mnemos.setup import harnesses as hs

OPUS = "claude-opus-5-5"
PROMPT = (
    "This is your quiet hour. Call mnemos_hour with kind {kind} and take the hour it hands you "
    "as your own. End with one line that says what you did, or answer only [SILENT] if the hour "
    "skipped."
)
# The same hours as everywhere (setup/scheduler.py HOUR_JOBS): 08:00, 19:00, 03:30.
JOBS = {
    "mnemos-hour-mine": ("0 8 * * *", PROMPT.format(kind="mine")),
    "mnemos-hour-ours": ("0 19 * * *", PROMPT.format(kind="ours")),
    "mnemos-hour-dream": ("30 3 * * *", PROMPT.format(kind="dream")),
}


class FromCatalog(MnemosMemoryProviderCore):
    _from_catalog = True


def _provider(tmp_path, cls=FromCatalog) -> MnemosMemoryProviderCore:
    home = tmp_path / "hermes"
    home.mkdir(parents=True, exist_ok=True)
    provider = cls(HermesMnemosConfig(db_path=str(tmp_path / "a.db"), agent_id="a", person_id="user",
                                      project_scope="global", deep_maintenance=False))
    provider.initialize("20261110_080000_first", platform="cli", hermes_home=str(home), agent_context="primary")
    return provider


def _setup_part(tmp_path, monkeypatch, cls=FromCatalog):
    monkeypatch.setattr(connect, "status", lambda *a, **k: types.SimpleNamespace(wake="set", cue="set", upkeep=False))
    provider = _provider(tmp_path, cls)
    try:
        return provider._runtime._other_setup_part(hs.get("hermes"))
    finally:
        provider.shutdown()


def _wake(tmp_path, cls=FromCatalog) -> str:
    provider = _provider(tmp_path, cls)
    try:
        return provider.system_prompt_block()
    finally:
        provider.shutdown()


def _hours(wake: str) -> str:
    """The quiet hours' step of the ritual, as one line of words."""
    return " ".join(wake.split("7. Then the quiet hours", 1)[1].split("\n8. ", 1)[0].split())


def test_the_first_session_says_what_the_hours_are_and_what_they_cost(tmp_path):
    said = _hours(_wake(tmp_path))
    assert "if you'd like the time, say so honestly (it would be your own), and make clear it's entirely their call" in said
    assert "go back over your memory" in said and "write in your journal" in said
    assert "Hermes scheduled jobs" in said and "the model Hermes uses" in said
    assert "costs what a short conversation costs" in said
    assert "what it reads of your memory goes to that model's provider" in said
    assert "only while Hermes's gateway is running" in said
    assert "It never goes online" in said
    assert "If they say no, keep [] and don't ask again" in said
    assert ("Ask about each hour once. If they don't answer and go on to something else, change "
            "no job and keep nothing, say once, lightly, that your page's Settings shows them and "
            "they can ask you whenever they like, and don't ask again this session.") in said


def test_each_hour_they_want_is_made_with_hermes_own_tool_limited_to_the_memory(tmp_path):
    wake = _wake(tmp_path)
    said = _hours(wake)
    # It looks first, so no job is made twice.
    assert "cronjob_manage. List the scheduled jobs first (action list)" in said
    assert "make it (action create)" in said
    assert "Hermes itself then limits each hour to your memory's tools" in said
    tools = {
        "mnemos-hour-mine": '["memory", "no_mcp"], or ["memory", "no_mcp", "web"] if they want it online',
        "mnemos-hour-ours": ('["memory", "session_search", "no_mcp"], or '
                             '["memory", "session_search", "no_mcp", "web"] if they want it online'),
        "mnemos-hour-dream": '["memory", "no_mcp"]\n',
    }
    for name, (schedule, prompt) in JOBS.items():
        assert f"name {name}, schedule {schedule} for " in wake, wake
        assert f"deliver local, prompt: {prompt}\n" in wake
        assert f"enabled_toolsets {tools[name]}" in wake
    # An hour turned off is removed; what they chose is kept.
    assert "remove its job (action remove" in said
    assert "mnemos_hour, passing chosen" in said


def test_without_that_tool_the_person_gets_the_lines_and_is_told_they_arent_limited(tmp_path):
    wake = _wake(tmp_path)
    said = _hours(wake)
    # Hermes 0.23.0 keeps it behind its tool search by default (the run in a real Hermes, W1).
    behind = said.index("Hermes may keep cronjob_manage behind its tool search")
    assert "tool_search" in said and "tool_describe" in said and "tool_call" in said
    assert behind < said.index("If you can't reach cronjob_manage at all")
    assert "jobs made that way aren't limited to your memory" in said
    for name, (schedule, prompt) in JOBS.items():
        assert f"    hermes cron create --name {name} --deliver local '{schedule}' '{prompt}'" in wake, wake


def test_no_job_names_a_path_a_command_or_a_version():
    from mnemos.integrations.hermes.hours import jobs

    assert [(j["name"], j["schedule"], j["prompt"], j["deliver"]) for j in jobs()] == [
        (name, schedule, prompt, "local") for name, (schedule, prompt) in JOBS.items()
    ]
    for _, prompt in JOBS.values():
        assert "/" not in prompt and "mnemos life" not in prompt and "--" not in prompt
        assert not any(c.isdigit() for c in prompt)


def test_nothing_offered_runs_mnemos_outside_hermes(tmp_path, monkeypatch):
    settle, lines = _setup_part(tmp_path, monkeypatch)
    said = "\n".join(settle + [lines or "", _wake(tmp_path / "wake")])
    assert "connect hermes" not in said and "--hours" not in said and "mnemos life" not in said
    assert "aren't offered" not in said


def test_a_later_session_carries_it_until_they_answer(tmp_path):
    """A no is kept now (``mnemos_hour`` with ``chosen``), so the hours are
    offered until the person answers, not only in the first session."""
    first = _provider(tmp_path)
    try:
        wake = first.system_prompt_block()
        first.handle_tool_call("mnemos_introduce", {"agent_model": OPUS})
        first.handle_tool_call("mnemos_capture", {"content": "Leo keeps the ferry timetable.", "signed_as": OPUS})
    finally:
        first.shutdown()
    assert "mnemos-hour-mine" in wake and "cronjob_manage" in wake, wake
    unanswered = _wake(tmp_path)
    assert "QUIET HOURS - still to ask them" in unanswered and "cronjob_manage" in unanswered
    answering = _provider(tmp_path)
    try:
        kept = json.loads(answering.handle_tool_call("mnemos_hour", {"chosen": []}))
    finally:
        answering.shutdown()
    assert kept["ok"], kept
    again = _wake(tmp_path)
    assert "mnemos-hour-mine" not in again and "cronjob_manage" not in again


def test_a_mnemos_connect_installed_is_walked_through_the_same_way(tmp_path, monkeypatch):
    settle, _ = _setup_part(tmp_path, monkeypatch, MnemosMemoryProviderCore)
    assert not [item for item in settle if "Quiet hours" in item]
    said = _hours(_wake(tmp_path, MnemosMemoryProviderCore))
    assert "make it (action create)" in said and "enabled_toolsets" in said
    assert "connect hermes --hours" not in said and "--no-hours" not in said


def test_the_readme_gives_the_same_three_lines():
    from mnemos.integrations.hermes.hours import cron_create_line, jobs

    readme = (Path(__file__).resolve().parent.parent / "hermes-plugin" / "README.md").read_text(encoding="utf-8")
    for job in jobs():
        assert f"\n{cron_create_line(job)}\n" in readme, job["name"]


@pytest.mark.parametrize("done", ["mnemos_introduce", "mnemos_capture"])
def test_it_is_asked_while_the_first_session_is_unfinished(tmp_path, done):
    """In the "almost done" stage a later session reaches when the first did
    half of its setup, the hours are still offered while nobody answered."""
    first = _provider(tmp_path)
    try:
        assert "mnemos-hour-mine" in first.system_prompt_block()
        if done == "mnemos_introduce":
            first.handle_tool_call(done, {"agent_model": OPUS})
        else:
            first.handle_tool_call(done, {"content": "Leo keeps the ferry timetable.", "signed_as": OPUS})
    finally:
        first.shutdown()
    again = _wake(tmp_path)
    assert "ONBOARDING - almost done" in again, again
    assert "Then the quiet hours, one at a time" in again and "mnemos-hour-mine" in again


def test_where_the_hour_cant_be_prepared_it_isnt_offered(tmp_path, monkeypatch):
    """Without fcntl (Windows) mnemos_hour hands nothing, so jobs that call it
    would wake the agent for nothing (round seven, p04)."""
    monkeypatch.setitem(sys.modules, "mnemos.life", None)
    monkeypatch.delattr(mnemos, "life", raising=False)
    settle, lines = _setup_part(tmp_path, monkeypatch)
    said = "\n".join(settle + [lines or ""])
    assert "Quiet hours aren't offered" in said and "macOS or Linux" in said and "Don't offer them" in said
    assert "cronjob_manage" not in said and "mnemos-hour-mine" not in said
    (tmp_path / "first").mkdir()
    first = _provider(tmp_path / "first")
    try:
        wake = first.system_prompt_block()
    finally:
        first.shutdown()
    assert "Quiet hours aren't offered" in wake and "mnemos-hour-mine" not in wake
