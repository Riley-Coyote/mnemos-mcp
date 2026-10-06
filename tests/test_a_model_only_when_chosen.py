"""Mnemos calls a model only when the person chose one for it.

Until 2026-10-05 a provider key in the environment was enough. With only
OPENROUTER_API_KEY set, there for some other tool, a capture's words went to
openrouter.ai. A key on its own chooses nothing now: the choice is
MNEMOS_LLM_PROVIDER, or ``llm.provider`` in Mnemos's config. A chosen
provider without its key is no provider, never another one.
"""

import json
import urllib.request

import pytest

from mnemos import llm
from mnemos.config.loader import save_config
from mnemos.simple_runtime import MnemosRuntime, _dedicated_model_requested

KEYS = ("OPENROUTER_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY")


@pytest.mark.parametrize("key", KEYS)
def test_a_key_on_its_own_chooses_nothing(monkeypatch, key):
    monkeypatch.setenv(key, "test-key-for-another-tool")

    assert llm.create_client() is None
    assert _dedicated_model_requested() is False


def test_a_key_in_a_projects_env_file_chooses_nothing(monkeypatch, tmp_path):
    dotenv = tmp_path / ".env"
    dotenv.write_text("OPENAI_API_KEY=test-key-for-the-project\n")
    monkeypatch.setenv("MNEMOS_ENV_PATHS", str(dotenv))
    monkeypatch.delenv("MNEMOS_DISABLE_DOTENV")

    assert llm.create_client() is None

    dotenv.write_text("OPENAI_API_KEY=test-key-for-the-project\nMNEMOS_LLM_PROVIDER=openai\n")
    assert isinstance(llm.create_client(), llm.OpenAIClient)


def test_the_chosen_provider_is_used(monkeypatch):
    monkeypatch.setenv("MNEMOS_LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")

    assert isinstance(llm.create_client(), llm.OpenRouterClient)
    assert _dedicated_model_requested() is True


def test_a_chosen_provider_without_its_key_is_no_provider_not_another(monkeypatch):
    monkeypatch.setenv("MNEMOS_LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    assert llm.create_client() is None


@pytest.mark.parametrize("provider, chosen", [("openrouter", True), ("none", False)])
def test_setups_answer_in_the_config_is_the_choice(monkeypatch, provider, chosen):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    save_config({"llm": {"provider": provider, "api_key_env": "OPENROUTER_API_KEY"}})

    assert isinstance(llm.create_client(), llm.OpenRouterClient) is chosen
    assert _dedicated_model_requested() is chosen


def _captures_send(monkeypatch, tmp_path) -> list[str]:
    """The URLs two related captures send to, caught before they leave."""
    sent = []

    class Reply:
        def __init__(self, body):
            self.body = body

        def read(self):
            return self.body

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def urlopen(request, timeout=None):
        sent.append(request.full_url)
        return Reply(json.dumps({"choices": [{"message": {"content": "[]"}}]}).encode())

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    runtime = MnemosRuntime(db_path=str(tmp_path / "memory.db"), agent_id="nova")
    try:
        for words in (
            "Riley keeps his health details private; never repeat them.",
            "Riley said his health details stay private, even from notes.",
        ):
            runtime.capture(words, signed_as="claude-opus-5-5")
    finally:
        runtime.close()
    return sent


def test_a_capture_with_only_a_key_around_sends_nothing(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key-for-another-tool")

    assert _captures_send(monkeypatch, tmp_path) == []


def test_a_capture_with_a_chosen_provider_does_reach_it(monkeypatch, tmp_path):
    """The catch above can see a send: with the provider chosen, the same
    captures reach it."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("MNEMOS_LLM_PROVIDER", "openrouter")

    sent = _captures_send(monkeypatch, tmp_path)

    assert sent and all(url.startswith("https://openrouter.ai/") for url in sent)


def test_a_provider_mnemos_does_not_know_is_no_provider(monkeypatch, caplog):
    """A live ~/.mnemos/.env named "hermes", left from an integration: no
    provider, said once rather than on every client."""
    monkeypatch.setenv("MNEMOS_LLM_PROVIDER", "hermes")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setattr(llm, "_WARNED", set())

    with caplog.at_level("WARNING", logger="mnemos.llm"):
        assert llm.create_client() is None
        assert llm.create_client() is None
    assert _dedicated_model_requested() is False
    assert sum("'hermes' is not one it knows" in r.getMessage() for r in caplog.records) == 1
