"""Codex's memory-only dream configuration and JSONL event decoding."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import queue
import re
import signal
import subprocess
import threading

logger = logging.getLogger(__name__)

DISABLED_FEATURES = (
    "shell_tool",
    "view_image",
    "apps",
    "plugins",
    "hooks",
    "multi_agent",
    "multi_agent_v2",
    "js_repl",
    "code_mode",
    "code_mode_only",
    "in_app_browser",
    "memories",
    "goals",
    "request_permissions_tool",
    "exec_permission_approvals",
    "default_mode_request_user_input",
    "current_time_reminder",
)


def environment(source: dict) -> dict:
    """Keep CLI auth, excluding an enclosing app's session and tool bridges."""
    return {
        k: v
        for k, v in source.items()
        if not k.startswith("CODEX_") or k in ("CODEX_HOME", "CODEX_API_KEY")
    }


def isolation(binary: str, config_dir: str | None = None) -> None:
    """Read native configuration before running, honoring managed restrictions.

    Ignoring user config does not remove managed requirements. Ask Codex
    itself, so Python needs no second TOML parser.
    """
    env = environment(dict(os.environ))
    if config_dir:
        env["CODEX_HOME"] = str(Path(config_dir).expanduser())
    version = subprocess.run(
        [binary, "--version"], capture_output=True, text=True, env=env, timeout=15
    )
    seen = re.search(r"codex-cli\s+(\d+)\.(\d+)\.(\d+)", version.stdout)
    if version.returncode or not seen or tuple(map(int, seen.groups())) < (0, 167, 0):
        raise ValueError(
            "Codex dreams require Codex CLI 0.167.0 or newer; no dream was launched."
        )
    with subprocess.Popen(
        [binary, "app-server"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        env=env,
        start_new_session=True,
    ) as proc:
        messages: queue.Queue = queue.Queue()

        def read():
            for line in proc.stdout:
                try:
                    messages.put(json.loads(line))
                except ValueError:
                    pass
            messages.put(None)

        reader = threading.Thread(target=read, daemon=True)
        reader.start()

        def send(message):
            proc.stdin.write(json.dumps(message) + "\n")
            proc.stdin.flush()

        def request(ident, method, params):
            send({"jsonrpc": "2.0", "id": ident, "method": method, "params": params})
            while True:
                message = messages.get(timeout=15)
                if message is None:
                    raise ValueError(
                        "Codex configuration inspection ended before answering."
                    )
                if message.get("id") == ident:
                    if "error" in message:
                        raise ValueError(
                            f"Codex cannot inspect {method}; update the CLI before running dreams."
                        )
                    return message["result"]

        try:
            request(
                1,
                "initialize",
                {
                    "clientInfo": {"name": "mnemos-dream", "version": "1.0.0"},
                    "capabilities": {"experimentalApi": True},
                },
            )
            send({"jsonrpc": "2.0", "method": "initialized"})
            requirements = (
                request(2, "configRequirements/read", {}).get("requirements") or {}
            )
            required = requirements.get("featureRequirements") or {}
            conflicts = [
                name for name in DISABLED_FEATURES if required.get(name) is True
            ]
            if (
                conflicts
                or requirements.get("hooks")
                or requirements.get("allowManagedHooksOnly")
                or requirements.get("modelCatalogJson")
            ):
                raise ValueError(
                    "Codex's managed policy requires capabilities a memory-only dream disables: "
                    + ", ".join(conflicts or ["managed hooks or model catalog"])
                    + ". No dream was launched."
                )
        except queue.Empty as exc:
            raise ValueError(
                "Codex configuration inspection timed out; no dream was launched."
            ) from exc
        finally:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
                proc.wait(timeout=2)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                pass
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            proc.wait()
            reader.join(timeout=2)


DREAM_TOOLS = (
    "mnemos_context",
    "mnemos_health",
    "mnemos_introduce",
    "mnemos_recall",
    "mnemos_capture",
    "mnemos_correct",
    "mnemos_reflect",
    "mnemos_journal",
    "mnemos_maintain",
)

PREAMBLE = """This is an unattended dream for the one Mnemos store configured in this run.
Introduce yourself with your actual model ID, then request mnemos_context without a graph.
Read any shortened standing guidance in full before relying on it. Recall each selected
memory by its exact ID before reflecting: the excerpts below select material, not replace
its words. Preserve authorship and uncertainty; a colleague's experience is theirs.
Use only this store's memory tools. Do no project work, use no shell, files or web, publish
no shared memory, leave no note and write no handoff. Sign writes as yourself. Writing
nothing is a successful dream when no useful reflection comes.\n\n"""


def model_catalog(model: str, config_dir: str | None = None) -> dict:
    """Keep the installed model's instructions, removing its non-memory tools.

    Codex exposes apply_patch through model metadata independently of the
    shell feature. Reusing its own catalog preserves model instructions and
    context limits; inventing a minimal model would silently replace them.
    """
    home = Path(
        config_dir or os.environ.get("CODEX_HOME") or Path.home() / ".codex"
    ).expanduser()
    try:
        models = json.loads((home / "models_cache.json").read_text())["models"]
        entry = next(m for m in models if m.get("slug") == model)
    except (OSError, ValueError, KeyError, StopIteration, TypeError) as exc:
        raise ValueError(
            f"Codex has no cached catalog entry for {model}. Run Codex once with that model "
            f"using {home}, then retry the dream."
        ) from exc
    entry.update(
        shell_type="disabled",
        apply_patch_tool_type=None,
        experimental_supported_tools=[],
        supports_search_tool=False,
        tool_mode=None,
        multi_agent_version=None,
    )
    return {"models": [entry]}


def command(
    binary: str, model: str, folder: Path, mcp: dict, config_dir: str | None = None
) -> list[str]:
    """Build an unattended command with only the scoped Mnemos server."""
    cmd = [
        binary,
        "exec",
        "--model",
        model,
        "--json",
        "--ephemeral",
        "--ignore-user-config",
        "--ignore-rules",
        "--skip-git-repo-check",
        "--sandbox",
        "read-only",
        "--color",
        "never",
    ]
    settings = {
        "approval_policy": "never",
        "web_search": "disabled",
        "project_doc_max_bytes": 0,
        "model_catalog_json": str(folder / "model-catalog.json"),
        "skills.include_instructions": False,
    }
    for feature in DISABLED_FEATURES:
        settings[f"features.{feature}"] = False
    isolation(binary, config_dir)
    server = mcp["mcpServers"]["mnemos"]
    scoped = {key: server[key] for key in ("command", "args", "env")}
    scoped.update(enabled=True, required=True, enabled_tools=list(DREAM_TOOLS))
    # Replace earlier CLI registrations as a table; leaf disables can recreate
    # ignored user servers without a transport.
    settings["mcp_servers"] = {"mnemos": scoped}

    def toml(value):
        if isinstance(value, dict):
            return (
                "{"
                + ", ".join(f"{json.dumps(k, ensure_ascii=False)} = {toml(v)}" for k, v in value.items())
                + "}"
            )
        return json.dumps(value, ensure_ascii=False)

    for key, value in settings.items():
        cmd += ["-c", f"{key}={toml(value)}"]
    return [*cmd, "-"]


class Events:
    """Translate Codex events into the shared quiet-hour outcome accounting."""

    def __init__(self) -> None:
        self.session_id = ""
        self.forbidden = ""

    def accept(self, event: dict) -> dict | None:
        """Return an accounting event, failing closed on a non-memory action."""
        kind = event.get("type")
        if kind == "thread.started":
            self.session_id = event.get("thread_id", "")
        if kind in ("item.started", "item.completed"):
            item = event.get("item") or {}
            action = item.get("type")
            if action in ("command_execution", "file_change", "web_search") or (
                action == "mcp_tool_call"
                and (
                    item.get("server") != "mnemos"
                    or item.get("tool") not in DREAM_TOOLS
                )
            ):
                self.forbidden = str(action)
        if kind in ("turn.failed", "error"):
            error = event.get("error") or event
            return {
                "type": "result",
                "is_error": True,
                "result": error.get("message", "Codex failed."),
                "session_id": self.session_id,
            }
        if kind == "turn.completed":
            used = event.get("usage") or {}
            cached = used.get("cached_input_tokens", 0)
            usage = {
                "input_tokens": max(0, used.get("input_tokens", 0) - cached),
                "cache_read_input_tokens": cached,
                "output_tokens": used.get("output_tokens", 0),
            }
            return {
                "type": "result",
                "is_error": False,
                "usage": usage,
                "session_id": self.session_id,
            }
        return None
