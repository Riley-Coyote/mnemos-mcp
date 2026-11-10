"""A memory restored under another home folder is still the memory.

The first session writes the memory's path into ``mnemos.json`` spelled out in
full (``/Users/ann/.mnemos/hermes.db``), as 0.6.6 did. Hermes's backup puts the
memory back under whatever home it is restored to (``/Users/annb`` on a new
Mac, another username), and the settings it restores still name the old one:
the session opened a new, empty memory there.

An earlier fix wrote the path as ``~/.mnemos/...`` instead, and rewrote homes
to that form. That broke one Hermes home used by two processes with
different ``HOME`` (a service and a shell: each then opened its own), and a
profile not started since the upgrade still restored to an empty memory.

Now nothing is rewritten. When the file a home names isn't there, the folder
it names is called ``.mnemos``, and this user's own ``~/.mnemos/`` holds a
file of the same name, that file is the memory: it is opened, and the log
says so once, with both paths. ``mnemos.json`` is left as it is. In every
other case nothing changes: a named file that is there is opened, and one
that is nowhere is made where it is named.
"""

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path

from mnemos.integrations.hermes import MnemosMemoryProviderCore
from mnemos.integrations.hermes import scope as scope_module
from mnemos.integrations.hermes.scope import HermesMnemosConfig, memory_file


def _start(home: Path) -> MnemosMemoryProviderCore:
    provider = MnemosMemoryProviderCore()
    provider.initialize("s-1", hermes_home=str(home), platform="cli")
    return provider


def _settings(home: Path) -> dict:
    return json.loads((home / "mnemos.json").read_text())


def _kept_by(home_folder: Path, words: str, monkeypatch) -> Path:
    """A Hermes home whose memory holds ``words``, settled as the first session
    settles it, with ``home_folder`` the user's home."""
    monkeypatch.setenv("HOME", str(home_folder))
    hermes = home_folder / ".hermes"
    hermes.mkdir(parents=True)
    provider = _start(hermes)
    assert json.loads(provider.handle_tool_call("mnemos_capture", {"content": words}))["ok"]
    provider.shutdown()
    return hermes


def test_the_path_is_written_spelled_out_and_never_rewritten(tmp_path, monkeypatch):
    hermes = _kept_by(tmp_path / "ann", "Ann's sister is called Maud.", monkeypatch)
    written = _settings(hermes)
    assert written["db_path"] == str(tmp_path / "ann" / ".mnemos" / "hermes.db")

    _start(hermes).shutdown()
    assert _settings(hermes) == written


def test_a_memory_restored_under_another_home_wakes_with_what_was_kept(tmp_path, monkeypatch, caplog):
    first, second = tmp_path / "ann", tmp_path / "annb"
    hermes = _kept_by(first, "Ann's sister is called Maud.", monkeypatch)
    before = _settings(hermes)
    # Restored as Hermes restores: its own folder, and the provider's files
    # under the new home by their place under the old one.
    shutil.copytree(first / ".hermes", second / ".hermes")
    shutil.copytree(first / ".mnemos", second / ".mnemos")
    shutil.rmtree(first)
    monkeypatch.setenv("HOME", str(second))
    monkeypatch.setattr(scope_module, "_told_of_a_memory_found_here", set())

    with caplog.at_level(logging.WARNING, logger=scope_module.logger.name):
        for _ in range(2):
            provider = _start(second / ".hermes")
            try:
                assert Path(provider.scope.db_path) == second / ".mnemos" / "hermes.db"
                assert "Maud" in json.loads(provider.handle_tool_call("mnemos_recall", {"query": "Ann's sister"}))["result"]
            finally:
                provider.shutdown()

    said = [record.getMessage() for record in caplog.records if record.levelno == logging.WARNING]
    told = [line for line in said if before["db_path"] in line]
    assert len(told) == 1 and str(second / ".mnemos" / "hermes.db") in told[0], said
    assert _settings(second / ".hermes") == {**before, "hermes_home": str(second / ".hermes")}
    assert not (first / ".mnemos").exists(), "a new memory was made where the settings name it"


def test_two_processes_with_different_homes_open_the_one_memory(tmp_path, monkeypatch):
    """A service started with another HOME than the shell: the memory the
    settings name is there, so both open it."""
    hermes = _kept_by(tmp_path / "ann", "Ann's sister is called Maud.", monkeypatch)
    monkeypatch.setenv("HOME", str(tmp_path / "service"))
    (tmp_path / "service" / ".mnemos").mkdir(parents=True)
    (tmp_path / "service" / ".mnemos" / "hermes.db").write_bytes(b"")  # one of its own, by the same name

    provider = _start(hermes)
    try:
        assert Path(provider.scope.db_path) == tmp_path / "ann" / ".mnemos" / "hermes.db"
        assert "Maud" in json.loads(provider.handle_tool_call("mnemos_recall", {"query": "Ann's sister"}))["result"]
    finally:
        provider.shutdown()


def test_other_paths_are_opened_exactly_as_written(tmp_path, monkeypatch):
    home_folder = Path.home()
    real = home_folder / "store"
    real.mkdir()
    (home_folder / ".mnemos").symlink_to(real)
    (real / "g.db").write_bytes(b"")
    (real / "b.db").write_bytes(b"")
    (tmp_path / "elsewhere").mkdir()
    (tmp_path / "elsewhere" / "b.db").write_bytes(b"")
    hermes = home_folder / ".hermes"
    for given in (
        str(tmp_path / "gone" / ".mnemos" / "g.db"),   # gone; this user's ~/.mnemos (a link) holds a g.db
        f"{home_folder}/.mnemos/../g.db",               # its folder isn't called .mnemos: as written
        str(tmp_path / "elsewhere" / "b.db"),           # there: opened
        str(tmp_path / "someone" / ".mnemos" / "c.db"),  # nothing of that name here
    ):
        named = HermesMnemosConfig(db_path=given)
        opened = memory_file(hermes, named)
        if given.startswith(str(tmp_path / "gone")):
            assert opened == str(home_folder / ".mnemos" / "g.db")
        else:
            assert opened == given


def test_a_path_written_with_a_tilde_is_still_read_with_it_expanded():
    hermes = Path.home() / ".hermes"
    assert memory_file(hermes, HermesMnemosConfig(db_path="~/.mnemos/h.db")) == str(Path.home() / ".mnemos" / "h.db")
