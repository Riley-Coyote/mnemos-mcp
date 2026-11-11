"""Startup attribution and quiet-hour controls keep their supported contracts."""

import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from mnemos.attribution import bind_origin
from mnemos.companion.server import LogServer
from mnemos.simple_runtime import MnemosRuntime


@pytest.mark.parametrize("wake", ["full", "light"])
def test_standing_origins_reach_startup_context(tmp_path, monkeypatch, wake):
    monkeypatch.setenv("MNEMOS_WAKE", wake)
    runtime = MnemosRuntime(
        db_path=str(tmp_path / "memory.db"), use_dedicated_model=False
    )
    try:
        with bind_origin(
            {
                "thread_id": "standing-source-thread",
                "project_id": "project-review",
                "project_name": "Attribution review",
                "thread_title": "Standing source",
            }
        ):
            runtime.capture(
                "Keep published source references with repository decisions.",
                standing=True,
            )
        packet = runtime.context()
        assert "project=Attribution review (project-review)" in packet
        assert "task=Standing source (standing-source-thread)" in packet
    finally:
        runtime.close()


@pytest.mark.parametrize(
    "on,model,allowed,expected_model",
    [
        (True, "claude-opus-4-6[1m]", True, "claude-opus-4-6[1m]"),
        (False, "claude-opus-4-6[1m]", True, "claude-opus-4-6[1m]"),
        (False, "bad model", True, ""),
        (True, "bad model", False, ""),
    ],
)
def test_hours_models_follow_supported_validation(
    tmp_path, monkeypatch, on, model, allowed, expected_model
):
    from mnemos import cli
    from mnemos.setup import state

    monkeypatch.setattr(
        state, "hour_settings", lambda _: {"runner": "claude-code", "model": model}
    )
    command = Mock(return_value=0)
    monkeypatch.setattr(cli, "_cmd_daemon", command)
    server = object.__new__(LogServer)
    server._settings = threading.Lock()
    scope = SimpleNamespace(
        agent_id="review",
        person_id="user",
        project_scope="global",
        db_path=str(tmp_path / "memory.db"),
    )
    mind = SimpleNamespace(exporter=SimpleNamespace(scope=scope), forget=Mock())
    result = server._hours({"on": on}, mind)
    assert ("error" not in result) == allowed, result
    assert command.call_count == int(allowed)
    if allowed:
        assert command.call_args.args[0].daemon_command == (
            "install" if on else "uninstall"
        )
        assert command.call_args.args[0].model == expected_model
