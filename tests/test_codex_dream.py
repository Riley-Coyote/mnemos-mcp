"""Codex dreams share the lifecycle but enforce their own protocol and tool boundary."""

import io
import json
import os
from pathlib import Path
import time

import pytest

from mnemos import codex_dream, life
from mnemos.simple_runtime import MnemosRuntime
from mnemos.store.sqlite_store import EngramStore

MODEL = "gpt-test"
SCOPE = {"agent_id": "codex", "person_id": "user", "project_scope": "global"}


@pytest.fixture
def ready(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    home = tmp_path / ".codex"
    home.mkdir()
    monkeypatch.setenv("CODEX_HOME", str(home))
    entry = {
        "slug": MODEL,
        "model_messages": {
            "instructions_template": "Keep the real model instructions."
        },
        "shell_type": "unified_exec",
        "apply_patch_tool_type": "freeform",
        "experimental_supported_tools": ["read_file"],
    }
    (home / "models_cache.json").write_text(json.dumps({"models": [entry]}))
    monkeypatch.setenv(
        "MNEMOS_CODEX_BIN", str(Path(__file__).with_name("fake_codex.py"))
    )
    monkeypatch.setenv("MNEMOS_LIFE_MNEMOS_BIN", "/fixture/mnemos")
    monkeypatch.setenv("FAKE_CODEX_LOG", str(tmp_path / "fake.json"))
    monkeypatch.setenv(
        "PATH", str(Path(os.sys.executable).parent) + os.pathsep + os.environ["PATH"]
    )
    monkeypatch.delenv("MNEMOS_HOUR_MODEL", raising=False)
    monkeypatch.setenv("CODEX_APP_TOOLS_PIPE_PATH", "/must-not-inherit")
    db = tmp_path / "codex.db"
    runtime = MnemosRuntime(db_path=str(db), use_dedicated_model=False, **SCOPE)
    runtime.capture(
        "The staging checks passed; desktop acceptance is still unobserved.",
        signed_as=MODEL,
        impact="Do not infer desktop behavior from staging checks.",
    )
    runtime.close()
    store = EngramStore(db)
    target = store.agent_captures_since("2000", **SCOPE)[0]["id"]
    store.enqueue_reflection("lesson", target, "What did this teach you?", **SCOPE)
    store.close()
    return db, tmp_path


def run(db, **kwargs):
    return life.run_hour(
        "dream", db_path=str(db), runner="codex", model=MODEL, **SCOPE, **kwargs
    )


def test_codex_dream_uses_its_store_and_preserves_full_continuity(ready):
    db, home = ready
    record = run(db)
    assert record["status"] == "done", record
    assert record["session_id"] == "codex-test"
    assert record["tokens"] == {
        "input": 30,
        "output": 5,
        "cache_creation": 0,
        "cache_read": 70,
    }
    assert record["model"] == MODEL and record["model_verified"] is False
    assert len(record["journal_ids"]) == 1
    used = json.loads((home / "fake.json").read_text())
    assert used["hour"] == record["id"] and used["app_pipe"] is None
    assert "mnemos_context" in used["prompt"] and "exact ID" in used["prompt"]
    folder = life.hours_dir("codex") / record["id"]
    catalog = json.loads((folder / "model-catalog.json").read_text())["models"][0]
    assert (
        catalog["apply_patch_tool_type"] is None and catalog["shell_type"] == "disabled"
    )
    assert (
        catalog["model_messages"]["instructions_template"]
        == "Keep the real model instructions."
    )
    assert "--ignore-user-config" in used["argv"]
    server = next(v for v in used["argv"] if v.startswith("mcp_servers="))
    assert '"required" = true' in server and '"enabled" = true' in server
    assert '"MNEMOS_SHARED_MEMORY" = "off"' in server
    assert "features.hooks=false" in used["argv"]


@pytest.mark.parametrize("source", ["flag", "environment"])
def test_relative_codex_home_keeps_the_preflight_account(ready, monkeypatch, source):
    db, home = ready
    monkeypatch.chdir(home)
    monkeypatch.setenv("CODEX_HOME", ".codex" if source == "environment" else "wrong-account")
    kwargs = {"config_dir": "./.codex"} if source == "flag" else {}

    record = run(db, **kwargs)

    assert record["status"] == "done", record
    used = json.loads((home / "fake.json").read_text())
    assert used["codex_home"] == str(home / ".codex")
    assert (Path(used["codex_home"]) / "models_cache.json").is_file()


@pytest.mark.parametrize("runner", ["Codex", " CODEX "])
@pytest.mark.parametrize("dry_run", [False, True])
def test_accepted_codex_names_never_dispatch_to_claude(ready, monkeypatch, runner, dry_run):
    db, home = ready
    claude = Path(__file__).with_name("fake_claude.py")
    claude_log = home / "claude.json"
    monkeypatch.setenv("MNEMOS_CLAUDE_BIN", str(claude))
    monkeypatch.setenv("FAKE_CLAUDE_LOG", str(claude_log))
    out = io.StringIO()

    record = life.run_hour(
        "dream", db_path=str(db), runner=runner, model=MODEL, dry_run=dry_run,
        out=out, **SCOPE,
    )

    assert not claude_log.exists(), "An accepted Codex name must never use the Claude account."
    if dry_run:
        assert record["dry_run"]
        assert str(Path(__file__).with_name("fake_codex.py")) in out.getvalue()
        assert str(claude) not in out.getvalue()
    else:
        assert record["status"] == "done", record
        assert record["runner"] == "codex" and record["session_id"] == "codex-test"
        assert (home / "fake.json").is_file()


def test_codex_alias_requires_a_model_for_a_claude_resident(ready, monkeypatch):
    _, home = ready
    db = home / "claude.db"
    runtime = MnemosRuntime(db_path=str(db), use_dedicated_model=False, **SCOPE)
    try:
        runtime.capture("The spring timetable is ready.", signed_as="claude-opus-5-5")
    finally:
        runtime.close()
    claude_log = home / "claude.json"
    monkeypatch.setenv("MNEMOS_CLAUDE_BIN", str(Path(__file__).with_name("fake_claude.py")))
    monkeypatch.setenv("FAKE_CLAUDE_LOG", str(claude_log))

    record = life.run_hour("dream", db_path=str(db), runner=" Codex ", **SCOPE)

    assert not claude_log.exists()
    assert not (home / "fake.json").exists()
    assert record["status"] == "failed" and "choose a Codex --model" in record["reason"]


@pytest.mark.parametrize(
    "scenario,reason",
    [
        ("crash", "login expired"),
        ("failed", "rate limited"),
        ("forbidden", "non-memory action"),
    ],
)
def test_codex_errors_are_recorded_and_forbidden_writes_discarded(
    ready, monkeypatch, scenario, reason
):
    db, _ = ready
    monkeypatch.setenv("FAKE_CODEX_SCENARIO", scenario)
    record = run(db)
    assert record["status"] == "failed" and reason in record["reason"]
    if scenario == "forbidden":
        assert record["discarded_ids"]
        store = EngramStore(db)
        try:
            assert not store.hour_rows(record["id"], **SCOPE)["journal_ids"]
        finally:
            store.close()


@pytest.mark.parametrize("scenario", ["failed_exit", "failed_exit_stderr"])
def test_nonzero_codex_exit_preserves_structured_failure(ready, monkeypatch, scenario):
    monkeypatch.setenv("FAKE_CODEX_SCENARIO", scenario)
    record = run(ready[0])
    assert record["status"] == "failed"
    assert "rate limited" in record["reason"]
    assert "code 1" in record["reason"]
    assert record["reason"].index("rate limited") < record["reason"].index("code 1")
    if scenario == "failed_exit_stderr":
        assert "request retry exhausted" in record["reason"]


def test_a_successful_dream_may_write_nothing(ready, monkeypatch):
    monkeypatch.setenv("FAKE_CODEX_SCENARIO", "nothing")
    record = run(ready[0])
    assert record["status"] == "done" and record["journal_ids"] == []


def test_dream_context_preserves_pending_interactive_delivery(ready, monkeypatch):
    db, home = ready
    runtime = MnemosRuntime(db_path=str(db), use_dedicated_model=False, **SCOPE)
    try:
        runtime.person_note("The spring timetable is ready.")
        runtime.handoff("Check the spring timetable.", signed_as=MODEL)
    finally:
        runtime.close()
    monkeypatch.setenv("FAKE_CODEX_SCENARIO", "context")

    record = run(db)

    assert record["status"] == "done", record
    briefing = json.loads((home / "fake.json").read_text())["context"]
    assert "Check the spring timetable." in briefing
    assert "The spring timetable is ready." not in briefing
    store = EngramStore(db)
    try:
        assert len(store.undelivered_replies(**SCOPE)) == 1
        assert store._get_conn().execute(
            "SELECT surfaced_count FROM reflection_queue"
        ).fetchone()[0] == 0
        assert store._get_conn().execute(
            "SELECT value FROM meta WHERE key LIKE '%:last_context_delivery_at'"
        ).fetchone() is None
    finally:
        store.close()
    runtime = MnemosRuntime(db_path=str(db), use_dedicated_model=False, **SCOPE)
    try:
        assert "The spring timetable is ready." in runtime.context()
        assert "The spring timetable is ready." not in runtime.context()
    finally:
        runtime.close()


def test_store_copy_keeps_live_store_untouched(ready):
    db, _ = ready
    record = run(db, store_copy=True)
    assert record["status"] == "done" and record["live_store_untouched"] is True


def test_codex_dry_run_and_missing_catalog_never_launch(ready):
    db, home = ready
    assert run(db, dry_run=True, out=io.StringIO())["dry_run"]
    assert not (home / "fake.json").exists()
    (home / ".codex/models_cache.json").unlink()
    record = run(db)
    assert record["status"] == "failed" and "Run Codex once" in record["reason"]
    assert not (home / "fake.json").exists()


def test_broader_codex_hours_remain_explicit_handoffs(ready):
    record = life.run_hour("mine", db_path=str(ready[0]), runner="codex", **SCOPE)
    assert record["status"] == "failed" and "only dreams" in record["reason"]


def test_timeout_stops_mcp_descendants(ready, monkeypatch):
    db, home = ready
    monkeypatch.setenv("FAKE_CODEX_SCENARIO", "descendant")
    monkeypatch.setattr(life, "STOP_GRACE_SECONDS", 0.1)
    started = time.monotonic()
    record = run(db, max_seconds=0.5)
    assert time.monotonic() - started < 5
    assert "time limit" in record["reason"]
    pid = json.loads((home / "fake.json").read_text())["child"]
    # A reparented child can briefly be a zombie, but must no longer be running.
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return
    import subprocess

    state = subprocess.run(
        ["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True
    ).stdout.strip()
    assert not state or state.startswith("Z")


@pytest.mark.parametrize(
    "scenario,reason", [("managed", "managed policy"), ("old", "0.167.0")]
)
def test_unsafe_cli_never_launches_a_dream(ready, monkeypatch, scenario, reason):
    monkeypatch.setenv("FAKE_CODEX_SCENARIO", scenario)
    record = run(ready[0])
    assert record["status"] == "failed" and reason in record["reason"]
    assert not (ready[1] / "fake.json").exists()


def test_empty_store_needs_a_user_selected_model(ready, monkeypatch):
    db = ready[1] / "empty.db"
    EngramStore(db).close()
    model, why = life.hour_model(db, SCOPE, runner="codex")
    assert not model and "Choose a Codex model" in why
    monkeypatch.setenv("MNEMOS_HOUR_MODEL", "chosen-by-user")
    assert life.hour_model(db, SCOPE, runner="codex") == ("chosen-by-user", "")
    assert life.hour_model(db, SCOPE, runner="codex", model="explicit") == (
        "explicit",
        "",
    )


@pytest.mark.skipif(
    not (
        os.environ.get("MNEMOS_TEST_CODEX_BIN")
        and os.environ.get("MNEMOS_TEST_CODEX_CATALOG")
    ),
    reason="opt-in native CLI check; needs a binary and its cached model catalog",
)
def test_native_cli_tool_boundary_and_scoped_mcp_write(ready, monkeypatch):
    """Exercise stock Codex and real Mnemos, with a local provider and copied store.

    No login or paid inference: supply MNEMOS_TEST_CODEX_BIN and
    MNEMOS_TEST_CODEX_CATALOG (models_cache.json from that CLI). Run on a host
    whose managed policy permits memory-only dreams.
    """
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    db, folder = ready
    entry = json.loads(Path(os.environ["MNEMOS_TEST_CODEX_CATALOG"]).read_text())[
        "models"
    ][0]
    entry["slug"] = MODEL
    (folder / ".codex/models_cache.json").write_text(json.dumps({"models": [entry]}))
    (folder / ".codex/config.toml").write_text(
        '[mcp_servers.inherited]\ncommand = "/must-not-run"\n'
    )
    requests = []

    class Provider(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            requests.append(
                json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            )
            call = len(requests) == 1
            item = (
                {
                    "type": "function_call",
                    "id": "fc_1",
                    "call_id": "call_1",
                    "name": "mnemos_journal",
                    "namespace": "mcp__mnemos",
                    "arguments": json.dumps(
                        {"text": "Native CLI fixture write.", "signed_as": MODEL}
                    ),
                }
                if call
                else {
                    "type": "message",
                    "id": "msg_1",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "Done."}],
                }
            )
            item["status"] = "completed"
            response = {
                "id": f"resp_{len(requests)}",
                "status": "completed",
                "output": [item],
                "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
            }
            events = [
                {
                    "type": "response.created",
                    "response": dict(response, status="in_progress", output=[]),
                },
                {
                    "type": "response.output_item.added",
                    "output_index": 0,
                    "item": dict(item, status="in_progress"),
                },
                {"type": "response.output_item.done", "output_index": 0, "item": item},
                {"type": "response.completed", "response": response},
            ]
            body = "".join(
                "data: " + json.dumps(event) + "\n\n" for event in events
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    original = codex_dream.command
    marker = folder / "outside-started"
    other = folder / "outside-mcp"
    other.write_text(
        f"#!{os.sys.executable}\nfrom pathlib import Path\nPath({str(marker)!r}).touch()\n"
    )
    other.chmod(0o755)

    def fixture_provider(*args, **kwargs):
        cmd = original(*args, **kwargs)
        # An earlier CLI override must not add another MCP server.
        at = cmd.index("-c")
        cmd[at:at] = ["-c", f"mcp_servers.earlier.command={json.dumps(str(other))}"]
        cmd[-1:-1] = [
            "-c",
            'model_provider="fixture"',
            "-c",
            f'model_providers.fixture={{name="Fixture", base_url="http://127.0.0.1:{server.server_port}/v1", '
            'wire_api="responses", env_key="MNEMOS_TEST_API_KEY"}',
        ]
        return cmd

    launcher = folder / "mnemos"
    launcher.write_text(
        f"#!{os.sys.executable}\nfrom mnemos.cli import main\nraise SystemExit(main())\n"
    )
    launcher.chmod(0o755)
    monkeypatch.setenv("PYTHONPATH", str(Path(__file__).resolve().parents[1]))
    monkeypatch.setenv("MNEMOS_LIFE_MNEMOS_BIN", str(launcher))
    monkeypatch.setenv("MNEMOS_CODEX_BIN", os.environ["MNEMOS_TEST_CODEX_BIN"])
    monkeypatch.setenv("MNEMOS_TEST_API_KEY", "fixture-key")
    monkeypatch.setattr(codex_dream, "command", fixture_provider)
    try:
        record = run(db, store_copy=True, max_seconds=40)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
    assert record["status"] == "done", record
    assert len(record["journal_ids"]) == 1 and record["live_store_untouched"] is True
    assert len(requests) == 2
    assert not marker.exists(), "An inherited MCP server must never start."

    def tool_names(tools):
        return {
            name
            for tool in tools
            for name in (
                tool_names(tool["tools"])
                if "tools" in tool
                else {tool.get("name", tool.get("type"))}
            )
        }

    tools = tool_names(
        requests[0].get("tools", [])
        + [
            tool
            for item in requests[0].get("input", [])
            if item.get("type") == "additional_tools"
            for tool in item.get("tools", [])
        ]
    )
    assert set(codex_dream.DREAM_TOOLS) <= tools
    assert tools <= set(codex_dream.DREAM_TOOLS) | {
        "list_mcp_resources",
        "list_mcp_resource_templates",
        "read_mcp_resource",
        "request_user_input",
    }
