"""A clean install: what a stranger meets from a fresh install of the wheel.

``mnemos --version``; loading the local model without transformers' progress
bar; the identity templates inside the package; plurals that agree.
"""

from __future__ import annotations

import ast
import importlib.metadata
import re
import sys
import types
from pathlib import Path

import pytest

from mnemos import cli
from mnemos.simple_runtime import _index_lines
from mnemos.store.embedding_index import _load_local_model

ROOT = Path(__file__).resolve().parent.parent


def _pyproject_version() -> str:
    text = (ROOT / "pyproject.toml").read_text()
    return re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE).group(1)


# ── R.1 · mnemos --version ──


def test_version_flag_prints_the_pyproject_version(capsys):
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["--version"])
    assert exit_info.value.code == 0
    assert capsys.readouterr().out.strip() == f"mnemos {_pyproject_version()}"


def test_version_falls_back_to_pyproject_without_package_metadata(monkeypatch):
    def missing(name):
        raise importlib.metadata.PackageNotFoundError(name)

    monkeypatch.setattr(importlib.metadata, "version", missing)
    from mnemos.package_version import mnemos_version

    assert mnemos_version() == _pyproject_version()


def test_package_version_imports_only_the_standard_library():
    source = (ROOT / "mnemos" / "package_version.py").read_text()
    imported: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, "package_version imports from Mnemos"
            imported.add(node.module.split(".")[0])
    assert imported, "package_version imports nothing at all"
    assert imported <= set(sys.stdlib_module_names) | {"__future__"}, imported


# ── R.2 · loading the model prints no progress bar ──


def _fake_transformers(monkeypatch, enabled: bool) -> dict[str, bool]:
    state = {"enabled": enabled}
    logging_module = types.ModuleType("transformers.utils.logging")
    logging_module.is_progress_bar_enabled = lambda: state["enabled"]
    logging_module.disable_progress_bar = lambda: state.update(enabled=False)
    logging_module.enable_progress_bar = lambda: state.update(enabled=True)
    utils_module = types.ModuleType("transformers.utils")
    utils_module.logging = logging_module
    transformers_module = types.ModuleType("transformers")
    transformers_module.utils = utils_module
    monkeypatch.setitem(sys.modules, "transformers", transformers_module)
    monkeypatch.setitem(sys.modules, "transformers.utils", utils_module)
    monkeypatch.setitem(sys.modules, "transformers.utils.logging", logging_module)
    return state


def _fake_sentence_transformers(monkeypatch) -> list[bool | None]:
    """A SentenceTransformer that records whether the bar was on while it
    was being constructed (None when transformers can't be imported)."""
    seen: list[bool | None] = []

    class SentenceTransformer:
        def __init__(self, model_name, **kwargs):
            module = sys.modules.get("transformers")
            seen.append(
                module.utils.logging.is_progress_bar_enabled() if module else None
            )
            self.model_name = model_name

    fake = types.ModuleType("sentence_transformers")
    fake.SentenceTransformer = SentenceTransformer
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake)
    return seen


def test_the_bar_is_off_while_loading_and_on_again_after(monkeypatch):
    state = _fake_transformers(monkeypatch, enabled=True)
    seen = _fake_sentence_transformers(monkeypatch)
    model = _load_local_model("all-MiniLM-L6-v2")
    assert model.model_name == "all-MiniLM-L6-v2"
    assert seen == [False]
    assert state["enabled"] is True


def test_a_bar_that_was_off_stays_off(monkeypatch):
    state = _fake_transformers(monkeypatch, enabled=False)
    seen = _fake_sentence_transformers(monkeypatch)
    _load_local_model("all-MiniLM-L6-v2")
    assert seen == [False]
    assert state["enabled"] is False


def test_the_load_works_without_transformers(monkeypatch):
    monkeypatch.setitem(sys.modules, "transformers", None)
    seen = _fake_sentence_transformers(monkeypatch)
    model = _load_local_model("all-MiniLM-L6-v2")
    assert model.model_name == "all-MiniLM-L6-v2"
    assert seen == [None]


# ── R.3 · the templates install inside the package ──


def test_templates_install_inside_the_package():
    try:
        import tomllib
    except ModuleNotFoundError:  # Python 3.10
        tomllib = pytest.importorskip("tomli")
    with (ROOT / "pyproject.toml").open("rb") as handle:
        pyproject = tomllib.load(handle)
    force_include = pyproject["tool"]["hatch"]["build"]["targets"]["wheel"]["force-include"]
    assert force_include["templates"] == "mnemos/setup/templates"


# ── R.4 · one memory, one passage ──


def test_one_memory_one_passage():
    assert _index_lines({"items": 1, "passages": 1}) == [
        "Recall index: 1 memory or handoff made findable by meaning (1 passage)"
    ]


def test_three_memories_five_passages():
    assert _index_lines({"items": 3, "passages": 5}) == [
        "Recall index: 3 memories or handoffs made findable by meaning (5 passages)"
    ]


def test_the_waiting_tail_is_unchanged():
    assert _index_lines({"items": 1, "passages": 1, "waiting": 2}) == [
        "Recall index: 1 memory or handoff made findable by meaning (1 passage); "
        "2 still waiting"
    ]
