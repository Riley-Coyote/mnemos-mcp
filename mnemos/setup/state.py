"""What setup has left on this machine, read without changing anything.

The first session needs it to tell the person the truth about their memory
(``MnemosRuntime._onboarding_block``), and doctor shows it: whether Claude
Code wakes this memory at the start of every session, whether the quiet
hours are on, and what the person chose when asked about them. Setup writes
the hooks and the schedule; the one thing kept here is that choice
(``record_hours_choice``), so a first session doesn't ask what setup already
did.

Nothing here imports the quiet hours' runner (``life``), which can't be
imported where fcntl is missing: knowing about them must not need it.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shlex
import shutil
import sys
from typing import Any

# The person's choice about the quiet hours, in their own folder.
CHOICE_FILE = "choice.json"


def claude_code_settings_path() -> Path:
    """Claude Code's settings file: ``$CLAUDE_CONFIG_DIR/settings.json`` when
    that variable is set and not empty, else ``~/.claude/settings.json``."""
    config_dir = os.environ.get("CLAUDE_CONFIG_DIR", "")
    if config_dir:
        return Path(config_dir).expanduser() / "settings.json"
    return Path.home() / ".claude" / "settings.json"


def is_mnemos_hook(candidate: Any, subcommand: str) -> bool:
    """Whether a hooks entry is one of Mnemos's own: a command that runs
    `mnemos hook <subcommand>`. Anyone else's hooks never are."""
    if not isinstance(candidate, dict):
        return False
    for configured_hook in candidate.get("hooks", []):
        if not isinstance(configured_hook, dict):
            continue
        command = configured_hook.get("command", "")
        if not isinstance(command, str):
            continue
        try:
            parts = shlex.split(command)
        except ValueError:
            continue
        if (
            len(parts) >= 3
            and Path(parts[0]).stem.lower().startswith("mnemos")
            and parts[1:3] == ["hook", subcommand]
        ):
            return True
    return False


def mnemos_command() -> str:
    """Absolute path to *this* Mnemos installation's CLI.

    A bare PATH lookup can resolve to a different installation than the one
    the user just ran — a Homebrew copy shadowing a pipx or venv one. The
    generated hook and client configs would then invoke the wrong Mnemos,
    against a different environment and a different store, or none at all.
    Prefer the running script, then this interpreter's own bin directory.
    """
    argv0 = sys.argv[0] if sys.argv and sys.argv[0] else ""
    if argv0:
        candidate = Path(argv0).resolve()
        if candidate.is_file() and candidate.stem == "mnemos":
            return str(candidate)

    # Running as `python -m mnemos.cli`: the console script installed
    # alongside this interpreter is still the right installation.
    sibling = Path(sys.executable).parent / "mnemos"
    if sibling.is_file():
        return str(sibling)

    return shutil.which("mnemos") or "mnemos"


def command_line(agent_id: str, db_path, *command: str, mnemos: str | None = None) -> str:
    """A Mnemos command for one memory, as an agent should run it: this
    installation's own CLI, with the agent and its store named, so it reaches
    this memory whatever its shell's defaults are."""
    return shlex.join([
        mnemos or mnemos_command(),
        "--agent-id", agent_id,
        "--db-path", str(Path(db_path).expanduser()),
        *command,
    ])


def _same_file(path: str) -> Path:
    return Path(path).expanduser().resolve()


def _store_named(command: str) -> Path | None:
    """The store a hook's command reads: the one it names with --db-path and
    --agent-id, resolved as the hook resolves them, or the default."""
    try:
        parts = shlex.split(command)
    except ValueError:
        return None
    named: dict[str, str] = {}
    for index, part in enumerate(parts):
        for flag in ("--db-path", "--agent-id"):
            if part == flag and index + 1 < len(parts):
                named[flag] = parts[index + 1]
            elif part.startswith(flag + "="):
                named[flag] = part.split("=", 1)[1]
    from ..simple_scope import resolve_scope

    scope = resolve_scope(db_path=named.get("--db-path"), agent_id=named.get("--agent-id"))
    return _same_file(scope.db_path)


def wake_hook(db_path: str) -> Path | None:
    """The Claude Code settings file whose SessionStart hook wakes the memory
    at ``db_path``, or None when no hook there does. A Mnemos hook for another
    agent's memory doesn't count: it would wake someone else."""
    path = claude_code_settings_path()
    try:
        settings = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    hooks = settings.get("hooks") if isinstance(settings, dict) else None
    listed = hooks.get("SessionStart") if isinstance(hooks, dict) else None
    if not isinstance(listed, list):
        return None
    wanted = _same_file(db_path)
    for entry in listed:
        if not is_mnemos_hook(entry, "session-start"):
            continue
        for handler in entry.get("hooks", []):
            command = handler.get("command", "") if isinstance(handler, dict) else ""
            if isinstance(command, str) and _store_named(command) == wanted:
                return path
    return None


def hours_dir(agent_id) -> Path:
    """The quiet hours' own folder for one agent: their record (hours.jsonl),
    a folder for each hour, and the person's choice about them."""
    return Path.home() / ".mnemos" / "hours" / agent_id


def hours_choice(agent_id: str) -> str | None:
    """What the person chose when asked about the quiet hours, "yes" or "no",
    or None when no one has asked them."""
    try:
        kept = json.loads((hours_dir(agent_id) / CHOICE_FILE).read_text())
    except (OSError, ValueError):
        return None
    choice = kept.get("choice") if isinstance(kept, dict) else None
    return choice if choice in ("yes", "no") else None


def record_hours_choice(agent_id: str, choice: str) -> None:
    """Keep what the person chose about the quiet hours. A setup that did
    what they asked never fails over this."""
    from ..file_security import atomic_write_text

    kept = {"choice": choice, "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    try:
        folder = hours_dir(agent_id)
        folder.mkdir(parents=True, exist_ok=True)
        atomic_write_text(folder / CHOICE_FILE, json.dumps(kept) + "\n")
    except OSError:
        pass


def scheduled(agent_id: str, job, backend: str, crontab: str = "") -> bool:
    """Whether one of Mnemos's jobs is scheduled for this agent: loaded in
    launchd, its systemd timer enabled, or a line in the crontab."""
    from . import scheduler

    if backend == "launchd":
        return (
            scheduler.launchd_plist_path(agent_id, job).exists()
            and scheduler.launchd_job_active(agent_id, job)
        )
    if backend == "systemd":
        return (
            (scheduler.systemd_unit_dir() / scheduler.systemd_unit_names(agent_id, job)[1]).exists()
            and scheduler.systemd_timer_active(agent_id, job)
        )
    return scheduler.cron_has(crontab, agent_id, job.name)


def quiet_hours_on(agent_id: str) -> bool:
    """Whether the quiet hours are scheduled for this agent on this host."""
    from . import scheduler

    backend = scheduler.detect_backend()
    if backend == "unsupported":
        return False
    crontab = scheduler.read_crontab() if backend == "crontab" else ""
    return any(scheduled(agent_id, job, backend, crontab) for job in scheduler.HOUR_JOBS)
