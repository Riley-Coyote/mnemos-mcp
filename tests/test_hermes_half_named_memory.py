"""A home that names part of its memory gets the rest as its settings promise.

Hermes's dashboard shows four settings for Mnemos, each "left empty" for a
default: the file in ~/.mnemos, the profile's own agent, "user", "global". That
held only when all four were empty. With the agent named and nothing else, the
first start settled nothing: the memory was kept inside Hermes's own folder,
under the name of whoever wrote and of the chat they wrote in, another memory
for each. With only the person named, the first start replaced their name
with "user".

Now each setting left empty is its default, and each one set stays as set.
Only before there is a memory: one a home has kept until now stays where and
as it is named.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mnemos.integrations.hermes.provider import MnemosMemoryProviderCore

_A_CHAT = dict(
    platform="telegram", agent_context="primary", gateway_session_key="telegram:chat:42",
    user_name="Riley C", user_id="777", chat_id="42", chat_name="Family group",
)


def _first_start(home: Path, settings: dict) -> tuple:
    home.mkdir(parents=True, exist_ok=True)
    (home / "mnemos.json").write_text(json.dumps(settings))
    provider = MnemosMemoryProviderCore()
    try:
        provider.initialize("s1", hermes_home=str(home), **_A_CHAT)
        scope = provider.scope
        return scope, json.loads((home / "mnemos.json").read_text())
    finally:
        provider.shutdown()


def test_naming_nothing_is_one_memory_outside_hermes():
    scope, _kept = _first_start(Path.home() / ".hermes", {})
    assert Path(scope.db_path) == Path.home() / ".mnemos" / "hermes.db"
    assert (scope.agent_id, scope.person_id, scope.project_scope) == ("hermes", "user", "global")


@pytest.mark.parametrize("named", [
    {"agent_id": "ada"},
    {"person_id": "riley"},
    {"project_scope": "the-boat"},
    {"agent_id": "ada", "person_id": "riley"},
    {"agent_id": "ada", "db_path": ""},  # the dashboard saves an untouched field empty
    {"db_path": "{here}/mine/ada.db"},
    {"agent_id": "ada", "db_path": "{here}/mine/ada.db"},
    {"agent_id": "ada", "db_path": "$HERMES_HOME/kept/ada.db"},
])
def test_what_is_left_empty_is_its_default_and_what_is_set_stays(tmp_path, named):
    home = Path.home() / ".hermes"
    named = {key: value.replace("{here}", str(tmp_path)) for key, value in named.items()}

    scope, kept = _first_start(home, named)

    wanted = {
        "db_path": "~/.mnemos/hermes.db", "agent_id": "hermes", "person_id": "user",
        "project_scope": "global", **{key: value for key, value in named.items() if value},
    }
    assert (scope.agent_id, scope.person_id, scope.project_scope) == (
        wanted["agent_id"], wanted["person_id"], wanted["project_scope"],
    ), "named after the chat and whoever wrote in it"
    assert scope.db_path == str(Path(wanted["db_path"].replace("$HERMES_HOME", str(home))).expanduser()), (
        "kept somewhere else"
    )
    assert {key: kept[key] for key in wanted} == wanted, "a setting the person chose was replaced"


@pytest.mark.parametrize("named", [
    {"agent_id": "ada"},
    {"db_path": "{here}/mine/ada.db"},
    {"agent_id": "ada", "db_path": "{here}/mine/ada.db"},
])
def test_a_memory_kept_until_now_stays_where_and_as_it_is(tmp_path, named):
    """A home that has been running on half-named settings has a memory under
    the names it worked out: those stay, or what it kept would be out of reach."""
    home = Path.home() / ".hermes"
    named = {key: value.replace("{here}", str(tmp_path)) for key, value in named.items()}
    before, _kept = _first_start(home, named)
    in_use = Path(named.get("db_path") or home / "mnemos" / "mnemos.db")
    # The memory those settings opened before 0.6.7, now with something in it.
    (home / "mnemos.json").write_text(json.dumps(named))
    in_use.parent.mkdir(parents=True, exist_ok=True)
    in_use.write_bytes(Path(before.db_path).read_bytes())

    scope, kept = _first_start(home, named)

    assert kept == named, "its settings were rewritten"
    assert Path(scope.db_path) == in_use
    assert (scope.person_id, scope.project_scope) == ("riley-c", "family-group")
