"""A hermetic run never reaches a live ~/.mnemos (mnemos/live_guard.py).

Every case here proves the guard on a fake real home under the test's own
temporary folder; nothing in this file names, opens or creates anything in
the real ~/.mnemos.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from mnemos import live_guard
from mnemos.live_guard import LiveStoreRefused
from mnemos.simple_scope import resolve_scope
from mnemos.store.sqlite_store import EngramStore

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture
def fake_real_home(tmp_path, monkeypatch):
    """A home that stands in for the real one: protected, and never Path.home()."""
    home = tmp_path / "fake-real-home"
    home.mkdir()
    monkeypatch.setenv(live_guard.PROTECTED_HOME_ENV, str(home))
    yield home
    # The refusals these tests make on purpose are theirs, not a leak.
    live_guard.refusals.clear()


def test_the_suite_is_hermetic():
    assert os.environ.get("MNEMOS_HERMETIC") == "1"
    assert "MNEMOS_I_MEAN_IT" not in os.environ
    # The temporary HOME is not the protected one.
    assert live_guard.protected_root_for(Path.home() / ".mnemos" / "x.db") is None


def test_a_store_under_the_fake_real_home_is_refused(fake_real_home):
    target = fake_real_home / ".mnemos" / "claude-code.db"
    with pytest.raises(LiveStoreRefused, match="--i-mean-it"):
        EngramStore(target)
    # Refused before anything was made: no folder, no file.
    assert not (fake_real_home / ".mnemos").exists()
    assert live_guard.refusals


def test_the_flag_lets_it_through(fake_real_home, monkeypatch):
    monkeypatch.setenv(live_guard.I_MEAN_IT_ENV, "1")
    store = EngramStore(fake_real_home / ".mnemos" / "claude-code.db")
    store.close()
    assert (fake_real_home / ".mnemos" / "claude-code.db").is_file()


def test_outside_a_hermetic_run_nothing_changes(fake_real_home, monkeypatch):
    """A person's own server, hooks and host apps open their store as before."""
    monkeypatch.delenv(live_guard.HERMETIC_ENV)
    store = EngramStore(fake_real_home / ".mnemos" / "claude-code.db")
    store.close()
    assert not live_guard.refusals


def test_resolving_into_it_is_refused_by_every_route(fake_real_home, monkeypatch):
    absolute = fake_real_home / ".mnemos" / "claude-code.db"
    with pytest.raises(LiveStoreRefused):
        resolve_scope(db_path=str(absolute))
    monkeypatch.setenv("MNEMOS_DB_PATH", str(absolute))
    with pytest.raises(LiveStoreRefused):
        resolve_scope()
    monkeypatch.delenv("MNEMOS_DB_PATH")
    # The default, when HOME is the real home.
    monkeypatch.setenv("HOME", str(fake_real_home))
    with pytest.raises(LiveStoreRefused):
        resolve_scope(agent_id="claude-code")
    assert not (fake_real_home / ".mnemos").exists()


def test_a_link_into_it_is_refused(fake_real_home, tmp_path):
    live = fake_real_home / ".mnemos"
    live.mkdir()
    link = tmp_path / "innocent"
    link.symlink_to(live, target_is_directory=True)
    with pytest.raises(LiveStoreRefused):
        EngramStore(link / "claude-code.db")
    assert list(live.iterdir()) == []


def test_a_swallowed_refusal_is_still_on_the_record(fake_real_home):
    try:
        EngramStore(fake_real_home / ".mnemos" / "claude-code.db")
    except Exception:
        pass
    assert any("fake-real-home" in message for message in live_guard.refusals)


def _cli(args, env):
    return subprocess.run(
        [sys.executable, "-m", "mnemos.cli", *args],
        cwd=REPO, env=env, capture_output=True, text=True, timeout=120,
    )


def test_the_command_refuses_and_the_flag_allows(fake_real_home, tmp_path):
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    target = fake_real_home / ".mnemos" / "claude-code.db"

    refused = _cli(["--db-path", str(target), "init"], env)
    assert refused.returncode == 2, refused.stderr
    assert "--i-mean-it" in refused.stderr
    assert not (fake_real_home / ".mnemos").exists()

    allowed = _cli(["--i-mean-it", "--db-path", str(target), "init"], env)
    assert allowed.returncode == 0, allowed.stderr
    assert target.is_file()


def test_a_suite_with_a_test_that_reaches_it_fails(fake_real_home, tmp_path):
    """The tripwire CI relies on: one test that reaches the live home, even
    behind an ``except``, fails the run. Run on a copy of this suite's
    conftest, with the fake real home standing in for the real one."""
    suite = tmp_path / "suite"
    suite.mkdir()
    (suite / "conftest.py").write_text((REPO / "tests" / "conftest.py").read_text())
    (suite / "test_leak.py").write_text(
        "from mnemos.simple_scope import resolve_scope\n"
        "def test_leaks():\n"
        "    try:\n"
        "        resolve_scope(db_path='~/.mnemos/leak.db'.replace('~', "
        f"{str(fake_real_home)!r}))\n"
        "    except Exception:\n"
        "        pass\n"
    )
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    env[live_guard.PROTECTED_HOME_ENV] = str(fake_real_home)
    run = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", str(suite)],
        cwd=REPO, env=env, capture_output=True, text=True, timeout=300,
    )
    assert run.returncode != 0, run.stdout
    assert "a test reached a live ~/.mnemos" in run.stdout
    assert not (fake_real_home / ".mnemos").exists()
