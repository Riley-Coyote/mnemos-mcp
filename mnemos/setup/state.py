"""What setup has left on this machine, read without changing anything.

The first session needs it to tell the person the truth about their memory
(``MnemosRuntime._onboarding_block``), and doctor shows it: whether Claude
Code wakes this memory at the start of every session, whether the quiet
hours are on, and what the person chose about them. Setup writes the hooks
and the upkeep's schedule; the one thing kept here is the person's choices
about their quiet hours (``choice.json``): whether they want them, when each
starts, how long it may last, and whether it may go online. ``hour_settings``
is the one answer to what an hour gets, and ``hours_now`` adds whether each is
scheduled on this machine right now.

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

# The person's choices about the quiet hours, in their own folder.
CHOICE_FILE = "choice.json"

# The quiet hours: "mine" is the agent's own hour, "ours" half an hour for the
# day's work, "dream" a short time each night after the deep upkeep at 03:00.
# When each starts and how long it may last when the person hasn't said;
# the scheduler's jobs (``scheduler.HOUR_JOBS``) and the runner (``life``)
# both take theirs from here.
HOUR_KINDS = ("mine", "ours", "dream")
DEFAULT_AT = {"mine": (8, 0), "ours": (19, 0), "dream": (3, 30)}
DEFAULT_MINUTES = {"mine": 60, "ours": 30, "dream": 20}
# The hours that may go online, when the person turns it on for them. A dream
# never does.
ONLINE_KINDS = ("mine", "ours")
# How long the person may give an hour, in whole minutes.
MINUTES_RANGE = (5, 120)


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
    Prefer the running script, then this interpreter's own bin directory, then
    the one a host was told about when it was connected (``MNEMOS_COMMAND``:
    inside Hermes, this interpreter is Hermes' own, and its shell may not find
    Mnemos at all).
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

    return os.environ.get("MNEMOS_COMMAND", "").strip() or shutil.which("mnemos") or "mnemos"


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


def _kept(agent_id: str) -> dict:
    """Everything kept in ``choice.json``, or nothing when there is none or it
    can't be read."""
    try:
        kept = json.loads((hours_dir(agent_id) / CHOICE_FILE).read_text())
    except (OSError, ValueError):
        return {}
    return kept if isinstance(kept, dict) else {}


def _keep(agent_id: str, change) -> bool:
    """Apply ``change`` (a function of the kept dict) to ``choice.json`` and
    write it back, keeping everything else in it. Whether it was kept: a change
    to the schedule that did what was asked never fails over this."""
    from ..file_security import atomic_write_text

    kept = _kept(agent_id)
    change(kept)
    try:
        folder = hours_dir(agent_id)
        folder.mkdir(parents=True, exist_ok=True)
        atomic_write_text(folder / CHOICE_FILE, json.dumps(kept) + "\n")
    except OSError:
        return False
    return True


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def clock_text(at: tuple[int, int]) -> str:
    """(8, 0) as "08:00"."""
    return f"{at[0]:02d}:{at[1]:02d}"


def parse_clock(text) -> tuple[int, int] | None:
    """"08:00" as (8, 0); None when it isn't a time of day on the 24-hour clock."""
    if not isinstance(text, str):
        return None
    hour, colon, minute = text.strip().partition(":")
    if not (colon and len(minute) == 2 and hour.isdigit() and minute.isdigit()):
        return None
    if 0 <= int(hour) <= 23 and 0 <= int(minute) <= 59:
        return int(hour), int(minute)
    return None


def _minutes_ok(value) -> bool:
    return (
        isinstance(value, int) and not isinstance(value, bool)
        and MINUTES_RANGE[0] <= value <= MINUTES_RANGE[1]
    )


def hours_choice(agent_id: str) -> str | None:
    """What the person chose about the quiet hours, "yes" (at least one hour
    on, after they answered) or "no", or None when no one has asked them."""
    choice = _kept(agent_id).get("choice")
    return choice if choice in ("yes", "no") else None


def answered_at(agent_id: str) -> str | None:
    """When the person last answered about their hours (``record_answered``),
    or None if they never have since this was kept."""
    when = _kept(agent_id).get("answered_at")
    return when if isinstance(when, str) and when else None


def record_hours_choice(agent_id: str, choice: str) -> None:
    """Keep what the person chose about the quiet hours, keeping everything
    else already kept. A setup that did what they asked never fails over
    this."""
    def change(kept: dict) -> None:
        kept["choice"] = choice
        kept["at"] = _now()

    _keep(agent_id, change)


def record_answered(agent_id: str) -> bool:
    """Keep that the person answered about their hours just now."""
    return _keep(agent_id, lambda kept: kept.__setitem__("answered_at", _now()))


def record_hour(
    agent_id: str, kind: str, *, at=None, minutes: int | None = None, online: bool | None = None,
) -> bool:
    """Keep one hour's settings: when it starts (``at``, "HH:MM" or (hour,
    minute)), how long it may last (``minutes``) and whether it may go online
    (``online``; a dream never may). What isn't given stays as it was. Raises
    ValueError for a setting no hour can have."""
    if kind not in HOUR_KINDS:
        raise ValueError(f"There's no hour called {kind!r}.")
    if at is not None:
        parsed = at if isinstance(at, tuple) else parse_clock(at)
        if parsed is None or parse_clock(clock_text(parsed)) != parsed:
            raise ValueError(f"{at!r} isn't a time like 08:00.")
        at = clock_text(parsed)
    if minutes is not None and not _minutes_ok(minutes):
        raise ValueError(f"An hour lasts {MINUTES_RANGE[0]} to {MINUTES_RANGE[1]} minutes.")
    if online and kind not in ONLINE_KINDS:
        raise ValueError("A dream never goes online.")

    def change(kept: dict) -> None:
        hours = kept.get("hours") if isinstance(kept.get("hours"), dict) else {}
        hour = hours.get(kind) if isinstance(hours.get(kind), dict) else {}
        if at is not None:
            hour["at"] = at
        if minutes is not None:
            hour["minutes"] = minutes
        if online is not None and kind in ONLINE_KINDS:
            hour["online"] = bool(online)
        hours[kind] = hour
        kept["hours"] = hours

    return _keep(agent_id, change)


def _recorded(kept: dict, kind: str) -> dict:
    hours = kept.get("hours")
    hour = hours.get(kind) if isinstance(hours, dict) else None
    return hour if isinstance(hour, dict) else {}


def _online(kept: dict, kind: str, mine_scheduled) -> bool:
    """Whether ``kind`` may go online: what the person chose for it, and for
    an own hour nobody has chosen for, whether it is scheduled right now
    (``mine_scheduled``, asked only then)."""
    if kind not in ONLINE_KINDS:
        return False
    recorded = _recorded(kept, kind).get("online")
    if isinstance(recorded, bool):
        return recorded
    # The legacy rule: an own hour set up before this setting existed had the
    # web, and keeps it while it stays scheduled. Every way of turning an hour
    # on records this setting, so the rule covers only those hours.
    return kind == "mine" and bool(mine_scheduled())


def hour_online(agent_id: str, kind: str) -> bool:
    """Whether this agent's ``kind`` hour may go online. An hour the person
    hasn't chosen for is offline, except an own hour that is scheduled right
    now: it was set up before this setting existed and keeps the web it had.
    A dream never goes online."""
    def mine_scheduled() -> bool:
        return _hour_scheduled(agent_id, "mine")

    return _online(_kept(agent_id), kind, mine_scheduled)


def hour_settings(agent_id: str) -> dict[str, dict]:
    """What each hour gets, as the person chose it over the defaults:
    ``{kind: {"at": "HH:MM", "minutes": n, "online": bool}}``. ``at`` is the
    time remembered for it (``hours_now`` says when a scheduled one runs)."""
    kept = _kept(agent_id)
    asked: list[bool] = []

    def mine_scheduled() -> bool:
        if not asked:
            asked.append(_hour_scheduled(agent_id, "mine"))
        return asked[0]

    return {kind: _settings(kept, kind, mine_scheduled) for kind in HOUR_KINDS}


def _chosen_minutes(kept: dict, kind: str) -> int | None:
    minutes = _recorded(kept, kind).get("minutes")
    return minutes if _minutes_ok(minutes) else None


def chosen_minutes(agent_id: str, kind: str) -> int | None:
    """The minutes the person chose for this hour, or None when they chose
    none or what is kept isn't a length an hour can have. ``hour_settings``
    fills in the default; this says only what was chosen."""
    return _chosen_minutes(_kept(agent_id), kind)


def _settings(kept: dict, kind: str, mine_scheduled) -> dict:
    recorded = _recorded(kept, kind)
    at = parse_clock(recorded.get("at")) or DEFAULT_AT[kind]
    minutes = _chosen_minutes(kept, kind)
    return {
        "at": clock_text(at),
        "minutes": DEFAULT_MINUTES[kind] if minutes is None else minutes,
        "online": _online(kept, kind, mine_scheduled),
    }


def _hour_job(kind: str):
    from . import scheduler

    return next(job for job in scheduler.HOUR_JOBS if job.name == f"hour-{kind}")


def _hour_scheduled(agent_id: str, kind: str) -> bool:
    from . import scheduler

    backend = scheduler.detect_backend()
    if backend == "unsupported":
        return False
    crontab = scheduler.read_crontab() if backend == "crontab" else ""
    return scheduled(agent_id, _hour_job(kind), backend, crontab)


def hours_now(agent_id: str) -> dict[str, dict]:
    """Each hour as it is on this machine now: ``{kind: {"on": bool, "at":
    "HH:MM", "minutes": n, "online": bool}}``. ``on`` is whether its job is
    scheduled; ``at`` is when it runs when it is (read from the job), else
    the time it would start at."""
    from . import scheduler

    kept = _kept(agent_id)
    backend = scheduler.detect_backend()
    on: dict[str, bool] = {kind: False for kind in HOUR_KINDS}
    when: dict[str, tuple[int, int] | None] = {kind: None for kind in HOUR_KINDS}
    if backend != "unsupported":
        crontab = scheduler.read_crontab() if backend == "crontab" else ""
        blueprint = scheduler.plan(
            agent_id=agent_id, mnemos_command="mnemos", has_model=False, backend=backend,
        )
        for entry in blueprint["hours"]:
            kind = entry["job"].name.removeprefix("hour-")
            on[kind] = scheduled(agent_id, entry["job"], backend, crontab)
            if on[kind]:
                when[kind] = scheduler.installed_daily_at(blueprint, entry, crontab)
    now = {}
    for kind in HOUR_KINDS:
        hour = _settings(kept, kind, lambda: on["mine"])
        if when[kind]:
            hour["at"] = clock_text(when[kind])
        now[kind] = {"on": on[kind], **hour}
    return now


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


def upkeep_on(agent_id: str) -> bool:
    """Whether the upkeep between sessions is scheduled for this agent."""
    from . import scheduler

    backend = scheduler.detect_backend()
    if backend == "unsupported":
        return False
    crontab = scheduler.read_crontab() if backend == "crontab" else ""
    return any(scheduled(agent_id, job, backend, crontab) for job in scheduler.JOBS)
