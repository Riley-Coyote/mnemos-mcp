"""Inside Hermes, writes are signed with the model Hermes runs, and the wake names
the folder the person works in, never Hermes's own.

Hermes 0.23.0 tells a memory provider which folder the session works in (``cwd``)
but not which model runs it; a later Hermes passes the turn's model to
``on_turn_start``. And 0.23.0 runs every chat inside its gateway, whose working
folder is Hermes's install folder. So on 0.23.0 the first save came back
unsigned, asking the model to introduce itself, and every wake began "in
hermes-agent" wherever the person was.
"""

from __future__ import annotations

import json
from pathlib import Path

from mnemos.integrations.hermes.provider import MnemosMemoryProviderCore


def _home(tmp_path: Path, model: str | None = None) -> Path:
    home = tmp_path / "hermes"
    home.mkdir(exist_ok=True)
    if model is not None:
        (home / "config.yaml").write_text(f"model:\n  default: {model}\n  provider: nous\n")
    return home


def _start(home: Path, **extra) -> MnemosMemoryProviderCore:
    provider = MnemosMemoryProviderCore()
    provider.initialize(
        "20261108_010000_names", platform="cli", hermes_home=str(home),
        agent_context="primary", agent_identity="default", agent_workspace="hermes", **extra,
    )
    return provider


def _capture(provider: MnemosMemoryProviderCore, text: str) -> str:
    saved = json.loads(provider.handle_tool_call("mnemos_capture", {"content": text}))
    assert saved.get("ok"), saved
    return saved["result"]


def _hermes_own_folder(tmp_path: Path, monkeypatch) -> Path:
    """Where 0.23.0's gateway runs a chat: Hermes's install folder, a git checkout."""
    install = tmp_path / "hermes-agent"
    (install / ".git").mkdir(parents=True)
    monkeypatch.chdir(install)
    return install


def test_a_hermes_that_names_no_model_signs_with_the_one_it_starts_with(tmp_path):
    provider = _start(_home(tmp_path, model="nousresearch/hermes-4-405b"))
    said = _capture(provider, "The harbour ferry stops running in November.")
    author = provider._runtime.author_model()
    provider.shutdown()
    assert "Unsigned" not in said, said
    assert "hermes-4-405b" in author


def test_the_model_hermes_names_for_a_turn_still_signs_it(tmp_path):
    provider = _start(_home(tmp_path, model="nousresearch/hermes-4-405b"))
    provider.on_turn_start(1, "the ferry", model="anthropic/claude-opus-4.6")
    _capture(provider, "The harbour ferry's winter timetable starts on the first.")
    author = provider._runtime.author_model()
    provider.shutdown()
    assert "claude-opus-4" in author and "hermes-4" not in author


def test_without_a_model_anywhere_it_still_asks_for_an_introduction(tmp_path):
    provider = _start(_home(tmp_path))
    said = _capture(provider, "The lighthouse lamp is serviced in March.")
    provider.shutdown()
    assert "mnemos_introduce" in said


def _wake_after_one_memory(provider: MnemosMemoryProviderCore) -> str:
    """The wake as a session after the first sees it: a memory kept, then a new start."""
    _capture(provider, "The pier survey restarts after the spring tides.")
    return provider.system_prompt_block()


def test_the_wake_names_the_persons_folder_not_hermess(tmp_path, monkeypatch):
    _hermes_own_folder(tmp_path, monkeypatch)
    person = tmp_path / "harbour-survey"
    person.mkdir()
    provider = _start(_home(tmp_path), cwd=str(person))
    wake = _wake_after_one_memory(provider)
    provider.shutdown()
    assert "in harbour-survey" in wake, wake[:600]
    assert "hermes-agent" not in wake


def test_with_no_folder_from_hermes_the_wake_names_none(tmp_path, monkeypatch):
    """A chat on Telegram has no folder: the wake names no place at all."""
    _hermes_own_folder(tmp_path, monkeypatch)
    provider = _start(_home(tmp_path))
    wake = _wake_after_one_memory(provider)
    provider.shutdown()
    assert "## waking up" in wake, wake[:600]
    assert "hermes-agent" not in wake


def test_a_note_left_in_hermes_is_placed_where_the_person_works(tmp_path, monkeypatch):
    _hermes_own_folder(tmp_path, monkeypatch)
    person = tmp_path / "harbour-survey"
    person.mkdir()
    provider = _start(_home(tmp_path), cwd=str(person))
    saved = json.loads(provider.handle_tool_call("mnemos_handoff", {"text": "Halfway through the pier survey."}))
    assert saved.get("ok"), saved
    store = provider._runtime._store
    places = [row[0] for row in store._get_conn().execute(
        "SELECT author_place FROM hypomnema_entries WHERE entry_kind = 'handoff'")]
    provider.shutdown()
    assert places and all("hermes-agent" not in (place or "") for place in places), places
    assert any((place or "").endswith("harbour-survey") for place in places), places
