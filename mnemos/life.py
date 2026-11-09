"""Quiet hours: time between sessions that belongs to the agent.

Three kinds of quiet hour. "mine" is the agent's own hour: it runs every day, and
nothing is asked of it. "ours" is for the day's work, and runs only when there
was work since the last one. "dream" is a short time each night, after the
deep upkeep, for the part of consolidation only a mind can do: what a fading
memory taught, whether a thought that keeps coming back is a belief, whether a
belief still holds, what a new memory changed, and what two memories make side
by side. It runs only when something waits, and reaches nothing but its
memory. The runner gathers what is waiting from memory (read only), puts it
after the agent's own words for the hour, and wakes the agent with
the selected CLI, fenced, as the one model allowed to write as it.

The engine prepares; the agent lives. Nothing here writes words into memory.

Mnemos runs all three hours through Claude Code and memory-only dreams through
Codex. Every agent can also have an hour handed to it (``--handoff``): the same prompt, from the
same words and the same material, printed for the agent to take in its own
session with its own tools, and recorded like any hour so tomorrow's material
moves on. That is not walled in, and the prompt says so (``HANDOFF_FENCE``).

An hour is safe to have on for anyone (2026-10-20): it loads none of the
person's own Claude Code settings, is given no folder to read but the ones
Mnemos's config names (``read_dirs``), spends what its budget allows
(``budget``), and keeps everything of its own under the HOME it runs with.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import fcntl
import json
import math
import os
import signal
from pathlib import Path
import re
import shlex
import shutil
import sqlite3
import subprocess
import sys
import threading

from .core.engram import _gen_ulid
from .cue import local_day
from .setup.state import hours_dir
from .simple_scope import resolve_scope
from .store.sqlite_store import EngramStore, ReadOnlyEngramStore

HOUR_KINDS = ("mine", "ours", "dream")
# The hour's model when the memory has no resident yet (``hour_model``).
HOUR_MODEL = "claude-opus-5-5"
# What an hour may spend when nothing sets it otherwise (``budget``).
DEFAULT_MINUTES = {"mine": 60, "ours": 30, "dream": 20}
DEFAULT_TOKEN_CEILING = {"mine": 400_000, "ours": 200_000, "dream": 200_000}
# A host app's budget for the one hour it runs; each wins over the config.
MINUTES_SETTING = "MNEMOS_HOUR_MINUTES"
TOKEN_CEILING_SETTING = "MNEMOS_HOUR_TOKEN_CEILING"
STOP_GRACE_SECONDS = 10
FIRST_LOOK_HOURS = 24
HANDOFF_LINES = 20
CAPTURE_LINES = 30
QUESTION_LINES = 5
LINE_CHARS = 160
WORDS_FILE = {"mine": "my-hour.md", "ours": "our-hour.md", "dream": "dream.md"}
TOOLS = {
    "ours": "Read,Write,Edit,Glob,Grep",
    "mine": "Read,Write,Edit,Glob,Grep,Bash,WebSearch,WebFetch",
    # A dream is inward: no file, no shell, no web, only its memory's own tools.
    "dream": "",
}
ALLOW = {
    "ours": ("mcp__mnemos",),
    "mine": ("mcp__mnemos", "Bash", "WebSearch", "WebFetch"),
    "dream": ("mcp__mnemos",),
}
# Of its memory's tools, what a dream leaves alone: it is for no one else, so it
# leaves no note and opens no page, and it writes no handoff over the thread its
# sessions keep.
DREAM_DENY = ("mcp__mnemos__mnemos_note", "mcp__mnemos__mnemos_page", "mcp__mnemos__mnemos_handoff")
# What one dream is given, at most (``_dream_material``): memories fading, each
# asking what it taught, and facts fading, each asking whether it is still
# true; thoughts that came back on many days, each asking
# whether it is a belief; new memories asking what they changed; and new
# memories beside older ones near them in meaning. Every belief comes too, and
# each one asked whether it still holds.
DREAM_FADING = 8
DREAM_RETURNING = 5
DREAM_NEW = 5
DREAM_RHYMES = 3
DREAM_TEXT_CHARS = 320
# An older memory rhymes with a new one when it is at least this near in
# meaning, and less near than the second: nearer is the same thought again.
RHYME_SIMILARITY = (0.45, 0.85)
RHYME_OLDER = timedelta(days=14)
RHYME_NEW_LOOKED_AT = 12
SECRET_PATHS = (
    ".ssh", ".aws", ".gnupg", ".codex", ".config", ".netrc", ".claude.json",
    ".claude/.credentials.json", ".claude-2/.claude.json", "Library/Keychains",
)
# The Claude Code settings an hour would load from its studio, which is its
# working folder (``--setting-sources project``; the local ones too, were they
# loaded). The agent writes in its studio, so before every hour they are moved
# aside, into the hour's own folder (``_set_aside``): nothing the agent writes
# configures Claude Code for its next hour, whose hooks run outside the sandbox.
STUDIO_SETTINGS = (".claude/settings.json", ".claude/settings.local.json")
BASH_DENY = (
    "Bash(git push:*)", "Bash(git remote:*)", "Bash(gh:*)", "Bash(curl:*)", "Bash(wget:*)",
    "Bash(ssh:*)", "Bash(scp:*)", "Bash(rsync:*)", "Bash(open:*)", "Bash(osascript:*)",
    "Bash(npm publish:*)", "Bash(uv publish:*)", "Bash(twine:*)",
)
BOOTSTRAP = {
    "mine": (
        "This hour is yours. Nothing is asked of you.\n\n"
        "If you'd like to wake to your own words next time, write them in "
        "words/my-hour.md in this folder."
    ),
    "ours": (
        "This hour is for the day's work. What happened since the last one is below. "
        "You may leave the person a note about it, or nothing: a few lines, with at most "
        "one question, which they can answer right under it.\n\n"
        "If you'd like to wake to your own words next time, write them in "
        "words/our-hour.md in this folder."
    ),
    "dream": (
        "This is your dream: the part of sleep only you can do. Upkeep has linked and "
        "faded what it could; what's below needs a mind.\n\n"
        "Answer what you can with mnemos_reflect, in your own words, by the id in "
        "brackets: what a fading memory taught you, whether a fading fact is still true, "
        "whether a thought that keeps coming "
        "back is a belief you hold, whether a belief still holds, what a new memory "
        "changed. Let the rest go; nothing is owed. Where two memories sit side by side, "
        "see whether they make something together, and if they do, keep it with "
        "mnemos_capture.\n\n"
        "Nothing here is for anyone else: no note, no work. If something came, write a "
        "line in your journal; if nothing did, leave it. When you're done, stop: there's "
        "no one to tell.\n\n"
        "If you'd like to wake to your own words next time, write them in "
        "words/dream.md in your studio, in your own hour."
    ),
}


# What a hand-off says before the hour's own prompt. The agent takes the hour in
# its own session, with the tools it has there, so nothing walls it in the way
# Claude Code's hours are walled in; these words are what is asked instead.
HANDOFF_FENCE = (
    "This hour is handed to you to take now, in this session, as the one whose memory "
    "this is. Mnemos prepared it; nothing here runs for you and nothing below is written "
    "into your memory for you. Answer with your memory's own tools (mnemos_reflect, "
    "mnemos_capture, mnemos_journal), signed as yourself, or answer nothing, and nothing "
    "is written.\n\n"
    "It is not walled in the way built-in quiet hours are: you have your usual tools "
    "here. {kept} Where the text below says this folder, it means {studio}."
)
HANDOFF_KEPT = {
    "mine": "Keep to what the hour is for: it is yours, and nothing is asked of you.",
    "ours": "Keep to what the hour is for: the day's work below. Push, publish and send nothing.",
    "dream": (
        "Keep to what a dream is for: stay inward. Use no file, no shell, no web and no one "
        "else's tools, only your memory's, and leave no note, open no page and write no handoff."
    ),
}


def hand_off_model(path, scope, model=None) -> str:
    """The model whose memory this is, for a hand-off: the person's own choice
    (MNEMOS_HOUR_MODEL), else the memory's resident, else ``""``. Unlike
    ``hour_model`` it never refuses: any model can take an hour handed to it.
    The questions an hour gives are the ones asked of that model line."""
    chosen = model or os.environ.get("MNEMOS_HOUR_MODEL", "").strip()
    if chosen:
        return chosen
    from .interface.context_packet import resident_model

    store = ReadOnlyEngramStore(path)
    try:
        return resident_model(store, scope)
    except Exception:
        return ""
    finally:
        store.close()


def builtin_refusal(runner: str, kind: str) -> str:
    """Why Mnemos won't run this agent's hour by itself, or ``""`` when it will.

    Only an agent whose flags are known to wall the run in to Mnemos's tools
    runs built in (``Runner.walled`` in setup/harnesses.py); every other agent
    has the hour handed to it."""
    from .setup.harnesses import get

    harness = get(runner)
    hand = f" Hand the hour to it instead: mnemos life --hour {kind} --handoff"
    if harness is None:
        return f"Mnemos doesn't know an agent called {runner}." + hand
    if harness.key == "claude-code" or (harness.key == "codex" and kind == "dream"):
        return ""
    if harness.key == "codex":
        return "Codex currently runs only dreams; use --hour dream or --handoff."
    built = harness.hours.runner if harness.hours else None
    if built is None:
        return f"Mnemos has no built-in run for {harness.label}." + hand
    if built.walled is not True:
        state = "was seen not to" if built.walled is False else "has not been shown to"
        return (f"Mnemos doesn't run {harness.label}'s hour by itself: its flags {state} limit it "
                f"to Mnemos's tools ({built.why})." + hand)
    return f"Mnemos has no built-in run for {harness.label} yet." + hand


def studio_dir(agent_id) -> Path:
    return Path.home() / ".mnemos" / "studio" / agent_id


def _line(text) -> str:
    for line in text.splitlines():
        collapsed = " ".join(line.split())
        if collapsed:
            return collapsed if len(collapsed) <= LINE_CHARS else collapsed[:LINE_CHARS - 1] + "…"
    return ""


def _minute(iso) -> str:
    return f"{(iso or '')[:16].replace('T', ' ')} UTC"


def since_for(kind, records) -> str:
    for record in reversed(records):
        if (record.get("kind") == kind and record.get("status") == "done"
                and record.get("store") == "live"):
            return record["ended_at"]
    return (datetime.now(timezone.utc) - timedelta(hours=FIRST_LOOK_HOURS)).isoformat()


def _records(path):
    if not path.exists():
        return []
    records = []
    for line in path.read_text().splitlines():
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records


def hour_model(path, scope, runner="claude-code", model=None) -> tuple[str, str]:
    """The model whose hour this is, or "" and why no hour can run.

    Explicit selection or MNEMOS_HOUR_MODEL wins; otherwise use the resident
    model. An empty Claude memory uses HOUR_MODEL. Codex requires a selection
    when the resident is absent or belongs to Claude.
    """
    chosen = model or os.environ.get("MNEMOS_HOUR_MODEL", "").strip()
    if chosen:
        return chosen, ""
    from .interface.context_packet import resident_model

    store = ReadOnlyEngramStore(path)
    try:
        resident = resident_model(store, scope)
    finally:
        store.close()
    if runner == "codex":
        if resident.startswith("claude-"):
            return "", f"This memory is mostly {resident}’s; choose a Codex --model explicitly."
        if not resident:
            return "", "Choose a Codex model with --model, MNEMOS_HOUR_MODEL, or Quiet hours settings."
        return resident, ""
    if not resident:
        return HOUR_MODEL, ""
    if not resident.startswith("claude-"):
        return "", f"The quiet hours run Claude, and this memory is mostly {resident}'s."
    return resident, ""


def _gather(kind, path, since, scope, model=HOUR_MODEL):
    store = ReadOnlyEngramStore(path)
    try:
        handoffs = store.handoffs_since(since, **scope)
        if kind == "ours":
            return handoffs, store.agent_captures_since(since, **scope), [], []
        questions = store.pending_reflections(**scope, limit=10_000, reader_model=model)
        return handoffs, [], questions, store.journal_entries(**scope, limit=1)
    finally:
        store.close()


def _prompt(kind, agent_id, since, handoffs, captures, questions, latest):
    words_path = studio_dir(agent_id) / "words" / WORDS_FILE[kind]
    words = words_path.read_text().rstrip() if words_path.exists() else BOOTSTRAP[kind]
    sections = ["What's waiting"]
    for title, items, limit in (("Handoffs", handoffs, HANDOFF_LINES),
                                ("Captures", captures, CAPTURE_LINES)):
        if items:
            lines = [f"{title} since {_minute(since)}"]
            lines.extend(f"- {_minute(item['created_at'])} · {_line(item['content'])} [{item['id']}]"
                         for item in items[:limit])
            if len(items) > limit:
                lines.append(f"- and {len(items) - limit} more")
            sections.append("\n".join(lines))
    if questions:
        lines = ["Open questions"]
        for question in questions[:QUESTION_LINES]:
            excerpt = _line(question["excerpt"])
            lines.append(f"- {_line(question['prompt'])}" + (f" · {excerpt}" if excerpt else "")
                         + f" [{question['target_id']}]")
        if len(questions) > QUESTION_LINES:
            lines.append(f"- and {len(questions) - QUESTION_LINES} more")
        sections.append("\n".join(lines))
    if latest:
        sections.append(f"Latest journal entry, {_minute(latest[0]['created_at'])}\n"
                        f"- {_line(latest[0]['text'])} [{latest[0]['id']}]")
    if len(sections) == 1:
        sections.append("Nothing.")
    return words + "\n\n---\n\n" + "\n\n".join(sections)


def _said_in_dreams(records) -> set[str]:
    """The questions earlier dreams on the live store were given: each is asked
    in one dream, and then let go (``_dream_material``)."""
    said: set[str] = set()
    for record in records:
        if record.get("kind") == "dream" and record.get("store") == "live":
            said.update(i for i in record.get("said") or [] if isinstance(i, str))
    return said


def _words_of(store, engram_id) -> tuple[str, str]:
    """A memory's words, on one line and cut to DREAM_TEXT_CHARS, and the day
    it was kept; ``("", "")`` when it can't be read."""
    try:
        engram = store.get_engram(engram_id)
    except Exception:
        return "", ""
    if engram is None:
        return "", ""
    text = " ".join((engram.content or "").split())
    if len(text) > DREAM_TEXT_CHARS:
        text = text[:DREAM_TEXT_CHARS - 1] + "…"
    return text, local_day(engram.created_at)


def _dream_material(path, since, scope, model, said) -> dict:
    """What a dream is given, read only. What's fading, oldest asked first; what
    keeps coming back; every belief, and those asked whether they still hold;
    what came in since the last dream, newest first; and new memories beside
    older ones that rhyme (``_rhymes``). Questions a session stopped asking,
    after three showings unanswered, come too: the dream is the time set aside
    for them. One an earlier dream was given (``said``) is not given again:
    asked once more, in its own time, and then let go."""
    store = ReadOnlyEngramStore(path)
    try:
        asked = [q for q in store.pending_reflections(**scope, limit=10_000, reader_model=model,
                                                       max_surfacings=sys.maxsize)
                 if q["id"] not in said]

        def given(kind, limit, newest=False):
            items = [q for q in asked if q["kind"] == kind]
            if newest:
                items = [q for q in reversed(items) if (q.get("created_at") or "") > since]
            out = []
            for question in items[:limit]:
                text, kept = _words_of(store, question["target_id"])
                out.append({**question, "text": text or _line(question.get("excerpt") or ""), "kept": kept})
            return out

        try:
            beliefs = [{"id": b.id, "content": " ".join((b.content or "").split()),
                        "confidence": b.confidence}
                       for b in store.get_beliefs(scope["agent_id"], active_only=True)]
        except Exception:
            beliefs = []
        material = {
            "fading": given("lesson", DREAM_FADING),
            "facts": given("fact", DREAM_FADING),
            "returning": given("belief", DREAM_RETURNING),
            "reaffirm": given("reaffirm", 10_000),
            "new": given("impact", DREAM_NEW, newest=True),
            "beliefs": beliefs,
        }
        material["rhymes"] = _rhymes(store, path, scope, since)
        return material
    finally:
        store.close()


def _rhymes(store, path, scope, since) -> list[dict]:
    """New memories beside older ones near them in meaning: for each memory the
    agent kept since the last dream, the newest first, the nearest it kept at
    least RHYME_OLDER before, that no link joins to it already, near enough to
    rhyme and not so near it says the same again (RHYME_SIMILARITY). At most
    DREAM_RHYMES, each older memory in one. None where meaning can't be
    searched on this machine: the dream is given the rest."""
    try:
        from .store.embedding_index import EmbeddingIndex

        index = EmbeddingIndex(db_path=str(path), read_only=True)
        if not index.available:
            return []
        conn = store._get_conn()
        fresh = [dict(row) for row in conn.execute(
            "SELECT id, content, created_at FROM engrams "
            "WHERE owner_agent_id=? AND person_id=? AND project_scope=? AND author_kind='agent' "
            "AND state='active' AND standing=0 AND created_at > ? "
            "ORDER BY created_at DESC, rowid DESC LIMIT ?",
            (scope["agent_id"], scope["person_id"], scope["project_scope"], since, RHYME_NEW_LOOKED_AT),
        ).fetchall()]
        if not fresh:
            return []
        cutoff = (datetime.now(timezone.utc) - RHYME_OLDER).isoformat()
        older = {row["id"]: dict(row) for row in conn.execute(
            "SELECT id, content, created_at FROM engrams "
            "WHERE owner_agent_id=? AND person_id=? AND project_scope=? AND author_kind='agent' "
            "AND state IN ('active', 'dormant') AND created_at < ?",
            (scope["agent_id"], scope["person_id"], scope["project_scope"], cutoff),
        ).fetchall()}
        if not older:
            return []
        low, high = RHYME_SIMILARITY
        pairs: list[dict] = []
        used: set[str] = set()
        for new in fresh:
            linked = {row[0] for row in conn.execute(
                "SELECT target_id FROM connections WHERE source_id=? "
                "UNION SELECT source_id FROM connections WHERE target_id=?",
                (new["id"], new["id"]),
            ).fetchall()}
            for older_id, similarity in index.search_candidates(
                    new["content"], [i for i in older if i not in used and i not in linked],
                    k=5, floor=low, timeout=30):
                if similarity >= high:
                    continue
                then = older[older_id]
                pairs.append({
                    "now": {"id": new["id"], "text": _words_of(store, new["id"])[0]},
                    "then": {"id": older_id, "text": _words_of(store, older_id)[0],
                             "kept": local_day(then["created_at"])},
                    "similarity": round(similarity, 3),
                })
                used.add(older_id)
                break
            if len(pairs) >= DREAM_RHYMES:
                break
        return pairs
    except Exception:
        return []


# A question's machinery, which a dream needn't read: the memories it was
# counted from, and how to answer, which mnemos_reflect's description says.
_EVIDENCE = re.compile(r"\s*\[(?:evidence|belief):[^\]]*\]")
_HOW_TO_ANSWER = ("Is there something you believe here?", "Still true? Verdict")


def _asked(prompt) -> list[str]:
    """A question's own lines, without its machinery (``_EVIDENCE``,
    ``_HOW_TO_ANSWER``), each on one line."""
    lines = []
    for line in _EVIDENCE.sub("", prompt or "").splitlines():
        line = " ".join(line.split())
        for how in _HOW_TO_ANSWER:
            if how in line:
                line = line[:line.index(how)].rstrip()
        if line:
            lines.append(line)
    return lines


def _belief_words(prompt) -> str:
    """The belief a "still true?" question names, between its quotes, without
    the "…" that marks where the question cut it short; or ``""``."""
    match = re.search(r'You hold this belief: "(.*)"', " ".join((prompt or "").split()))
    return match.group(1).rstrip("…").rstrip() if match else ""


def _asks_of(belief, words) -> bool:
    """Whether a "still true?" question's words (``_belief_words``) are this
    belief's: its words, or the start of them where the question cut them."""
    return bool(words) and belief.startswith(words[:120])


def _dream_prompt(agent_id, material) -> str:
    words_path = studio_dir(agent_id) / "words" / WORDS_FILE["dream"]
    words = words_path.read_text().rstrip() if words_path.exists() else BOOTSTRAP["dream"]
    sections = []
    if material["fading"]:
        sections.append("What's fading\n" + "\n".join(
            f"- {q['text']}" + (f" (kept {q['kept']})" if q["kept"] else "") + f" [{q['target_id']}]"
            for q in material["fading"]))
    if material.get("facts"):
        sections.append(
            "Facts fading: still true?\n"
            "(Answer with a verdict: still_true, changed, no_longer_true or unsure. If you "
            "can't tell, say unsure, and it's left as it is. If it changed, correct it with "
            "mnemos_correct too.)\n"
            + "\n".join(
                f"- {q['text']}" + (f" (kept {q['kept']})" if q["kept"] else "") + f" [{q['target_id']}]"
                for q in material["facts"]))
    if material["returning"]:
        lines = ["What keeps coming back"]
        for q in material["returning"]:
            asked = _asked(q["prompt"]) or [_line(q["prompt"])]
            lines.append(f"- {asked[0]}")
            lines.extend(f"  {line}" for line in asked[1:])
            lines.append(f"  [{q['target_id']}]")
        sections.append("\n".join(lines))
    if material["beliefs"] or material["reaffirm"]:
        # A belief asked whether it still holds carries the question's id on its
        # own line; one whose belief isn't listed is asked on a line of its own.
        asking = [(_belief_words(q["prompt"]), q) for q in material["reaffirm"]]
        lines = ["What you believe"]
        for b in material["beliefs"]:
            q = next((q for words, q in asking if _asks_of(b["content"], words)), None)
            if q is not None:
                asking = [(words, other) for words, other in asking if other is not q]
            lines.append(f"- {b['content']} (held at {round(b['confidence'] * 100)}%)"
                         + (f" Still true? [{q['target_id']}]" if q else ""))
        lines.extend(f"- Still true? {words or _line(q['prompt'])} [{q['target_id']}]"
                     for words, q in asking)
        sections.append("\n".join(lines))
    if material["new"]:
        sections.append("New since the last dream\n" + "\n".join(
            f"- {q['text']} [{q['target_id']}]" for q in material["new"]))
    if material["rhymes"]:
        sections.append("Side by side\n" + "\n".join(
            f"- now: {pair['now']['text']} [{pair['now']['id']}]\n"
            f"  then, {pair['then']['kept']}: {pair['then']['text']} [{pair['then']['id']}]"
            for pair in material["rhymes"]))
    if not sections:
        sections.append("Nothing.")
    return words + "\n\n---\n\n" + "\n\n".join(sections)


def _prepare(kind, store, since, scope, model, agent_id, records):
    """An hour's prompt, what was waiting for it, why it would skip (``""`` when
    it wouldn't), and the questions a dream is given (``[]`` for the others)."""
    if kind == "dream":
        material = _dream_material(store, since, scope, model, _said_in_dreams(records))
        waiting = {key: len(material[key]) for key in ("fading", "facts", "returning", "reaffirm", "new", "rhymes")}
        waiting["questions"] = (waiting["fading"] + waiting["facts"] + waiting["returning"]
                                + waiting["reaffirm"] + waiting["new"])
        skip = "" if waiting["questions"] or waiting["rhymes"] else (
            f"Nothing to dream over: no question waits, and nothing new since {_minute(since)}."
        )
        said = [q["id"] for key in ("fading", "facts", "returning", "reaffirm", "new") for q in material[key]]
        return _dream_prompt(agent_id, material), waiting, skip, said
    handoffs, captures, questions, latest = _gather(kind, store, since, scope, model)
    waiting = {"handoffs": len(handoffs), "captures": len(captures), "questions": len(questions)}
    skip = (f"No handoffs or captures since {_minute(since)}."
            if kind == "ours" and not handoffs and not captures else "")
    return _prompt(kind, agent_id, since, handoffs, captures, questions, latest), waiting, skip, []


def _there(path) -> bool:
    """Whether ``path`` exists for this process. A scheduled hour on macOS may
    not look inside ~/Documents (launchd jobs get no access to it), and
    there a folder it can't see isn't there, rather than an error that ends
    the hour."""
    try:
        return path.exists()
    except OSError:
        return False


def _life_config() -> dict:
    """The ``life`` section of Mnemos's config, read as ``embeddings.provider``
    is (``~/.mnemos/config.json`` under the HOME the hour runs with), or an
    empty one when there is none or it can't be read."""
    try:
        from .config.loader import load_config

        section = load_config().get("life")
    except Exception:
        return {}
    return section if isinstance(section, dict) else {}


def read_dirs() -> list[Path]:
    """The folders an hour may read besides its studio: ``life.read_dirs`` in
    Mnemos's config, a list of folders, each relative to HOME or absolute.
    None unless the config names them. Until 2026-10-20 the two folders
    Riley's hours read were named in this file, so an hour on anyone's machine
    could read that person's folders of the same names. A folder that isn't
    there for this process is left out (``_there``), and an entry that isn't a
    folder's name names none."""
    named = _life_config().get("read_dirs")
    if not isinstance(named, list):
        return []
    folders: list[Path] = []
    for name in named:
        if not isinstance(name, str) or not name:
            continue
        try:
            path = Path(os.path.normpath(Path.home() / Path(name).expanduser()))
        except RuntimeError:  # ~someone, whose home can't be found
            continue
        if path not in folders and _there(path):
            folders.append(path)
    return folders


def _above_zero(value, *, whole: bool):
    """``value`` as a number above zero, a whole one when ``whole``, or None."""
    if isinstance(value, bool):
        return None
    try:
        if not whole:
            number = float(value)
            if not math.isfinite(number):
                return None
        elif isinstance(value, float):
            number = int(value) if value.is_integer() else 0
        else:
            number = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if number > 0 else None


def budget(kind, *, max_minutes=None, max_tokens=None, max_seconds=None) -> tuple[float, int, str]:
    """What one hour may spend: ``(seconds, tokens, "")``, or with the third
    saying why no hour can run.

    Each comes from the first of these that sets it: what the caller passes
    (``mnemos life --max-minutes``, ``--max-tokens``); a host app's budget for
    the one hour it runs, MNEMOS_HOUR_MINUTES and MNEMOS_HOUR_TOKEN_CEILING;
    Mnemos's config, ``life.minutes.<kind>`` and ``life.token_ceiling.<kind>``;
    DEFAULT_MINUTES and DEFAULT_TOKEN_CEILING. A host app gives a new mind a
    gentler cap this way, and the defaults stay as they were. A setting that
    isn't a number above zero (a whole one, for tokens) runs no hour, rather
    than one on a budget nobody chose."""
    config = _life_config()
    wrong: list[str] = []

    def first(passed, setting, key, default, unit, whole):
        if passed is not None:
            return passed
        value, where = os.environ.get(setting, "").strip(), setting
        if not value:
            section = config.get(key)
            value = section.get(kind) if isinstance(section, dict) else None
            where = f"life.{key}.{kind} in Mnemos's config"
            if value is None:
                return default
        number = _above_zero(value, whole=whole)
        if number is None:
            wrong.append(f"{where} needs {unit} above zero, not {value!r}.")
            return default
        return number

    if max_seconds is None:
        max_seconds = first(max_minutes, MINUTES_SETTING, "minutes", DEFAULT_MINUTES[kind],
                            "a number of minutes", False) * 60
    max_tokens = first(max_tokens, TOKEN_CEILING_SETTING, "token_ceiling",
                       DEFAULT_TOKEN_CEILING[kind], "a whole number of tokens", True)
    return max_seconds, max_tokens, " ".join(wrong)


def _studio_settings(studio: Path) -> list[Path]:
    """The Claude Code settings files in the studio (``STUDIO_SETTINGS``), or
    its ``.claude`` itself when that is a link: what it points at (the
    person's own ``~/.claude``, say) is never touched, only the link."""
    claude = studio / ".claude"
    if claude.is_symlink():
        return [claude]
    return [studio / name for name in STUDIO_SETTINGS if os.path.lexists(studio / name)]


def _set_aside(studio: Path, folder: Path):
    """Move the studio's Claude Code settings, if any, into the hour's own
    folder (``folder/set-aside``) before the hour starts, yielding where each
    was once it has moved. A file the agent wrote there in an hour, or that
    came by any other way, would otherwise configure the next one: its hooks
    run outside the sandbox. A link moves as the link."""
    for path in _studio_settings(studio):
        target = folder / "set-aside" / path.name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(path), str(target))
        yield str(path)


def _files_and_command(kind, hour_id, folder, store, scope, claude_bin, mnemos_bin, model=HOUR_MODEL,
                       runner="claude-code", config_dir=None):
    folders = read_dirs()
    mcp = {"mcpServers": {"mnemos": {
        "type": "stdio", "command": mnemos_bin,
        "args": ["--db-path", str(store), "--agent-id", scope["agent_id"],
                 "--person-id", scope["person_id"], "--project-scope", scope["project_scope"], "serve"],
        "env": {"MNEMOS_HOUR_ID": hour_id},
    }}}
    if runner == "codex":
        from . import codex_dream

        mcp["mcpServers"]["mnemos"]["env"]["MNEMOS_SHARED_MEMORY"] = "off"
        return mcp, codex_dream.model_catalog(model, config_dir), codex_dream.command(claude_bin, model, folder, mcp, config_dir)
    from .setup import scheduler

    deny = []
    for directory in folders:
        deny.append(f"Edit(/{directory}/**)")
    # Nor may the agent write Claude Code's settings where an hour could find
    # them: in its studio, or a folder it reads. Claude Code holds every tool
    # that writes a file to the Edit rules.
    for directory in (studio_dir(scope["agent_id"]), *folders):
        deny.append(f"Edit(/{directory}/.claude/**)")
    # The secrets in the home the hour runs with, and in the account's own
    # when that is another: a host app runs an hour with a HOME of its own.
    homes = [Path.home()]
    account = scheduler.account_home()
    if os.path.normpath(account) != os.path.normpath(homes[0]):
        homes.append(account)
    for name in SECRET_PATHS:
        for home in homes:
            path = home / name
            deny.extend([f"Read(/{path})", f"Read(/{path}/**)"])
    deny.extend(["Read(//**/.env)", "Read(//**/.env.*)"])
    if kind == "mine":
        deny.extend(BASH_DENY)
    if kind == "dream":
        deny.extend(DREAM_DENY)
    # A dream wakes light (who it's with, how they work, where it was), and so
    # spends nothing a session would: a reply of the person's, a note waiting
    # for them, a question's turn.
    hook = shlex.join([
        mnemos_bin, "hook", "session-start", "--agent-id", scope["agent_id"],
        "--person-id", scope["person_id"], "--project-scope", scope["project_scope"],
        "--db-path", str(store), *(["--wake", "light"] if kind == "dream" else []),
    ])
    settings = {
        "hooks": {"SessionStart": [{"matcher": "*", "hooks": [{
            "type": "command", "command": hook, "timeout": 15,
        }]}]},
        "permissions": {"defaultMode": "acceptEdits", "allow": list(ALLOW[kind]), "deny": deny},
        "sandbox": {"enabled": True, "autoAllowBashIfSandboxed": True,
                    "allowUnsandboxedCommands": False},
    }
    # The hour loads none of the person's own Claude Code settings (their user
    # and local settings, whose hooks, another Mnemos's among them, would run
    # in the agent's hour): only its studio's, this file and its own MCP
    # config, as Mnemos's model does (mnemos/llm.py). The wake still comes
    # from Mnemos's own hook, in this file.
    cmd = [claude_bin, "--model", model, "--restricted",
           "--tools", TOOLS[kind],
           "--setting-sources", "project",
           "--strict-mcp-config", "--mcp-config", str(folder / "mcp.json"),
           "--settings", str(folder / "settings.json"),
           "--permission-mode", "acceptEdits", "--permission-prompts", "none",
           "--output-format", "stream-json", "--verbose",
           "--no-session-persistence", "-p"]
    for directory in folders if kind != "dream" else []:
        cmd += ["--add-dir", str(directory)]
    return mcp, settings, cmd


def _tokens(usages):
    return {name: sum(usage.get(field, 0) for usage in usages) for name, field in (
        ("input", "input_tokens"), ("output", "output_tokens"),
        ("cache_creation", "cache_creation_input_tokens"), ("cache_read", "cache_read_input_tokens"),
    )}


def _watch(cmd, studio, env, folder, prompt, max_seconds, max_tokens, hour=HOUR_MODEL,
           runner="claude-code"):
    from .codex_dream import Events

    codex = Events() if runner == "codex" else None
    usage_by_id = {}
    result = None
    model = hour if codex else ""
    seen_model = None
    last_synthetic = ""
    stopped = []
    stop_lock = threading.Lock()
    with (folder / "stderr.txt").open("w") as stderr, (folder / "stream.jsonl").open("w") as stream:
        proc = subprocess.Popen(cmd, cwd=studio, env=env, stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=stderr, text=True, bufsize=1,
                                start_new_session=True)

        def stop(cause):
            with stop_lock:
                if stopped:
                    return
                stopped.append(cause)
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                return
            try:
                proc.wait(timeout=STOP_GRACE_SECONDS)
            except subprocess.TimeoutExpired:
                pass
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

        timer = threading.Timer(max_seconds, lambda: stop("time"))
        timer.start()
        try:
            try:
                proc.stdin.write(prompt)
                proc.stdin.close()
            except BrokenPipeError:
                pass
            for raw in proc.stdout:
                stream.write(raw)
                stream.flush()
                try:
                    event = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if codex:
                    event = codex.accept(event)
                    if codex.forbidden:
                        stop("guard")
                    if event is None:
                        continue
                if event.get("type") == "system" and event.get("subtype") == "init":
                    model = event.get("model") or ""
                    if isinstance(model, str) and model and model not in (hour, "<synthetic>"):
                        seen_model = model
                        stop("guard")
                elif event.get("type") == "assistant":
                    message = event.get("message") or {}
                    message_model = message.get("model")
                    if message_model == "<synthetic>":
                        for block in message.get("content") or []:
                            if block.get("type") == "text":
                                last_synthetic = block.get("text") or ""
                                break
                        continue
                    if (isinstance(message_model, str) and message_model
                            and message_model != hour):
                        seen_model = message_model
                        stop("guard")
                    usage_key = message.get("id") or event.get("uuid")
                    if usage_key:
                        usage_by_id[usage_key] = message.get("usage") or {}
                    running = sum(u.get("input_tokens", 0) + u.get("cache_creation_input_tokens", 0)
                                  + u.get("output_tokens", 0) for u in usage_by_id.values())
                    if running > max_tokens:
                        stop("tokens")
                elif event.get("type") == "result":
                    result = event
                    if codex:
                        used = event.get("usage") or {}
                        if used.get("input_tokens", 0) + used.get("output_tokens", 0) > max_tokens:
                            stop("tokens")
            rc = proc.wait()
        finally:
            if proc.poll() is None:
                stop("error")
                proc.wait()
            timer.cancel()
            timer.join()
            proc.stdout.close()
    tokens = _tokens([result.get("usage", {})] if result is not None else list(usage_by_id.values()))
    cause = stopped[0] if stopped else ""
    if codex and codex.forbidden:
        status, reason = "failed", f"Codex attempted a non-memory action: {codex.forbidden}."
    elif seen_model is not None:
        status, reason = "skipped", (
            f"The hour ran as {seen_model}, not {hour}, so nothing it wrote was kept."
        )
    elif cause == "tokens":
        status, reason = "done", f"Stopped at the token ceiling ({max_tokens:,})."
    elif cause == "time":
        status, reason = "done", f"Stopped at the time limit ({max_seconds / 60:g} minutes)."
    elif codex and rc != 0:
        status, reason = "failed", f"codex exited with code {rc}: " + (folder / "stderr.txt").read_text()[-400:].strip()
    elif result is not None and result.get("is_error"):
        status, reason = "failed", "The session ended with an error: " + _line(str(result.get("result", "")))
    elif result is not None:
        status, reason = "done", ""
    elif rc != 0:
        status, reason = "failed", f"claude exited with code {rc}: " + (folder / "stderr.txt").read_text()[-400:].strip()
    else:
        status, reason = "failed", "codex ended without a result." if codex else "claude ended without a result."
    if status == "done" and not reason and last_synthetic:
        reason = "Claude Code said: " + _line(last_synthetic)
    return {
        "model": model, "status": status, "reason": reason, "tokens": tokens,
        "session_id": result.get("session_id", "") if result is not None else "",
    }, seen_model is not None or bool(codex and codex.forbidden)


def _answered(store, ids) -> list[str]:
    """Which of these questions have an answer now."""
    if not ids:
        return []
    marks = ", ".join("?" for _ in ids)
    return [row[0] for row in store._get_conn().execute(
        f"SELECT id FROM reflection_queue WHERE id IN ({marks}) AND answered_at IS NOT NULL", list(ids),
    ).fetchall()]


def _hand_off(kind, *, resolved, scope, live, hours, dry_run, out, model=None) -> dict:
    """An hour handed to the agent: the prompt the hour would get, printed to
    ``out`` for the agent to take in its own session, and recorded like any
    hour (a done hour on the live store) so the next one's material moves on
    and the same material can't be handed twice. Nothing is run, nothing is
    written to memory, and the store is not touched."""
    records_path = hours / "hours.jsonl"
    studio = studio_dir(resolved.agent_id)

    def fenced(prompt):
        fence = HANDOFF_FENCE.format(kept=HANDOFF_KEPT[kind], studio=studio)
        return fence + "\n\n---\n\n" + prompt

    if dry_run:
        if not live.exists():
            return {"status": "failed", "reason": f"There is no memory store at {live}."}
        records = _records(records_path)
        since = since_for(kind, records)
        model = hand_off_model(live, scope, model)
        prompt, waiting, skip, said = _prepare(kind, live, since, scope, model, resolved.agent_id, records)
        print(f"Dry run · {kind} hour · hand-off · nothing recorded", file=out)
        print(f"Store: {live}", file=out)
        print(f"Since: {_minute(since)}", file=out)
        if skip:
            print("The hour would skip: " + skip, file=out)
        print("\n── prompt ──\n" + fenced(prompt), file=out)
        return {"dry_run": True, "kind": kind, "skip": skip, "prompt": fenced(prompt), "waiting": waiting}

    hour_id = _gen_ulid()
    record = {
        "id": hour_id, "kind": kind, "started_at": datetime.now(timezone.utc).isoformat(),
        "ended_at": "", "model": "", "status": "", "reason": "", "tokens": None,
        "journal_ids": [], "note_ids": [], "store": "live", "session_id": "", "since": "",
        "waiting": {"handoffs": 0, "captures": 0, "questions": 0}, "discarded_ids": [],
        "handoff": True,
    }
    hours.mkdir(parents=True, exist_ok=True)
    with (hours / ".lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            record.update(status="skipped", reason="Another hour is running.")
            return record
        try:
            records = _records(records_path)
            since = since_for(kind, records)
            record["since"] = since
            if not live.exists():
                record.update(status="failed", reason=f"There is no memory store at {live}.")
                return record
            model = hand_off_model(live, scope, model)
            record["model"] = model
            prompt, waiting, skip, said = _prepare(kind, live, since, scope, model, resolved.agent_id, records)
            record["waiting"] = waiting
            if kind == "dream":
                record["said"] = said
            if skip:
                record.update(status="skipped", reason=skip)
                return record
            # Handed only once it has been written out: an hour whose prompt
            # never left (a closed pipe) hands nothing and moves nothing on.
            out.write(fenced(prompt) + "\n")
            out.flush()
            record.update(status="done", reason="Handed to the agent to take in its own session.")
            return record
        except Exception as exc:
            record.update(status="failed", reason=(
                f"The hand-off hit an error: {type(exc).__name__}: {_line(str(exc))}"
            ))
            return record
        finally:
            if not record["since"]:
                record["since"] = since_for(kind, _records(records_path))
            record["ended_at"] = datetime.now(timezone.utc).isoformat()
            with records_path.open("a") as output:
                output.write(json.dumps(record, ensure_ascii=False) + "\n")
            fcntl.flock(lock, fcntl.LOCK_UN)


def run_hour(kind: str, *, db_path: str | None = None, agent_id: str | None = None,
             person_id: str | None = None, project_scope: str | None = None,
             dry_run: bool = False, config_dir: str | None = None, store_copy: bool = False,
             max_minutes: float | None = None, max_tokens: int | None = None,
             max_seconds: float | None = None, out=sys.stdout,
             handoff: bool = False, runner: str = "claude-code", model: str | None = None) -> dict:
    started_at = datetime.now(timezone.utc).isoformat()
    resolved = resolve_scope(db_path=db_path, agent_id=agent_id, person_id=person_id,
                             project_scope=project_scope)
    scope = {"agent_id": resolved.agent_id, "person_id": resolved.person_id,
             "project_scope": resolved.project_scope}
    live = Path(resolved.db_path).expanduser()
    hours = hours_dir(resolved.agent_id)
    records_path = hours / "hours.jsonl"
    if handoff:
        return _hand_off(kind, resolved=resolved, scope=scope, live=live, hours=hours,
                         dry_run=dry_run, out=out, model=model)
    refusal = builtin_refusal(runner, kind)
    if refusal:
        return {"kind": kind, "id": "", "status": "failed", "reason": refusal}
    max_seconds, max_tokens, unbudgeted = budget(
        kind, max_minutes=max_minutes, max_tokens=max_tokens, max_seconds=max_seconds,
    )
    if dry_run:
        if unbudgeted:
            return {"status": "failed", "reason": unbudgeted}
        if not live.exists():
            return {"status": "failed", "reason": f"There is no memory store at {live}."}
        records = _records(records_path)
        since = since_for(kind, records)
        model, why = hour_model(live, scope, runner, model)
        if runner == "codex" and not model:
            return {"status": "failed", "reason": why}
        prompt, waiting, skip, said = _prepare(kind, live, since, scope, model or HOUR_MODEL,
                                               resolved.agent_id, records)
        skip = why or skip
        claude_bin = os.environ.get("MNEMOS_CODEX_BIN" if runner == "codex" else "MNEMOS_CLAUDE_BIN") or shutil.which("codex" if runner == "codex" else "claude")
        mnemos_bin = os.environ.get("MNEMOS_LIFE_MNEMOS_BIN") or shutil.which("mnemos")
        if not claude_bin or not mnemos_bin:
            return {"status": "failed", "reason": f"The {'codex' if runner == 'codex' else 'claude'} command wasn't found." if not claude_bin else "The mnemos command wasn't found."}
        folder = hours / "dry-run"
        store = folder / "store.db" if store_copy else live
        try:
            mcp, settings, cmd = _files_and_command(kind, "dry-run", folder, store, scope, claude_bin, mnemos_bin,
                                                    model or HOUR_MODEL, runner, config_dir)
        except (OSError, ValueError, RuntimeError) as exc:
            return {"status": "failed", "reason": str(exc)}
        print(f"Dry run · {kind} hour · nothing will run", file=out)
        print(f"Model: {model or '(none: ' + why + ')'}", file=out)
        print(f"Store: {live} ({'a copy would be used' if store_copy else 'live'})", file=out)
        print(f"Since: {_minute(since)}", file=out)
        if skip:
            print("The hour would skip: " + skip, file=out)
        if runner == "codex":
            from .codex_dream import PREAMBLE

            prompt = PREAMBLE + prompt
        else:
            for path in _studio_settings(studio_dir(resolved.agent_id)):
                print(f"Set aside before the hour, into its folder: {path}", file=out)
        print("\n── prompt (stdin) ──\n" + prompt, file=out)
        print("\n── command ──\n" + shlex.join(cmd), file=out)
        print("\n── mcp.json ──\n" + json.dumps(mcp, indent=2), file=out)
        settings_name = "model-catalog.json" if runner == "codex" else "settings.json"
        print(f"\n── {settings_name} ──\n" + json.dumps(settings, indent=2), file=out)
        return {"dry_run": True, "kind": kind, "skip": skip, "prompt": prompt, "waiting": waiting}

    hour_id = _gen_ulid()
    folder = hours / hour_id
    record = {
        "id": hour_id, "kind": kind, "started_at": started_at, "ended_at": "", "model": "",
        "status": "", "reason": "", "tokens": None, "journal_ids": [], "note_ids": [],
        "store": "copy" if store_copy else "live", "session_id": "", "since": "",
        "waiting": {"handoffs": 0, "captures": 0, "questions": 0}, "discarded_ids": [],
    }
    if store_copy:
        record["live_store_untouched"] = None
    hours.mkdir(parents=True, exist_ok=True)
    launched = False
    store = live
    with (hours / ".lock").open("a") as lock:
        locked = False
        try:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                locked = True
            except BlockingIOError:
                record.update(status="skipped", reason="Another hour is running.")
                return record
            records = _records(records_path)
            since = since_for(kind, records)
            record["since"] = since
            if unbudgeted:
                record.update(status="failed", reason=unbudgeted)
                return record
            if not live.exists():
                record.update(status="failed", reason=f"There is no memory store at {live}.")
                return record
            if store_copy:
                folder.mkdir()
                store = folder / "store.db"
                src = sqlite3.connect(f"file:{live}?mode=ro", uri=True)
                dst = sqlite3.connect(store)
                try:
                    src.backup(dst)
                    integrity = dst.execute("PRAGMA integrity_check").fetchone()[0]
                finally:
                    dst.close()
                    src.close()
                if integrity != "ok":
                    record.update(status="failed", reason="The store copy failed its integrity check.")
                    return record
            model, why = hour_model(store, scope, runner, model)
            if not model:
                record.update(status="failed" if runner == "codex" else "skipped", reason=why)
                return record
            record["model"] = model
            if runner == "codex":
                record["runner"] = runner
                record["model_verified"] = False
            prompt, waiting, skip, said = _prepare(kind, store, since, scope, model, resolved.agent_id, records)
            record["waiting"] = waiting
            if kind == "dream":
                record["said"] = said
            if skip:
                record.update(status="skipped", reason=skip)
                return record
            claude_bin = os.environ.get("MNEMOS_CODEX_BIN" if runner == "codex" else "MNEMOS_CLAUDE_BIN") or shutil.which("codex" if runner == "codex" else "claude")
            mnemos_bin = os.environ.get("MNEMOS_LIFE_MNEMOS_BIN") or shutil.which("mnemos")
            if not claude_bin or not mnemos_bin:
                record.update(status="failed", reason=f"The {'codex' if runner == 'codex' else 'claude'} command wasn't found." if not claude_bin else "The mnemos command wasn't found.")
                return record
            folder.mkdir(exist_ok=True)
            mcp, settings, cmd = _files_and_command(kind, hour_id, folder, store, scope, claude_bin, mnemos_bin, model, runner, config_dir)
            if runner == "codex":
                from .codex_dream import PREAMBLE

                prompt = PREAMBLE + prompt
            (folder / "prompt.md").write_text(prompt)
            (folder / "mcp.json").write_text(json.dumps(mcp, indent=2))
            (folder / ("model-catalog.json" if runner == "codex" else "settings.json")).write_text(json.dumps(settings, indent=2))
            studio = studio_dir(resolved.agent_id)
            if runner != "codex":
                (studio / "worktrees").mkdir(parents=True, exist_ok=True)
                # Nothing an hour writes may configure Claude Code for its next run.
                for path in _set_aside(studio, folder):
                    record.setdefault("set_aside", []).append(path)
            env = dict(os.environ)
            if runner == "codex":
                # A CLI launched from an app/session must not inherit its tool bridge.
                from .codex_dream import environment

                env = environment(env)
            env["MNEMOS_HOUR_ID"] = hour_id
            if config_dir is not None:
                env["CODEX_HOME" if runner == "codex" else "CLAUDE_CONFIG_DIR"] = str(Path(config_dir).expanduser())
            # An hour is the agent living: the day counts on its own clock, in
            # the store the hour uses.
            try:
                marker = EngramStore(store)
                try:
                    marker.mark_lived(resolved.agent_id)
                finally:
                    marker.close()
            except Exception:
                pass
            outcome, guarded = _watch(cmd, folder if runner == "codex" else studio, env, folder, prompt,
                                      max_seconds, max_tokens, model, runner=runner)
            launched = True
            record.update(outcome)
            if guarded:
                writer = EngramStore(store)
                try:
                    record["discarded_ids"] = writer.discard_hour_rows(hour_id, **scope)
                finally:
                    writer.close()
            else:
                reader = ReadOnlyEngramStore(store)
                try:
                    record.update(reader.hour_rows(hour_id, **scope))
                    if kind == "dream":
                        record["answered"] = _answered(reader, said)
                finally:
                    reader.close()
            return record
        except Exception as exc:
            record.update(status="failed", reason=(
                f"The runner hit an error: {type(exc).__name__}: {_line(str(exc))}"
            ))
            return record
        finally:
            if not record["since"]:
                record["since"] = since_for(kind, _records(records_path))
            if store_copy:
                if launched:
                    try:
                        reader = ReadOnlyEngramStore(live)
                        try:
                            live_rows = reader.hour_rows(hour_id, **scope)
                        finally:
                            reader.close()
                        record["live_store_untouched"] = not live_rows["journal_ids"] and not live_rows["note_ids"]
                    except Exception:
                        pass
                if not launched and store != live:
                    store.unlink(missing_ok=True)
            record["ended_at"] = datetime.now(timezone.utc).isoformat()
            with records_path.open("a") as output:
                output.write(json.dumps(record, ensure_ascii=False) + "\n")
            if locked:
                fcntl.flock(lock, fcntl.LOCK_UN)
