"""A memory restored under another home folder is still the memory.

The first session wrote ``db_path`` into ``mnemos.json`` as a full path under
the user's home folder (``/Users/ann/.mnemos/hermes.db``). Hermes's backup puts
the memory back under whatever home it is restored to (``/Users/annb`` on a
new Mac, another username), and the settings it restores still named the old
one: the session opened a new, empty memory there, or couldn't start.

Now a memory in the user's own ``~/.mnemos/`` is written as
``~/.mnemos/<file>``, never with the home folder spelled out. A home settled
before with the spelled-out form of a path under this home's ``.mnemos`` is
given the ``~`` form the next time the plugin starts there, and nothing else
in its settings changes. Any other path a person set stays exactly as it is.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from mnemos.integrations.hermes import MnemosMemoryProviderCore


def _start(home: Path) -> MnemosMemoryProviderCore:
    provider = MnemosMemoryProviderCore()
    provider.initialize("s-1", hermes_home=str(home), platform="cli")
    return provider


def _settings(home: Path) -> dict:
    return json.loads((home / "mnemos.json").read_text())


def test_a_memory_restored_under_another_home_wakes_with_what_was_kept(tmp_path, monkeypatch):
    first, second = tmp_path / "ann", tmp_path / "annb"
    monkeypatch.setenv("HOME", str(first))
    monkeypatch.setenv("HERMES_HOME", str(first / ".hermes"))
    (first / ".hermes").mkdir(parents=True)
    provider = _start(first / ".hermes")
    assert json.loads(provider.handle_tool_call("mnemos_capture", {"content": "Ann's sister is called Maud."}))["ok"]
    provider.shutdown()
    assert _settings(first / ".hermes")["db_path"] == "~/.mnemos/hermes.db"

    # Restored as Hermes restores: its own folder, and the provider's files
    # under the new home by their place under the old one.
    shutil.copytree(first / ".hermes", second / ".hermes")
    shutil.copytree(first / ".mnemos", second / ".mnemos")
    shutil.rmtree(first)
    monkeypatch.setenv("HOME", str(second))
    monkeypatch.setenv("HERMES_HOME", str(second / ".hermes"))

    provider = _start(second / ".hermes")
    try:
        assert Path(provider.scope.db_path) == second / ".mnemos" / "hermes.db"
        assert "Maud" in provider.system_prompt_block()
    finally:
        provider.shutdown()


def test_a_home_settled_with_the_home_spelled_out_is_given_the_short_form(monkeypatch):
    home = Path.home() / ".hermes"
    home.mkdir()
    spelled = str(Path.home() / ".mnemos" / "kept.db")
    before = {"db_path": spelled, "agent_id": "sage", "person_id": "ann", "project_scope": "pottery",
              "hermes_home": str(home), "max_recall_results": 6}
    (home / "mnemos.json").write_text(json.dumps(before))

    _start(home).shutdown()

    assert _settings(home) == {**before, "db_path": "~/.mnemos/kept.db"}


def test_any_other_path_a_person_set_stays_as_it_is(tmp_path):
    home = Path.home() / ".hermes"
    home.mkdir()
    for spelled in (str(tmp_path / "elsewhere" / "kept.db"), str(tmp_path / "someone" / ".mnemos" / "kept.db")):
        before = {"db_path": spelled, "agent_id": "sage", "person_id": "ann", "project_scope": "pottery",
                  "hermes_home": str(home)}
        (home / "mnemos.json").write_text(json.dumps(before))
        _start(home).shutdown()
        assert _settings(home) == before
