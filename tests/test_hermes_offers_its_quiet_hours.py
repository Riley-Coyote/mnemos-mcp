"""The first session of a catalog install offers the quiet hours, as Hermes jobs.

Where Hermes's plugin catalog installed Mnemos, the first session told the agent
that quiet hours aren't offered: the jobs Mnemos made ran a ``mnemos`` command
from a folder Hermes rebuilds at every update. Now the agent takes its hour with
``mnemos_hour``, so the first session tells it to ask the person once, plainly,
and with a yes to make three Hermes scheduled jobs with Hermes's own tool
(``cronjob_manage``), or to give the person the three ``hermes cron create``
lines. Each job names no path, no command and no version. Mnemos makes no job
itself. A Mnemos that ``mnemos connect hermes`` connected is asked as before.

Temporary homes only.
"""

from __future__ import annotations

from pathlib import Path
import types

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
    home.mkdir(exist_ok=True)
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


def test_a_catalog_install_asks_once_and_says_what_the_hours_are(tmp_path, monkeypatch):
    settle, _ = _setup_part(tmp_path, monkeypatch)
    (offer,) = [item for item in settle if "Quiet hours" in item]
    said = " ".join(offer.split())
    assert "Tell them once, in plain words" in said
    assert "go back over the day" in said and "write in your journal" in said
    assert "Hermes scheduled jobs" in said and "the model Hermes uses" in said
    assert "costs what a short conversation costs" in said
    assert "what it reads of your memory goes to that model" in said
    assert "only while Hermes's gateway is running" in said
    assert "off unless they say yes" in said and "If they say no, don't ask again" in said


def test_with_a_yes_it_makes_the_three_jobs_with_hermes_own_tool(tmp_path, monkeypatch):
    settle, _ = _setup_part(tmp_path, monkeypatch)
    (offer,) = [item for item in settle if "Quiet hours" in item]
    # It looks first, so no job is made twice.
    assert "cronjob_manage (action list)" in offer
    assert "isn't there yet" in offer and "cronjob_manage (action create" in offer
    for name, (schedule, prompt) in JOBS.items():
        assert f"  - name {name}, schedule {schedule}, deliver local, prompt: {prompt}\n" in offer, offer


def test_without_that_tool_the_person_gets_the_three_lines(tmp_path, monkeypatch):
    settle, _ = _setup_part(tmp_path, monkeypatch)
    (offer,) = [item for item in settle if "Quiet hours" in item]
    assert "If you have no cronjob_manage tool" in offer
    for name, (schedule, prompt) in JOBS.items():
        assert f"  hermes cron create --name {name} --deliver local '{schedule}' '{prompt}'" in offer, offer


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
    said = "\n".join(settle + [lines or ""])
    assert "connect hermes" not in said and "--hours" not in said and "mnemos life" not in said
    assert "aren't offered" not in said


def test_the_first_session_carries_it_and_a_later_one_doesnt(tmp_path):
    first = _provider(tmp_path)
    try:
        wake = first.system_prompt_block()
        first.handle_tool_call("mnemos_introduce", {"agent_model": OPUS})
        first.handle_tool_call("mnemos_capture", {"content": "Leo keeps the ferry timetable.", "signed_as": OPUS})
    finally:
        first.shutdown()
    assert "mnemos-hour-mine" in wake and "cronjob_manage" in wake, wake
    later = _provider(tmp_path)
    try:
        again = later.system_prompt_block()
    finally:
        later.shutdown()
    assert "mnemos-hour-mine" not in again and "cronjob_manage" not in again


def test_a_mnemos_connect_installed_is_asked_as_before(tmp_path, monkeypatch):
    settle, _ = _setup_part(tmp_path, monkeypatch, MnemosMemoryProviderCore)
    (ask,) = [item for item in settle if "Quiet hours" in item]
    assert "connect hermes --hours --write" in ask and "connect hermes --no-hours --write" in ask
    assert "cronjob_manage" not in ask and "mnemos_hour" not in ask


def test_the_readme_gives_the_same_three_lines():
    from mnemos.integrations.hermes.hours import cron_create_line, jobs

    readme = (Path(__file__).resolve().parent.parent / "hermes-plugin" / "README.md").read_text(encoding="utf-8")
    for job in jobs():
        assert f"\n{cron_create_line(job)}\n" in readme, job["name"]
