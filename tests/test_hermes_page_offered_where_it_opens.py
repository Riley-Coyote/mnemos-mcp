"""The page is offered only where it can be opened.

In a first session the agent is told to end by saying the person can see all
of it "on a page you'll open for them whenever they ask". The page is served
on 127.0.0.1 of the computer Hermes runs on. That is right in Hermes's
terminal, and no use to someone talking to the agent in Telegram on a phone.

In the terminal (``platform`` "cli") the first session's words stay exactly as
they were. On any other platform the agent is told the page opens in a browser
on the computer Hermes runs on, not to offer it unless the person asks, and if
they ask, to say where it opens.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mnemos.integrations.hermes.provider import MnemosMemoryProviderCore

_OFFERED = "on a page you'll open for them whenever they ask"
_WHERE_IT_OPENS = "opens in a browser on the computer Hermes runs on"


def _block(platform: str, *, almost_done: bool = False) -> str:
    home = Path.home() / ".hermes"
    home.mkdir(parents=True, exist_ok=True)
    if almost_done:  # a first session that kept one thing and went no further
        first = MnemosMemoryProviderCore()
        first.initialize("s0", platform=platform, hermes_home=str(home), agent_context="primary")
        assert json.loads(first.handle_tool_call("mnemos_capture", {"content": "Sam keeps the boat at the east pier."}))["ok"]
        first.shutdown()
    provider = MnemosMemoryProviderCore()
    try:
        provider.initialize("s1", platform=platform, hermes_home=str(home), agent_context="primary")
        return provider.system_prompt_block()
    finally:
        provider.shutdown()


@pytest.mark.parametrize("almost_done", [False, True])
def test_in_the_terminal_the_page_is_offered_as_before(almost_done):
    block = _block("cli", almost_done=almost_done)
    assert _OFFERED in block
    assert _WHERE_IT_OPENS not in block


@pytest.mark.parametrize("platform", ["telegram", "discord", "gui"])
@pytest.mark.parametrize("almost_done", [False, True])
def test_elsewhere_it_says_where_the_page_opens(platform, almost_done):
    block = _block(platform, almost_done=almost_done)
    assert "ONBOARDING" in block
    assert _OFFERED not in block, "offered a page the person can't open"
    assert _WHERE_IT_OPENS in block
    assert "Don't offer it unless they ask" in block
    assert "if they ask, tell them it opens there" in block
