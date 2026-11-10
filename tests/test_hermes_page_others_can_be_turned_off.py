"""Whether the page in Hermes's classic terminal shows the other agents is a setting.

In Hermes's terminal (platform "cli") the page also lets the person read the
other agents whose memory is kept beside this one. Hermes gives "cli" to every
classic-terminal run, including one a third-party integration starts with
``hermes chat --source tool``, where the person talking may be someone else,
and it doesn't tell the provider the source. So ``page_shows_other_agents`` in
``mnemos.json`` (true by default) turns that off: the page is then this agent's
alone on every platform, and neither the tool's words nor the first session's
speak of the other agents.

The TUI (platform "tui") is left out: Hermes's web dashboard runs ``hermes --tui``
behind its in-browser chat, and the dashboard can be opened from another
computer on the network (hermes_cli/web_server_chat.py, main_dashboard.py).
"""

from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.request

import pytest

from mnemos.integrations.hermes import HermesMnemosConfig, MnemosMemoryProviderCore
from mnemos.integrations.hermes import provider as provider_module

TOLD_OF_OTHERS = "the memory of the other agents kept beside yours in ~/.mnemos, only to read"
FIRST_SESSION = "the page also lets them read the memory of the other agents Mnemos keeps on this computer"


def _provider(tmp_path, name: str, platform: str = "cli", **settings) -> MnemosMemoryProviderCore:
    provider = MnemosMemoryProviderCore(HermesMnemosConfig(
        db_path=str(tmp_path / f"{name}.db"), agent_id=name, person_id="user",
        project_scope="global", deep_maintenance=False, **settings,
    ))
    provider.initialize("session-1", hermes_home=str(tmp_path / f"home-{name}"), platform=platform)
    return provider


def _call(provider: MnemosMemoryProviderCore, tool: str, **args) -> str:
    reply = json.loads(provider.handle_tool_call(tool, args))
    assert reply["ok"], reply
    return reply["result"]


def _minds(said: str) -> list[str]:
    base = re.search(r"http://127\.0\.0\.1:\d+/\S+", said).group().rsplit("/log/", 1)[0]
    with urllib.request.urlopen(f"{base}/data/minds.json", timeout=60) as answer:
        return [mind["agentId"] for mind in json.loads(answer.read())["minds"]]


def _other_beside(tmp_path) -> None:
    other = _provider(tmp_path, "b")
    try:
        _call(other, "mnemos_capture", content="The glaze room is locked after six.")
    finally:
        other.shutdown()


@pytest.fixture(autouse=True)
def _close_pages():
    yield
    for page in list(provider_module._pages.values()):
        page.shutdown()
        page.server_close()
    provider_module._pages.clear()
    provider_module._page_holders.clear()


def test_it_is_on_unless_mnemos_json_turns_it_off(tmp_path):
    home = tmp_path / "hermes"
    home.mkdir()
    assert HermesMnemosConfig.load(home).page_shows_other_agents is True
    (home / "mnemos.json").write_text(json.dumps({"page_shows_other_agents": False}))
    assert HermesMnemosConfig.load(home).page_shows_other_agents is False
    assert HermesMnemosConfig.load(home).to_json_dict()["page_shows_other_agents"] is False


@pytest.mark.parametrize("platform", ["cli", "tui", "telegram"])
def test_turned_off_the_page_is_this_agents_alone_everywhere(tmp_path, platform):
    _other_beside(tmp_path)
    mine = _provider(tmp_path, "a", platform, page_shows_other_agents=False)
    try:
        assert _minds(_call(mine, "mnemos_page")) == ["a"]
    finally:
        mine.shutdown()


def test_turned_off_nothing_speaks_of_the_other_agents(tmp_path):
    mine = _provider(tmp_path, "a", page_shows_other_agents=False)
    try:
        tool = next(t["description"] for t in mine.get_tool_schemas() if t["name"] == "mnemos_page")
        woke = " ".join(mine.system_prompt_block().split())
    finally:
        mine.shutdown()
    assert TOLD_OF_OTHERS not in " ".join(tool.split()), tool
    assert "ONBOARDING" in woke and FIRST_SESSION not in woke
    # The terminal's own sentence about the page stays as it was: offered as anywhere it opens here.
    assert "on a page you'll open for them whenever they ask" in woke


def test_on_the_classic_terminal_still_shows_them(tmp_path):
    _other_beside(tmp_path)
    mine = _provider(tmp_path, "a")
    try:
        assert _minds(_call(mine, "mnemos_page")) == ["a", "b"]
    finally:
        mine.shutdown()


def test_the_tui_is_not_taken_for_the_classic_terminal(tmp_path):
    _other_beside(tmp_path)
    mine = _provider(tmp_path, "a", "tui")
    try:
        tool = next(t["description"] for t in mine.get_tool_schemas() if t["name"] == "mnemos_page")
        woke = " ".join(mine.system_prompt_block().split())
        assert _minds(_call(mine, "mnemos_page")) == ["a"]
    finally:
        mine.shutdown()
    assert TOLD_OF_OTHERS not in " ".join(tool.split()) and FIRST_SESSION not in woke


# ── It fails closed ──

ABSENT = object()


def _load(tmp_path, value):
    from mnemos.integrations.hermes import scope

    home = tmp_path / "hermes"
    home.mkdir(exist_ok=True)
    (home / "mnemos.json").write_text(json.dumps({} if value is ABSENT else {"page_shows_other_agents": value}))
    with scope._told_lock:  # each test starts with nothing said yet
        getattr(scope, "_told_page_setting", set()).clear()
    return HermesMnemosConfig.load(home)


@pytest.mark.parametrize("value", [ABSENT, True, 1, "true", " Yes ", "ON", "on"])
def test_it_is_on_only_when_it_says_so(tmp_path, value, caplog):
    with caplog.at_level(logging.WARNING):
        assert _load(tmp_path, value).page_shows_other_agents is True
    assert "page_shows_other_agents" not in caplog.text


@pytest.mark.parametrize("value", [False, 0, "false", "False ", "no", "OFF"])
def test_a_plain_no_turns_it_off_and_says_nothing(tmp_path, value, caplog):
    with caplog.at_level(logging.WARNING):
        assert _load(tmp_path, value).page_shows_other_agents is False
    assert "page_shows_other_agents" not in caplog.text


@pytest.mark.parametrize("value", [None, "disabled", "flase", [], {}, 2, 1.0, "y", ["true"], {"on": True}])
def test_anything_else_turns_it_off_and_hermes_log_says_so_once(tmp_path, value, caplog):
    """Read loosely, 0, null, "disabled", "flase", [] and {} all left the
    other agents shown (round seven, p11)."""
    with caplog.at_level(logging.WARNING):
        assert _load(tmp_path, value).page_shows_other_agents is False
        home = tmp_path / "hermes"
        assert HermesMnemosConfig.load(home).page_shows_other_agents is False  # read again: said once
    told = [r for r in caplog.records if "page_shows_other_agents" in r.getMessage()]
    assert len(told) == 1 and told[0].levelno == logging.WARNING, caplog.text
    # The setting's name and its file, never its value.
    assert re.fullmatch(
        r"Mnemos's page_shows_other_agents in \S+/hermes/mnemos\.json isn't a yes or a no, "
        r"so the page shows only this agent meanwhile\.", told[0].getMessage(),
    ), told[0].getMessage()


def test_turned_off_by_a_word_it_doesnt_know_the_page_is_its_own(tmp_path):
    _other_beside(tmp_path)
    home = tmp_path / "home-a"
    home.mkdir()
    (home / "mnemos.json").write_text(json.dumps({
        "db_path": str(tmp_path / "a.db"), "agent_id": "a", "person_id": "user",
        "project_scope": "global", "page_shows_other_agents": "disabled",
    }))
    mine = MnemosMemoryProviderCore()
    mine.initialize("session-1", hermes_home=str(home), platform="cli")
    try:
        assert mine.scope.agent_id == "a"
        assert _minds(_call(mine, "mnemos_page")) == ["a"]
    finally:
        mine.shutdown()
