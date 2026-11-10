"""The settings Hermes's dashboard shows say which person and project are used.

They said "Left empty: user" and "Left empty: global". That held for a new
home on a machine without Mnemos's own config. Two homes used something else:

- a new home on a machine where Mnemos is set up takes the person and the
  project ``~/.mnemos/config.json`` names (``user_name`` or ``person_id``,
  ``project_scope``), and the first session writes those in;
- a home that already had a memory with these empty goes on as it did, so what
  it kept stays in reach: the person each chat names (``user`` when none does),
  and the chat's name or, with none, the folder Hermes was started in.

The behaviour is what it was; the words now say it. A home with a memory going
on as it did is also pinned in ``tests/test_hermes_half_named_memory.py``.

The same held for where the memory is and which agent it is: "Left empty:
~/.mnemos/hermes.db" and "Left empty: hermes". A home that already had a
memory with these empty goes on with it where it is, in
``$HERMES_HOME/mnemos/mnemos.db``, as the agent Hermes names for the profile
(``default`` for the default one), or ``hermes`` where Hermes names none.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mnemos.integrations.hermes.provider import MnemosMemoryProviderCore

_A_CHAT = dict(
    platform="telegram", gateway_session_key="telegram:chat:42",
    user_name="Riley C", user_id="777", chat_id="42", chat_name="Family group",
)


def _help() -> dict[str, str]:
    return {field["key"]: field["description"] for field in MnemosMemoryProviderCore().get_config_schema()}


def _start(*, mnemos_config: dict | None = None, kept_already: bool = False, chat: bool = False, monkeypatch) -> tuple:
    home = Path.home() / ".hermes"
    home.mkdir(parents=True, exist_ok=True)
    if mnemos_config is not None:
        (Path.home() / ".mnemos").mkdir(exist_ok=True)
        (Path.home() / ".mnemos" / "config.json").write_text(json.dumps(mnemos_config))
    if kept_already:  # the memory a home kept before its settings were filled in
        (home / "mnemos").mkdir(exist_ok=True)
        (home / "mnemos" / "mnemos.db").write_bytes(b"")
    work = Path.home() / "work" / "boat-repairs"
    work.mkdir(parents=True, exist_ok=True)
    monkeypatch.chdir(work)
    provider = MnemosMemoryProviderCore()
    try:
        provider.initialize("s1", hermes_home=str(home), agent_context="primary",
                            **(_A_CHAT if chat else {"platform": "cli"}))
        return provider.scope.person_id, provider.scope.project_scope
    finally:
        provider.shutdown()


@pytest.mark.parametrize(("case", "used"), [
    ({}, ("user", "global")),
    ({"mnemos_config": {"user_name": "Riley Q", "project_scope": "claude-work"}}, ("riley-q", "claude-work")),
    ({"kept_already": True}, ("user", "boat-repairs")),
    ({"kept_already": True, "chat": True}, ("riley-c", "family-group")),
])
def test_the_person_and_project_used_are_the_ones_the_help_names(monkeypatch, case, used):
    assert _start(monkeypatch=monkeypatch, **case) == used


def test_the_help_says_each_of_them():
    shown = _help()
    person, project = shown["person_id"], shown["project_scope"]
    for said in (person, project):
        assert "~/.mnemos/config.json" in said, said
        assert "already had a memory" in said, said
    assert "Left empty: user." not in person and "user" in person
    assert "the person each chat names" in person
    assert "Left empty: global, one memory for everything." not in project and "global" in project
    assert "the chat's name" in project and "the folder Hermes was started in" in project


@pytest.mark.parametrize(("profile", "named_by_hermes", "agent"), [
    ("", "default", "default"),
    ("work", "work", "work"),
    ("work", None, "hermes"),
])
def test_a_home_with_a_memory_goes_on_where_and_as_the_help_says(profile, named_by_hermes, agent):
    home = Path.home() / ".hermes" / ("profiles/" + profile if profile else "")
    (home / "mnemos").mkdir(parents=True)
    (home / "mnemos" / "mnemos.db").write_bytes(b"")  # the memory it kept before its settings were filled in
    provider = MnemosMemoryProviderCore()
    identity = {"agent_identity": named_by_hermes} if named_by_hermes else {}
    try:
        provider.initialize("s1", hermes_home=str(home), platform="cli", **identity)
        assert Path(provider.scope.db_path) == home / "mnemos" / "mnemos.db"
        assert provider.scope.agent_id == agent
    finally:
        provider.shutdown()


def test_the_help_says_where_and_which_agent():
    shown = _help()
    where, who = shown["db_path"], shown["agent_id"]
    for said in (where, who):
        assert "already had a memory" in said, said
    # Said without $HERMES_HOME, which the dashboard never shows (test_hermes_same_tools.py).
    assert "mnemos/mnemos.db in the profile's own folder" in where and "~/.mnemos/hermes.db" in where
    assert "the profile's name as Hermes gives it" in who and "default" in who and "hermes" in who


def test_the_readme_says_the_same():
    readme = (Path(__file__).resolve().parents[1] / "hermes-plugin" / "README.md").read_text()
    settings = readme.split("## Settings", 1)[1].split("\n## ", 1)[0]
    assert "`person_id` (user)" not in settings
    assert "~/.mnemos/config.json" in settings and "already had a memory" in settings
    files = readme.split("**Its own files.**", 1)[1].split("\n- **", 1)[0]
    assert "`~/.mnemos/config.json`" in files and "person and project" in files
    kept = readme.split("## Where it's kept", 1)[1].split("\n## ", 1)[0]
    assert "`$HERMES_HOME/mnemos/mnemos.db`" in kept
