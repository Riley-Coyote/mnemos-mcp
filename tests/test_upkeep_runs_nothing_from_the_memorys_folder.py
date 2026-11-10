"""The upkeep process runs nothing from the memory's folder, whatever the paths say.

The background upkeep is ``python -c ...`` started in the store's own folder.
0.6.7 dropped the empty entry its own ``-c`` puts first on the path, but two
ways in were left: the environment's ``PYTHONPATH`` (an empty part, as
``export PYTHONPATH=$PYTHONPATH:/x`` leaves when it was unset, or a relative
one) is read before the child's first line runs, so a ``sitecustomize.py`` or
``json.py`` left beside the store ran; and a relative entry on the parent's
own path was handed on as it was, and found in the store's folder.

Now the child is started without ``PYTHONPATH`` (it is given its whole path
as an argument), and every entry handed to it is first made full against the
folder the parent runs in.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

from mnemos import simple_runtime
from mnemos.simple_scope import resolve_scope

_PLANT = "open({ran!r}, 'a').write({name!r} + '\\n')\n"


def _started(tmp_path, monkeypatch):
    """The command and options ``_spawn_upkeep`` starts its child with."""
    started = []

    class Child:
        def poll(self):
            return 0

    def popen(command, **options):
        started.append((command, options))
        return Child()

    monkeypatch.setattr(simple_runtime.subprocess, "Popen", popen)
    monkeypatch.setattr(simple_runtime, "_UPKEEP_CHILDREN", [])
    scope = resolve_scope(agent_id="a", db_path=str(tmp_path / "store" / "a.db"))
    assert simple_runtime._spawn_upkeep(scope, "token", dedicated_model=False)
    return started[0]


@pytest.mark.parametrize(
    ("pythonpath", "entry", "planted"),
    [
        (":" + os.devnull, None, ["sitecustomize.py", "json.py"]),
        ("lib", None, ["lib/json.py", "lib/sitecustomize.py"]),
        (".", None, ["json.py", "sitecustomize.py"]),
        (None, "vendor", ["vendor/mnemos/__init__.py", "vendor/mnemos/simple_runtime.py"]),
    ],
    ids=["an empty part of PYTHONPATH", "a relative part", "a dot", "a relative entry of the parent's"],
)
def test_upkeep_runs_nothing_planted_beside_the_memory(tmp_path, monkeypatch, pythonpath, entry, planted):
    store = tmp_path / "store"
    ran = tmp_path / "ran"
    for name in planted:
        file = store / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(_PLANT.format(ran=str(ran), name=name))
    parent = tmp_path / "parent"
    parent.mkdir()
    monkeypatch.chdir(parent)
    monkeypatch.delenv("PYTHONPATH", raising=False)
    if pythonpath is not None:
        monkeypatch.setenv("PYTHONPATH", pythonpath)
    if entry is not None:
        monkeypatch.setattr(sys, "path", [entry, *sys.path])

    command, options = _started(tmp_path, monkeypatch)
    env = options.get("env")
    env = dict(os.environ) if env is None else env  # None: the child inherits this one
    monkeypatch.undo()
    done = subprocess.run(
        command, cwd=options["cwd"], env=env,
        stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=120,
    )

    assert not ran.exists(), f"ran from the memory's folder: {ran.read_text().split()}"
    assert done.returncode == 0, done.stderr


def test_upkeep_is_started_without_pythonpath(tmp_path, monkeypatch):
    monkeypatch.setenv("PYTHONPATH", "/somewhere/else")
    monkeypatch.setenv("MNEMOS_TEST_KEPT", "yes")
    _command, options = _started(tmp_path, monkeypatch)

    assert "PYTHONPATH" not in options["env"]
    assert options["env"]["MNEMOS_TEST_KEPT"] == "yes"  # outside Hermes, the rest goes as ever


def test_every_path_handed_on_is_full(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "path", ["", ".", "vendor", *sys.path])
    command, _options = _started(tmp_path, monkeypatch)
    paths = json.loads(command[3])

    assert all(os.path.isabs(path) for path in paths)
    assert paths[:3] == [str(tmp_path), str(tmp_path), str(tmp_path / "vendor")]
