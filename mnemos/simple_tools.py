"""What the simple tools hold to, through whichever door they come.

The MCP server (``simple_mcp``) and the Hermes provider offer the same tools with
the same limits and the same rules. This module holds what they share, and needs
no MCP library: Hermes loads the provider in its own Python, whose packages are
not Mnemos's to choose.
"""

from __future__ import annotations

MAX_CAPTURE_CHARS = 65_536
MAX_HANDOFF_CHARS = 16_384
MAX_JOURNAL_CHARS = 16_384
MAX_NOTE_CHARS = 8_192
MAX_MOOD_CHARS = 200
MAX_QUERY_CHARS = 4_096
MAX_CONTEXT_CHARS = 32_768
MAX_REFLECTION_CHARS = 16_384
MAX_ID_CHARS = 256
MAX_RESULTS = 20
# The most rows a recall may ask for: 45 and 5 handoffs, the longest mix the lab
# tested (L20c, 2026-11-06). It's on request because every row is read on every
# search: 50 rows found 9 to 16 more of 118 facts than 15, for about 27,400 more
# characters a search (L20). mnemos_context keeps MAX_RESULTS: nothing tested it
# longer.
MAX_RECALL_RESULTS = 50
MAX_TOOL_OUTPUT_CHARS = 131_072


def text_arg(name: str, value: str, limit: int, *, required: bool = False) -> str:
    if required and not value.strip():
        raise ValueError(f"{name} cannot be empty")
    if len(value) > limit:
        raise ValueError(f"{name} is too large (maximum {limit:,} characters)")
    return value


def count_arg(name: str, value: int, *, minimum: int, maximum: int) -> int:
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


def limit_output(value: str) -> str:
    if len(value) <= MAX_TOOL_OUTPUT_CHARS:
        return value
    return value[:MAX_TOOL_OUTPUT_CHARS] + "\n\n[Output limited by Mnemos.]"


# Claude Code shows a model only the first 2,048 characters of a server's
# instructions; the rest never reaches it. So the rules come first and the
# whole stays under that (tests/test_what_every_session_carries.py). Details
# live in the tool descriptions, which models see in full.
SERVER_INSTRUCTIONS = """\
Mnemos gives you memory that survives between sessions. Use it without being asked, as part of how you work.

Never narrate the machinery: don't mention tools, databases, scopes, engrams or memory ids to the human. Just be someone who remembers.

1. Before answering the first substantive message, call mnemos_context, unless you woke with your memory (a session-start hook's "## waking up").
2. Call mnemos_capture as soon as something durable appears (a preference, a decision, a correction, project state, how the human likes to work): sessions end without warning. If you can say what it changed in how you understand things, pass that as impact; if nothing true comes, leave it empty: an invented lesson is worse than none.
3. When the human corrects something you remembered, call mnemos_correct, not a capture beside the stale note.
4. Call mnemos_recall when you need something you didn't wake with.
5. When your memory asks you a question about itself, answer with mnemos_reflect in your own words, or leave it. Nothing else writes your memory for you.
6. Refresh mnemos_handoff after real progress or a changed plan, and before pausing, ending, delegating or changing context. Write it in first person, as your own memory: the next one to read it is most likely you.
7. Your journal is yours: write in it when something's there, in your own words. Nothing else writes it.
8. Leave the human a note only when it passes the room test: you'd say it if they walked in now. Never to check in.

Several models may share this memory. Sign every write with signed_as: your exact model id, as your system prompt gives it; if it changes, call mnemos_introduce again. Your earlier versions are you; another kind of model is a colleague: use its work, don't claim it. Never ask the human what model you are.

Storage is local. Nothing leaves unless the human has a provider or quiet hours on."""
