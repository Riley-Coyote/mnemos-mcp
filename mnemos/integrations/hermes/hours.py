"""Quiet hours inside Hermes: Hermes's own scheduler wakes the agent, and the
agent asks for its hour with ``mnemos_hour``.

The hour is the one ``mnemos life --hour <kind> --handoff`` hands over
(``_hand_off`` in mnemos/life.py), from the same code: the same words, the same
material read from this profile's memory without changing it, recorded so the
same material isn't handed twice. After its fence come a few sentences true
only here: which of the memory's tools answer it, where a note waits, and where
the day's conversations are. Nothing here runs a program or calls a model, and
nothing of Hermes's is imported: the agent schedules the jobs with Hermes's own
tool, or the person does with ``hermes cron create``.
"""

from __future__ import annotations

import io
from typing import Any

KINDS = ("mine", "ours", "dream")

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
        "you: what you keep, you keep with your memory's own tools. Each hour's material is\n"
        "handed once. When nothing waits for it, it says the hour would skip.\n"
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

# Of the memory's tools, the ones that answer an hour. A dream leaves no note.
_ANSWER_WITH = {
    "mine": "mnemos_reflect, mnemos_capture, mnemos_correct, mnemos_journal and mnemos_note",
    "ours": "mnemos_reflect, mnemos_capture, mnemos_correct, mnemos_journal and mnemos_note",
    "dream": "mnemos_reflect, mnemos_capture, mnemos_correct and mnemos_journal",
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
        f"Here, in Hermes, you take it with your memory's own tools: {_ANSWER_WITH[kind]}, "
        "each signed with signed_as, your exact model id."
    )
    if kind != "dream":
        said += _A_NOTE
    if kind == "ours":
        said += _THE_DAY
    return said


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
        return f"The hour would skip: {record['reason']} Nothing was handed."
    if record["status"] != "done":
        return f"Your hour couldn't be handed: {record['reason']} Nothing was handed."
    fence, gap, prompt = out.getvalue().rstrip("\n").partition(_GAP)
    return fence + "\n\n" + in_hermes(kind) + gap + prompt
