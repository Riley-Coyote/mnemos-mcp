"""The OpenRouter key Mnemos borrows from OpenClaw is an OpenRouter key.

Mnemos with provider openrouter and no OPENROUTER_API_KEY falls back to
OpenClaw's ``tools.web.search.perplexity.apiKey``. That is OpenClaw's
Perplexity web-search slot, and OpenClaw takes either kind of key there: a
``pplx-`` key goes to Perplexity's own API, an ``sk-or-`` key (or a baseUrl at
openrouter.ai) goes through OpenRouter. Until 2026-11-08 Mnemos took whatever was
there, so a Perplexity key went to openrouter.ai as the Bearer token: a
credential sent to the wrong company, and upkeep failing with no reason given.
"""

import json
import logging
from pathlib import Path

import pytest

from mnemos import llm


def _openclaw(perplexity: dict) -> None:
    config = Path.home() / ".openclaw" / "openclaw.json"  # the test's own home
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(json.dumps({"tools": {"web": {"search": {"perplexity": perplexity}}}}))


@pytest.fixture
def openrouter_chosen(monkeypatch):
    monkeypatch.setenv("MNEMOS_LLM_PROVIDER", "openrouter")
    monkeypatch.delenv("MNEMOS_DISABLE_DOTENV")  # OpenClaw's file is read only then
    monkeypatch.setattr(llm, "_WARNED", set())


def test_a_perplexity_key_is_not_sent_to_openrouter(openrouter_chosen, caplog):
    _openclaw({"apiKey": "pplx-fake-key-for-the-test"})

    with caplog.at_level(logging.WARNING, logger=llm.logger.name):
        assert llm.create_client() is None
        llm.create_client()

    said = [r.getMessage() for r in caplog.records if "tools.web.search.perplexity.apiKey" in r.getMessage()]
    assert len(said) == 1  # once, not on every client
    assert "pplx-fake" not in caplog.text  # the setting is named, never the key


def test_an_openrouter_key_there_is_still_used(openrouter_chosen):
    _openclaw({"apiKey": "sk-or-v1-fake-key-for-the-test"})

    client = llm.create_client()
    assert isinstance(client, llm.OpenRouterClient)
    assert client._api_key == "sk-or-v1-fake-key-for-the-test"


def test_a_key_with_openclaws_openrouter_base_url_is_used(openrouter_chosen):
    _openclaw({"apiKey": "fake-key-for-the-test", "baseUrl": "https://openrouter.ai/api/v1"})

    assert isinstance(llm.create_client(), llm.OpenRouterClient)


def test_a_secret_reference_there_is_no_key(openrouter_chosen):
    # OpenClaw also takes a SecretRef object in its key fields; it isn't a key.
    _openclaw({"apiKey": {"source": "env", "id": "PERPLEXITY_API_KEY"}})

    assert llm.create_client() is None
