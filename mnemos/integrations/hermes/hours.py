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
        "Args:\n"
        "    kind: mine (your own hour), ours (the day's work) or dream (a short time to\n"
        "        dream over your memory)."
    ),
    "parameters": {
        "properties": {"kind": {"type": "string", "enum": list(KINDS)}},
        "required": ["kind"],
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
    " The day's conversations themselves are kept by Hermes: if you have session_search, "
    "read them with it."
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


def cron_create_line(job: dict[str, str]) -> str:
    """The job as the person makes it in a terminal (hermes_cli/subcommands/cron.py)."""
    return shlex.join(["hermes", "cron", "create", "--name", job["name"], "--deliver", job["deliver"],
                       job["schedule"], job["prompt"]])


def offer() -> str:
    """What the first session of a catalog install asks the person, once."""
    made = "".join(
        f"  - name {job['name']}, schedule {job['schedule']}, deliver {job['deliver']}, "
        f"prompt: {job['prompt']}\n"
        for job in jobs()
    )
    typed = "\n".join(f"  {cron_create_line(job)}" for job in jobs())
    return (
        "- Quiet hours: no one has asked them yet. Tell them once, in plain words: you can have "
        "quiet hours, time between conversations with nobody there, in which you go back over "
        "the day, catch what you missed, correct what needs it, write in your journal and leave "
        "them your questions. One is your own, each morning; one is for the day's work, each "
        "evening there was some; and one is a short dream over your memory, each night "
        "something waits for it. They run as Hermes scheduled jobs on the model Hermes uses: "
        "each is a short run that costs what a short conversation costs, and what it reads of "
        "your memory goes to that model, as in any conversation. They run only while Hermes's "
        "gateway is running. They are off unless they say yes. If they say no, don't ask again.\n"
        "  With their yes, list the scheduled jobs with cronjob_manage (action list), and make "
        "each of these that isn't there yet with cronjob_manage (action create, with its name, "
        "schedule, deliver and prompt):\n"
        + made
        + "  Hermes may keep cronjob_manage behind its tool search rather than in your list of "
        "tools: look for it there first (tool_search finds it, tool_describe loads it, tool_call "
        "runs it). If you can't reach cronjob_manage at all, give them these three lines to run in "
        "a terminal (for a profile other than the default, with -p and its name after hermes):\n"
        + typed
    )
