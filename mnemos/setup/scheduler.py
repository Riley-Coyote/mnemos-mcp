"""Native background scheduling for Mnemos: upkeep, and the quiet hours.

Memory that only works while a session happens to be open is not a memory
system. Consolidation, decay and connection discovery are what make
continuity feel alive between conversations — and until now the only way to
schedule them was OpenClaw's cron templates, which most users do not have.
Setup schedules this upkeep by default (``JOBS``). With no model chosen for
Mnemos it runs local passes only.

The quiet hours (``HOUR_JOBS``, mnemos/life.py) are scheduled only when asked
for: yes to setup's one question, or ``mnemos daemon install --hours``. They
run the person's own Claude Code on its own, on their Claude plan, so what
the agent thinks over in them goes to Anthropic (docs/privacy-security.md,
"Quiet Hours").

Two jobs an earlier install scheduled are retired, and installing or
uninstalling removes them (``RETIRED_JOBS``): the substrate tick and the
transcript indexer, which both wrote memories in a model's words.

None of that work was ever OpenClaw-specific. ``mnemos consolidate`` and
``mnemos life`` are plain CLI commands; only the *scheduling* was bound to
OpenClaw. This module supplies the missing half with whatever the host
actually provides: launchd on macOS, systemd user timers on Linux, and plain
crontab where systemd is absent.

Everything here is pure generation. Nothing touches the system until the
CLI decides to write, which keeps the whole surface testable without
shelling out to ``launchctl`` or ``systemctl``.
"""

from __future__ import annotations

import os
import plistlib
import re
import shlex
import shutil
import subprocess
import sys
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path


@dataclass(frozen=True)
class SchedulerJob:
    """One scheduled maintenance job.

    Either ``interval_seconds`` (run every N seconds) or ``daily_at``
    (run once a day at HH:MM) must be set, never both.
    """

    name: str
    args: tuple[str, ...]
    description: str
    interval_seconds: int | None = None
    daily_at: tuple[int, int] | None = None
    requires_model: bool = False

    def __post_init__(self) -> None:
        if (self.interval_seconds is None) == (self.daily_at is None):
            raise ValueError(
                f"job {self.name}: set exactly one of interval_seconds or daily_at"
            )

    @property
    def schedule_description(self) -> str:
        if self.daily_at is not None:
            return f"daily at {self.daily_at[0]:02d}:{self.daily_at[1]:02d}"
        assert self.interval_seconds is not None
        hours, remainder = divmod(self.interval_seconds, 3600)
        minutes = remainder // 60
        if hours and minutes:
            return f"every {hours}h {minutes}m"
        if hours:
            return f"every {hours}h"
        return f"every {minutes}m"


# The default schedule. Deliberately conservative: these run on someone
# else's machine, unattended, forever.
JOBS: tuple[SchedulerJob, ...] = (
    SchedulerJob(
        name="maintain",
        args=("consolidate",),
        description="Decay and connection discovery",
        interval_seconds=4 * 3600,
    ),
    SchedulerJob(
        name="maintain-deep",
        args=("consolidate", "--deep"),
        description="Softening and reflection",
        daily_at=(3, 0),
    ),
)

# The quiet hours (mnemos/life.py): time between sessions that belongs to the
# agent. "mine" is its own hour, every day, with nothing asked of it; "ours"
# is half an hour for the day's work, which the runner skips on a day with no
# work. Each runs the person's own Claude Code on its own (`claude -p`), on
# their Claude plan, and what the agent thinks over in it goes to Anthropic,
# so they are scheduled only when asked for: yes to setup's one question, or
# `mnemos daemon install --hours` (an app that runs Mnemos for people may keep
# them on).
HOUR_JOBS: tuple[SchedulerJob, ...] = (
    SchedulerJob(
        name="hour-mine",
        args=("life", "--hour", "mine"),
        description="The agent's own hour",
        daily_at=(8, 0),
    ),
    SchedulerJob(
        name="hour-ours",
        args=("life", "--hour", "ours"),
        description="Half an hour for the day's work",
        daily_at=(19, 0),
    ),
)

# Jobs an earlier `mnemos daemon install` scheduled that this one no longer
# does. Installing or uninstalling removes any of them still installed, so an
# upgrade does not leave one running unattended with nothing to remove it.
#
# The substrate tick's handlers write memories in a model's words whenever a
# provider key is present: dreams, insights, wanderings. Those are not the
# agent's words, and a memory is the agent's own or it is nothing to build an
# identity on. `mnemos substrate-tick` was retired in 0.4.0.
#
# The transcript indexer (`mnemos index`) had a model pull "facts" out of old
# conversations and file them as the agent's memories: on one live install
# about 7,058 of them against 13 the agent kept itself, and a session-start
# packet spent five of six long-term slots on paraphrases of one harvested
# fact. The first `mnemos daemon install` scheduled it every 30 minutes when
# a provider was configured. It was retired in 0.4.0, and `mnemos index` now
# only says so.
RETIRED_JOBS: tuple[SchedulerJob, ...] = (
    SchedulerJob(
        name="substrate-tick",
        args=("substrate-tick",),
        description="Cognitive substrate cycle: handlers and modulators",
        interval_seconds=4 * 3600,
    ),
    SchedulerJob(
        name="index",
        args=("index",),
        description="Index recent session transcripts into memory",
        interval_seconds=30 * 60,
        requires_model=True,
    ),
)


def jobs_for(*, has_model: bool) -> list[SchedulerJob]:
    """The jobs worth scheduling given what this install can actually do."""
    return [job for job in JOBS if has_model or not job.requires_model]


def model_is_configured() -> bool:
    """Whether a dedicated model provider is available for model-mediated jobs."""
    try:
        from ..simple_runtime import _dedicated_model_requested

        return bool(_dedicated_model_requested())
    except Exception:
        return False


def hour_jobs(
    *,
    mine_at: tuple[int, int] | None = None,
    ours_at: tuple[int, int] | None = None,
) -> list[SchedulerJob]:
    """The two quiet hours, at the given times or their own (08:00, 19:00)."""
    mine, ours = HOUR_JOBS
    return [
        replace(mine, daily_at=mine_at or mine.daily_at),
        replace(ours, daily_at=ours_at or ours.daily_at),
    ]


def find_claude() -> str | None:
    """The ``claude`` command a quiet hour runs, as an absolute path, or None.

    ``MNEMOS_CLAUDE_BIN`` when it is set (the runner reads it first too),
    else the ``claude`` on this PATH. Found now, at install time: a background
    job starts with almost no PATH and would not find it. The path is not
    followed through its links: Claude Code updates itself by moving the link,
    and a job pinned to the version behind it breaks once that version goes.
    """
    named = os.environ.get("MNEMOS_CLAUDE_BIN", "").strip()
    found = named or shutil.which("claude")
    if not found:
        return None
    path = os.path.abspath(os.path.expanduser(found))
    if not (os.path.isfile(path) and os.access(path, os.X_OK)):
        return None
    return path


# What a job's PATH holds besides the claude command's own folder: launchd
# starts a job with /usr/bin:/bin:/usr/sbin:/sbin, where a claude installed
# by Claude Code's installer, Homebrew or npm is not.
_SYSTEM_PATH = ("/usr/local/bin", "/usr/bin", "/bin", "/usr/sbin", "/sbin")


def hour_environment(
    *, claude_bin: str, mnemos_command: str, config_dir: str | None = None,
) -> dict[str, str]:
    """What a quiet hour needs from its environment when no shell made it:
    a PATH holding the folder the claude command is in (an npm claude needs
    the node beside it), and both commands' absolute paths, which the runner
    reads before any PATH lookup (``MNEMOS_CLAUDE_BIN``,
    ``MNEMOS_LIFE_MNEMOS_BIN``). ``config_dir`` is the Claude login the hours
    use (``CLAUDE_CONFIG_DIR``), when the person set one."""
    folders = dict.fromkeys([str(Path(claude_bin).parent), *_SYSTEM_PATH])
    environment = {
        "PATH": os.pathsep.join(folders),
        "MNEMOS_CLAUDE_BIN": claude_bin,
        "MNEMOS_LIFE_MNEMOS_BIN": mnemos_command,
    }
    if config_dir:
        environment["CLAUDE_CONFIG_DIR"] = os.path.abspath(os.path.expanduser(config_dir))
    return environment


def account_home() -> Path:
    """The account's own home folder, as the system has it, whatever HOME
    says; HOME's when the system has none to give."""
    try:
        import pwd

        return Path(pwd.getpwuid(os.getuid()).pw_dir)
    except (ImportError, AttributeError, KeyError, OSError):
        return Path.home()


def home_environment() -> dict[str, str]:
    """HOME, for jobs installed under a HOME that isn't the account's own (a
    host app's, say), so each runs where it was installed: a scheduler starts
    a job in the account's own home (launchd gives every job that HOME), and
    its memory, its record and its studio would be there instead. Nothing
    when HOME is the account's own, as for anyone who installs from their
    own shell."""
    home = Path.home()
    if os.path.normpath(home) == os.path.normpath(account_home()):
        return {}
    return {"HOME": str(home)}


def working_directory() -> str:
    """Where every job runs: ``~/.mnemos``, never a folder macOS keeps from
    background jobs (``~/Documents`` and the rest)."""
    return str(Path.home() / ".mnemos")


def detect_backend(system: str | None = None) -> str:
    """Pick the scheduler this host actually provides.

    Returns "launchd", "systemd", "crontab", or "unsupported".
    """
    system = (system or sys.platform).lower()
    if system.startswith("darwin"):
        return "launchd"
    if system.startswith("linux"):
        if shutil.which("systemctl"):
            return "systemd"
        if shutil.which("crontab"):
            return "crontab"
        return "unsupported"
    if shutil.which("crontab"):
        return "crontab"
    return "unsupported"


def label_for(agent_id: str, job: SchedulerJob) -> str:
    """Stable identifier for a job, namespaced per agent.

    Agent-scoped so several agents can each keep their own maintenance on
    one machine without overwriting each other's units.
    """
    return f"com.mnemos.{agent_id}.{job.name}"


def log_path_for(agent_id: str, job: SchedulerJob) -> str:
    return str(Path.home() / ".mnemos" / "logs" / f"{agent_id}-{job.name}.log")


def command_for(
    job: SchedulerJob,
    *,
    mnemos_command: str,
    scope_args: tuple[str, ...] = (),
) -> list[str]:
    """The full argv this job runs.

    Scope flags are global options on the Mnemos CLI, so they must precede
    the subcommand. Appending them instead produces a command that installs
    cleanly and then fails with "unrecognized arguments" on every scheduled
    run, into a log nobody reads.
    """
    return [mnemos_command, *scope_args, *job.args]


# ─────────────────────────── launchd (macOS) ───────────────────────────


def launchd_plist(
    job: SchedulerJob,
    *,
    agent_id: str,
    mnemos_command: str,
    scope_args: tuple[str, ...] = (),
    environment: Mapping[str, str] | None = None,
    working_dir: str | None = None,
) -> bytes:
    """A launchd user-agent plist for one job, run in ``working_dir`` with
    ``environment`` added to what launchd gives it."""
    label = label_for(agent_id, job)
    log = log_path_for(agent_id, job)
    payload: dict[str, object] = {
        "Label": label,
        "ProgramArguments": command_for(
            job, mnemos_command=mnemos_command, scope_args=scope_args
        ),
        # Maintenance must never race a login or fight for resources at
        # boot; it runs on its own schedule, not at load.
        "RunAtLoad": False,
        "StandardOutPath": log,
        "StandardErrorPath": log,
        "ProcessType": "Background",
        # Missed runs (laptop asleep) should still happen once on wake
        # rather than being silently skipped until the next interval.
        "LowPriorityIO": True,
    }
    if working_dir:
        payload["WorkingDirectory"] = working_dir
    if environment:
        payload["EnvironmentVariables"] = dict(environment)
    if job.daily_at is not None:
        hour, minute = job.daily_at
        payload["StartCalendarInterval"] = {"Hour": hour, "Minute": minute}
    else:
        payload["StartInterval"] = job.interval_seconds
    return plistlib.dumps(payload, sort_keys=True)


def launchd_plist_path(agent_id: str, job: SchedulerJob) -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{label_for(agent_id, job)}.plist"


# ─────────────────────────── systemd (Linux) ───────────────────────────


def _systemd_value(value: str) -> str:
    """``value`` as one double-quoted systemd word: its specifiers (``%``)
    and its own quotes and backslashes escaped."""
    escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%")
    return f'"{escaped}"'


def systemd_units(
    job: SchedulerJob,
    *,
    agent_id: str,
    mnemos_command: str,
    scope_args: tuple[str, ...] = (),
    environment: Mapping[str, str] | None = None,
    working_dir: str | None = None,
) -> tuple[str, str]:
    """The (service, timer) unit files for one job, run in ``working_dir``
    with ``environment`` set."""
    argv = command_for(job, mnemos_command=mnemos_command, scope_args=scope_args)
    exec_start = shlex.join(argv)
    service_lines = [
        "[Unit]",
        f"Description=Mnemos {job.name} ({job.description})",
        "",
        "[Service]",
        "Type=oneshot",
    ]
    if working_dir:
        service_lines.append(f"WorkingDirectory={working_dir.replace('%', '%%')}")
    for key, value in (environment or {}).items():
        service_lines.append(f"Environment={_systemd_value(f'{key}={value}')}")
    service = "\n".join([*service_lines, f"ExecStart={exec_start}", ""])
    if job.daily_at is not None:
        hour, minute = job.daily_at
        on = f"OnCalendar=*-*-* {hour:02d}:{minute:02d}:00"
    else:
        assert job.interval_seconds is not None
        on = f"OnUnitActiveSec={job.interval_seconds}s\nOnBootSec=15min"
    timer = "\n".join([
        "[Unit]",
        f"Description=Mnemos {job.name} schedule ({job.schedule_description})",
        "",
        "[Timer]",
        on,
        # A laptop that was asleep at 03:00 should still consolidate.
        "Persistent=true",
        "",
        "[Install]",
        "WantedBy=timers.target",
        "",
    ])
    return service, timer


def systemd_unit_dir() -> Path:
    return Path.home() / ".config" / "systemd" / "user"


def systemd_unit_names(agent_id: str, job: SchedulerJob) -> tuple[str, str]:
    stem = f"mnemos-{agent_id}-{job.name}"
    return f"{stem}.service", f"{stem}.timer"


def launchd_job_active(agent_id: str, job: SchedulerJob) -> bool:
    """Return true only when launchd has the generated job loaded."""
    import os

    try:
        result = subprocess.run(
            ["launchctl", "print", f"gui/{os.getuid()}/{label_for(agent_id, job)}"],
            capture_output=True, text=True, check=False,
        )
    except FileNotFoundError:
        return False
    return result.returncode == 0


def systemd_timer_active(agent_id: str, job: SchedulerJob) -> bool:
    """Return true only when the generated user timer is enabled and active."""
    _service, timer = systemd_unit_names(agent_id, job)
    try:
        enabled = subprocess.run(
            ["systemctl", "--user", "is-enabled", "--quiet", timer],
            capture_output=True, text=True, check=False,
        )
        active = subprocess.run(
            ["systemctl", "--user", "is-active", "--quiet", timer],
            capture_output=True, text=True, check=False,
        )
    except FileNotFoundError:
        return False
    return enabled.returncode == 0 and active.returncode == 0


# ─────────────────────────── crontab (fallback) ───────────────────────────

CRON_MARKER = "# mnemos-scheduler"


def cron_line(
    job: SchedulerJob,
    *,
    agent_id: str,
    mnemos_command: str,
    scope_args: tuple[str, ...] = (),
    environment: Mapping[str, str] | None = None,
    working_dir: str | None = None,
) -> str:
    """One crontab line, tagged so we can find our own entries again. With a
    ``working_dir`` it changes there first; ``environment`` is set for the
    command alone."""
    if job.daily_at is not None:
        hour, minute = job.daily_at
        schedule = f"{minute} {hour} * * *"
    else:
        assert job.interval_seconds is not None
        minutes = job.interval_seconds // 60
        if minutes < 60:
            schedule = f"*/{minutes} * * * *"
        else:
            schedule = f"0 */{minutes // 60} * * *"
    argv = command_for(job, mnemos_command=mnemos_command, scope_args=scope_args)
    command = shlex.join(argv)
    if environment:
        assignments = " ".join(f"{key}={shlex.quote(value)}" for key, value in environment.items())
        command = f"{assignments} {command}"
    if working_dir:
        command = f"cd {shlex.quote(working_dir)} && {command}"
    log = log_path_for(agent_id, job)
    return (
        f"{schedule} {command} >> {shlex.quote(log)} 2>&1 "
        f"{CRON_MARKER}:{agent_id}:{job.name}"
    )


def cron_marks(line: str, agent_id: str, name: str) -> bool:
    """Whether ``line`` is the one this agent's job ``name`` wrote. Whole
    names only: "maintain" is not "maintain-deep"."""
    return line.rstrip().endswith(f"{CRON_MARKER}:{agent_id}:{name}")


def cron_has(crontab: str, agent_id: str, name: str) -> bool:
    """Whether ``crontab`` holds this agent's job ``name``."""
    return any(cron_marks(line, agent_id, name) for line in crontab.splitlines())


def merge_cron_lines(
    existing: str,
    new_lines: list[str],
    agent_id: str,
    *,
    replacing: Iterable[str] | None = None,
) -> str:
    """Replace this agent's Mnemos entries, preserving everything else.

    A user's crontab is theirs. We only ever remove lines we previously
    wrote, identified by our own marker, and never reorder or drop
    anything else in the file. ``replacing`` names the jobs whose lines go;
    without it, every line of this agent's goes.
    """
    if replacing is None:
        tag = f"{CRON_MARKER}:{agent_id}:"
        kept = [line for line in existing.splitlines() if tag not in line]
    else:
        names = list(replacing)
        kept = [
            line for line in existing.splitlines()
            if not any(cron_marks(line, agent_id, name) for name in names)
        ]
    while kept and not kept[-1].strip():
        kept.pop()
    merged = kept + new_lines
    return "\n".join(merged) + "\n"


def read_crontab() -> str:
    try:
        result = subprocess.run(
            ["crontab", "-l"], capture_output=True, text=True, check=False
        )
    except FileNotFoundError:
        return ""
    return result.stdout if result.returncode == 0 else ""


def write_crontab(text: str) -> bool:
    """Replace this user's crontab with ``text``; whether it took."""
    try:
        result = subprocess.run(
            ["crontab", "-"], input=text, capture_output=True, text=True, check=False
        )
    except FileNotFoundError:
        return False
    return result.returncode == 0


# macOS restricts these directories through TCC. A launchd agent does not
# inherit the Full Disk Access a terminal may have been granted, so a
# Mnemos installed under one of them runs fine by hand and fails on every
# scheduled invocation with EPERM — silently, into a log file.
_TCC_PROTECTED_DIRS = ("Documents", "Desktop", "Downloads")


def _protected_folder(path: str | Path) -> tuple[str, str] | None:
    """``(top, shown)`` when ``path`` is under one of the folders macOS keeps
    from background jobs (``top``, e.g. "Documents"), with ``shown`` the path
    written from ``~``; else None."""
    try:
        relative = Path(path).expanduser().resolve().relative_to(Path.home().resolve())
    except (ValueError, OSError, RuntimeError):
        return None
    if not relative.parts or relative.parts[0] not in _TCC_PROTECTED_DIRS:
        return None
    return relative.parts[0], f"~/{relative.as_posix()}"


def package_folder() -> Path:
    """Where this Mnemos's own code is: in a source checkout installed in
    place (``pip install -e``), the checkout."""
    return Path(__file__).resolve().parent.parent


def tcc_warning(
    mnemos_command: str, *, backend: str, package_dir: str | Path | None = None,
) -> str | None:
    """Warn when scheduled jobs will be blocked by macOS privacy protection:
    the Mnemos command they run, or the code it imports (``package_dir``,
    this package's own folder by default), is under ``~/Documents``,
    ``~/Desktop`` or ``~/Downloads``. An install in place from a source
    checkout there is the usual way: its command can live anywhere and still
    import the checkout.

    Returns None when there is nothing to worry about.
    """
    if backend != "launchd":
        return None
    package_dir = package_folder() if package_dir is None else package_dir
    for place in (mnemos_command, package_dir):
        found = _protected_folder(place)
        if found is None:
            continue
        top, shown = found
        return (
            "Warning: background jobs will fail on this Mac.\n"
            "  This Mnemos runs from:\n"
            f"    {shown}\n"
            f"  macOS doesn't let background jobs read ~/{top}, so every scheduled\n"
            "  run fails, even though the same command works by hand. To fix it,\n"
            "  install Mnemos from PyPI (pipx install \"mnemos-continuity[mcp,embeddings]\")\n"
            "  or from a built wheel (uv build, then pipx install\n"
            "  dist/mnemos_continuity-*.whl), and run this again from that install."
        )
    return None


def _entry(
    job: SchedulerJob,
    *,
    backend: str,
    agent_id: str,
    mnemos_command: str,
    scope_args: tuple[str, ...],
    environment: Mapping[str, str] | None,
    working_dir: str | None,
) -> dict:
    """Everything an install needs for one job on ``backend``."""
    made = {
        "agent_id": agent_id,
        "mnemos_command": mnemos_command,
        "scope_args": scope_args,
        "environment": environment,
        "working_dir": working_dir,
    }
    entry: dict = {
        "job": job,
        "schedule": job.schedule_description,
        "command": shlex.join(
            command_for(job, mnemos_command=mnemos_command, scope_args=scope_args)
        ),
        "log": log_path_for(agent_id, job),
        "environment": dict(environment or {}),
        "working_dir": working_dir,
    }
    if backend == "launchd":
        entry["path"] = launchd_plist_path(agent_id, job)
        entry["content"] = launchd_plist(job, **made)
    elif backend == "systemd":
        service_name, timer_name = systemd_unit_names(agent_id, job)
        service, timer = systemd_units(job, **made)
        entry["units"] = {
            systemd_unit_dir() / service_name: service,
            systemd_unit_dir() / timer_name: timer,
        }
        entry["timer_name"] = timer_name
    elif backend == "crontab":
        entry["line"] = cron_line(job, **made)
    return entry


def plan(
    *,
    agent_id: str,
    mnemos_command: str,
    scope_args: tuple[str, ...] = (),
    has_model: bool | None = None,
    backend: str | None = None,
    hours: list[SchedulerJob] | None = None,
    hour_env: Mapping[str, str] | None = None,
) -> dict:
    """Describe exactly what an install would do, without doing any of it.

    ``entries`` are the upkeep jobs. ``hours`` are the quiet hours' entries,
    at ``hours``' times (their own by default), whether or not this install
    schedules them: status and uninstall find them by these. They can be
    scheduled only with ``hour_env`` (``hour_environment``), which needs the
    claude command found (``hours_ready``). Every job carries HOME when this
    HOME isn't the account's own (``home_environment``), and is found again
    under the same HOME.
    """
    backend = backend or detect_backend()
    if has_model is None:
        has_model = model_is_configured()
    selected = jobs_for(has_model=has_model)
    skipped = [job for job in JOBS if job not in selected]
    working_dir = working_directory()
    common = {
        "backend": backend,
        "agent_id": agent_id,
        "mnemos_command": mnemos_command,
        "scope_args": scope_args,
        "working_dir": working_dir,
    }
    home_env = home_environment()

    entries = [_entry(job, environment=home_env or None, **common) for job in selected]
    hour_entries = [
        _entry(job, environment={**(hour_env or {}), **home_env} or None, **common)
        for job in (hours if hours is not None else hour_jobs())
    ]

    # Where each retired job would be if an earlier install scheduled it, so
    # install and uninstall can remove it. On a crontab, its line is found by
    # its marker.
    retired: list[dict] = []
    for job in RETIRED_JOBS:
        entry = {"job": job}
        if backend == "launchd":
            entry["path"] = launchd_plist_path(agent_id, job)
        elif backend == "systemd":
            service_name, timer_name = systemd_unit_names(agent_id, job)
            entry["units"] = [
                systemd_unit_dir() / service_name,
                systemd_unit_dir() / timer_name,
            ]
            entry["timer_name"] = timer_name
        retired.append(entry)

    return {
        "backend": backend,
        "agent_id": agent_id,
        "entries": entries,
        "hours": hour_entries,
        "hours_ready": hour_env is not None,
        "skipped": skipped,
        "retired": retired,
        "has_model": has_model,
    }


def installed(blueprint: dict, entries: list[dict], crontab: str = "") -> list[dict]:
    """Those of ``entries`` an install left on this host: the plist, a unit
    file, or the crontab line is there. Whether the scheduler has it loaded
    is ``launchd_job_active`` and ``systemd_timer_active``."""
    found = []
    backend = blueprint["backend"]
    for entry in entries:
        if backend == "launchd":
            present = entry["path"].exists()
        elif backend == "systemd":
            present = any(path.exists() for path in entry["units"])
        else:
            present = cron_has(crontab, blueprint["agent_id"], entry["job"].name)
        if present:
            found.append(entry)
    return found


def retired_installed(blueprint: dict, crontab: str = "") -> list[dict]:
    """The retired jobs an earlier install left scheduled on this host."""
    return installed(blueprint, blueprint.get("retired") or [], crontab)


_ON_CALENDAR = re.compile(r"^OnCalendar=\*-\*-\* (\d{1,2}):(\d{2})", re.MULTILINE)


def installed_daily_at(blueprint: dict, entry: dict, crontab: str = "") -> tuple[int, int] | None:
    """The time of day an installed daily job runs, read from what the
    install wrote, or None when it can't be read."""
    backend = blueprint["backend"]
    try:
        if backend == "launchd":
            when = plistlib.loads(entry["path"].read_bytes()).get("StartCalendarInterval") or {}
            return int(when["Hour"]), int(when["Minute"])
        if backend == "systemd":
            timer = next(path for path in entry["units"] if str(path).endswith(".timer"))
            found = _ON_CALENDAR.search(Path(timer).read_text())
            return (int(found.group(1)), int(found.group(2))) if found else None
        for line in crontab.splitlines():
            if cron_marks(line, blueprint["agent_id"], entry["job"].name):
                minute, hour = line.split()[:2]
                return int(hour), int(minute)
    except (OSError, ValueError, KeyError, TypeError, StopIteration, plistlib.InvalidFileException):
        return None
    return None
