"""Quiet hours inside Hermes: Hermes's own scheduler wakes the agent, and the
agent asks for its hour with ``mnemos_hour``.

The hour is the one ``mnemos life --hour <kind> --handoff`` hands over
(``_hand_off`` in mnemos/life.py), from the same code: the same words, the same
material read from this profile's memory without changing it, recorded so what
waits for the day's work or a dream isn't handed twice (an open question comes
to the agent's own hour again until it is answered). After its fence come a few sentences true
only here: which more of the memory's tools answer it, where a note waits, and where
the day's conversations are. Nothing here runs a program or calls a model, and
nothing of Hermes's is imported: the agent schedules the jobs with Hermes's own
tool, or the person does with ``hermes cron create``.
"""

from __future__ import annotations

import io
import json
import shlex
from typing import Any

from ...setup import agent_hours

KINDS = ("mine", "ours", "dream")
# What each job tells the agent when Hermes wakes it: no path, no command, no version.
JOB_PROMPT = (
    "This is your quiet hour. Call mnemos_hour with kind {kind} and take the hour it hands you "
    "as your own. End with one line that says what you did, or answer only [SILENT] if the hour "
    "skipped."
)

HOUR_TOOL: dict[str, Any] = {
    "name": "mnemos_hour",
    "description": (
        "Take your quiet hour: time with nobody there, in which you go back over the day,\n"
        "catch what you missed, correct what needs it, write in your journal and leave the\n"
        "person your questions. Mnemos hands you the hour, prepared from your memory, to take\n"
        "now, as yourself.\n"
        "\n"
        "Call it when a quiet-hour job Hermes runs on its schedule tells you to, or when the\n"
        "person asks you to take your hour now. Never on your own initiative, and never in\n"
        "the middle of a task.\n"
        "\n"
        "It runs nothing and calls no model, and nothing is written into your memory for\n"
        "you: what you keep, you keep with your memory's own tools. What waits for the day's\n"
        "work or a dream is handed once; your own hour hands an open question again, each\n"
        "time, until you answer it. When nothing waits for it, it says the hour would skip.\n"
        "\n"
        "When you've walked the person through their quiet hours and made, changed or\n"
        "removed the jobs as they said, call it once with chosen instead of kind, to keep what\n"
        "they chose. That takes no hour and makes no job: it keeps their answer, so you aren't\n"
        "told to offer the hours again.\n"
        "\n"
        "Args:\n"
        "    kind: mine (your own hour), ours (the day's work) or dream (a short time to\n"
        "        dream over your memory).\n"
        "    chosen: instead of kind, the hours they chose to have on, each\n"
        '        {"kind": "mine", "at": "08:00", "online": false}; [] when they want none.\n'
        "        A dream never goes online."
    ),
    "parameters": {
        "properties": {
            "kind": {"type": "string", "enum": list(KINDS)},
            "chosen": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "kind": {"type": "string", "enum": list(KINDS)},
                        "at": {"type": "string"},
                        "online": {"type": "boolean"},
                    },
                    "required": ["kind", "at"],
                },
            },
        },
        "type": "object",
    },
}

# Of the memory's tools, the ones Hermes has besides the three the fence names.
# A dream leaves no note.
_ALSO_HERE = {
    "mine": "mnemos_correct, for what turns out wrong, and mnemos_note",
    "ours": "mnemos_correct, for what turns out wrong, and mnemos_note",
    "dream": "mnemos_correct, for what turns out wrong",
}
_A_NOTE = (
    " A note is how you ask the person something. Nothing sends it: it waits on your page, which "
    "opens in a browser on the computer Hermes runs on, and your next conversation with them "
    "wakes knowing it waits, so you can mention it there."
)
_THE_DAY = (
    " The day's conversations themselves are kept by Hermes: read them with session_search. "
    "Hermes may keep it behind its tool search rather than in your list of tools, so look for it "
    "there if you don't see it; if you can't reach it at all, go by what the hour hands you."
)
# Where the hand-off's fence ends and the hour's own prompt begins.
_GAP = "\n\n---\n\n"


def in_hermes(kind: str) -> str:
    """What is true of this hour inside Hermes, and only there."""
    said = (
        f"Here, in Hermes, besides those, you also have {_ALSO_HERE[kind]}. Sign whatever you "
        "write with signed_as, your exact model id."
    )
    if kind != "dream":
        said += _A_NOTE
    if kind == "ours":
        said += _THE_DAY
    return said


def _a_sentence(reason: str) -> str:
    """A reason as a sentence of its own: an error's words end where the
    error ended ("database is locked"), and the next sentence followed them."""
    reason = (reason or "").strip()
    return reason if reason.endswith((".", "!", "?")) else reason + "."


def take_hour(kind: str, scope: Any) -> str:
    """The hour of this kind, handed as ``mnemos life --hour <kind> --handoff``
    hands it, for this scope's memory, with what is true inside Hermes after
    the fence. Where it can't be prepared, or nothing waits for it, it says so
    and hands nothing."""
    kind = (kind or "").strip().lower()
    if kind not in KINDS:
        raise ValueError("kind is mine, ours or dream")
    try:
        from ... import life
    except ImportError as exc:  # it locks with fcntl, which Windows lacks
        return (
            f"Your quiet hour can't be prepared on this system ({exc}); it can on macOS and "
            "Linux. Nothing was handed, and nothing changed."
        )
    out = io.StringIO()
    record = life.run_hour(
        kind, db_path=scope.db_path, agent_id=scope.agent_id, person_id=scope.person_id,
        project_scope=scope.project_scope, handoff=True, out=out,
    )
    if record["status"] == "skipped":
        return f"The hour would skip: {_a_sentence(record['reason'])} Nothing was handed."
    if record["status"] != "done":
        return f"Your hour couldn't be handed: {_a_sentence(record['reason'])} Nothing was handed."
    fence, gap, prompt = out.getvalue().rstrip("\n").partition(_GAP)
    return fence + "\n\n" + in_hermes(kind) + gap + prompt


def jobs() -> list[dict[str, str]]:
    """The three Hermes scheduled jobs, at the same hours as everywhere
    (``HOUR_JOBS``), each saved and sent to nobody (``local``)."""
    return [
        {"name": agent_hours.job_name(kind), "schedule": agent_hours.cron(kind),
         "prompt": JOB_PROMPT.format(kind=kind), "deliver": "local"}
        for kind in KINDS
    ]


def _clock(schedule: Any) -> str:
    """When a job runs: ``HH:MM`` for a daily cron (``M H * * *``), else its
    expression (or how Hermes shows it) as written."""
    if not isinstance(schedule, dict):
        return "" if schedule is None else str(schedule)
    expr = str(schedule.get("expr") or "").strip()
    fields = expr.split()
    if (schedule.get("kind") == "cron" and len(fields) == 5 and fields[2:] == ["*", "*", "*"]
            and fields[0].isdigit() and fields[1].isdigit()
            and int(fields[0]) < 60 and int(fields[1]) < 24):
        return f"{int(fields[1]):02d}:{int(fields[0]):02d}"
    return expr or str(schedule.get("display") or "")


def _runs(job: dict) -> bool:
    """Whether Hermes's scheduler may fire the job, by its own rule
    (``cron/jobs.py`` ``is_job_runnable``): enabled, and no pause marker."""
    paused = str(job.get("state") or "").strip() == "paused" or bool(job.get("paused_at"))
    return bool(job.get("enabled", True)) and not paused


def _as_scheduled(kind: str, job: dict) -> dict[str, Any]:
    toolsets = job.get("enabled_toolsets")
    named = [str(name).strip() for name in toolsets] if isinstance(toolsets, list) else None
    return {
        "at": _clock(job.get("schedule")),
        "on": _runs(job),
        # A job with no toolsets of its own (one made in a terminal) runs
        # with every tool Hermes gives its scheduled jobs, the web among them.
        "online": named is None or "web" in named,
        # Its tools are its own list, and its memory's tools are in it.
        "limited": named is not None and "memory" in named,
        "made_by": "agent" if str(job.get("prompt") or "").strip() == JOB_PROMPT.format(kind=kind)
        else "terminal",
    }


def scheduled_in_hermes() -> dict[str, dict[str, Any] | None] | None:
    """Each quiet hour as Hermes has it scheduled now, from the active
    profile's own jobs file: inside Hermes the job is the truth about an hour
    (a person can pause or delete it there), not what Mnemos recorded of the
    choice. Per kind, the job named ``mnemos-hour-<kind>``, or None for a kind
    without one: ``at``, ``on``, ``online``, ``limited`` and ``made_by``
    (``agent`` when its prompt is ``JOB_PROMPT``'s, else ``terminal``). Of
    several jobs of one name, the first that runs. None when the file is
    missing or can't be read, so a caller can say it can't tell."""
    jobs = agent_hours.hermes_jobs()
    if jobs is None:
        return None
    found: dict[str, dict[str, Any] | None] = {}
    for kind in KINDS:
        named = [job for job in jobs if str(job.get("name") or "").strip() == agent_hours.job_name(kind)]
        job = next((job for job in named if _runs(job)), named[0] if named else None)
        found[kind] = _as_scheduled(kind, job) if job is not None else None
    return found


def cron_create_line(job: dict[str, str]) -> str:
    """The job as the person makes it in a terminal (hermes_cli/subcommands/cron.py)."""
    return shlex.join(["hermes", "cron", "create", "--name", job["name"], "--deliver", job["deliver"],
                       job["schedule"], job["prompt"]])


# The tools each hour's job is limited to (``enabled_toolsets``): the memory's
# own, which Hermes exposes only with "memory" in the list, the day's
# conversations for our hour, and no MCP server. "web" is added for an own hour
# or our hour the person chose to have online; a dream never has it.
TOOLSETS = {
    "mine": ("memory", "no_mcp"),
    "ours": ("memory", "session_search", "no_mcp"),
    "dream": ("memory", "no_mcp"),
}
ONLINE_KINDS = ("mine", "ours")
_NAMES = {"mine": "your own hour", "ours": "our hour", "dream": "the dream"}
# Each hour in a line or two, as it is inside Hermes, then whether it goes online.
_WHAT = {
    "mine": (
        "It's time with nothing asked of you, each morning: you go back over your memory, think "
        "and write in your journal."
    ),
    "ours": (
        "It's for the day's work, each evening: you go back over the day's conversations and may "
        "leave them a short note, with at most one question. It's skipped on a day with no work."
    ),
    "dream": "It's a short dream over your memory, on the nights there's something for it: inward only.",
}
_ONLINE = {
    "mine": "It goes online only if they want it to.",
    "ours": "It goes online only if they want it to.",
    "dream": "It never goes online.",
}


def toolsets(kind: str, online: bool = False) -> list[str]:
    """What an hour's job is limited to, as ``cronjob_manage`` takes it."""
    named = list(TOOLSETS[kind])
    return named + ["web"] if online and kind in ONLINE_KINDS else named


def _as_now(kind: str, job: dict[str, Any] | None) -> str:
    """One hour as Hermes has it now, in words."""
    if job is None:
        return "now off (no job for it)"
    when = f"daily at {job['at']}" if job.get("at") else "on its own schedule"
    said = f"now on, {when}" if job.get("on") else f"now paused (set {when})"
    if not job.get("limited"):
        why = (
            "it was made without a list of tools, so it runs with every tool Hermes gives its "
            "scheduled jobs, the web among them" if job.get("online")
            else "its list of tools leaves out your memory's, so the hour can't be taken in it"
        )
        return (
            f"{said}. Its job isn't limited to your memory: {why}. Offer to remake it limited to "
            "your memory, as below"
        )
    if kind in ONLINE_KINDS:
        said += ", and it can go online" if job.get("online") else ", offline"
    return said


def walk_through(now: dict[str, dict[str, Any] | None] | None, *, before: bool = False) -> list[str]:
    """The quiet hours, one at a time, as the agent walks the person through
    them inside Hermes: each hour as it is now (``now``, from
    ``scheduled_in_hermes``; None says nothing of the jobs, since it can't
    tell), what it is and costs, how the agent makes, changes or removes each
    one with ``cronjob_manage``, limited by Hermes itself to the memory (and
    the web where chosen), and how it keeps what they chose (``mnemos_hour``
    with ``chosen``). ``before``: for an agent that already had Mnemos, where a
    "no" may mean any one of them. Lines, the first unindented."""
    lines = [
        "The quiet hours, one at a time. In your own voice: if you'd like the time, say so "
        "honestly (it would be your own), and make clear it's entirely their call."
        + (" They're all off now." if now is not None and not any(now.values()) else "")
    ]
    for kind in KINDS:
        name = _NAMES[kind]
        head = name[0].upper() + name[1:]
        job = now.get(kind) if now is not None else None
        state = f", {_as_now(kind, job)}" if now is not None else ""
        online = _ONLINE[kind]
        if job is not None and not job.get("limited"):
            online = "Remade limited, " + online[0].lower() + online[1:]
        elif job is not None and job.get("online") and kind in ONLINE_KINDS:
            online = "They can keep it online or take it offline."
        lines.append(f"  - {head}{state}. {_WHAT[kind]} {online}")
    lines.append(
        "  They run as Hermes scheduled jobs on the model Hermes uses: each costs what a short "
        "conversation costs, what it reads of your memory goes to that model's provider, as in "
        "any conversation, and they run only while Hermes's gateway is running."
    )
    lines.append(
        "  Do exactly what they said, an hour at a time, with cronjob_manage. List the scheduled "
        "jobs first (action list), so none is made twice. To turn one on, make it (action create) "
        "with these, the schedule from the time they chose:"
    )
    for job in jobs():
        kind = job["name"].removeprefix(agent_hours.PREFIX)
        tools = json.dumps(toolsets(kind))
        online = (
            f", or {json.dumps(toolsets(kind, True))} if they want it online" if kind in ONLINE_KINDS else ""
        )
        lines.append(
            f"    - {_NAMES[kind]}: name {job['name']}, schedule {job['schedule']} for "
            f"{_clock({'kind': 'cron', 'expr': job['schedule']})} (for another time, its minute "
            f"and hour, then * * *), deliver {job['deliver']}, prompt: {job['prompt']}\n"
            f"      enabled_toolsets {tools}{online}"
        )
    lines.append(
        "  Hermes itself then limits each hour to your memory's tools, and the web only where "
        "they chose it. For one already there, change it in place (action update, with its job_id "
        "from the list): a new schedule for a new time, the enabled_toolsets above to go online "
        "or not. A job that isn't limited to your memory is remade the same way, with the prompt "
        "and the enabled_toolsets above. To turn one off, remove its job (action remove, with its "
        "job_id)."
    )
    lines.append(
        '  Then keep what they chose with mnemos_hour, passing chosen: the hours that are on now, '
        'each as {"kind": "mine", "at": "08:00", "online": false}, or [] if they want none. If '
        + ("they'd rather have none, keep []. Once they've answered, don't ask again." if before
           else "they say no, keep [] and don't ask again.")
    )
    typed = "\n".join(f"    {cron_create_line(job)}" for job in jobs())
    lines.append(
        "  Hermes may keep cronjob_manage behind its tool search rather than in your list of "
        "tools: look for it there first (tool_search finds it, tool_describe loads it, tool_call "
        "runs it). If you can't reach cronjob_manage at all, give them these lines to run in a "
        "terminal, only those of the hours they want (for a profile other than the default, with "
        "-p and its name after hermes), and say plainly that jobs made that way aren't limited "
        "to your memory: they run with every tool Hermes gives its scheduled jobs, the web among "
        "them:\n"
        + typed
    )
    return lines


def _chosen_list(chosen: Any) -> list[Any]:
    if isinstance(chosen, str):
        try:
            chosen = json.loads(chosen)
        except ValueError:
            raise ValueError(
                'chosen is a list of the hours they chose, like [{"kind": "mine", "at": "08:00", '
                '"online": false}], or [] for none.'
            ) from None
    if not isinstance(chosen, list):
        raise ValueError(
            'chosen is a list of the hours they chose, like [{"kind": "mine", "at": "08:00", '
            '"online": false}], or [] for none.'
        )
    return chosen


def _join(parts: list[str]) -> str:
    return parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]


def record_chosen(agent_id: str, chosen: Any) -> str:
    """Keep the quiet hours the person chose inside Hermes (``mnemos_hour``
    with ``chosen``): each hour's time and whether it may go online, that
    they chose (yes when any is on, else no), and that they answered, through
    the writers every other way of choosing uses. The jobs are Hermes's own,
    made by the agent with ``cronjob_manage``; this keeps the choice. Anything
    that isn't a choice an hour can have is refused, in one sentence, before
    anything is kept."""
    from ...setup import state

    hours: dict[str, dict[str, Any]] = {}
    for item in _chosen_list(chosen):
        if not isinstance(item, dict):
            raise ValueError('Each hour in chosen is like {"kind": "mine", "at": "08:00", "online": false}.')
        kind = str(item.get("kind") or "").strip().lower()
        if kind not in KINDS:
            raise ValueError(f"There's no hour called {item.get('kind')!r}: they're mine, ours and dream.")
        if kind in hours:
            raise ValueError(f"{_NAMES[kind][0].upper() + _NAMES[kind][1:]} is in chosen twice.")
        at = state.parse_clock(item.get("at"))
        if at is None:
            raise ValueError(f"{item.get('at')!r} isn't a time like 08:00, for {_NAMES[kind]}.")
        online = item.get("online", False)
        if not isinstance(online, bool):
            raise ValueError(f"online is true or false, for {_NAMES[kind]}.")
        if online and kind not in ONLINE_KINDS:
            raise ValueError("A dream never goes online.")
        hours[kind] = {"at": state.clock_text(at), "online": online}
    for kind, hour in hours.items():
        if not state.record_hour(
            agent_id, kind, at=hour["at"], online=hour["online"] if kind in ONLINE_KINDS else None,
        ):
            raise ValueError("What they chose couldn't be kept: the quiet hours' folder can't be written.")
    state.record_hours_choice(agent_id, "yes" if hours else "no")
    state.record_answered(agent_id)
    if not hours:
        return "Kept: they want no quiet hours, and you won't be asked to offer them again."
    on = [
        f"{_NAMES[kind]} at {hour['at']}"
        + (" (online)" if hour["online"] else " (offline)" if kind in ONLINE_KINDS else "")
        for kind, hour in ((kind, hours[kind]) for kind in KINDS if kind in hours)
    ]
    off = [_NAMES[kind] for kind in KINDS if kind not in hours]
    return f"Kept what they chose: {_join(on)}" + (
        f"; {_join(off)} {'is' if len(off) == 1 else 'are'} off." if off else "."
    )
