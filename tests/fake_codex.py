#!/usr/bin/env python3
"""A Codex JSONL fixture; uses no provider or real MCP server."""

import json
import os
from pathlib import Path
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mnemos.store.sqlite_store import EngramStore

argv = sys.argv[1:]
if argv == ["--version"]:
    print(
        "codex-cli 0.166.0"
        if os.environ.get("FAKE_CODEX_SCENARIO") == "old"
        else "codex-cli 0.167.0"
    )
    sys.exit(0)
if argv == ["app-server"]:
    for line in sys.stdin:
        request = json.loads(line)
        if "id" not in request:
            continue
        result = {}
        if request["method"] == "config/read":
            result = {"config": {"mcp_servers": {"other": {}}}}
        if request["method"] == "configRequirements/read":
            result = (
                {"requirements": {"featureRequirements": {"hooks": True}}}
                if os.environ.get("FAKE_CODEX_SCENARIO") == "managed"
                else {"requirements": None}
            )
        print(json.dumps({"id": request["id"], "result": result}), flush=True)
    sys.exit(0)

settings = {}
for i, arg in enumerate(argv):
    if arg == "-c":
        key, _, value = argv[i + 1].partition("=")
        settings[key] = value
args, _ = json.JSONDecoder().raw_decode(
    settings["mcp_servers"].split('"args" = ', 1)[1]
)
model = argv[argv.index("--model") + 1]
prompt = sys.stdin.read()
log = {
    "argv": argv,
    "prompt": prompt,
    "hour": os.environ.get("MNEMOS_HOUR_ID"),
    "app_pipe": os.environ.get("CODEX_APP_TOOLS_PIPE_PATH"),
}
scenario = os.environ.get("FAKE_CODEX_SCENARIO", "ok")
if scenario == "descendant":
    child = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); time.sleep(60)",
        ]
    )
    log["child"] = child.pid
Path(os.environ["FAKE_CODEX_LOG"]).write_text(json.dumps(log))


def emit(event):
    print(json.dumps(event), flush=True)


emit({"type": "thread.started", "thread_id": "codex-test"})
if scenario in ("sleep", "descendant"):
    time.sleep(60)
if scenario == "crash":
    print("login expired", file=sys.stderr)
    sys.exit(3)
if scenario != "nothing":
    store = EngramStore(args[args.index("--db-path") + 1])
    store.write_journal_entry(
        "A useful dream.",
        agent_id=args[args.index("--agent-id") + 1],
        person_id="user",
        project_scope="global",
        model_id=model,
        hour_id=os.environ["MNEMOS_HOUR_ID"],
    )
    store.close()
if scenario == "forbidden":
    emit(
        {
            "type": "item.started",
            "item": {"type": "command_execution", "command": "false"},
        }
    )
    time.sleep(60)
elif scenario == "failed":
    emit({"type": "turn.failed", "error": {"message": "rate limited"}})
else:
    print("a non-event line", flush=True)
    emit(
        {
            "type": "turn.completed",
            "usage": {
                "input_tokens": 100,
                "cached_input_tokens": 70,
                "output_tokens": 5,
            },
        }
    )
