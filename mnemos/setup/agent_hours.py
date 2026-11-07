"""Quiet hours for the agents that have a scheduler of their own.

Claude Code's hours are run by Mnemos, walled in (``mnemos/life.py``). Hermes
and OpenClaw each have a cron of their own that wakes the agent itself, so a
job in it hands the agent its hour: the job's message tells the agent to run
``mnemos life --hour H --handoff`` in its shell and take what that prints as
its own hour. The agent answers with its own tools, signed as itself; nothing
Mnemos prints writes words into its memory.

Three things to know, and ``mnemos connect`` says them:

* The hour is not walled in. The agent has its usual tools; the hand-off's
  words ask it to keep to what the hour is for.
* It runs on the model and provider the agent is set to use, so it spends that
  provider's tokens and what the agent thinks over goes there.
* A job's reply goes nowhere: Hermes' ``--deliver local`` keeps it on this
  machine, and OpenClaw's ``--no-deliver`` sends it to no chat or channel.

Jobs are named ``mnemos-hour-<kind>`` and sit at the same times Claude's hours
do (``scheduler.HOUR_JOBS``). Hermes' jobs fire only while its gateway runs,
which is Hermes' own setting; connect says so. Nothing here runs unless the
person asked for the hours (``mnemos connect <agent> --hours``).
"""

from __future__ import annotations

import json
import re
import shlex
import shutil
import subprocess

from . import scheduler

KINDS = ("mine", "ours", "dream")
PREFIX = "mnemos-hour-"
# The agents that schedule their own hours, and the command each uses.
AGENTS = {"hermes": "hermes", "openclaw": "openclaw"}
TIMEOUT = 60


def job_name(kind: str) -> str:
    return PREFIX + kind


def cron(kind: str) -> str:
    """The job's cron expression: the same time Claude's hour of this kind has."""
    job = next(j for j in scheduler.HOUR_JOBS if j.name == f"hour-{kind}")
    hour, minute = job.daily_at
    return f"{minute} {hour} * * *"


def message(kind: str, mnemos: str, flags: list[str], key: str = "") -> str:
    """What the job tells the agent when it wakes it."""
    command = shlex.join([mnemos, "life", "--hour", kind, "--handoff", *flags])
    words = (
        f"It is time for your quiet hour ({kind}). Run this in your shell:\n\n{command}\n\n"
        "What it prints is your hour. Take it as yourself, as it says, with your memory's own "
        "tools (mnemos_reflect, mnemos_capture, mnemos_journal), or answer nothing. If it "
        "prints nothing there is nothing to do: stop. Your reply to this job goes nowhere and "
        "no one reads it, so write no summary and message no one."
    )
    if key == "hermes":
        # Hermes from before September 2026 runs a job without its memory provider,
        # which carries these tools in Provider Mode. It does give a job a shell.
        tool = shlex.join([mnemos, "hermes", "tool", "mnemos_capture", *flags])
        words += (
            "\n\nIf those tools aren't offered to you in this job, the same ones run from your "
            f"shell, by name, with their arguments as JSON:\n\n{tool} <<'EOF'\n"
            '{"content": "...", "signed_as": "your exact model id"}\nEOF'
        )
    return words


def _hermes_prompts() -> dict[str, str]:
    """What Hermes' jobs say, by name, from its own file; nothing if it can't be read."""
    from ..integrations.hermes.scope import default_hermes_home

    try:
        data = json.loads((default_hermes_home() / "cron" / "jobs.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    jobs = data.get("jobs") if isinstance(data, dict) else data
    if not isinstance(jobs, list):
        return {}
    return {
        str(job.get("name")): str(job.get("prompt") or "")
        for job in jobs if isinstance(job, dict)
    }


def out_of_date(key: str, mnemos: str, flags: list[str]) -> list[str]:
    """Which of Mnemos's hour jobs say something other than this Mnemos would: from
    an older one, or another place it was installed. Hermes' only: it's the one whose
    jobs can be read, and whose words have changed."""
    if key != "hermes":
        return []
    prompts = _hermes_prompts()
    return [
        job_name(kind) for kind in KINDS
        if job_name(kind) in prompts and prompts[job_name(kind)] != message(kind, mnemos, flags, key)
    ]


def create_command(key: str, binary: str, kind: str, mnemos: str, flags: list[str]) -> list[str]:
    text = message(kind, mnemos, flags, key)
    name = job_name(kind)
    if key == "hermes":
        return [binary, "cron", "create", "--name", name, "--deliver", "local", cron(kind), text]
    if key == "openclaw":
        return [binary, "cron", "add", "--name", name, "--cron", cron(kind), "--message", text,
                "--session", "isolated", "--no-deliver", "--declaration-key", name]
    raise ValueError(f"{key} has no scheduler of its own that Mnemos uses")


def _run(command: list[str]) -> tuple[bool, str]:
    try:
        done = subprocess.run(command, capture_output=True, text=True, check=False, timeout=TIMEOUT)
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"{shlex.join(command[:3])} failed: {exc}"
    said = " ".join((done.stdout + " " + done.stderr).split())
    return done.returncode == 0, said


def _hermes_jobs(text: str) -> dict[str, str]:
    """Job name to id, from ``hermes cron list``'s text."""
    jobs: dict[str, str] = {}
    current = ""
    for line in text.splitlines():
        head = re.match(r"^\s*([0-9a-f]{6,})\s+\[", line)
        if head:
            current = head.group(1)
            continue
        named = re.match(r"^\s*Name:\s*(\S.*?)\s*$", line)
        if named and current:
            jobs[named.group(1)] = current
            current = ""
    return jobs


def _openclaw_jobs(text: str) -> dict[str, str]:
    """Job name to id, from ``openclaw cron list --json``, read loosely: any
    object with a name and an id, wherever it sits."""
    jobs: dict[str, str] = {}
    try:
        found = json.loads(text)
    except ValueError:
        return jobs

    def walk(node):
        if isinstance(node, dict):
            name = node.get("name") or node.get("displayName")
            ident = node.get("id") or node.get("jobId")
            if isinstance(name, str) and isinstance(ident, str):
                jobs[name] = ident
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(found)
    return jobs


def listed(key: str, binary: str) -> dict[str, str] | None:
    """Mnemos's hour jobs the agent's scheduler holds, name to id, or None when
    it can't be read (the agent isn't answering)."""
    if key == "hermes":
        # Hermes 0.17 leaves paused jobs out of a plain listing.
        ok, text = _raw(binary, ["cron", "list", "--all"])
        if not ok:
            ok, text = _raw(binary, ["cron", "list"])
        return {n: i for n, i in _hermes_jobs(text).items() if n.startswith(PREFIX)} if ok else None
    if key == "openclaw":
        ok, text = _raw(binary, ["cron", "list", "--json"])
        return {n: i for n, i in _openclaw_jobs(text).items() if n.startswith(PREFIX)} if ok else None
    return None


def _raw(binary: str, args: list[str]) -> tuple[bool, str]:
    """A command's whole output (the listings are read line by line)."""
    try:
        done = subprocess.run([binary, *args], capture_output=True, text=True, check=False, timeout=TIMEOUT)
    except (OSError, subprocess.SubprocessError):
        return False, ""
    return done.returncode == 0, done.stdout


def install(key: str, mnemos: str, flags: list[str]) -> tuple[bool, str]:
    """Create the three hour jobs in the agent's own scheduler, those it doesn't
    already hold. Returns whether all are there, and what was done."""
    binary = shutil.which(AGENTS.get(key, ""))
    if not binary:
        return False, f"`{AGENTS.get(key, key)}` isn't on this machine's PATH, so I can't schedule its hours."
    held = listed(key, binary)
    if held is None:
        return False, f"I couldn't read {key}'s scheduled jobs, so I scheduled nothing."
    lines: list[str] = []
    stale = out_of_date(key, mnemos, flags)
    for kind in KINDS:
        name = job_name(kind)
        if name not in held:
            ok, said = _run(create_command(key, binary, kind, mnemos, flags))
            done = f"scheduled at {cron(kind)}"
        elif name in stale:
            # In place, so a job someone paused or changed stays as they left it.
            ok, said = _run([binary, "cron", "edit", held[name], "--prompt", message(kind, mnemos, flags, key)])
            done = "what it says brought up to date"
        else:
            lines.append(f"{name}: already scheduled")
            continue
        if not ok:
            lines.append(f"{name}: failed ({said[:200]})")
            return False, "\n".join(lines)
        lines.append(f"{name}: {done}")
    return True, "\n".join(lines)


def _remove_command(key: str, binary: str, ident: str) -> list[str]:
    return [binary, "cron", "remove", ident] if key == "hermes" else [binary, "cron", "rm", ident]


def remove(key: str) -> tuple[bool, str]:
    """Remove Mnemos's hour jobs from the agent's scheduler."""
    binary = shutil.which(AGENTS.get(key, ""))
    if not binary:
        return True, ""
    held = listed(key, binary)
    if held is None:
        return False, f"I couldn't read {key}'s scheduled jobs, so I removed nothing."
    lines: list[str] = []
    for name, ident in sorted(held.items()):
        ok, said = _run(_remove_command(key, binary, ident))
        lines.append(f"{name}: " + ("removed" if ok else f"failed ({said[:200]})"))
        if not ok:
            return False, "\n".join(lines)
    return True, "\n".join(lines)


def scheduled(key: str) -> bool | None:
    """Whether the agent's scheduler holds Mnemos's hours, or None when that
    can't be told (the agent isn't on this machine, or isn't answering)."""
    binary = shutil.which(AGENTS.get(key, ""))
    if not binary:
        return None
    held = listed(key, binary)
    return None if held is None else bool(held)
