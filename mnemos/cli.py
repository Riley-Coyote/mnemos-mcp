"""
CLI entry point for Mnemos.

Commands:
    mnemos init                  Initialize a new memory database
    mnemos serve                 Start MCP server (stdio mode)
    mnemos inspect ID            Inspect a specific engram
    mnemos stats                 Show memory statistics
    mnemos snapshot              Print an inline Mermaid memory snapshot
    mnemos search QUERY          Search memories, by meaning and words (writes nothing)
    mnemos memories              List the memories, oldest first (reads only)
    mnemos correct ID TEXT       Correct a memory, in your own words
    mnemos forget ID             Let a memory go: archived, never deleted
    mnemos interface             The commands above for an app, one JSON line each
    mnemos consolidate [--deep]  Run a consolidation cycle
    mnemos export [--workspace]  Export workspace files (MEMORY.md, etc.)
    mnemos setup-openclaw        Register cron jobs for OpenClaw
    mnemos bootstrap             Bootstrap a complete agent stack
    mnemos identity diff         Diff graph-derived identity against SOUL.md
    mnemos identity accept       Accept a divergence, open a new epoch
    mnemos remember CONTENT      Capture durable continuity from the CLI
    mnemos journal [--last N]    Read the agent's journal
    mnemos notes [--unread]      Read the agent's notes to you
    mnemos notes reply ID TEXT   Reply to one of them, in your own words
    mnemos log [--no-open]       A page to watch the agent's days (read-only, this machine only)
    mnemos hermes install        Install Mnemos for Hermes Agent
    mnemos hermes quickstart     Safely install Mnemos for Hermes Agent
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import shutil
import shlex
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any

from .config.loader import load_config
from .package_version import mnemos_version


# Advanced mode is optional: simple mode, unchanged, plus its own tools. It
# needs no switch to run or install, and says this when it starts or is
# installed.
ADVANCED_MODE_NOTE = (
    "Advanced mode adds tools for inspecting and administering memory, "
    "and it's less tested than simple mode."
)


def _resolve_default_mode() -> str:
    """Resolve the default tool surface for ``mnemos serve``.

    Precedence (highest first):
      1. ``MNEMOS_MODE`` environment variable
      2. ``server.mode`` in ~/.mnemos/config.json (also settable via
         ``MNEMOS_SERVER_MODE``)
      3. ``"simple"``

    This lets advanced mode be set persistently in config.json — surviving
    reboot — instead of only via a volatile env var or a per-client --mode flag.
    """
    env_mode = os.environ.get("MNEMOS_MODE")
    if env_mode:
        return env_mode
    try:
        return load_config().get("server", {}).get("mode", "simple")
    except Exception:
        return "simple"


# The scope options, defined once. The main parser gives each a default of
# None. A command that takes them after it as well adds them with SUPPRESS:
# argparse copies every default a subcommand sets over what the main parser
# has already read, so a default there threw away the value given before the
# command (`mnemos --db-path X --agent-id Y hook session-start` read the
# default store and contributed nothing). With SUPPRESS a value given after
# the command wins, one given before it survives, and one given nowhere stays
# None for resolve_scope.
_SCOPE_OPTIONS = {
    "--db-path": "Database path",
    "--agent-id": "Agent identity",
    "--person-id": "Person/user scope",
    "--project-scope": "Project/workspace scope",
}


def _scope_options(
    parser: argparse.ArgumentParser,
    *flags: str,
    top_level: bool = False,
    helps: dict[str, str] | None = None,
) -> None:
    """Add the scope options ``flags`` to ``parser`` (all four when none are
    named), with ``helps`` replacing the help of any of them."""
    for flag in flags or tuple(_SCOPE_OPTIONS):
        parser.add_argument(
            flag,
            default=None if top_level else argparse.SUPPRESS,
            help=(helps or {}).get(flag, _SCOPE_OPTIONS[flag]),
        )


def _clock(text: str) -> tuple[int, int]:
    """A time of day, HH:MM on the 24-hour clock, as (hour, minute)."""
    hour, colon, minute = text.strip().partition(":")
    try:
        if colon and len(minute) == 2 and 0 <= int(hour) <= 23 and 0 <= int(minute) <= 59:
            return int(hour), int(minute)
    except ValueError:
        pass
    raise argparse.ArgumentTypeError(f"{text!r} is not a time like 08:00 or 19:30")


def main(argv: list[str] | None = None) -> int:
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="mnemos",
        description="Mnemos: Living Memory Architecture for Autonomous AI Agents",
    )
    parser.add_argument(
        "--version", action="version", version=f"mnemos {mnemos_version()}"
    )
    _scope_options(parser, top_level=True, helps={
        "--db-path": "Path to the SQLite database (default: ~/.mnemos/<agent>.db)",
        "--agent-id": "Agent identifier (default: env, then config, then mnemos-agent)",
    })

    sub = parser.add_subparsers(dest="command", help="Available commands")

    # ── init ──
    sub.add_parser("init", help="Initialize a new memory database")

    # ── serve ──
    p_serve = sub.add_parser("serve", help="Start MCP server (stdio mode)")
    p_serve.add_argument(
        "--mode",
        choices=("simple", "advanced"),
        default=_resolve_default_mode(),
        help="MCP tool surface to expose: 'simple' (default) or 'advanced'. "
             "Persist a machine-wide default via server.mode in "
             "~/.mnemos/config.json (or the MNEMOS_MODE env var).",
    )
    _scope_options(p_serve)

    # ── inspect ──
    p_inspect = sub.add_parser("inspect", help="Inspect a specific engram")
    p_inspect.add_argument("engram_id", help="The engram ID to inspect")

    # ── stats ──
    sub.add_parser("stats", help="Show memory statistics")

    # ── snapshot ──
    p_snapshot = sub.add_parser("snapshot", help="Print an inline Mermaid memory snapshot")
    _scope_options(p_snapshot)
    p_snapshot.add_argument("--session-id", default="", help="Optional functional-memory session")
    p_snapshot.add_argument("-n", "--max-items", type=int, default=6)

    # ── search ──
    p_search = sub.add_parser(
        "search", help="Search memories, by meaning and by words (writes nothing)",
        description=(
            "Search the memories as the agent's own recall does, by meaning and by "
            "words, closest first. It only looks: nothing found is woken, "
            "strengthened or linked, and an archived memory never comes back."
        ),
    )
    _scope_options(p_search)
    p_search.add_argument("query", help="Search query")
    p_search.add_argument("-n", "--max-results", type=int, default=10)
    p_search.add_argument(
        "--json", action="store_true",
        help='Print {"query", "results": [{"id", "words", "kept", "closeness", "found"}]}, '
             "closest first; closeness is relative within one search, the first 1.0",
    )

    # ── memories ──
    p_memories = sub.add_parser(
        "memories", help="List the memories, active and dormant, oldest first (reads only)",
    )
    _scope_options(p_memories)
    p_memories.add_argument(
        "--state", default=None, metavar="active|dormant",
        help="Only the active memories, or only the dormant ones",
    )
    p_memories.add_argument("--limit", type=int, default=None, metavar="N",
                            help="At most N memories (default: all)")
    p_memories.add_argument("--offset", type=int, default=0, metavar="M",
                            help="Leave out the first M (default 0)")
    p_memories.add_argument(
        "--json", action="store_true",
        help='Print {"memories": [{"id", "words", "kept", "state", "alive", "conversation", '
             '"corrected", "impact", "author"}], "counts": {"active", "dormant", "archived"}}',
    )

    # ── correct / forget ──
    for name, help_text, description in (
        (
            "correct", "Correct a memory, in your own words (in an agent's shell: the agent's)",
            "Replace a memory's words with yours, by its id. The old version is archived, "
            "never deleted, and the new one keeps what it meant. Run by you, the words are "
            "yours, unsigned, and the agent wakes to the correction once. In an agent's own "
            "shell (CLAUDECODE or AI_AGENT set), or with --signed-as, it is the agent's "
            "correction instead. An id that is archived, or that a correction has replaced, "
            "changes nothing and says so.",
        ),
        (
            "forget", "Let a memory go: archived, never deleted (in an agent's shell: the agent's)",
            "Let a memory go, by its id: it and its note are archived, never deleted, and "
            "recall never brings it back. Run by you, the agent's next wake says that you "
            "let a memory go, and when, never its words. In an agent's own shell "
            "(CLAUDECODE or AI_AGENT set), or with --signed-as, it is the agent's forget "
            "instead. An id that is archived, or that a correction has replaced, changes "
            "nothing and says so.",
        ),
    ):
        p_change = sub.add_parser(name, help=help_text, description=description)
        _scope_options(p_change)
        p_change.add_argument("memory_id", metavar="ID", help="The memory's id")
        if name == "correct":
            p_change.add_argument("text", metavar="TEXT", help="Its new words")
        p_change.add_argument(
            "--json", action="store_true",
            help='Print {"id": <new>, "replaces": <old>, "corrected": <time>}' if name == "correct"
            else 'Print {"id", "state": "archived", "forgotten": <time>}',
        )
        p_change.add_argument(
            "--signed-as", default="", metavar="MODEL",
            help="Do it as the agent, signed with this model id",
        )

    # ── interface ──
    p_interface = sub.add_parser(
        "interface", help="Answer the person's commands for an app: one JSON line each, on stdin",
        description=(
            "One long-lived process for an app the person uses. Each line on stdin is one "
            'request, {"id": ..., "command": ..., ...}, for memories, search, correct, '
            "forget, journal, notes or reply; each answer is one line on stdout, "
            '{"id": ..., "result": ...} with what the one-shot --json command prints, or '
            '{"id": ..., "error": "<one sentence>"}. The meaning model loads once, in the '
            "background, as it starts. It ends when stdin closes."
        ),
    )
    _scope_options(p_interface)

    # ── consolidate ──
    p_cons = sub.add_parser("consolidate", help="Run a consolidation cycle")
    p_cons.add_argument("--deep", action="store_true", help="Run deep cycle")

    # ── export ──
    p_export = sub.add_parser("export", help="Export workspace files")
    p_export.add_argument(
        "--workspace", default=".", help="Output directory (default: current dir)"
    )

    # ── setup-openclaw ──
    p_setup = sub.add_parser("setup-openclaw", help="Register OpenClaw cron jobs")
    p_setup.add_argument("--agent", default="main", help="OpenClaw agent ID")
    p_setup.add_argument("--dry-run", action="store_true", help="Show what would be registered")

    # ── index (retired) ──
    p_index = sub.add_parser("index", help="Retired: the transcript indexer (says why)")
    # Accepted so old instructions reach the reason rather than a usage error.
    p_index.add_argument("--backfill", action="store_true", help=argparse.SUPPRESS)

    # ── bootstrap ──
    p_bootstrap = sub.add_parser("bootstrap", help="Bootstrap a turnkey memory stack")
    p_bootstrap.add_argument("--agent-name", required=True, help="Agent name (e.g., Nova)")
    p_bootstrap.add_argument("--workspace", required=True, help="Workspace directory path")
    p_bootstrap.add_argument("--user-name", default="User", help="User name (default: User)")
    p_bootstrap.add_argument("--timezone", default="America/New_York", help="Timezone for crons")
    p_bootstrap.add_argument("--api-key", default="", help="Optional LLM provider API key")
    p_bootstrap.add_argument("--llm-provider", default="openrouter", help="LLM provider")
    p_bootstrap.add_argument("--model", default="anthropic/claude-sonnet-4-5", help="Memory model")

    # ── bridge ──
    p_bridge = sub.add_parser("bridge", help="Direct memory operations")
    bridge_sub = p_bridge.add_subparsers(dest="bridge_command")
    bridge_sub.add_parser("status", help="Quick memory status")
    p_br_recall = bridge_sub.add_parser("recall", help="Retrieve memories")
    p_br_recall.add_argument("query", help="Search query")
    p_br_remember = bridge_sub.add_parser("remember", help="Encode a memory")
    p_br_remember.add_argument("content", help="Memory content")
    p_br_remember.add_argument("--impact", default="", help="What it meant")

    # ── remember ──
    p_remember = sub.add_parser(
        "remember", help="Keep something in your own words (in an agent's shell: the agent's)",
        description=(
            "Keep something in the agent's memory, in your own words: unsigned, shown "
            "to the agent once at its next wake, and marked as yours when it recalls "
            "it. In an agent's own shell (Claude Code's, which sets CLAUDECODE, or one "
            "that sets AI_AGENT), or with --signed-as, it keeps the agent's words "
            "instead. To write as yourself, run it in your own terminal."
        ),
    )
    p_remember.add_argument("content", help="What to remember")
    p_remember.add_argument("--context", default="", help="Where/why this came up")
    p_remember.add_argument(
        "--impact", default="",
        help="What this changed in how you understand things — the lesson, not the event",
    )
    p_remember.add_argument(
        "--importance", default="auto", help="auto, or a number from 0.0 to 1.0"
    )
    p_remember.add_argument(
        "--signed-as", default="", metavar="MODEL",
        help="Keep these as the agent's own words, signed with this model id",
    )
    _scope_options(p_remember)

    # ── journal ──
    p_journal = sub.add_parser(
        "journal", help="Read the agent's journal (the agent writes it; this only reads)",
    )
    _scope_options(p_journal)
    p_journal.add_argument(
        "--last", type=int, default=5, metavar="N",
        help="How many of the newest entries to read (default 5)",
    )
    p_journal.add_argument(
        "--json", action="store_true",
        help='Print the entries as JSON: [{"id", "text", "mood", "written", "model", "created_at"}]',
    )

    p_life = sub.add_parser("life", help="Run one quiet hour between sessions (the agent's own, or the day's work)")
    _scope_options(p_life)
    p_life.add_argument("--hour", choices=["mine", "ours"], required=True,
                        help="mine: the agent's own hour; ours: the day's work")
    p_life.add_argument("--dry-run", action="store_true",
                        help="Print what would be gathered and run, and run nothing")
    p_life.add_argument("--config-dir",
                        help="Which Claude login pays, e.g. ~/.claude-2 (sets CLAUDE_CONFIG_DIR for the hour)")
    p_life.add_argument("--store-copy", action="store_true",
                        help="Run the hour on a copy of the store; the live store is not touched")
    p_life.add_argument("--max-minutes", type=float)
    p_life.add_argument("--max-tokens", type=int)

    # ── notes ──
    p_notes = sub.add_parser(
        "notes", help="The notes the agent leaves you, and your replies",
        description=(
            "Read the notes the agent left you, newest first. Reading them marks the "
            "agent's notes as read; --json only reads. `notes reply ID TEXT` answers "
            "one in your own words, and the agent wakes with your reply."
        ),
    )
    _scope_options(p_notes)
    p_notes.add_argument(
        "--unread", action="store_true", help="Only the agent's notes you have not read",
    )
    p_notes.add_argument(
        "--json", action="store_true",
        help='Print the notes as JSON: [{"id", "kind", "text", "author", "model", '
             '"in_reply_to", "created_at", "read_at"}]',
    )
    notes_sub = p_notes.add_subparsers(dest="notes_command")
    p_notes_reply = notes_sub.add_parser(
        "reply", help="Reply to one of the agent's notes, in your own words",
    )
    _scope_options(p_notes_reply)
    p_notes_reply.add_argument("note_id", help="The id of the note you are answering")
    p_notes_reply.add_argument("text", nargs="+", help="Your reply, in your own words")

    # ── log ──
    p_log = sub.add_parser(
        "log", help="A page to watch the agent's days: its quiet hours, journal, notes and memory",
        description=(
            "Open the log: a small page, in your browser, of what the agent does on "
            "its own and what it keeps (its quiet hours, journal, the notes it leaves "
            "you, what its memory asks it, its beliefs, every memory). It reads the "
            "memory and never writes it, and it is served on 127.0.0.1 only, so "
            "nothing leaves this machine. Ctrl-C stops it."
        ),
    )
    _scope_options(p_log)
    p_log.add_argument(
        "--person-name", default=None,
        help="Your name, so the page can say it (default: MNEMOS_PERSON_NAME; without one it says \"you\")",
    )
    p_log.add_argument(
        "--no-open", action="store_true", help="Print the page's address without opening a browser",
    )

    # ── doctor ──
    p_doctor = sub.add_parser("doctor", help="Check Mnemos simple-mode readiness")
    _scope_options(p_doctor)

    # ── repair-softening ──
    p_repair = sub.add_parser(
        "repair-softening",
        help="Restore memories truncated by an earlier version's softening",
    )
    _scope_options(p_repair)
    p_repair.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would be restored without writing",
    )

    # ── adopt-legacy ──
    p_adopt = sub.add_parser(
        "adopt-legacy",
        help="Bring back memories the scope migration left unreachable "
             "(dry run unless --write)",
    )
    # Whether the target person was named is part of the safety check, so a
    # flag given before the subcommand must survive and an absent one must
    # stay absent (None).
    _scope_options(p_adopt, helps={
        "--person-id": "Target person scope",
        "--project-scope": "Target project scope",
    })
    p_adopt.add_argument(
        "--include",
        default="lessons,other",
        help="Comma-separated kinds to bring back: lessons, other, indexer "
             "(default: lessons,other)",
    )
    p_adopt.add_argument(
        "--write",
        action="store_true",
        help="Apply the change instead of printing what it would do",
    )

    # ── repair-lessons ──
    p_repair = sub.add_parser(
        "repair-lessons",
        help="Remove lesson links filed on a shared word or a placeholder "
             "(dry run unless --write)",
    )
    _scope_options(p_repair)
    p_repair.add_argument(
        "--write",
        action="store_true",
        help="Remove them instead of printing what would go",
    )

    # ── repair-versions ──
    p_repair = sub.add_parser(
        "repair-versions",
        help="Remove version rows that only repeat the one before them "
             "(dry run unless --write)",
    )
    _scope_options(p_repair)
    p_repair.add_argument(
        "--write",
        action="store_true",
        help="Remove them instead of printing what would go",
    )

    # ── repair <what> ──
    p_repair_group = sub.add_parser(
        "repair", help="Guarded repairs of a store (dry run unless --write)"
    )
    repair_sub = p_repair_group.add_subparsers(dest="repair_command")
    p_min_code = repair_sub.add_parser(
        "min-code-version",
        help="Show the lowest code version allowed to maintain this store, "
             "or change it with --set N --write",
    )
    _scope_options(p_min_code)
    p_min_code.add_argument(
        "--set", dest="set_to", type=int, default=None, metavar="N",
        help="The minimum to set, 1 or more (lower or higher than now)",
    )
    p_min_code.add_argument(
        "--write",
        action="store_true",
        help="Change it instead of printing what would change",
    )
    p_quarantine = repair_sub.add_parser(
        "quarantine-tool-written",
        help="Move the memories a tool wrote (the transcript indexer's and the "
             "substrate's) out of this scope into the legacy quarantine "
             "(dry run unless --write)",
    )
    _scope_options(p_quarantine)
    p_quarantine.add_argument(
        "--undo",
        action="store_true",
        help="Bring back exactly what this moved out of this scope",
    )
    p_quarantine.add_argument(
        "--write",
        action="store_true",
        help="Move them instead of printing what would move",
    )
    p_keyword = repair_sub.add_parser(
        "keyword-contradictions",
        help="Undo the contradiction links and belief revisions the removed "
             "no-model keyword-and-negation check wrote (dry run unless --write)",
    )
    _scope_options(p_keyword)
    p_keyword.add_argument(
        "--write",
        action="store_true",
        help="Undo them instead of printing what would change",
    )
    for name, text, verb in (
        (
            "split-notes",
            "Join again the notes older code left apart from their memories: a "
            "memory corrected through its note takes the note's words, and a note "
            "left over a replaced memory moves to its replacement (dry run unless "
            "--write)",
            "Join them",
        ),
        (
            "archive-rows",
            "Drop the archive rows that only repeat a memory that is no longer "
            "archived; rows whose words differ stay as history (dry run unless --write)",
            "Drop them",
        ),
        (
            "dead-embeddings",
            "Prune stored vectors from embedding models this Mnemos does not use "
            "(dry run unless --write)",
            "Prune them",
        ),
        (
            "placeholder-impacts",
            "Empty the meanings the server wrote itself after a correction or a "
            "promotion, leaving the meaning to the agent (dry run unless --write)",
            "Empty them",
        ),
        (
            "word-questions",
            "Remove the unanswered 'you keep returning to <word>' questions that hold no words of yours; questions you answered or wrote on stay (dry run unless --write)",
            "Remove them",
        ),
        (
            "early-lessons",
            "Fold back the lessons drawn before their memory faded, which repeat its meaning word for word, and the 'this is fading' questions about memories that have not faded (dry run unless --write)",
            "Fold them back",
        ),
        (
            "faded-words",
            "Bring back, from the words they were encoded with, the words of live "
            "memories an earlier softening cut to '... [details faded]' "
            "(dry run unless --write)",
            "Restore them",
        ),
    ):
        p_clean = repair_sub.add_parser(name, help=text)
        _scope_options(p_clean)
        p_clean.add_argument(
            "--write",
            action="store_true",
            help=f"{verb} instead of printing what would change",
        )

    # ── hermes ──
    p_hermes = sub.add_parser("hermes", help="Hermes Agent identity-continuity integration")
    hermes_sub = p_hermes.add_subparsers(dest="hermes_command")
    hermes_scope = {
        "--db-path": "Mnemos SQLite database path",
        "--agent-id": "Fixed Mnemos agent scope",
        "--person-id": "Fixed person/user scope",
        "--project-scope": "Fixed project scope",
    }
    p_hermes_install = hermes_sub.add_parser("install", help="Install Mnemos for Hermes")
    p_hermes_install.add_argument("--hermes-home", default=None, help="Hermes home directory")
    _scope_options(p_hermes_install, helps=hermes_scope)
    p_hermes_install.add_argument(
        "--mode",
        choices=("provider", "sidecar"),
        default="provider",
        help="Provider Mode uses memory.provider=mnemos; Sidecar Mode preserves the existing provider and adds MCP",
    )
    p_hermes_install.add_argument("--activate", action="store_true", help="Set memory.provider to mnemos in Provider Mode")
    p_hermes_install.add_argument("--with-mcp", action="store_true", help="Also add Mnemos to Hermes mcp_servers")
    p_hermes_install.add_argument("--mcp-name", default="mnemos", help="Hermes MCP server name")
    p_hermes_install.add_argument("--force", action="store_true", help="Replace an existing shim")
    p_hermes_install.add_argument("--dry-run", action="store_true", help="Show what would be written")
    p_hermes_quickstart = hermes_sub.add_parser(
        "quickstart",
        help="Safely install Mnemos for Hermes and run doctor",
    )
    p_hermes_quickstart.add_argument("--hermes-home", default=None, help="Hermes home directory")
    _scope_options(p_hermes_quickstart, helps=hermes_scope)
    p_hermes_quickstart.add_argument(
        "--agent-safe",
        action="store_true",
        help="Noninteractive Sidecar Mode only; never changes memory.provider",
    )
    p_hermes_quickstart.add_argument(
        "--provider",
        action="store_true",
        help="Use Provider Mode and activate memory.provider=mnemos",
    )
    p_hermes_quickstart.add_argument(
        "--activate-provider",
        action="store_true",
        help="Alias for --provider",
    )
    p_hermes_quickstart.add_argument("--mcp-name", default="mnemos", help="Hermes MCP server name")
    p_hermes_quickstart.add_argument("--dry-run", action="store_true", help="Show what would be written")
    p_hermes_doctor = hermes_sub.add_parser("doctor", help="Check Hermes Mnemos setup")
    p_hermes_doctor.add_argument("--hermes-home", default=None, help="Hermes home directory")
    hermes_sub.add_parser("shim", help="Print the Hermes provider shim")

    # ── identity ──
    p_identity = sub.add_parser("identity", help="Computed vs declared identity")
    identity_sub = p_identity.add_subparsers(dest="identity_command")
    p_id_diff = identity_sub.add_parser(
        "diff", help="Diff graph-derived identity against SOUL.md"
    )
    p_id_diff.add_argument(
        "--soul",
        default=None,
        help="Path to SOUL.md (default: $MNEMOS_WORKSPACE/SOUL.md, then ./SOUL.md)",
    )
    p_id_diff.add_argument("--json", action="store_true", help="Emit machine-readable report")
    p_id_diff.add_argument(
        "--no-note",
        action="store_true",
        help="Do not write the continuity note that surfaces at next mnemos_context",
    )
    p_id_diff.add_argument(
        "--no-enrich",
        action="store_true",
        help="Skip optional model-assisted annotation",
    )
    _scope_options(p_id_diff)
    p_id_accept = identity_sub.add_parser(
        "accept", help="Accept a divergence and open a new epoch"
    )
    p_id_accept.add_argument(
        "--divergence",
        type=int,
        required=True,
        metavar="N",
        help="Divergence number from the last `identity diff` run",
    )
    p_id_accept.add_argument("--note", default="", help="Optional note recorded with the transition")
    p_id_accept.add_argument("--json", action="store_true", help="Emit machine-readable result")
    _scope_options(p_id_accept)

    # ── mcp ──
    p_mcp = sub.add_parser("mcp", help="MCP client helpers")
    mcp_sub = p_mcp.add_subparsers(dest="mcp_command")
    p_mcp_install = mcp_sub.add_parser("install", help="Print or write MCP client config")
    p_mcp_install.add_argument(
        "client",
        choices=("claude", "claude-code", "cursor", "codex", "generic"),
        help="Client config style",
    )
    p_mcp_install.add_argument("--name", default="mnemos", help="MCP server name")
    p_mcp_install.add_argument("--mode", choices=("simple", "advanced"), default="simple")
    _scope_options(p_mcp_install, "--agent-id", "--db-path", helps={
        "--agent-id": "Optional agent identity",
        "--db-path": "Optional database path",
    })
    p_mcp_install.add_argument(
        "--write",
        action="store_true",
        help="Write config where safely supported instead of printing a snippet",
    )
    p_mcp_install.add_argument(
        "--no-upkeep",
        action="store_true",
        help=(
            "For Claude Desktop with --write, don't schedule upkeep between "
            "sessions (on by default)"
        ),
    )

    # ── hook ──
    p_hook = sub.add_parser(
        "hook", help="Emit agent-harness hook payloads (used by installed hooks)"
    )
    hook_sub = p_hook.add_subparsers(dest="hook_command")
    p_hook_start = hook_sub.add_parser(
        "session-start", help="Print the SessionStart continuity payload as JSON"
    )
    _scope_options(p_hook_start)
    p_hook_start.add_argument(
        "--wake", default=None,
        help="How much of memory to wake with: full (default), light (who you're with, how they work, where you left off; spends nothing), or off (nothing). Also read from MNEMOS_WAKE.",
    )
    p_hook_start.add_argument(
        "--query",
        default="what should I know to continue our work?",
        help="Retrieval cue for --include-graph (the packet itself takes no cue)",
    )
    p_hook_start.add_argument(
        "--token-budget", type=int, default=2000,
        help=(
            "Approximate packet size in tokens, besides the handoff shown whole "
            "(2000 is about 8,000 characters)"
        ),
    )
    p_hook_start.add_argument(
        "--person-name", default=None,
        help=(
            "The name of the person this memory works with, so the packet can "
            "say it (default: MNEMOS_PERSON_NAME)"
        ),
    )
    p_hook_start.add_argument(
        "--include-graph",
        action="store_true",
        help=(
            "Also inject long-term graph recall. Off by default: the packet "
            "carries scoped continuity, which is what the agent cannot "
            "reconstruct from anywhere else."
        ),
    )
    p_hook_prompt = hook_sub.add_parser(
        "prompt",
        help="Print, for the model, the memories that may bear on a message (UserPromptSubmit)",
    )
    _scope_options(p_hook_prompt)

    # ── hooks ──
    p_hooks = sub.add_parser(
        "hooks", help="Install the hooks that bring memory into each session (setup's last step)",
    )
    hooks_sub = p_hooks.add_subparsers(dest="hooks_command")
    p_hooks_install = hooks_sub.add_parser(
        "install",
        help="Print or write the hooks that bring memory into each session",
        description=(
            "Install the SessionStart hook, which wakes the agent with its memory, "
            "and for Claude Code the cue (a UserPromptSubmit hook) that brings the "
            "memories that may bear on each message. With --write it also schedules "
            "upkeep between sessions, and at a terminal asks once about quiet hours "
            "(Claude Code)."
        ),
    )
    p_hooks_install.add_argument(
        "client", nargs="?", default="claude-code", choices=("claude-code", "codex"),
        help="Agent harness to install the hook for",
    )
    _scope_options(p_hooks_install)
    p_hooks_install.add_argument("--timeout", type=int, default=15, help="Hook timeout seconds")
    p_hooks_install.add_argument(
        "--settings",
        default=None,
        help="Settings file to write (default is selected for the client)",
    )
    p_hooks_install.add_argument(
        "--write", action="store_true", help="Write the settings file instead of printing it"
    )
    cue_choice = p_hooks_install.add_mutually_exclusive_group()
    cue_choice.add_argument(
        "--no-prompt",
        action="store_true",
        help=(
            "Leave out the cue, the UserPromptSubmit hook that brings the memories "
            "that may bear on each message (Claude Code; on by default). Removes "
            "one an earlier install added."
        ),
    )
    # The cue is on by default now; --prompt stays accepted for instructions
    # written when it had to be asked for.
    cue_choice.add_argument("--prompt", action="store_true", help=argparse.SUPPRESS)
    p_hooks_install.add_argument(
        "--no-upkeep",
        action="store_true",
        help="With --write, don't schedule upkeep between sessions (on by default)",
    )

    # ── daemon ──
    p_daemon = sub.add_parser(
        "daemon", help="Schedule upkeep and quiet hours with the OS scheduler"
    )
    daemon_sub = p_daemon.add_subparsers(dest="daemon_command")
    for _name, _help in (
        ("install", "Print or write the scheduled jobs: upkeep, and with --hours the quiet hours"),
        ("status", "Show which jobs are scheduled"),
        ("uninstall", "Remove the scheduled jobs (with --hours, only the quiet hours)"),
    ):
        _p = daemon_sub.add_parser(_name, help=_help)
        _scope_options(_p)
        if _name != "status":
            _p.add_argument(
                "--write",
                action="store_true",
                help="Apply the change instead of printing what it would do",
            )
        if _name == "install":
            _p.add_argument(
                "--hours",
                action="store_true",
                help=(
                    "Also schedule the quiet hours: an hour a day that's the agent's "
                    "own, and half an hour for the day's work. They run Claude on its "
                    "own and use your Claude plan."
                ),
            )
            _p.add_argument(
                "--mine-at", type=_clock, default=None, metavar="HH:MM",
                help="With --hours: when the agent's own hour starts (default 08:00)",
            )
            _p.add_argument(
                "--ours-at", type=_clock, default=None, metavar="HH:MM",
                help="With --hours: when the half hour for the day's work starts (default 19:00)",
            )
        if _name == "uninstall":
            _p.add_argument(
                "--hours",
                action="store_true",
                help="Remove only the quiet hours, and keep upkeep",
            )

    # ── uninstall ──
    p_uninstall = sub.add_parser(
        "uninstall",
        help="Take Mnemos out of Claude Code, Claude Desktop and Codex, and unschedule its jobs; the memories stay",
    )
    _scope_options(p_uninstall)
    p_uninstall.add_argument("--name", default="mnemos", help="The MCP server's name (default mnemos)")
    p_uninstall.add_argument(
        "--write", action="store_true",
        help="Remove it instead of printing what would be removed",
    )

    # ── backup ──
    p_backup = sub.add_parser("backup", help="Create, inspect, or restore verified backups")
    backup_sub = p_backup.add_subparsers(dest="backup_command")
    p_backup_create = backup_sub.add_parser("create", help="Create and verify a private backup")
    p_backup_create.add_argument("--output", default=None, help="Backup destination")
    _scope_options(p_backup_create, "--db-path")
    p_backup_inspect = backup_sub.add_parser("inspect", help="Verify and inspect a backup")
    p_backup_inspect.add_argument("path", help="Backup file")
    p_backup_restore = backup_sub.add_parser("restore", help="Restore a verified backup")
    p_backup_restore.add_argument("path", help="Backup file")
    _scope_options(p_backup_restore, "--db-path", helps={"--db-path": "Restore destination"})
    p_backup_restore.add_argument(
        "--force", action="store_true",
        help="Replace an existing database after preserving a safety backup",
    )

    # ── embeddings ──
    p_embeddings = sub.add_parser(
        "embeddings", help="The local embedding model semantic recall uses",
    )
    embeddings_sub = p_embeddings.add_subparsers(dest="embeddings_command")
    embeddings_sub.add_parser(
        "download",
        help="Download the local embedding model (the one step that uses the network)",
    )
    embeddings_sub.add_parser(
        "index",
        help="Index everything waiting for recall's meaning search, and nothing else",
    )

    args = parser.parse_args(argv)
    # Whether this process is the command itself (the console script, or
    # `python -m mnemos.cli`), not a host that called main() with arguments.
    # Only the command itself may end its own process (see _hook_prompt).
    args.command_line = argv is None

    if args.command is None:
        parser.print_help()
        return 0

    handlers = {
        "init": _cmd_init,
        "serve": _cmd_serve,
        "inspect": _cmd_inspect,
        "stats": _cmd_stats,
        "snapshot": _cmd_snapshot,
        "search": _cmd_search,
        "memories": _cmd_memories,
        "correct": _cmd_correct,
        "forget": _cmd_forget,
        "interface": _cmd_interface,
        "consolidate": _cmd_consolidate,
        "export": _cmd_export,
        "setup-openclaw": _cmd_setup_openclaw,
        "bootstrap": _cmd_bootstrap,
        "index": _cmd_index,
        "bridge": _cmd_bridge,
        "remember": _cmd_remember,
        "journal": _cmd_journal,
        "life": _cmd_life,
        "notes": _cmd_notes,
        "log": _cmd_log,
        "doctor": _cmd_doctor,
        "repair-softening": _cmd_repair_softening,
        "adopt-legacy": _cmd_adopt_legacy,
        "repair-lessons": _cmd_repair_lessons,
        "repair-versions": _cmd_repair_versions,
        "repair": _cmd_repair,
        "hermes": _cmd_hermes,
        "identity": _cmd_identity,
        "mcp": _cmd_mcp,
        "hook": _cmd_hook,
        "hooks": _cmd_hooks,
        "daemon": _cmd_daemon,
        "uninstall": _cmd_uninstall,
        "backup": _cmd_backup,
        "embeddings": _cmd_embeddings,
    }

    handler = handlers.get(args.command)
    if handler:
        return handler(args)
    parser.print_help()
    return 1


def _cmd_hook(args: argparse.Namespace) -> int:
    """Emit an agent-harness hook payload.

    This is what an installed SessionStart hook actually runs. Keeping it a
    CLI subcommand rather than a generated script means the injection logic
    ships with the package and upgrades with it, instead of going stale in
    a copy someone's harness wrote out months ago.
    """
    if getattr(args, "hook_command", None) == "prompt":
        return _hook_prompt(args)
    if getattr(args, "hook_command", None) != "session-start":
        print("Usage: mnemos hook session-start|prompt", file=sys.stderr)
        return 1

    # A memory hiccup must never cost someone their session. Every failure
    # path here exits 0 with no stdout, which the harness reads as "this
    # hook contributed nothing" rather than as an error.
    #
    # Drain any payload the harness passed on stdin, but never block on it. A
    # bare read() waits for EOF, so a harness that spawns the hook and leaves
    # stdin open would hang session start forever. select() drains only what is
    # already there and returns the moment there is nothing more to read.
    #
    # The payload can name the model starting the session (Claude Code sends
    # `model` on SessionStart when it has one), always names the session
    # (`session_id`, the same id its MCP servers get as CLAUDE_CODE_SESSION_ID,
    # kept across compaction) and says where it works (`cwd`). Those are the
    # only uses made of it: the packet can then say whether the reader wrote a
    # handoff, hand a session its own note first, and rank what the reader is
    # carrying by the folder and repository it works in. The folder ranks; it
    # never chooses whose memory this is.
    received = bytearray()
    try:
        import select

        fd = sys.stdin.fileno()
        while select.select([fd], [], [], 0.0)[0]:
            chunk = os.read(fd, 65536)
            if not chunk:
                break  # EOF — writer closed its end
            if len(received) < 1_048_576:
                received.extend(chunk)
    except Exception:
        pass
    wake = (getattr(args, "wake", None) or os.environ.get("MNEMOS_WAKE", "") or "full").strip().lower()
    if wake not in ("full", "light", "off"):
        print(f"[mnemos hook] unknown wake mode {wake!r}; using full", file=sys.stderr)
        wake = "full"
    if wake == "off":
        return 0
    reader_model = ""
    reader_session = ""
    workdir = ""
    environ: dict[str, str] = dict(os.environ)
    try:
        from .authorship import clean_model_id, clean_session_id

        payload = json.loads(bytes(received).decode("utf-8")) if received.strip() else {}
        if isinstance(payload, dict):
            reader_model = clean_model_id(payload.get("model"))
            reader_session = clean_session_id(payload.get("session_id"))
            if isinstance(payload.get("cwd"), str):
                workdir = payload["cwd"]
        if reader_session:
            environ["CLAUDE_CODE_SESSION_ID"] = reader_session
    except Exception:
        reader_model = ""
        reader_session = ""
    if not workdir:
        try:
            workdir = os.getcwd()
        except OSError:
            workdir = ""

    try:
        from .interface.context_packet import build_context_packet
        from .store.sqlite_store import EngramStore

        scope = _cli_scope(args)
        # Opening a store builds the schema, so a hook that ran against a
        # mistyped --db-path would silently create a fresh empty database
        # at every session start. Reading memory must never bring one into
        # existence: with no store yet, contribute nothing.
        if not Path(scope.db_path).expanduser().exists():
            return 0
        store = EngramStore(scope.db_path)
        try:
            # Who is reading, found the way the MCP server finds who is
            # writing: the operator's setting, what the harness said (or, when
            # it said nothing, what this session last introduced itself as),
            # then the session's own transcript (after a resume or compaction
            # it names the model). Never another session's introduction. A
            # fresh session has no transcript yet, so last comes the model the
            # harness was launched with.
            try:
                from .authorship import (
                    launch_model,
                    resolve_author_model,
                    session_introduction,
                )

                declared = reader_model or session_introduction(store.get_meta, environ)[0]
                reader_model = resolve_author_model(declared, environ) or launch_model(environ)
            except Exception:
                reader_model = ""
            person_name = getattr(args, "person_name", None)
            if person_name is None:
                person_name = environ.get("MNEMOS_PERSON_NAME", "")
            packet = build_context_packet(
                store,
                args.query,
                agent_id=scope.agent_id,
                person_id=scope.person_id,
                project_scope=scope.project_scope,
                token_budget=args.token_budget,
                include_prompt=True,
                include_engrams=bool(getattr(args, "include_graph", False)),
                reader_model=reader_model,
                reader_session=reader_session,
                workdir=workdir,
                person_name=person_name,
                wake=wake,
            )
            # Waking is living: the day counts on the agent's own clock.
            try:
                store.mark_lived(scope.agent_id)
            except Exception:
                pass
        finally:
            store.close()
        text = (packet.get("prompt") or "").strip()
        if text and reader_session:
            # What the briefing showed, so the prompt hook's cue never shows it
            # again in this session. Outside the store; never fails the hook.
            from .cue import record_briefing
            from .interface.context_packet import shown_memories

            ids, texts = shown_memories(packet)
            record_briefing(
                reader_session,
                db_path=scope.db_path,
                agent_id=scope.agent_id,
                person_id=scope.person_id,
                project_scope=scope.project_scope,
                ids=ids,
                texts=texts,
            )
    except Exception as exc:
        print(f"[mnemos hook] {type(exc).__name__}: {exc}", file=sys.stderr)
        return 0

    if not text:
        return 0

    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": text,
        }
    }))
    return 0


def _hook_prompt(args: argparse.Namespace) -> int:
    """What an installed UserPromptSubmit hook runs (``mnemos hook prompt``):
    the memories that may bear on the message the human just sent, printed for
    the model, or nothing (see ``mnemos.cue``).

    It never blocks or breaks a prompt. Any error, an unexpected payload, or
    running out of time prints nothing and exits 0. Every wait is bounded by a
    deadline (``cue.HOOK_BUDGET`` after it starts, which with the process's own
    start keeps it under ``cue.HOOK_SECONDS``); and run as the command itself,
    the process also ends at that deadline whatever it is doing. The block is
    written whole, in one write, or not at all. A timeout and a store locked
    through a second try are counted by kind in the session's file, and say
    nothing on stderr; anything else is named there too.
    """
    import time

    from . import cue

    started = time.monotonic()
    finished = cue.arm_hard_stop(cue.HOOK_BUDGET) if getattr(args, "command_line", False) else None
    try:
        raw = cue.read_payload(sys.stdin, deadline=started + 0.25)
        payload = json.loads(raw.decode("utf-8")) if raw.strip() else None
        if not isinstance(payload, dict):
            return 0
        scope = _cli_scope(args)
        block = cue.prompt_hook(
            payload,
            db_path=scope.db_path,
            agent_id=scope.agent_id,
            person_id=scope.person_id,
            project_scope=scope.project_scope,
            deadline=started + cue.HOOK_BUDGET - cue.HOOK_MARGIN,
        )
        if block:
            out = json.dumps({
                "hookSpecificOutput": {
                    "hookEventName": "UserPromptSubmit",
                    "additionalContext": block,
                }
            }, ensure_ascii=False)
            if finished is not None:
                finished.set()
            _write_whole(out + "\n")
    except BaseException as exc:  # a hook never breaks a prompt, even on Ctrl-C
        if not isinstance(exc, (cue.HookTimeout, cue.StoreBusy)):
            print(f"[mnemos hook] {type(exc).__name__}: {exc}", file=sys.stderr)
    finally:
        if finished is not None:
            finished.set()
    return 0


def _write_whole(text: str) -> None:
    """Write ``text`` to stdout in one system call when stdout is a real file
    (a pipe takes up to 4 KiB whole), else through ``sys.stdout``."""
    data = text.encode("utf-8")
    try:
        fd = sys.stdout.fileno()
    except (AttributeError, OSError, ValueError):
        fd = None
    if fd is None:
        sys.stdout.write(text)
        sys.stdout.flush()
        return
    sys.stdout.flush()
    view = memoryview(data)
    while view:
        written = os.write(fd, view)
        view = view[written:]


def _scope_args(args: argparse.Namespace) -> tuple[str, ...]:
    """The scope flags a scheduled job needs to reach the same memory.

    A background job runs with no session, no client and no inherited
    environment, so whatever scope this command resolved must be written
    into the job itself or the job would maintain a different store.

    Only the flags the top-level parser accepts are emitted, and they are
    global options, so ``command_for`` places them before the subcommand.
    The complete scope prevents unattended maintenance from touching a
    different person or project in the same agent store.

    The path is expanded here. ``resolve_scope`` returns the default store
    as the literal string ``~/.mnemos/<agent>.db``, and launchd and systemd
    are not shells — they pass argv through verbatim, so an unexpanded
    tilde makes the job operate on a phantom store relative to its own
    working directory. It then reports a perfectly healthy cycle over an
    empty database while the real memory is never maintained.
    """
    scope = _cli_scope(args)
    db_path = str(Path(scope.db_path).expanduser())
    return (
        "--agent-id", scope.agent_id,
        "--person-id", scope.person_id,
        "--project-scope", scope.project_scope,
        "--db-path", db_path,
    )


def _cmd_daemon(args: argparse.Namespace) -> int:
    """Schedule upkeep, and with ``--hours`` the quiet hours, with whatever
    scheduler the host provides."""
    command = getattr(args, "daemon_command", None)
    if command not in {"install", "status", "uninstall"}:
        print("Usage: mnemos daemon {install|status|uninstall}", file=sys.stderr)
        return 1
    hours = bool(getattr(args, "hours", False))
    mine_at, ours_at = getattr(args, "mine_at", None), getattr(args, "ours_at", None)
    if (mine_at or ours_at) and not hours:
        print("--mine-at and --ours-at set the quiet hours' times: add --hours.", file=sys.stderr)
        return 1

    blueprint = _blueprint(
        args, hours=command == "install" and hours, mine_at=mine_at, ours_at=ours_at,
    )
    backend = blueprint["backend"]

    if backend == "unsupported":
        print(
            "No supported scheduler found on this system (looked for launchd, "
            "systemd and crontab).\n"
            "Mnemos still maintains itself opportunistically while a session is "
            "open; only unattended background maintenance is unavailable.",
            file=sys.stderr,
        )
        return 1

    if command == "status":
        return _daemon_status(blueprint)
    if command == "uninstall":
        return _daemon_uninstall(blueprint, write=args.write, only_hours=hours)
    return _daemon_install(blueprint, write=args.write, hours=hours)


def _blueprint(
    args: argparse.Namespace,
    *,
    hours: bool = False,
    mine_at: tuple[int, int] | None = None,
    ours_at: tuple[int, int] | None = None,
) -> dict:
    """What would be scheduled for this command's scope (``scheduler.plan``).

    With ``hours``, the quiet hours' environment is found now, the claude
    command and the Claude login, because a job started in the background
    finds neither. Without a claude command they can't be scheduled
    (``hours_ready`` is false)."""
    from .setup import scheduler

    scope = _cli_scope(args)
    mnemos_command = _mnemos_command()
    hour_env = None
    if hours:
        claude = scheduler.find_claude()
        if claude:
            hour_env = scheduler.hour_environment(
                claude_bin=claude,
                mnemos_command=mnemos_command,
                config_dir=os.environ.get("CLAUDE_CONFIG_DIR") or None,
            )
    return scheduler.plan(
        agent_id=scope.agent_id,
        mnemos_command=mnemos_command,
        scope_args=_scope_args(args),
        hours=scheduler.hour_jobs(mine_at=mine_at, ours_at=ours_at),
        hour_env=hour_env,
    )


# What the quiet hours are, said wherever they're offered or scheduled: what
# they cost the person, up to an hour and a half a day of Claude on their plan.
QUIET_HOURS = (
    "up to an hour a day that's its own, and half an hour for the day's work; "
    "they run Claude on its own and use your Claude plan"
)
QUIET_HOURS_QUESTION = f"Quiet hours give the agent {QUIET_HOURS}. Turn them on? [Y/n] "
_HOURS_ON = "mnemos daemon install --hours --write"
_HOURS_OFF = "mnemos daemon uninstall --hours --write"
_NO_CLAUDE = (
    "they run Claude Code's claude command, and none was found (on your PATH, "
    "or in MNEMOS_CLAUDE_BIN)"
)


def _print_job(entry: dict) -> None:
    job = entry["job"]
    print(f"\n  {job.name} — {job.description}")
    print(f"    schedule: {entry['schedule']}")
    print(f"    command:  {entry['command']}")
    for key, value in (entry.get("environment") or {}).items():
        print(f"    env:      {key}={value}")
    print(f"    log:      {entry['log']}")


def _daemon_install(blueprint: dict, *, write: bool, hours: bool = False) -> int:
    from .setup import scheduler as _scheduler

    backend = blueprint["backend"]
    agent_id = blueprint["agent_id"]
    entries = list(blueprint["entries"])
    no_claude = hours and not blueprint["hours_ready"]

    print(f"Scheduler:   {backend}")
    print(f"Agent:       {agent_id}")
    print(f"Folder:      {_scheduler.working_directory()} (where every job runs)")
    for entry in entries:
        _print_job(entry)
    for job in blueprint["skipped"]:
        print(
            f"\n  {job.name} — skipped: needs a model provider "
            f"(set MNEMOS_LLM_PROVIDER and a key, then reinstall)"
        )
    if no_claude:
        print(f"\n  The quiet hours are not scheduled: {_NO_CLAUDE}.")
    elif hours:
        print(f"\n  Quiet hours give the agent {QUIET_HOURS}.")
        for entry in blueprint["hours"]:
            _print_job(entry)
        entries += blueprint["hours"]

    retired = _scheduler.retired_installed(
        blueprint, _read_crontab_safe() if backend == "crontab" else ""
    )
    for entry in retired:
        print(
            f"\n  {entry['job'].name} — an earlier install scheduled it; it is "
            "removed: it writes memories in a model's words, not yours"
        )

    warning = _scheduler.tcc_warning(_mnemos_command(), backend=backend)
    if warning:
        print(f"\n{warning}")

    if not write:
        print("\nThis is a preview. Re-run with --write to schedule these jobs.")
        return 1 if no_claude else 0

    try:
        _apply_schedule(blueprint, entries, retired)
    except (OSError, RuntimeError) as exc:
        print(f"Failed to activate background maintenance: {exc}", file=sys.stderr)
        return 1

    print(f"\nScheduled {len(entries)} job(s). Background maintenance is active.")
    if retired:
        print(f"Removed {len(retired)} job(s) an earlier install scheduled.")
    print("Check them any time with: mnemos daemon status")
    return 1 if no_claude else 0


def _apply_schedule(blueprint: dict, entries: list[dict], retired: list[dict]) -> None:
    """Schedule ``entries`` on this host, and take off the ``retired`` jobs
    an earlier install left. Jobs already scheduled are replaced, never
    stacked; on a crontab every other line stays as it was. Raises OSError or
    RuntimeError when the scheduler refuses."""
    from .file_security import atomic_write_bytes, atomic_write_text, secure_directory
    from .setup import scheduler

    backend = blueprint["backend"]
    # The logs' folder, and so ~/.mnemos, the folder every job runs in: it
    # has to be there before any job starts.
    secure_directory(Path.home() / ".mnemos" / "logs", force=True)
    _remove_retired(backend, retired)
    if backend == "launchd":
        for entry in entries:
            path = entry["path"]
            secure_directory(path.parent)
            _launchctl("bootout", path, allow_missing=True)
            atomic_write_bytes(path, entry["content"], backup_existing=True)
            _launchctl("bootstrap", path)
    elif backend == "systemd":
        for entry in entries:
            for path, content in entry["units"].items():
                secure_directory(path.parent)
                atomic_write_text(path, content, backup_existing=True)
        if entries:
            _systemctl("daemon-reload")
            for entry in entries:
                _systemctl("enable", "--now", entry["timer_name"])
    else:
        names = [entry["job"].name for entry in entries]
        names += [job.name for job in scheduler.RETIRED_JOBS]
        merged = scheduler.merge_cron_lines(
            scheduler.read_crontab(), [entry["line"] for entry in entries],
            blueprint["agent_id"], replacing=names,
        )
        if not scheduler.write_crontab(merged):
            raise RuntimeError("the crontab could not be written")


def _unschedule(backend: str, entries: list[dict]) -> None:
    """Take ``entries`` off launchd or systemd: stopped, and their files
    gone, with the copies an install kept of what it replaced (``.bak``).
    A crontab is the caller's: its lines go in one merge."""
    if backend == "launchd":
        for entry in entries:
            _launchctl("bootout", entry["path"], allow_missing=True)
            _unlink_with_backup(entry["path"])
    elif backend == "systemd" and entries:
        for entry in entries:
            try:
                _systemctl("disable", "--now", entry["timer_name"])
            except RuntimeError:
                pass  # already stopped or never enabled; the files still go
            for path in entry["units"]:
                _unlink_with_backup(Path(path))
        _systemctl("daemon-reload")


def _unlink_with_backup(path: Path) -> None:
    path.unlink(missing_ok=True)
    path.with_suffix(path.suffix + ".bak").unlink(missing_ok=True)


def _remove_retired(backend: str, retired: list[dict]) -> None:
    """Unschedule jobs an earlier install scheduled and this one no longer
    does. A crontab needs nothing: its lines go with the merge."""
    _unschedule(backend, retired)


def _scheduled(blueprint: dict, entry: dict, crontab: str) -> bool:
    """Whether ``entry`` is installed and its scheduler has it."""
    from .setup import scheduler

    backend = blueprint["backend"]
    agent_id = blueprint["agent_id"]
    job = entry["job"]
    if backend == "launchd":
        return entry["path"].exists() and scheduler.launchd_job_active(agent_id, job)
    if backend == "systemd":
        return (
            all(path.exists() for path in entry["units"])
            and scheduler.systemd_timer_active(agent_id, job)
        )
    return scheduler.cron_has(crontab, agent_id, job.name)


def _daemon_status(blueprint: dict) -> int:
    from .setup import scheduler

    backend = blueprint["backend"]
    crontab = _read_crontab_safe() if backend == "crontab" else ""

    print(f"Scheduler:   {backend}")
    print(f"Agent:       {blueprint['agent_id']}")

    installed_any = False
    for entry in blueprint["entries"]:
        installed = _scheduled(blueprint, entry, crontab)
        installed_any = installed_any or installed
        state = "scheduled" if installed else "not scheduled"
        print(f"  {entry['job'].name:<16} {state:<15} {entry['schedule']}")

    for job in blueprint["skipped"]:
        print(f"  {job.name:<16} {'unavailable':<15} needs a model provider")

    hours_on = [entry for entry in blueprint["hours"] if _scheduled(blueprint, entry, crontab)]
    for entry in hours_on:
        when = scheduler.installed_daily_at(blueprint, entry, crontab)
        schedule = f"daily at {when[0]:02d}:{when[1]:02d}" if when else "daily"
        print(f"  {entry['job'].name:<16} {'scheduled':<15} {schedule}")
    if not hours_on:
        print(f"  {'quiet hours':<16} {'off':<15} to turn them on: {_HOURS_ON}")

    for entry in scheduler.retired_installed(blueprint, crontab):
        print(
            f"  {entry['job'].name:<16} {'retired':<15} "
            "no longer scheduled; 'mnemos daemon install --write' removes it"
        )

    if not installed_any:
        print("\nNo background maintenance scheduled. Install it with:")
        print("  mnemos daemon install --write")
    return 0


def _read_crontab_safe() -> str:
    from .setup import scheduler

    return scheduler.read_crontab()


def _daemon_uninstall(blueprint: dict, *, write: bool, only_hours: bool = False) -> int:
    """Remove what is scheduled for this agent: everything, or with
    ``only_hours`` only the quiet hours."""
    from .setup import scheduler

    backend = blueprint["backend"]
    agent_id = blueprint["agent_id"]
    crontab = _read_crontab_safe() if backend == "crontab" else ""
    targets = list(blueprint["hours"])
    if not only_hours:
        targets = [*blueprint["entries"], *targets]
    found = scheduler.installed(blueprint, targets, crontab)
    if not only_hours:
        found += scheduler.retired_installed(blueprint, crontab)

    if not found:
        if only_hours:
            print("The quiet hours aren't scheduled.")
        else:
            print(f"Nothing is scheduled for {agent_id} ({backend}).")
        return 0

    if not write:
        print(f"Would remove {len(found)} scheduled job(s) ({backend}):")
        for entry in found:
            print(f"  {entry['job'].name}")
        print("\nRe-run with --write to remove them.")
        return 0

    try:
        if backend in ("launchd", "systemd"):
            _unschedule(backend, found)
        else:
            names = [entry["job"].name for entry in targets] if only_hours else None
            merged = scheduler.merge_cron_lines(crontab, [], agent_id, replacing=names)
            if not scheduler.write_crontab(merged):
                raise RuntimeError("the crontab could not be written")
    except (OSError, RuntimeError) as exc:
        print(f"Failed to remove the scheduled jobs: {exc}", file=sys.stderr)
        return 1

    print(f"Removed {len(found)} scheduled job(s).")
    return 0


def _can_ask() -> bool:
    """Whether a person is at this terminal to answer a question: input and
    output both a terminal. An agent's shell, a pipe or a script is not."""
    try:
        return sys.stdin.isatty() and sys.stdout.isatty()
    except (AttributeError, ValueError, OSError):
        return False


def _background_setup(args: argparse.Namespace, *, ask_hours: bool) -> int:
    """Setup's part between sessions, once its hooks or client config are
    written: upkeep, scheduled unless ``--no-upkeep``, and for a Claude client
    the quiet hours, asked about once at a terminal, yes by default, and
    never scheduled without one. Returns 1 when something it set out to
    schedule could not be."""
    from .setup import scheduler

    blueprint = _blueprint(args, hours=ask_hours)
    backend = blueprint["backend"]
    print()
    if backend == "unsupported":
        print(
            "Between sessions: this system has no scheduler Mnemos can use (launchd, "
            "systemd or crontab), so upkeep happens only while a session is open."
        )
        return 0
    warning = scheduler.tcc_warning(_mnemos_command(), backend=backend)
    if warning:
        print(warning)
        print()

    failed = False
    if getattr(args, "no_upkeep", False):
        print(
            "Upkeep between sessions: not scheduled (--no-upkeep). To schedule it: "
            "mnemos daemon install --write"
        )
    else:
        crontab = _read_crontab_safe() if backend == "crontab" else ""
        try:
            _apply_schedule(
                blueprint, blueprint["entries"], scheduler.retired_installed(blueprint, crontab),
            )
        except (OSError, RuntimeError) as exc:
            print(
                f"Upkeep between sessions: not scheduled ({exc}). To try again: "
                "mnemos daemon install --write"
            )
            failed = True
        else:
            _say_upkeep(blueprint)
    if ask_hours:
        failed = _quiet_hours_setup(blueprint) or failed
    return 1 if failed else 0


def _say_upkeep(blueprint: dict) -> None:
    """What the upkeep just scheduled does, and whether anything leaves the
    machine: with no model chosen for Mnemos, nothing does."""
    by_name = {entry["job"].name: entry for entry in blueprint["entries"]}
    every = by_name["maintain"]["job"].interval_seconds // 3600
    deep = by_name["maintain-deep"]["schedule"]
    print(
        f"Upkeep between sessions is on ({blueprint['backend']}): every {every} hours "
        f"memories fade a little with time and related ones are linked, and a deeper "
        f"pass runs {deep}."
    )
    provider = ""
    if blueprint["has_model"]:
        try:
            from .llm import chosen_provider, create_client

            provider = chosen_provider() if create_client() is not None else ""
        except Exception:
            provider = ""
    if provider:
        print(
            f"  You chose a model for Mnemos ({provider}), so upkeep sends it "
            "memories, to classify the links between them."
        )
    else:
        print(
            "  No model is chosen for Mnemos, so these are local passes only: "
            "nothing leaves this machine."
        )
    print("  Turn it off: mnemos daemon uninstall --write")


def _quiet_hours_setup(blueprint: dict) -> bool:
    """Setup's one question about the quiet hours, yes by default, and what
    the answer does. Without a terminal nothing is asked or scheduled, and the
    way to turn them on is printed; without a claude command they can't be
    scheduled, and that is said. Returns whether scheduling them failed."""
    from .setup import scheduler

    crontab = _read_crontab_safe() if blueprint["backend"] == "crontab" else ""
    if scheduler.installed(blueprint, blueprint["hours"], crontab):
        print(f"Quiet hours: on. Turn them off: {_HOURS_OFF}")
        return False
    if not blueprint["hours_ready"]:
        print(f"Quiet hours: off, because {_NO_CLAUDE}. Once it's there: {_HOURS_ON}")
        return False
    if not _can_ask():
        print(f"Quiet hours: off. They give the agent {QUIET_HOURS}.")
        print(f"  To turn them on: {_HOURS_ON}")
        return False
    try:
        answer = input(QUIET_HOURS_QUESTION).strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        answer = "no"
    if answer and not answer.startswith("y"):
        print(f"Quiet hours: off. To turn them on later: {_HOURS_ON}")
        return False
    try:
        _apply_schedule(blueprint, blueprint["hours"], [])
    except (OSError, RuntimeError) as exc:
        print(f"Quiet hours: not scheduled ({exc}). To try again: {_HOURS_ON}")
        return True
    mine, ours = (entry["job"].daily_at for entry in blueprint["hours"])
    print(
        f"Quiet hours are on: the agent's own hour daily at {mine[0]:02d}:{mine[1]:02d}, "
        f"and the day's work at {ours[0]:02d}:{ours[1]:02d} (skipped on a day with no work)."
    )
    print("  Other times: mnemos daemon install --hours --mine-at HH:MM --ours-at HH:MM --write")
    print(f"  Turn them off: {_HOURS_OFF}")
    return False


def _launchctl(action: str, plist: Path, *, allow_missing: bool = False) -> None:
    import os

    domain = f"gui/{os.getuid()}"
    if action == "bootout":
        target = f"{domain}/{plist.stem}"
        result = subprocess.run(
            ["launchctl", "bootout", target],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0 and not allow_missing:
            raise RuntimeError(result.stderr.strip() or "launchctl bootout failed")
        return
    result = subprocess.run(
        ["launchctl", "bootstrap", domain, str(plist)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "launchctl bootstrap failed")


def _systemctl(*args: str) -> None:
    result = subprocess.run(
        ["systemctl", "--user", *args], capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"systemctl {' '.join(args)} failed")


def _claude_code_settings_path() -> Path:
    """Claude Code's settings file: ``$CLAUDE_CONFIG_DIR/settings.json`` when
    that variable is set and not empty, else ``~/.claude/settings.json``."""
    config_dir = os.environ.get("CLAUDE_CONFIG_DIR", "")
    if config_dir:
        return Path(config_dir).expanduser() / "settings.json"
    return Path.home() / ".claude" / "settings.json"


def _codex_hooks_path() -> Path:
    return Path.home() / ".codex" / "hooks.json"


# Claude Code's own timeout for the prompt hook, in seconds. The hook stops
# itself well before this (``cue.HOOK_SECONDS``); a prompt waits on its hooks,
# so this only bounds a hook that could not stop itself.
PROMPT_HOOK_TIMEOUT = 2


def _is_mnemos_hook(candidate: Any, subcommand: str) -> bool:
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


def _cmd_hooks(args: argparse.Namespace) -> int:
    """Install the SessionStart hook that injects memory before turn one, and
    for Claude Code the cue: the UserPromptSubmit hook that brings the
    memories that may bear on each message. The cue is on by default;
    ``--no-prompt`` leaves it out and takes out one an earlier install added
    (``--prompt`` is still taken, and changes nothing).

    This is the last step of setup for Claude Code and Codex, so with
    ``--write`` it also schedules upkeep between sessions (``--no-upkeep``
    leaves it out) and, for Claude Code, asks once about the quiet hours
    (``_background_setup``)."""
    if getattr(args, "hooks_command", None) != "install":
        print(
            "Usage: mnemos hooks install [claude-code|codex] [--no-prompt] "
            "[--no-upkeep] [--write]",
            file=sys.stderr,
        )
        return 1
    if getattr(args, "prompt", False) and args.client != "claude-code":
        print(
            "The prompt hook is for Claude Code: mnemos hooks install claude-code",
            file=sys.stderr,
        )
        return 1
    claude_code = args.client == "claude-code"
    prompt = claude_code and not getattr(args, "no_prompt", False)

    scope_flags: list[str] = []
    for flag, value in (
        ("--agent-id", args.agent_id),
        ("--person-id", args.person_id),
        ("--project-scope", args.project_scope),
        # Expanded for the same reason as the scheduler: a hook runner is
        # not guaranteed to be a shell, and an unexpanded tilde silently
        # points the packet at a store that does not exist.
        ("--db-path", str(Path(args.db_path).expanduser()) if args.db_path else None),
    ):
        if value:
            scope_flags.extend([flag, value])
    command_parts = [_mnemos_command(), "hook", "session-start", *scope_flags]

    handler = {
            "type": "command",
            "command": shlex.join(command_parts),
            "timeout": args.timeout,
        }
    if args.client == "codex":
        handler.update({
            "statusMessage": "Loading Mnemos continuity",
            # The hook command enforces a bounded packet, and handoffs must
            # reach the next session whole rather than becoming a spill-file
            # preview that the model may never read.
            "additionalContextLimit": 8000,
            "commandWindows": subprocess.list2cmdline(command_parts),
        })
    entry = {
        "matcher": (
            "startup|resume|clear|compact" if args.client == "codex" else "*"
        ),
        "hooks": [handler],
    }
    installing = {"SessionStart": entry}
    if prompt:
        installing["UserPromptSubmit"] = {
            "hooks": [{
                "type": "command",
                # A prompt hook that exits 2 blocks the prompt and erases it.
                # `hook prompt` itself always exits 0; the guard covers a Mnemos
                # that cannot run it at all (rolled back to a version without
                # it, or moved), which argparse would answer with a 2.
                "command": shlex.join([_mnemos_command(), "hook", "prompt", *scope_flags]) + " || true",
                "timeout": PROMPT_HOOK_TIMEOUT,
            }],
        }

    default_path = (
        _codex_hooks_path()
        if args.client == "codex"
        else _claude_code_settings_path()
    )
    path = Path(args.settings).expanduser() if args.settings else default_path

    if not args.write:
        print(json.dumps(
            {"hooks": {event: [item] for event, item in installing.items()}}, indent=2,
        ))
        print()
        print(f"Merge this into {path}, or re-run with --write to do it automatically.")
        between = []
        if not getattr(args, "no_upkeep", False):
            between.append("schedules upkeep between sessions (mnemos daemon install shows it)")
        if claude_code:
            between.append("asks once about quiet hours")
        if between:
            print(f"With --write it also {' and '.join(between)}.")
        return 0

    from .file_security import atomic_write_text

    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        try:
            with open(path) as f:
                settings = json.load(f)
        except json.JSONDecodeError as exc:
            # Never clobber a settings file we cannot parse — that file is
            # the user's whole harness configuration, not just ours.
            print(f"Refusing to overwrite unparseable {path}: {exc}", file=sys.stderr)
            return 1
    else:
        settings = {}

    hooks = settings.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        print(
            f"Refusing to overwrite {path}: top-level hooks must be an object",
            file=sys.stderr,
        )
        return 1
    for event in installing:
        if not isinstance(hooks.setdefault(event, []), list):
            print(
                f"Refusing to overwrite {path}: hooks.{event} must be a list",
                file=sys.stderr,
            )
            return 1

    actions: dict[str, str] = {}
    for event, item in installing.items():
        subcommand = "session-start" if event == "SessionStart" else "prompt"
        listed = hooks[event]
        existing = [e for e in listed if _is_mnemos_hook(e, subcommand)]
        for stale in existing:
            listed.remove(stale)
        listed.append(item)
        actions[event] = "Replaced" if existing else "Installed"
    # The cue left out: the one an earlier install added goes too, and only
    # that one. Anyone else's prompt hooks stay.
    dropped = False
    if claude_code and not prompt and isinstance(hooks.get("UserPromptSubmit"), list):
        listed = hooks["UserPromptSubmit"]
        cues = [e for e in listed if _is_mnemos_hook(e, "prompt")]
        for cue_hook in cues:
            listed.remove(cue_hook)
        dropped = bool(cues)

    atomic_write_text(
        path, json.dumps(settings, indent=2) + "\n", backup_existing=True
    )

    for event, item in installing.items():
        print(f"{actions[event]} the Mnemos {event} hook in {path}")
        print(f"  Command: {item['hooks'][0]['command']}")
    if dropped:
        print(f"Removed the Mnemos UserPromptSubmit hook (the cue) from {path}")
    if args.client == "codex":
        print(
            "In Codex, open /hooks and complete the normal review before "
            "trusting the new hook."
        )
        print(
            "After review, continuity is injected at startup, resume, clear, "
            "and after compaction."
        )
    else:
        print(
            "Start a new session — memory is injected before the first turn "
            "and after compaction."
        )
        if prompt:
            print(
                "Each message then brings up to three memories that may bear on "
                "it, found by meaning once the session's Mnemos server has its "
                "model loaded, by words until then."
            )
            print("  Turn it off: mnemos hooks install claude-code --no-prompt --write")
    if getattr(args, "no_upkeep", False) and not claude_code:
        return 0
    return _background_setup(args, ask_hours=claude_code)


def _cli_scope(args: argparse.Namespace):
    """Resolve CLI identity and storage through the one shared resolver.

    The CLI used to answer "which agent, which database" on its own
    (``default`` / ``~/.mnemos/memory.db``) while simple mode answered
    through ``resolve_scope`` (``mnemos-agent`` / ``~/.mnemos/<agent>.db``).
    So ``mnemos stats`` and ``mnemos serve`` reported on different stores,
    and ``mnemos serve --mode advanced`` used a third combination again.
    One resolver, one answer, every entry point.
    """
    from .simple_scope import resolve_scope

    return resolve_scope(
        db_path=getattr(args, "db_path", None),
        agent_id=getattr(args, "agent_id", None),
        person_id=getattr(args, "person_id", None),
        project_scope=getattr(args, "project_scope", None),
    )


def _resolve_db_path(args: argparse.Namespace) -> str:
    """Resolve the CLI's database path."""
    return _cli_scope(args).db_path


def _resolve_agent_id(args: argparse.Namespace) -> str:
    """Resolve the CLI's agent identity."""
    return _cli_scope(args).agent_id


def _get_store(args: argparse.Namespace):
    """Create or open the engram store."""
    from .store.sqlite_store import EngramStore
    return EngramStore(_resolve_db_path(args))


def _cmd_init(args: argparse.Namespace) -> int:
    """Initialize a new memory database."""
    db_path = Path(_resolve_db_path(args)).expanduser()
    if db_path.exists():
        print(f"Database already exists: {db_path}")
        print("Mnemos is ready.")
        return 0

    store = _get_store(args)
    store.close()
    print(f"Initialized Mnemos database: {db_path}")
    print("Run 'mnemos stats' to verify.")
    return 0


def _cmd_embeddings(args: argparse.Namespace) -> int:
    """The local embedding model: download it, or index what waits for it.

    Mnemos loads the model only from files already on this machine, so a slow
    or hanging network can never stall recall, health or doctor. Downloading
    is the explicit step that uses the network.
    """
    command = getattr(args, "embeddings_command", None)
    if command == "index":
        return _embeddings_index(args)
    if command != "download":
        print("Usage: mnemos embeddings download | mnemos embeddings index")
        return 1
    from .store.embedding_index import download_local_model

    try:
        name = download_local_model()
    except Exception as exc:
        print(f"The embedding model was not downloaded: {type(exc).__name__}: {exc}")
        return 1
    print(f"Downloaded the local embedding model {name}; semantic recall can use it now.")
    return 0


def _embeddings_index(args: argparse.Namespace) -> int:
    """Index everything waiting for recall's meaning search, in every scope of
    the store, and do nothing else: no maintenance cycle, no decay, no links.

    Sessions index as they write, and the scheduled job a bounded part each
    run; code older than the store writes nothing to the index, so this is the
    way to catch up at once (after an upgrade, say). The model loads only from
    this machine. Running it again indexes nothing new. The store is opened
    the way every writer opens it, so it records this code's version.
    """
    import time

    from .code_version import MAINTENANCE_CODE_VERSION, OLDER_CODE_FIX, OLDER_CODE_MESSAGE
    from .simple_runtime import index_for_recall
    from .store.embedding_index import EmbeddingIndex
    from .store.sqlite_store import EngramStore

    db_path = Path(_resolve_db_path(args)).expanduser()
    if not db_path.exists():
        print(f"No store at {db_path}: nothing to index.")
        return 1
    store = EngramStore(str(db_path))
    index = None
    try:
        minimum = store.min_code_version()
        if minimum is not None and minimum > MAINTENANCE_CODE_VERSION:
            print("Nothing indexed.")
            print(f"This code is version {MAINTENANCE_CODE_VERSION}; the store needs {minimum} or newer.")
            print(f"{OLDER_CODE_MESSAGE} {OLDER_CODE_FIX}")
            return 1
        index = EmbeddingIndex(db_path=str(db_path))
        if not index.available:
            print(f"Nothing indexed: semantic recall is off here: {index.unavailable_reason}")
            return 1
        started = time.monotonic()
        totals = {"items": 0, "passages": 0, "waiting": 0}
        print(f"Recall index for {db_path}, embedding with {index.backend}:")
        for scope in store.recall_scopes():
            done = index_for_recall(store, index, record="mnemos embeddings index", **scope)
            if done["skipped"]:
                print(f"Nothing indexed: {done['skipped']}")
                return 1
            for key in totals:
                totals[key] += done[key]
            print(
                f"  {scope['agent_id']}/{scope['person_id']}/{scope['project_scope']}: "
                f"{done['items']:,} indexed ({_passages(done['passages'])}), "
                f"{done['waiting']:,} still waiting"
            )
        print(
            f"Indexed {_items(totals['items'])} ({_passages(totals['passages'])}) "
            f"in {time.monotonic() - started:.1f} s; {totals['waiting']:,} still waiting."
        )
        return 0
    finally:
        if index is not None:
            index.close()
        store.close()


def _cmd_backup(args: argparse.Namespace) -> int:
    """Create, inspect, or atomically restore a verified SQLite backup."""
    from .backup import RestoreDidNotHold, check_database, create_backup, restore_backup

    command = getattr(args, "backup_command", None)
    try:
        if command == "create":
            result = create_backup(_resolve_db_path(args), args.output)
            print(f"Backup verified: {result['path']}")
            print(f"  Memories: {result['engrams']}  Size: {result['size_bytes']} bytes")
            return 0
        if command == "inspect":
            result = check_database(args.path)
            print(json.dumps(result, indent=2, sort_keys=True))
            return 0
        if command == "restore":
            result = restore_backup(
                args.path, _resolve_db_path(args), replace=args.force,
            )
            print(f"Restore verified: {result['path']}")
            if result.get("safety_backup"):
                print(f"  Previous database preserved: {result['safety_backup']}")
            return 0
        print("Usage: mnemos backup {create|inspect|restore}", file=sys.stderr)
        return 1
    except RestoreDidNotHold as exc:
        if exc.safety_backup is None:
            print(f"Backup failed: {exc}", file=sys.stderr)
            return 1
        print(
            f"The restore didn't hold: {exc.differs}. Your current memory is "
            f"unchanged in {exc.safety_backup}. Close every session using this "
            "memory and run the restore again.",
            file=sys.stderr,
        )
        return 1
    except (FileNotFoundError, FileExistsError, RuntimeError, sqlite3.DatabaseError) as exc:
        print(f"Backup failed: {exc}", file=sys.stderr)
        return 1


def _cmd_serve(args: argparse.Namespace) -> int:
    """Start MCP server."""
    try:
        if getattr(args, "mode", "simple") == "advanced":
            # stderr: stdout is the MCP protocol's.
            print(ADVANCED_MODE_NOTE, file=sys.stderr)
            from .mcp_server import run_server

            run_server(
                db_path=_resolve_db_path(args),
                agent_id=_resolve_agent_id(args),
                person_id=getattr(args, "person_id", None),
                project_scope=getattr(args, "project_scope", None),
            )
        else:
            from .simple_mcp import run_simple_server

            run_simple_server(
                db_path=getattr(args, "db_path", None),
                agent_id=getattr(args, "agent_id", None),
                person_id=getattr(args, "person_id", None),
                project_scope=getattr(args, "project_scope", None),
            )
        return 0
    except ImportError as exc:
        # Surface the real import that failed instead of assuming it is `mcp`
        # (mcp is now a core dependency). A deep ImportError in the runtime
        # should not be misreported as a missing MCP package.
        print(
            f"Failed to start the MCP server: {exc}\n"
            "If the 'mcp' package is missing, reinstall: pip install mnemos-continuity",
            file=sys.stderr,
        )
        return 1


def _cmd_inspect(args: argparse.Namespace) -> int:
    """Inspect a specific engram."""
    store = _get_store(args)
    engram = store.get_engram(args.engram_id)
    if engram is None:
        print(f"Engram not found: {args.engram_id}", file=sys.stderr)
        store.close()
        return 1

    print(f"ID:            {engram.id}")
    print(f"Content:       {engram.content}")
    print(f"Kind:          {engram.kind}")
    print(f"Tags:          {', '.join(engram.tags) or '(none)'}")
    print(f"State:         {engram.state}")
    print(f"Resolution:    {engram.resolution}")
    print(f"Strength:      {engram.strength:.4f}")
    print(f"Stability:     {engram.stability:.4f}")
    print(f"Accessibility: {engram.accessibility:.4f}")
    print(f"Confidence:    {engram.source.confidence} ({engram.source.confidence_source})")
    print(f"Created:       {engram.created_at}")
    print(f"Last accessed: {engram.last_accessed}")
    print(f"Access count:  {engram.access_count}")
    print(f"Reconsolidations: {engram.reconsolidation_count}")
    print(f"Connections:   {len(engram.connections)}")
    for c in engram.connections:
        print(f"  → {c.target_id[:25]}... ({c.relation}, strength={c.strength:.2f})")
    print(f"Versions:      {len(engram.versions)}")
    for v in engram.versions:
        print(f"  v{v.version_num}: {v.change_reason} at {v.changed_at}")
    if engram.content != engram.content_at_encoding:
        print(f"Original:      {engram.content_at_encoding[:100]}...")

    store.close()
    return 0


def _cmd_stats(args: argparse.Namespace) -> int:
    """Show memory statistics."""
    store = _get_store(args)
    agent_id = _resolve_agent_id(args)
    stats = store.get_stats(agent_id)

    print(f"Mnemos Stats (agent: {agent_id})")
    print(f"{'─' * 40}")
    print(f"Active engrams:      {stats.get('engrams_active', 0)}")
    print(f"Dormant engrams:     {stats.get('engrams_dormant', 0)}")
    print(f"Archived engrams:    {stats.get('archived', 0)}")
    print(f"Connections:         {stats.get('connections', 0)}")
    print(f"Active beliefs:      {stats.get('beliefs_active', 0)}")
    print(f"Functional active:   {stats.get('functional_active', 0)}")
    print(f"Functional pinned:   {stats.get('functional_pinned', 0)}")
    print(f"Needs confirmation:  {stats.get('functional_needs_confirmation', 0)}")
    print(f"Active sessions:     {stats.get('functional_sessions_active', 0)}")
    print(f"Hypomnema active:    {stats.get('hypomnema_active', 0)}")
    print(f"Reconsolidations:    {stats.get('reconsolidation_events', 0)}")
    if "accessibility_avg" in stats:
        print(f"Avg accessibility:   {stats['accessibility_avg']:.3f}")
        print(f"Min accessibility:   {stats['accessibility_min']:.3f}")
        print(f"Max accessibility:   {stats['accessibility_max']:.3f}")

    store.close()
    return 0


def _cmd_snapshot(args: argparse.Namespace) -> int:
    """Print an inline visual snapshot."""
    store = _get_store(args)
    from .interface.visual_snapshot import build_memory_visual_snapshot

    scope = _cli_scope(args)
    print(
        build_memory_visual_snapshot(
            store,
            agent_id=scope.agent_id,
            person_id=scope.person_id,
            project_scope=scope.project_scope,
            session_id=args.session_id,
            max_items=args.max_items,
        )
    )
    store.close()
    return 0


def _cmd_search(args: argparse.Namespace) -> int:
    """Search the memories by meaning and by words, as the agent's own recall
    finds them, and change nothing (``MnemosRuntime.search_memories``).

    It used to count as a return: the retriever reinforced what it found, so
    a person searching woke dormant memories, strengthened them and linked
    them, and it searched by words alone. It opened the store for writing
    too, which makes a store that isn't there. Now it reads only."""
    from .interface.person import Refused, search_view
    from .simple_runtime import how_found

    runtime = _journal_runtime(args, read_only=True)
    try:
        if args.json:
            try:
                view = search_view(runtime, args.query, args.max_results)
            except Refused as exc:
                print(exc, file=sys.stderr)
                return 2
            print(json.dumps(view, indent=2, ensure_ascii=False))
            return 0
        results = runtime.search_memories(args.query, max_results=args.max_results)
    finally:
        runtime.close()

    if not results:
        print("No memories found.")
        return 0

    for r in results:
        content = r.engram.content
        if len(content) > 80:
            content = content[:77] + "..."
        print(f"{how_found(r)} {content}")
        print(f"         id={r.engram.id} kind={r.engram.kind}")
    return 0


def _cmd_memories(args: argparse.Namespace) -> int:
    """List the memories, active and dormant, oldest first; reads only, and
    never creates a store (``interface.person.memories_view``)."""
    from .interface.person import Refused, memories_view

    try:
        view = memories_view(
            _cli_scope(args), state=args.state, limit=args.limit, offset=args.offset,
        )
    except Refused as exc:
        print(exc, file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(view, indent=2, ensure_ascii=False))
        return 0
    for index, memory in enumerate(view["memories"]):
        if index:
            print()
        header = f"{_utc_minute(memory['kept'])}, {memory['state']}, alive {memory['alive']:.2f}"
        if memory["corrected"]:
            header += f", corrected {_utc_minute(memory['corrected'])}"
        if memory["author"] == "person":
            header += ", in your words"
        print(header)
        print(f"  {memory['words']}".replace("\n", "\n  "))
        print(f"  id: {memory['id']}")
    counts = view["counts"]
    if view["memories"]:
        print()
    print(
        f"{counts['active']:,} active, {counts['dormant']:,} dormant, "
        f"{counts['archived']:,} archived."
    )
    return 0


def _cmd_correct(args: argparse.Namespace) -> int:
    """Correct a memory by its id (``MnemosRuntime.correct_memory``)."""
    return _change_memory(args, correcting=True)


def _cmd_forget(args: argparse.Namespace) -> int:
    """Forget a memory by its id (``MnemosRuntime.forget_memory``)."""
    return _change_memory(args, correcting=False)


def _change_memory(args: argparse.Namespace, *, correcting: bool) -> int:
    """`mnemos correct` and `mnemos forget`: the person's, run in their own
    terminal or app; the agent's in an agent's shell or with --signed-as, as
    ``mnemos remember`` decides (``authorship.run_by_agent``). A refusal is
    one plain sentence on stderr, and nothing changes."""
    from .authorship import run_by_agent
    from .code_version import OLDER_CODE_FIX, OLDER_CODE_MESSAGE
    from .simple_runtime import MnemosRuntime, NothingChanged

    signed_as = (getattr(args, "signed_as", "") or "").strip()
    agent = run_by_agent(signed_as)
    runtime = MnemosRuntime(
        db_path=getattr(args, "db_path", None),
        agent_id=getattr(args, "agent_id", None),
        person_id=getattr(args, "person_id", None),
        project_scope=getattr(args, "project_scope", None),
        use_dedicated_model=False,
        marks_lived=False,  # a person at the command line, not the agent living
    )
    try:
        try:
            if correcting:
                done = runtime.correct_memory(
                    args.memory_id, args.text, person=not agent, signed_as=signed_as,
                )
            else:
                done = runtime.forget_memory(args.memory_id, person=not agent, signed_as=signed_as)
        except NothingChanged as exc:
            print(exc, file=sys.stderr)
            return 1
        stale = runtime._stale()
    finally:
        runtime.close()
    if args.json:
        print(json.dumps(done, indent=2, ensure_ascii=False))
        return 0
    if correcting:
        whose = "as the agent's own words" if agent else "in your words"
        print(f"Corrected, {whose}: {done['id']} replaces {done['replaces']}.")
    else:
        print(f"Forgotten: {done['id']} is archived, never deleted, and recall won't bring it back.")
    if stale:
        print(f"{OLDER_CODE_MESSAGE} {OLDER_CODE_FIX}")
    return 0


def _cmd_interface(args: argparse.Namespace) -> int:
    """Answer the person's commands for an app until stdin closes
    (``interface.person.serve``)."""
    from .interface.person import serve

    return serve(**{
        key: getattr(args, key, None)
        for key in ("db_path", "agent_id", "person_id", "project_scope")
    })


def _cmd_consolidate(args: argparse.Namespace) -> int:
    """Run a consolidation cycle, holding the scope's claim on its maintenance
    while it runs."""
    store = _get_store(args)
    from .code_version import MAINTENANCE_CODE_VERSION, OLDER_CODE_FIX, OLDER_CODE_MESSAGE
    from .simple_runtime import claim_upkeep, release_upkeep, upkeep_claim_key

    # The same gate as maintenance through a session: code older than the
    # store runs none of the passes, whose rules newer code has replaced.
    minimum = store.min_code_version()
    if minimum is not None and minimum > MAINTENANCE_CODE_VERSION:
        store.close()
        print("Consolidation skipped: no passes ran.")
        print(
            f"This code is version {MAINTENANCE_CODE_VERSION}; the store needs "
            f"{minimum} or newer."
        )
        print(f"{OLDER_CODE_MESSAGE} {OLDER_CODE_FIX}")
        return 0

    # One cycle at a time per scope. A capture's maintenance claims the scope
    # before it starts a cycle, and this job took no claim: a capture while
    # the job's cycle ran found nothing running and started a second cycle
    # beside it. The job holds the same claim while it runs and gives it up
    # however it ends. While another process holds it, the job runs no cycle,
    # and the next run starts one.
    scope = _cli_scope(args)
    claim = upkeep_claim_key(scope.agent_id, scope.person_id, scope.project_scope)
    token = secrets.token_hex(8)
    taken = claim_upkeep(store, claim, token)
    if taken != "claimed":
        store.close()
        print("Consolidation skipped: no passes ran.")
        print(
            "Another process is running this memory's maintenance now."
            if taken == "running"
            else "The store was busy; the next run starts it."
        )
        return 0
    try:
        _consolidate(args, store, scope)
    finally:
        release_upkeep(store, claim, token)
        store.close()
    return 0


def _consolidate(args: argparse.Namespace, store, scope) -> None:
    """The job's cycle, its report and the indexing after it, run while the
    job holds the scope's claim (``_cmd_consolidate``)."""
    from .consolidation.daemon import ConsolidationDaemon
    from .llm import create_client

    llm_client = create_client()
    try:
        daemon_config = load_config()
    except Exception:
        daemon_config = {}
    # The cycle links by meaning with the index a session's maintenance uses
    # (``maintenance_index``), for `consolidate` and `--deep` alike. It was
    # given none, so the scheduled jobs linked by words alone. Without the
    # model the pass links by words and says why; the index serves the
    # indexing after the cycle too.
    try:
        from .simple_runtime import maintenance_index

        index = maintenance_index(_resolve_db_path(args))
    except Exception as exc:
        index = None
        print(f"Meaning search: off, the index could not be opened ({type(exc).__name__}: {exc})")
    daemon = ConsolidationDaemon(
        store=store, config=daemon_config, llm_client=llm_client, embedding_index=index,
    )
    label = "deep" if args.deep else "shallow"
    print(f"Running {label} consolidation...")

    stats = daemon.run_cycle(
        deep=args.deep, agent_id=scope.agent_id, person_id=scope.person_id,
        project_scope=scope.project_scope,
    )

    print(f"Passes: {', '.join(stats.get('passes_run', []))}")
    if "decay" in stats:
        d = stats["decay"]
        print(f"  Decay: {d.get('engrams_decayed', 0)} decayed, {d.get('engrams_archived', 0)} archived")
    if "connection_discovery" in stats:
        cd = stats["connection_discovery"]
        said = f"  Connections: {cd.get('connections_created', 0)} created, {cd.get('connections_strengthened', 0)} strengthened"
        if cd.get("connections_removed"):
            said += f", {cd['connections_removed']} removed"
        if cd.get("words_only"):
            said += f"; {cd['words_only']}"
        if cd.get("reclassify_stopped"):
            said += f"; {cd['reclassify_stopped']}"
        print(said)
    if "softening" in stats:
        s = stats["softening"]
        print(f"  Softening: {s.get('engrams_softened', 0)} softened")
    if "reflection" in stats:
        ref = stats["reflection"]
        print(f"  Reflection: {ref.get('thoughts_generated', 0)} thoughts, narrative={'updated' if ref.get('narrative_updated') else 'unchanged'}")

    # Check for errors
    errors = [k for k in stats if k.endswith("_error")]
    for e in errors:
        print(f"  ERROR ({e}): {stats[e]}", file=sys.stderr)

    _report_consolidation(store, scope, stats)
    _index_after_consolidating(store, args, scope, index)
    if index is not None:
        index.close()


def _report_consolidation(store, scope, stats: dict) -> None:
    """The cycle's maintenance report, under the dream journal's rule: written
    only when the cycle did something worth telling, superseding the last one,
    as a session's maintenance writes it (``dream_journal.report_cycle``).
    Without it the scheduled job's cycles went untold: the briefing's newest
    report fell behind what had changed, and the watchdog said so. The cycle
    has already run and nothing here can undo it."""
    try:
        from .dream_journal import report_cycle

        _entry, narrative = report_cycle(store, scope, stats)
    except Exception as exc:
        print(f"Maintenance report: not written ({type(exc).__name__}: {exc})")
        return
    print("Maintenance report: written" if narrative else "Maintenance report: none, nothing worth reporting")


def _index_after_consolidating(store, args: argparse.Namespace, scope, index=None) -> None:
    """Index a bounded part of what waits for recall's meaning search in the
    scope just consolidated (``SCHEDULED_INDEX_BUDGET``), after the cycle, so
    what code older than the store writes is indexed within hours without any
    session. Consolidation has already run and nothing here can undo or stop
    it: without the model, indexing is skipped and says why, and the health
    card says so too.

    ``index`` is the cycle's, used while it is on. One that went off in the
    cycle (a local model that failed to load), or none, is replaced by a
    fresh one from the same builder, so the failure is met and recorded here
    as it always was."""
    own = None
    try:
        from .simple_runtime import SCHEDULED_INDEX_BUDGET, index_for_recall, maintenance_index

        if index is None or not index.available:
            index = own = maintenance_index(_resolve_db_path(args))
        try:
            if not index.available:
                print(f"Recall index: off, {index.unavailable_reason}")
                return
            done = index_for_recall(
                store, index,
                agent_id=scope.agent_id, person_id=scope.person_id,
                project_scope=scope.project_scope,
                budget=SCHEDULED_INDEX_BUDGET, record="mnemos consolidate",
            )
        finally:
            if own is not None:
                own.close()
    except Exception as exc:
        print(f"Recall index: not updated ({type(exc).__name__}: {exc})")
        return
    if done["skipped"]:
        print(f"Recall index: skipped: {done['skipped']}")
    else:
        print(
            f"Recall index: {_items(done['items'])} indexed "
            f"({_passages(done['passages'])}, at most {SCHEDULED_INDEX_BUDGET} a run); "
            f"{done['waiting']} still waiting"
        )


def _items(count: int) -> str:
    return f"{count:,} memory or handoff" if count == 1 else f"{count:,} memories and handoffs"


def _passages(count: int) -> str:
    return f"{count:,} passage" if count == 1 else f"{count:,} passages"


def _cmd_export(args: argparse.Namespace) -> int:
    """Export workspace files."""
    store = _get_store(args)
    from .interface.openclaw_export import OpenClawExporter

    Path(args.workspace).expanduser().mkdir(parents=True, exist_ok=True)
    exporter = OpenClawExporter(store, args.workspace)
    result = exporter.export_all(_resolve_agent_id(args))

    for path, size in result.items():
        print(f"  Wrote {path} ({size} bytes)")

    store.close()
    return 0


def _cmd_setup_openclaw(args: argparse.Namespace) -> int:
    """Register OpenClaw cron jobs."""
    from .openclaw_cron import generate_cron_jobs, install_cron_jobs

    jobs = generate_cron_jobs(agent_id=args.agent)

    if args.dry_run:
        print("Would register the following cron jobs:")
        for job in jobs:
            print(f"  {job['name']}: {job['schedule']['expr']} → {job['payload']['message'][:60]}...")
        return 0

    result = install_cron_jobs(jobs)
    if result["success"]:
        print(f"Registered {result['jobs_added']} cron jobs for agent '{args.agent}'")
    else:
        print(f"Failed: {result['error']}", file=sys.stderr)
        return 1

    return 0


# What `mnemos index` says now, in place of indexing.
INDEX_RETIRED = """\
mnemos index is retired.
It had a model pull "facts" out of old conversations and file them as the
agent's own memories. Only the agent writes its memory, and on one install
the indexer wrote about 7,000 memories against 13 the agent kept itself.
What it wrote before is still in the store, marked as a tool's words. To see
it, and move it out of recall: mnemos repair quarantine-tool-written
(add --write to move it)."""


def _cmd_index(args: argparse.Namespace) -> int:
    """The transcript indexer, retired in 0.4.0: says so and why, and runs
    nothing."""
    print(INDEX_RETIRED, file=sys.stderr)
    return 1


def _cmd_bootstrap(args: argparse.Namespace) -> int:
    """Bootstrap a turnkey memory stack."""
    from .setup.bootstrap import bootstrap, print_result

    result = bootstrap(
        agent_name=args.agent_name,
        workspace=args.workspace,
        user_name=args.user_name,
        timezone=args.timezone,
        api_key=args.api_key,
        llm_provider=args.llm_provider,
        model=args.model,
    )

    print_result(result)
    return 1 if result["errors"] else 0


def _cmd_bridge(args: argparse.Namespace) -> int:
    """Direct memory operations via bridge."""
    from .bridge import MnemosBridge

    bridge = MnemosBridge(agent_id=_resolve_agent_id(args), db_path=_resolve_db_path(args))

    if args.bridge_command == "status":
        print(bridge.status())
    elif args.bridge_command == "recall":
        print(bridge.recall(args.query))
    elif args.bridge_command == "remember":
        print(bridge.remember(args.content, impact=args.impact))
    else:
        print("Usage: mnemos bridge {status|recall|remember}", file=sys.stderr)
        return 1
    return 0


def _cmd_remember(args: argparse.Namespace) -> int:
    """Keep what the person types, in their own words: the mnemos_capture
    path, unsigned, as the person's (``author_kind`` 'person').

    Run from an agent's own shell (``CLAUDECODE`` or ``AI_AGENT`` set, as
    Claude Code sets it in every shell its agent runs) or with
    ``--signed-as``, it keeps the agent's own words, signed, as before."""
    import re

    from .authorship import run_by_agent
    from .code_version import OLDER_CODE_FIX, OLDER_CODE_MESSAGE
    from .simple_runtime import MnemosRuntime

    signed_as = (getattr(args, "signed_as", "") or "").strip()
    agent = run_by_agent(signed_as)

    runtime = MnemosRuntime(
        db_path=getattr(args, "db_path", None),
        agent_id=getattr(args, "agent_id", None),
        person_id=getattr(args, "person_id", None),
        project_scope=getattr(args, "project_scope", None),
        use_dedicated_model=False,  # CLI capture stays local and deterministic
        marks_lived=False,  # a person at the command line, not the agent living
    )
    try:
        close = _close_note(runtime, args.content)
        if close is not None:
            words = " ".join(str(close.get("content") or "").split())[:80]
            print(f'A memory already says something close: "{words}" ({close["id"]}). Saved yours too.')
        if agent:
            # The agent's own words, signed, from its own shell.
            said = runtime.capture(
                args.content, context=args.context, importance=args.importance,
                impact=getattr(args, "impact", ""), signed_as=signed_as,
            )
        else:
            # The person's own words, unsigned: never the agent's.
            said = runtime.capture(
                args.content, context=args.context, importance=args.importance,
                impact=getattr(args, "impact", ""), author_kind="person",
            )
        kept = re.search(r"Memory ID: (\S+)", said)
        if kept is None:
            print(said)
            return 1
        if agent:
            print(f"Remembered, as the agent's own words: {kept.group(1)}")
        else:
            print(f"Remembered, in your words: {kept.group(1)}")
        if runtime._stale():
            print(f"{OLDER_CODE_MESSAGE} {OLDER_CODE_FIX}")
        return 0
    finally:
        runtime.close()


def _close_note(runtime, content: str) -> dict | None:
    """The active note that ``content`` names, searched the way
    ``correct(query=...)`` searches, or None."""
    from .simple_runtime import _named_matches

    if not content.strip():
        return None
    runtime._ensure_init()
    matches = _named_matches(content, runtime._store.search_hypomnema(
        content,
        **runtime._scope_args(),
        limit=10,
        exclude_kinds=("handoff",),
        live_only=False,
    ), lambda note: note.get("content") or "")
    return matches[0] if matches else None


def _cmd_life(args: argparse.Namespace) -> int:
    from . import life
    from .simple_scope import resolve_scope

    scope_args = {
        key: getattr(args, key, None)
        for key in ("db_path", "agent_id", "person_id", "project_scope")
    }
    record = life.run_hour(
        args.hour, **scope_args, dry_run=args.dry_run, config_dir=args.config_dir,
        store_copy=args.store_copy, max_minutes=args.max_minutes, max_tokens=args.max_tokens,
    )
    if args.dry_run and record.get("status") == "failed":
        print(record["reason"], file=sys.stderr)
        return 1
    if not args.dry_run:
        kind, hour_id, status, reason = (record[key] for key in ("kind", "id", "status", "reason"))
        print(f"{kind} hour {hour_id}: {status}" + (f". {reason}" if reason else "."))
        scope = resolve_scope(**scope_args)
        print(f"Record: {life.hours_dir(scope.agent_id) / 'hours.jsonl'}")
    return 1 if record.get("status") == "failed" else 0


def _journal_runtime(args: argparse.Namespace, *, read_only: bool):
    """The runtime the journal and notes commands read or write through, with
    the scope the same resolver gives every other command."""
    from .simple_runtime import MnemosRuntime

    return MnemosRuntime(
        db_path=getattr(args, "db_path", None),
        agent_id=getattr(args, "agent_id", None),
        person_id=getattr(args, "person_id", None),
        project_scope=getattr(args, "project_scope", None),
        use_dedicated_model=False,
        read_only=read_only,
        marks_lived=False,
    )


def _utc_minute(created_at: str) -> str:
    """``2026-10-02T04:12:33+00:00`` as ``2026-10-02 04:12 UTC``."""
    return f"{(created_at or '')[:16].replace('T', ' ')} UTC"


def _cmd_journal(args: argparse.Namespace) -> int:
    """Read the agent's journal, newest first. The agent writes it, only
    through its own tool; this only reads, and never creates a store."""
    from .authorship import display_name

    if args.last < 1:
        print("--last takes a number of entries, 1 or more.", file=sys.stderr)
        return 2
    runtime = _journal_runtime(args, read_only=True)
    try:
        entries = runtime.journal_entries(last=args.last)
    finally:
        runtime.close()
    if args.json:
        print(json.dumps(entries, indent=2, ensure_ascii=False))
        return 0
    if not entries:
        print("The journal is empty.")
        return 0
    for index, entry in enumerate(entries):
        if index:
            print()
        header = f"{_utc_minute(entry['created_at'])}, {entry['written'].replace('_', ' ')}"
        if entry["model"]:
            header += f", {display_name(entry['model'])}"
        if entry["mood"]:
            header += f", mood: {entry['mood']}"
        print(header)
        print(entry["text"])
    return 0


def _cmd_notes(args: argparse.Namespace) -> int:
    """The notes the agent left you and your replies: list them, or reply."""
    from .authorship import display_name
    from .simple_runtime import current_hour

    if getattr(args, "notes_command", None) == "reply":
        return _cmd_notes_reply(args)
    runtime = _journal_runtime(args, read_only=True)
    try:
        notes = runtime.notes(unread=args.unread)
    finally:
        runtime.close()
    if args.json:
        # The interface reads this: only reading, so nothing is marked read.
        print(json.dumps(notes, indent=2, ensure_ascii=False))
        return 0
    if not notes:
        print("No unread notes." if args.unread else "No notes yet.")
        return 0
    for index, note in enumerate(notes):
        if index:
            print()
        if note["author"] == "person":
            header = f"{_utc_minute(note['created_at'])}  your reply"
        else:
            by = display_name(note["model"]) if note["model"] else "unsigned"
            unread = "" if note["read_at"] else "  (unread)"
            header = f"{_utc_minute(note['created_at'])}  {note['kind'] or 'note'}, {by}{unread}"
        print(header)
        print(f"  {note['text']}".replace("\n", "\n  "))
        if note["in_reply_to"]:
            print(f"  answers: {note['in_reply_to']}")
        print(f"  id: {note['id']}")
    # Reading them is what makes them read; a pass of the agent's own hours has
    # no one in the room to have read anything.
    unread_ids = [note["id"] for note in notes if note["author"] == "agent" and not note["read_at"]]
    if unread_ids and not current_hour():
        # Bookkeeping: they were shown, and a lock held by another process
        # must not make the listing look as though it failed.
        try:
            writer = _journal_runtime(args, read_only=False)
            try:
                writer.mark_notes_read(unread_ids)
            finally:
                writer.close()
        except sqlite3.Error:
            pass
    return 0


def _cmd_notes_reply(args: argparse.Namespace) -> int:
    """Store your own reply to one of the agent's notes. It is your words, kept
    as yours (never signed as a model's), and the agent wakes with it once."""
    probe = _journal_runtime(args, read_only=False)
    try:
        if not probe.db_path.exists():
            print("Nothing saved: there are no notes here yet.", file=sys.stderr)
            return 1
        try:
            reply_id = probe.reply_to_note(args.note_id, " ".join(args.text))
        except ValueError as exc:
            print(f"Nothing saved: {exc}", file=sys.stderr)
            return 1
        # Answering a note is reading it. Bookkeeping: the reply is kept either
        # way, so a failure here must not make it look unsaved.
        try:
            probe.mark_notes_read([args.note_id])
        except sqlite3.Error:
            pass
    finally:
        probe.close()
    print("Reply kept, in your own words.")
    print(f"Reply ID: {reply_id}")
    return 0


def _cmd_log(args: argparse.Namespace) -> int:
    """Serve the log, a read-only page of the agent's days, on 127.0.0.1 until
    Ctrl-C. Whose: the scope every other command resolves."""
    from .companion.server import serve

    return serve(
        db_path=getattr(args, "db_path", None),
        agent_id=getattr(args, "agent_id", None),
        person_id=getattr(args, "person_id", None),
        project_scope=getattr(args, "project_scope", None),
        person=args.person_name,
        open_browser=not args.no_open,
    )


def _cmd_repair_softening(args: argparse.Namespace) -> int:
    """Restore memories an earlier version truncated without a model.

    Before ``soften_without_model`` defaulted to False, a store with no
    provider rewrote fading memories to "An impression related to <word>...
    [faded]" and left the impact empty. Nothing recovers that on its own.
    """
    from .simple_runtime import MnemosRuntime

    runtime = MnemosRuntime(
        db_path=getattr(args, "db_path", None),
        agent_id=getattr(args, "agent_id", None),
        person_id=getattr(args, "person_id", None),
        project_scope=getattr(args, "project_scope", None),
        marks_lived=False,
    )
    try:
        dry_run = bool(getattr(args, "dry_run", False))
        count = runtime.repair_softening(dry_run=dry_run)
        if not count:
            print(f"Nothing to repair in {runtime.db_path}.")
            return 0
        verb = "would be restored" if dry_run else "restored"
        print(f"{count} memory(ies) {verb} in {runtime.db_path}.")
        if dry_run:
            print("Re-run without --dry-run to write the restoration.")
        return 0
    finally:
        runtime.close()


def _cmd_repair_lessons(args: argparse.Namespace) -> int:
    """Remove the lesson links that were filed wrong, and only those.

    Softening used to take the first lesson sharing any word with a fading
    memory's impact as the lesson it taught, and to file placeholder impacts
    under placeholder lessons. A human runs this: a dry run unless --write,
    and a verified backup before anything is removed.
    """
    from .simple_runtime import MnemosRuntime

    runtime = MnemosRuntime(
        db_path=getattr(args, "db_path", None),
        agent_id=getattr(args, "agent_id", None),
        person_id=getattr(args, "person_id", None),
        project_scope=getattr(args, "project_scope", None),
        marks_lived=False,
    )
    try:
        plan = runtime.repair_lessons(write=args.write)
    finally:
        runtime.close()

    if not plan["exists"]:
        print(f"No store at {runtime.db_path}; nothing to repair.")
        return 0

    agent, person, project = plan["target"]
    reasons = {"unrelated": 0, "placeholder": 0}
    for item in plan["misfiled"]:
        reasons[item["reason"]] += 1
    kept = plan["links"] - len(plan["misfiled"])
    print(f"Lesson links for {agent} / {person} / {project} in {runtime.db_path}")
    print()
    print(f"  {plan['links']:>7,}  links from a memory to the lesson it taught")
    print(f"  {reasons['unrelated']:>7,}  to a lesson that says something else    go")
    print(f"  {reasons['placeholder']:>7,}  from a placeholder impact               go")
    print(f"  {kept:>7,}  that hold                                stay")
    if not plan["misfiled"]:
        print()
        print("Nothing to repair.")
        return 0
    print()
    if args.write:
        print(f"Removed {plan['removed']:,} links. Backup: {plan['backup']}")
        print("A memory whose link went is filed again, correctly, the next time it fades.")
    else:
        print("Dry run: nothing changed. Run again with --write to remove them")
        print("(a verified backup is made first).")
    return 0


def _cmd_repair_versions(args: argparse.Namespace) -> int:
    """Remove the version rows that only repeat the one before them.

    Every return used to append a full copy of the memory to its history,
    although nothing a version records had changed. A human runs this: a dry
    run unless --write, and a verified backup before anything is removed.
    """
    from .simple_runtime import MnemosRuntime

    runtime = MnemosRuntime(
        db_path=getattr(args, "db_path", None),
        agent_id=getattr(args, "agent_id", None),
        person_id=getattr(args, "person_id", None),
        project_scope=getattr(args, "project_scope", None),
        marks_lived=False,
    )
    try:
        plan = runtime.repair_versions(write=args.write)
    finally:
        runtime.close()

    if not plan["exists"]:
        print(f"No store at {runtime.db_path}; nothing to repair.")
        return 0

    found = plan["found"]
    copies = len(found["duplicates"])

    def row(count: int, what: str, action: str = "") -> None:
        print(f"  {count:>9,}  {what:<56} {action}".rstrip())

    print(f"Version history in {runtime.db_path}")
    print()
    row(found["rows"], f"version rows, for {found['memories']:,} memories")
    row(copies, "copies of the version before them, written by a return", "go")
    row(found["rows"] - copies, "that record a state or a change", "stay")
    for engram_id, count in found["most_repeated"]:
        print(f"             {engram_id}: {count:,} copies")

    print()
    if plan["older_than_store"]:
        print(
            "This code is older than the store expects, so it changes nothing. "
            "Run the repair with current Mnemos."
        )
        return 1 if args.write else 0
    if not copies:
        print("Nothing to repair.")
        return 0
    if args.write:
        print(
            f"Removed {plan['removed']:,} rows; {found['rows'] - plan['removed']:,} "
            f"remain. Backup: {plan['backup']}"
        )
        print("The file keeps its size; SQLite reuses the space.")
    else:
        print("Dry run: nothing changed. Run again with --write to remove them")
        print("(a verified backup is made first).")
    return 0


def _cmd_repair(args: argparse.Namespace) -> int:
    """Guarded repairs named by what they repair: `mnemos repair <what>`."""
    if getattr(args, "repair_command", None) == "min-code-version":
        return _cmd_repair_min_code_version(args)
    if getattr(args, "repair_command", None) == "keyword-contradictions":
        return _cmd_repair_keyword_contradictions(args)
    if getattr(args, "repair_command", None) == "quarantine-tool-written":
        return _cmd_repair_quarantine_tool_written(args)
    clean_ups = {
        "split-notes": _cmd_repair_split_notes,
        "archive-rows": _cmd_repair_archive_rows,
        "dead-embeddings": _cmd_repair_dead_embeddings,
        "placeholder-impacts": _cmd_repair_placeholder_impacts,
        "faded-words": _cmd_repair_faded_words,
        "word-questions": _cmd_repair_word_questions,
        "early-lessons": _cmd_repair_early_lessons,
    }
    if getattr(args, "repair_command", None) in clean_ups:
        return clean_ups[args.repair_command](args)
    print(
        "Usage: mnemos repair min-code-version [--set N] [--write]\n"
        "       mnemos repair keyword-contradictions [--write]\n"
        "       mnemos repair quarantine-tool-written [--write]\n"
        "       mnemos repair split-notes [--write]\n"
        "       mnemos repair archive-rows [--write]\n"
        "       mnemos repair dead-embeddings [--write]\n"
        "       mnemos repair placeholder-impacts [--write]\n"
        "       mnemos repair faded-words [--write]\n"
        "       mnemos repair word-questions [--write]\n"
        "       mnemos repair early-lessons [--write]",
        file=sys.stderr,
    )
    return 1


def _repair_runtime(args: argparse.Namespace) -> Any:
    from .simple_runtime import MnemosRuntime

    return MnemosRuntime(
        db_path=getattr(args, "db_path", None),
        agent_id=getattr(args, "agent_id", None),
        person_id=getattr(args, "person_id", None),
        project_scope=getattr(args, "project_scope", None),
        marks_lived=False,
    )


def _repair_ending(plan: dict[str, Any], args: argparse.Namespace, *, todo: bool,
                   done: str, verb: str) -> int:
    """How every clean-up ends: refused by older code, nothing to do, done
    (with the backup's path), or a dry run."""
    print()
    if plan["older_than_store"]:
        print(
            "This code is older than the store expects, so it changes nothing. "
            "Run the repair with current Mnemos."
        )
        return 1 if args.write else 0
    if not todo:
        print("Nothing to repair.")
        return 0
    if args.write:
        print(f"{done} Backup: {plan['backup']}")
    else:
        print(f"Dry run: nothing changed. Run again with --write to {verb}")
        print("(a verified backup is made first).")
    return 0


def _repair_row(count: int, what: str, action: str = "") -> None:
    print(f"  {count:>7,}  {what:<58} {action}".rstrip())


def _repair_count(count: int, one: str, many: str = "") -> str:
    return f"{count:,} {one if count == 1 else (many or one + 's')}"


def _repair_words(text: str, limit: int = 80) -> str:
    words = " ".join((text or "").split())
    return words if len(words) <= limit else words[: limit - 1].rstrip() + "…"


def _cmd_repair_split_notes(args: argparse.Namespace) -> int:
    """Join again the notes older code left apart from their memories.

    Before one capture was one object, correcting a note rewrote it and left
    its memory saying the old words, and correcting a memory saved the
    correction as a new memory without a note, leaving the old note over the
    archived memory. The agent's newest words win; history keeps both. A
    human runs this: a dry run unless --write, and a verified backup first.
    """
    runtime = _repair_runtime(args)
    try:
        plan = runtime.repair_split_notes(write=args.write)
    finally:
        runtime.close()

    if not plan["exists"]:
        print(f"No store at {runtime.db_path}; nothing to repair.")
        return 0

    agent, person, project = plan["target"]
    found = plan["found"]
    print(f"Notes and their memories for {agent} / {person} / {project} in {runtime.db_path}")
    print()
    _repair_row(found["notes"], "notes in use, each with a memory of its own")
    _repair_row(found["same"], "that say what their memory says", "stay")
    _repair_row(
        len(found["ahead"]), "corrected, while the memory kept the old words",
        "the memory takes the note's words",
    )
    _repair_row(
        len(found["behind"]), "over a replaced memory, while the new one has no note",
        "the note moves to the new memory",
    )
    if found["differ"]:
        _repair_row(len(found["differ"]), "that differ from their memory for another reason", "stay")
    if found["unclear"]:
        _repair_row(len(found["unclear"]), "that can't be joined without a guess", "stay")
    for item in found["ahead"]:
        print(f"           - memory {item['memory_id']} (note {item['note_id']})")
        print(f"             was: \"{_repair_words(item['memory_words'])}\"")
        print(f"             now: \"{_repair_words(item['words'])}\"")
    for item in found["behind"]:
        print(f"           - note {item['note_id']}: memory {item['memory_id']} -> "
              f"{item['replacement_id']}")
        if item["words_change"]:
            print(f"             now: \"{_repair_words(item['words'])}\"")
    for item in [*found["differ"], *found["unclear"]]:
        print(f"           - left alone: note {item['note_id']}, memory {item['memory_id']}")

    todo = bool(found["ahead"] or found["behind"])
    done = plan["done"] or {"ahead": 0, "behind": 0}
    return _repair_ending(
        plan, args, todo=todo,
        done=(
            f"Joined {_repair_count(done['ahead'] + done['behind'], 'pair')}: "
            f"{_repair_count(done['ahead'], 'memory', 'memories')} took the note's "
            f"words, {_repair_count(done['behind'], 'note')} moved to the memory that "
            "replaced theirs. Their new words are found by meaning after the next "
            "maintenance, or at once with: mnemos --db-path "
            f"{shlex.quote(str(runtime.db_path))} embeddings index."
        ),
        verb="join them",
    )


def _cmd_repair_archive_rows(args: argparse.Namespace) -> int:
    """Drop the archive rows that only repeat a memory no longer archived.

    A human runs this: a dry run unless --write, and a verified backup first.
    """
    runtime = _repair_runtime(args)
    try:
        plan = runtime.repair_archive_rows(write=args.write)
    finally:
        runtime.close()

    if not plan["exists"]:
        print(f"No store at {runtime.db_path}; nothing to repair.")
        return 0

    found = plan["found"]
    states = ", ".join(
        f"{count:,} {'quiet' if state == 'dormant' else state}"
        for state, count in sorted(found["repeats_by_state"].items())
    )
    print(f"Archive rows in {runtime.db_path}")
    print()
    _repair_row(found["rows"], "rows in the archive")
    _repair_row(found["archived"], "for memories in the archive", "stay")
    _repair_row(len(found["repeats"]), "repeating a memory no longer archived, word for word", "go")
    if states:
        print(f"           ({states})")
    _repair_row(
        len(found["history"]), "for a memory no longer archived, in other words", "stay, as history"
    )
    _repair_row(found["gone"], "for memories no longer in the store", "stay")

    done = plan["done"] or {"dropped": 0}
    return _repair_ending(
        plan, args, todo=bool(found["repeats"]),
        done=(
            f"Dropped {_repair_count(done['dropped'], 'row')}; "
            f"{found['rows'] - done['dropped']:,} remain. "
            "The file keeps its size; SQLite reuses the space."
        ),
        verb="drop them",
    )


def _cmd_repair_dead_embeddings(args: argparse.Namespace) -> int:
    """Prune stored vectors from embedding models this Mnemos does not use.

    A human runs this: a dry run unless --write, and a verified backup first.
    With no embedding model set up where it runs, it prunes nothing.
    """
    runtime = _repair_runtime(args)
    try:
        plan = runtime.repair_dead_embeddings(write=args.write)
    finally:
        runtime.close()

    if not plan["exists"]:
        print(f"No store at {runtime.db_path}; nothing to repair.")
        return 0

    found = plan["found"]
    model = plan["model"]
    print(f"Stored embeddings in {runtime.db_path}")
    if model:
        print(f"This Mnemos embeds with: {plan['backend']} model {model}")
    else:
        print(f"This Mnemos embeds with no model here (why: {plan['reason']}).")
    for table, title in (("embeddings", "Whole-text vectors"), ("passage_vectors", "Passages")):
        print()
        print(title)
        if not found[table]:
            _repair_row(0, "stored")
        for name, count in found[table].items():
            action = "" if not model else ("stay" if name == model else "go")
            _repair_row(count, name, action)

    if not model:
        print()
        print(
            "With no model in use here, a dead vector can't be told from a live one, "
            "so nothing is pruned. Run it where Mnemos embeds (the same Python and "
            "settings as the server)."
        )
        return 1 if args.write else 0
    dead = sum(
        count for table in ("embeddings", "passage_vectors")
        for name, count in found[table].items() if name in found["dead"]
    )
    done = plan["done"] or {"embeddings": 0, "passage_vectors": 0}
    return _repair_ending(
        plan, args, todo=bool(dead),
        done=(
            f"Pruned {_repair_count(done['embeddings'], 'whole-text vector')} and "
            f"{_repair_count(done['passage_vectors'], 'passage')}. The file keeps its "
            "size; SQLite reuses the space."
        ),
        verb="prune them",
    )


def _cmd_repair_placeholder_impacts(args: argparse.Namespace) -> int:
    """Empty the meanings the server wrote itself, leaving them to the agent.

    A human runs this: a dry run unless --write, and a verified backup first.
    """
    runtime = _repair_runtime(args)
    try:
        plan = runtime.repair_placeholder_impacts(write=args.write)
    finally:
        runtime.close()

    if not plan["exists"]:
        print(f"No store at {runtime.db_path}; nothing to repair.")
        return 0

    found = plan["found"]
    print(f"Meanings the server wrote itself, in {runtime.db_path}")
    print()
    for text, ids in found["by_text"].items():
        _repair_row(len(ids), f'"{text}"', "emptied")
    if found["left"]:
        _repair_row(
            sum(found["left"].values()), "other phrases, from the older capture path",
            "stay (not this repair)",
        )
        for text, count in sorted(found["left"].items(), key=lambda item: (-item[1], item[0])):
            print(f"           {count:>3,}  \"{text}\"")

    done = plan["done"] or {"emptied": 0}
    return _repair_ending(
        plan, args, todo=any(found["by_text"].values()),
        done=(
            f"Emptied {_repair_count(done['emptied'], 'meaning')}; what each meant is "
            "left to the agent."
        ),
        verb="empty them",
    )


def _cmd_repair_word_questions(args: argparse.Namespace) -> int:
    """Remove the word-count belief asks that hold no words of the agent's.

    A human runs this: a dry run unless --write, and a verified backup first.
    """
    runtime = _repair_runtime(args)
    try:
        plan = runtime.repair_word_questions(write=args.write)
    finally:
        runtime.close()
    if not plan["exists"]:
        print(f"No store at {runtime.db_path}; nothing to repair.")
        return 0
    found = plan["found"]
    empty, worded = found["empty"], found["worded"]
    _repair_row(len(empty), "word questions with no words of yours", "removed")
    _repair_row(len(worded), "word questions you wrote on", "stay")
    done = plan["done"] or {"removed": 0}
    return _repair_ending(
        plan, args, todo=bool(empty),
        done=f"Removed {_repair_count(done['removed'], 'word question')}; nothing you wrote was touched.",
        verb="remove them",
    )


def _cmd_repair_early_lessons(args: argparse.Namespace) -> int:
    """Fold back the lessons and fading questions drawn before a memory faded.

    A human runs this: a dry run unless --write, and a verified backup first.
    """
    runtime = _repair_runtime(args)
    try:
        plan = runtime.repair_early_lessons(write=args.write)
    finally:
        runtime.close()
    if not plan["exists"]:
        print(f"No store at {runtime.db_path}; nothing to repair.")
        return 0
    found = plan["found"]
    lessons, questions = found["lessons"], found["questions"]
    _repair_row(len(lessons), "lessons that repeat a memory's meaning before it faded", "archived (recallable)")
    _repair_row(len(questions), "'this is fading' questions about memories in reach", "removed")
    done = plan["done"] or {"lessons": 0, "questions": 0}
    return _repair_ending(
        plan, args, todo=bool(lessons or questions),
        done=f"Folded back {_repair_count(done['lessons'], 'lesson')} and removed {_repair_count(done['questions'], 'question')}. Each memory keeps its meaning, and is asked again when it really fades.",
        verb="fold them back",
    )


def _cmd_repair_faded_words(args: argparse.Namespace) -> int:
    """Bring back the words an earlier softening cut, from the words the
    memories were encoded with (one scope).

    A human runs this: a dry run unless --write, and a verified backup first.
    """
    runtime = _repair_runtime(args)
    try:
        plan = runtime.repair_faded_words(write=args.write)
    finally:
        runtime.close()

    if not plan["exists"]:
        print(f"No store at {runtime.db_path}; nothing to repair.")
        return 0

    agent, person, project = plan["target"]
    found = plan["found"]
    print(f"Faded words for {agent} / {person} / {project} in {runtime.db_path}")
    print()
    _repair_row(found["faded"], "live memories whose words were cut when they faded")
    _repair_row(
        len(found["restorable"]), "that come back whole from their words at encoding",
        "restored",
    )
    if found["left"]:
        _repair_row(
            len(found["left"]), "whose words don't come from their words at encoding", "stay",
        )
    for item in found["restorable"]:
        quiet = " (quiet)" if item["state"] == "dormant" else ""
        print(f"           - memory {item['id']}{quiet}")
        for label, words in (("now", item["words"]), ("was", item["encoded"])):
            print(
                f"             {label}: \"{_repair_words(words)}\" "
                f"({len(words.strip()):,} characters)"
            )
    for item in found["left"]:
        print(f"           - left alone: memory {item['id']}")

    done = plan["done"] or {"restored": 0}
    return _repair_ending(
        plan, args, todo=bool(found["restorable"]),
        done=(
            f"Restored {_repair_count(done['restored'], 'memory', 'memories')}; each "
            "keeps its cut words as a version. Their words are found by meaning after "
            "the next maintenance, or at once with: mnemos --db-path "
            f"{shlex.quote(str(runtime.db_path))} embeddings index."
        ),
        verb="restore them",
    )


def _cmd_repair_quarantine_tool_written(args: argparse.Namespace) -> int:
    """Move the memories a tool wrote out of this scope, into the quarantine.

    The transcript indexer's model wrote memories and lessons into the same
    scope as the agent's own, where recall and the packet reached them as the
    agent's. A human runs this: a dry run unless --write, a verified backup
    before anything moves, and `mnemos adopt-legacy --include indexer` brings
    them back.
    """
    from .simple_runtime import MnemosRuntime

    runtime = MnemosRuntime(
        db_path=getattr(args, "db_path", None),
        agent_id=getattr(args, "agent_id", None),
        person_id=getattr(args, "person_id", None),
        project_scope=getattr(args, "project_scope", None),
        marks_lived=False,
    )
    try:
        plan = runtime.repair_quarantine_tool_written(write=args.write, undo=args.undo)
    finally:
        runtime.close()

    if not plan["exists"]:
        print(f"No store at {runtime.db_path}; nothing to repair.")
        return 0

    agent, person, project = plan["target"]
    found = plan["found"]
    archived = sum(1 for row in found if row["state"] == "archived")
    linked = sum(1 for row in found if row["state"] != "archived" and row["linked"])
    movable = plan["movable"]

    def row(count: int, what: str, action: str = "") -> None:
        print(f"  {count:>7,}  {what:<52} {action}".rstrip())

    if plan["undo"]:
        print(f"Memories quarantine-tool-written moved out of {agent} / {person} / "
              f"{project}, {runtime.db_path}")
        print()
        row(len(movable), "still in the quarantine", "come back")
        if archived:
            row(archived, "archived since", "stay archived")
        print()
        if plan["older_than_store"]:
            print(
                "This code is older than the store expects, so it changes nothing. "
                "Run the repair with current Mnemos."
            )
            return 1 if args.write else 0
        if not movable:
            print("Nothing to bring back.")
            return 0
        if args.write:
            print(f"Brought back {plan['moved']:,} memories. Backup: {plan['backup']}")
        else:
            print("Dry run: nothing changed. Run again with --undo --write to bring")
            print("them back (a verified backup is made first).")
        return 0

    print(f"Memories a tool wrote in {agent} / {person} / {project}, {runtime.db_path}")
    print()
    row(len(found), "written by a tool (the indexer or the substrate)")
    row(len(movable), "in recall and the packet", "move to the quarantine")
    if linked:
        row(linked, "that a continuity note points at", "stay")
    if archived:
        row(archived, "archived", "stay archived")
    for item in movable[:5]:
        text = " ".join(str(item["content"]).split())
        print(f"           - {text[:90]}{'...' if len(text) > 90 else ''}")

    print()
    if plan["older_than_store"]:
        print(
            "This code is older than the store expects, so it changes nothing. "
            "Run the repair with current Mnemos."
        )
        return 1 if args.write else 0
    if not movable:
        print("Nothing to move.")
        return 0
    if args.write:
        print(f"Moved {plan['moved']:,} memories into the quarantine. Backup: {plan['backup']}")
        print("Bring exactly these back with: mnemos repair quarantine-tool-written "
              "--undo --write")
    else:
        print("Dry run: nothing changed. Run again with --write to move them")
        print("(a verified backup is made first). '--undo --write' brings exactly")
        print("these back; 'mnemos adopt-legacy --include indexer' brings back all")
        print("tool-written memories the quarantine holds.")
    return 0


def _cmd_repair_keyword_contradictions(args: argparse.Namespace) -> int:
    """Undo what the removed no-model keyword-and-negation check wrote.

    Without a model, encoding lowered a belief and linked the new memory as
    contradicting it whenever the two shared a word and the memory held a
    negation. A human runs this: a dry run unless --write, and a verified
    backup before anything changes. Beliefs belong to the agent, so it covers
    the agent's memories in every scope.
    """
    from .simple_runtime import MnemosRuntime

    runtime = MnemosRuntime(
        db_path=getattr(args, "db_path", None),
        agent_id=getattr(args, "agent_id", None),
        person_id=getattr(args, "person_id", None),
        project_scope=getattr(args, "project_scope", None),
        marks_lived=False,
    )
    try:
        plan = runtime.repair_keyword_contradictions(write=args.write)
    finally:
        runtime.close()

    if not plan["exists"]:
        print(f"No store at {runtime.db_path}; nothing to repair.")
        return 0

    found = plan["found"]
    links = found["links"]

    def row(count: int, what: str, action: str) -> None:
        print(f"  {count:>7,}  {what:<52} {action}")

    print(f"Keyword contradictions for agent {plan['agent_id']} in {runtime.db_path}")
    print()
    print("Contradiction links")
    row(len(links), "the check's: from notes saved without a model", "go")
    row(len(found["model_links"]), "of its shape, from notes a model weighed", "stay")
    row(len(found["ambiguous_links"]), "of its shape, but nothing shows how they were saved", "stay")
    row(found["other_links"], "not of its shape", "stay")
    if links:
        notes = len({link["source_id"] for link in links})
        by_link = sum(1 for link in links if link["no_model_link"])
        by_revision = sum(1 for link in links if link["revision"])
        print(
            f"           ({notes:,} notes; {by_link:,} links shown by a no-model link, "
            f"{by_revision:,} by a revision the check wrote)"
        )
    print("Belief revisions")
    row(found["revisions"], "the check's, lowering an active belief by 0.05", "undone")
    if found["retired_revisions"]:
        row(found["retired_revisions"], "the check's, on retired beliefs", "stay")
    if found["ambiguous_revisions"]:
        row(found["ambiguous_revisions"], "with its reason but not its step", "stay")
    if found["beliefs"]:
        print("Beliefs")
        for item in found["beliefs"]:
            content = " ".join((item["content"] or "").split())
            if len(content) > 56:
                content = content[:55].rstrip() + "…"
            count = item["revisions"]
            print(
                f"  {item['before']:.2f} -> {item['after']:.2f}  {item['belief_id']}  "
                f"{count} revision{'s' if count != 1 else ''}  \"{content}\""
            )
    if found["ambiguous_links"]:
        print("Ambiguous links, left alone")
        for link in found["ambiguous_links"]:
            print(f"  {link['source_id']} -> {link['target_id']}  {link['formed_at']}")

    print()
    if plan["older_than_store"]:
        print(
            "This code is older than the store expects, so it changes nothing. "
            "Run the repair with current Mnemos."
        )
        return 1 if args.write else 0
    if not (links or found["beliefs"]):
        print("Nothing to repair.")
        return 0
    if args.write:
        print(
            f"Removed {plan['removed']:,} links and restored {plan['restored']:,} "
            f"beliefs. Backup: {plan['backup']}"
        )
    else:
        print("Dry run: nothing changed. Run again with --write to undo them")
        print("(a verified backup is made first).")
    return 0


def _cmd_repair_min_code_version(args: argparse.Namespace) -> int:
    """Show, or reset, the lowest code version allowed to maintain a store.

    Every Mnemos that opens a store raises this to its own version, and code
    below it stops maintaining the store. If code newer than what is
    installed raised it, nothing installed here maintains the store again
    until it is updated or reset. A human runs this: a dry run unless
    --write, a verified backup before any change, and never below 1.
    """
    from .simple_runtime import MnemosRuntime

    set_to = args.set_to
    if set_to is not None and set_to < 1:
        print(f"Refused: the minimum code version is 1 or more, not {set_to}.")
        return 1
    if args.write and set_to is None:
        print("Nothing to write: give the version to set with --set N.")
        return 1

    runtime = MnemosRuntime(
        db_path=getattr(args, "db_path", None),
        agent_id=getattr(args, "agent_id", None),
        person_id=getattr(args, "person_id", None),
        project_scope=getattr(args, "project_scope", None),
        marks_lived=False,
    )
    try:
        plan = runtime.repair_min_code_version(set_to=set_to, write=args.write)
    finally:
        runtime.close()

    if not plan["exists"]:
        print(f"No store at {runtime.db_path}; nothing to repair.")
        return 0

    running = plan["running"]
    minimum = plan["store_minimum"]
    shown = "not set yet" if minimum is None else str(minimum)
    print(f"Maintenance code version for {runtime.db_path}")
    print()
    print(f"  This code:      version {running}")
    print(f"  Store minimum:  {shown}")
    print()
    if minimum is not None and minimum > running:
        print("This code is older than the store expects, so it does not maintain it.")
    else:
        print("This code maintains this store.")

    if set_to is None:
        print("Dry run: nothing changed. To change the minimum, run again with")
        print("--set N --write (a verified backup is made first).")
        return 0
    if set_to == minimum:
        print(f"The minimum is already {set_to}; nothing changed.")
        return 0
    if not args.write:
        print(f"Would set the minimum from {shown} to {set_to}.")
        print("Dry run: nothing changed. Run again with --write to change it")
        print("(a verified backup is made first).")
        return 0
    print(f"Set the minimum from {shown} to {set_to}. Backup: {plan['backup']}")
    if set_to <= running:
        print(
            f"Code at version {set_to} or newer maintains this store again; "
            "sessions already running pick this up at their next maintenance."
        )
    else:
        print(f"This code (version {running}) no longer maintains this store.")
    print("Any newer Mnemos raises the minimum again when it opens the store.")
    return 0


def _cmd_adopt_legacy(args: argparse.Namespace) -> int:
    """Bring back memories the v6 scope migration left where no read reaches.

    The migration gave each legacy engram a person and project only when one
    continuity scope claimed it; the rest were quarantined, and on a real
    store that was thousands of rows, lessons among them. This is the way
    back out, and only a human runs it: a dry run unless --write, a verified
    backup before anything moves, and no guessing between people.
    """
    from .simple_runtime import LEGACY_CLASSES, MnemosRuntime

    include = tuple(dict.fromkeys(
        part.strip() for part in args.include.split(",") if part.strip()
    ))
    if not include or any(part not in LEGACY_CLASSES for part in include):
        print(
            f"--include takes {', '.join(LEGACY_CLASSES)}; got {args.include!r}",
            file=sys.stderr,
        )
        return 2

    person = getattr(args, "person_id", None)
    project = getattr(args, "project_scope", None)
    runtime = MnemosRuntime(
        db_path=getattr(args, "db_path", None),
        agent_id=getattr(args, "agent_id", None),
        person_id=person,
        project_scope=project,
        marks_lived=False,
    )
    try:
        plan = runtime.adopt_legacy(
            include=include,
            write=args.write,
            scope_confirmed=person is not None and project is not None,
        )
    finally:
        runtime.close()

    if not plan["exists"]:
        print(f"No store at {runtime.db_path}; nothing to bring back.")
        return 0

    agent, target_person, target_project = plan["target"]
    counts = plan["counts"]
    labels = {
        "lessons": "lessons",
        "other": "written some other way",
        "indexer": "written by a tool",
    }
    print(f"Legacy memories for {agent} in {runtime.db_path}")
    print("They predate scoping, so recall and maintenance never reach them.")
    print()
    for name in LEGACY_CLASSES:
        fate = "come back" if name in plan["include"] else "stay hidden"
        print(f"  {counts[name]:>7,}  {labels[name]:<28} {fate}")
    print(f"  {counts['archived']:>7,}  {'archived':<28} stay archived")
    print()
    print(f"Into:    {agent} / {target_person} / {target_project}")
    if plan["other_scopes"]:
        print("Also in use by this agent: " + ", ".join(
            f"{p}/{s}" for p, s in plan["other_scopes"]
        ))

    if plan["refused"]:
        print()
        print(plan["refused"])
        return 1
    if not plan["selected"]:
        print()
        print("Nothing to bring back.")
        return 0
    if args.write:
        print()
        print(
            f"Brought back {plan['adopted']:,} memories into "
            f"{agent} / {target_person} / {target_project}."
        )
        print(f"Backup: {plan['backup']}")
        return 0

    print()
    print("First of what comes back:")
    for row in plan["selected"][:5]:
        text = " ".join(str(row["content"]).split())
        print(f"  - [{row['class']}] {text[:100]}{'...' if len(text) > 100 else ''}")
    print()
    print(
        f"Dry run: nothing changed. Re-run with --write to bring back "
        f"{len(plan['selected']):,} memories; a verified backup is made first."
    )
    if "indexer" not in plan["include"]:
        print(
            "What a tool wrote stays hidden unless named with --include "
            "indexer: the indexer's volume is what buried continuity before."
        )
    return 0


def _cmd_doctor(args: argparse.Namespace) -> int:
    """Check simple-mode readiness without changing anything.

    Doctor opens the store read-only and never builds a context packet:
    building one runs maintenance and uses up the showings of pending
    questions, and even a plain open migrates the schema and rewrites the
    file. A check that changes what it checks reports on itself.
    """
    from .simple_runtime import MnemosRuntime, SIMPLE_TOOL_NAMES

    runtime = MnemosRuntime(
        db_path=getattr(args, "db_path", None),
        agent_id=getattr(args, "agent_id", None),
        person_id=getattr(args, "person_id", None),
        project_scope=getattr(args, "project_scope", None),
        read_only=True,
        marks_lived=False,
    )
    try:
        print("Mnemos Doctor")
        print("-" * 40)
        print(f"Agent:       {runtime.scope.agent_id}")
        print(f"Person:      {runtime.scope.person_id}")
        print(f"Project:     {runtime.scope.project_scope}")
        print(f"Database:    {runtime.db_path}")
        print(f"MCP SDK:      {'yes' if _mcp_available() else 'no'}")

        # A diagnostic must not create the thing it inspects: on a fresh or
        # mistyped scope that would mint a phantom empty database and then
        # report it healthy. When there is no store yet, report the store-free
        # readiness fields and stop.
        if not runtime.db_path.exists():
            print("DB exists:    no")
            _print_background_status(runtime.scope)
            _print_meaning_status()
            print(f"Simple tools: {', '.join(SIMPLE_TOOL_NAMES)}")
            print()
            print("No store yet for this scope — nothing has been captured here.")
            print("If you expected memory, check the --db-path / --agent-id in use.")
            return 0

        print("DB exists:    yes")
        # Read once, before the semantic probe, and printed last: nothing of
        # it when all is well.
        try:
            watched = runtime.watchdog()
        except Exception:
            watched = None
        _print_code_status(runtime)
        _print_identity_status(runtime)
        print(f"Model:        {'dedicated provider configured' if runtime.has_dedicated_model else 'local baseline only'}")
        _print_background_status(runtime.scope)
        _print_meaning_status()
        _print_semantic_status(runtime, watched)
        _print_judge_status(watched)
        print(f"Simple tools: {', '.join(SIMPLE_TOOL_NAMES)}")
        _print_memory_status(runtime)
        _print_continuity_status(runtime)
        _print_legacy_status(runtime)
        _print_watchdog(watched)
        return 0
    finally:
        runtime.close()


def _print_judge_status(watched=None) -> None:
    """Say whether the cue's judge is on, where the switch was read from, and
    whether a key file is there (by its size: the key is never read), as this
    shell sees them; the prompt hook reads the same switch, from the config
    file or the environment Claude Code started in. Then, when any session's
    answerer has kept calls, how the last of them ended (the watchdog flags
    repeated failures with the others)."""
    from . import jev

    try:
        status = jev.status()
    except Exception as exc:
        print(f"Cue judge:    unknown ({type(exc).__name__}: {exc})")
        return
    # Without a key file there, one named, or the judge switched on, Jev means
    # nothing to the person reading: no line. Switched on without a key, the
    # line below says what's missing.
    if (status["key_state"] == "missing" and not (os.environ.get(jev.KEY_FILE_ENV) or "").strip()
            and not status["switched_on"]):
        return
    key = f"key file {status['key_file']}: {status['key_state']}"
    if status["in_use"]:
        print(f"Cue judge:    on: Jev decides which memories the cue shows (switch: {status['source']}; {key})")
    elif status["switched_on"]:
        print(
            f"Cue judge:    switched on ({status['source']}), but with no key the cue runs "
            f"without Jev ({key})"
        )
    else:
        print(f"Cue judge:    off (switch: {status['source']}; {key})")
    calls = ((watched or {}).get("checks") or {}).get("cue_judge") or {}
    if calls.get("calls"):
        print(
            f"              Jev's last {calls['calls']} call(s), all sessions: {calls['answered']} "
            f"answered, {calls['timeouts']} timed out, {calls['errors']} failed"
        )


def _print_watchdog(watched) -> None:
    """Say what has stalled for more than a day, one line each with the
    command that fixes or inspects it, and nothing when all is well."""
    from .watchdog import flag_lines

    for flag in flag_lines(watched):
        print(f"  ATTENTION:  {flag}")


def _print_memory_status(runtime) -> None:
    """How many memories are active, dormant and archived, and the faded ones
    an ordinary recall never returns, with the call that does: the health
    card's numbers, in its words."""
    from .simple_runtime import format_memory_counts, format_unreachable_summary

    try:
        counts = runtime.memory_counts()
        unreachable = runtime.unreachable_memories()
    except Exception as exc:
        print(f"Memories:     unknown ({type(exc).__name__}: {exc})")
        return
    print(f"Memories:     {format_memory_counts(counts)}")
    summary = format_unreachable_summary(unreachable)
    if summary:
        print(f"Unreachable:  {summary}")


def _print_code_status(runtime) -> None:
    """Say which code version runs here and what the store expects.

    A session keeps the code it started with. Once a newer Mnemos has opened
    the store, an older process stops maintaining it, which is correct, and
    otherwise invisible.
    """
    from .simple_runtime import describe_code

    try:
        headline, attention = describe_code(runtime.code_versions())
    except Exception as exc:
        print(f"Code:         unknown ({type(exc).__name__}: {exc})")
        return
    print(f"Code:         {headline}")
    if attention:
        print(f"  ATTENTION:  {attention}")


def _print_identity_status(runtime) -> None:
    """Say whom this session introduced itself as, as the health card does.

    Only this session's own introduction: the scope's last one is whichever
    session made it, and on a real store it named a Grok session.
    """
    from .simple_runtime import describe_identity

    try:
        said = describe_identity(runtime._identity_health())
    except Exception as exc:
        print(f"Identity:     unknown ({type(exc).__name__}: {exc})")
        return
    print(f"Identity:     {said}")


def _print_meaning_status() -> None:
    """Say which provider meaning search uses and its model, and why: the
    answer every index here acts on (``embedding_choice``), as this shell sees
    it. A GEMINI_API_KEY lying around, there for another tool, used to send
    every memory and question to Google; when one is there and not chosen,
    say so, and how to choose Gemini."""
    from .store.embedding_index import embedding_choice

    try:
        lines = _describe_meaning(embedding_choice())
    except Exception as exc:
        print(f"Meaning:      unknown ({type(exc).__name__}: {exc})")
        return
    print(f"Meaning:      {lines[0]}")
    for line in lines[1:]:
        print(f"              {line}")


def _describe_meaning(choice: dict[str, str]) -> list[str]:
    """Doctor's lines about meaning's provider, from ``embedding_choice()``
    as the settings make it (no choice or key from code)."""
    from .store.embedding_index import GEMINI, LOCAL, PROVIDER_SETTING

    model, chosen, chosen_in = choice["model"], choice["chosen"], choice["chosen_in"]
    if chosen_in == "config":
        by = "embeddings.provider in Mnemos's config"
    else:
        by = f"{PROVIDER_SETTING} in {chosen_in}"
    here = "meaning stays on this machine"
    if choice["provider"] == GEMINI:
        return [
            f"gemini, model {model}, chosen with {by}: the words of memories and "
            "questions go to Google to be embedded"
        ]
    if not chosen:
        lines = [f"local, model {model}, the default: {here}"]
    elif chosen == LOCAL:
        lines = [f"local, model {model}, chosen with {by}: {here}"]
    elif chosen == GEMINI:
        lines = [f"local, model {model}: Gemini is chosen ({by}), but no GEMINI_API_KEY was found, so {here}"]
    else:
        lines = [
            f"local, model {model}: {by} is {chosen!r}, which Mnemos doesn't know "
            f"(it knows local and gemini), so {here}"
        ]
    if choice["key_in"]:
        lines.append(
            f"A GEMINI_API_KEY is set in {choice['key_in']}, but Mnemos doesn't use it: {here}. "
            "To choose Gemini, which sends the words of memories and questions to Google, set "
            f"{PROVIDER_SETTING}=gemini."
        )
    return lines


def _print_semantic_status(runtime, watched=None) -> None:
    """Say whether recall can seed by meaning here, and why not if not.

    `sentence-transformers` is an optional extra, so retrieval is either
    semantic or keyword-only depending on what happens to be installed —
    and nothing told the user which. Two very different qualities of
    recall, silently selected, is the failure pattern this project keeps
    producing. This used to say only whether the import had succeeded, and
    told a user whose installed package failed to import to go install it.
    Now it embeds a probe, and names the root cause when that fails.
    """
    import platform

    from .simple_runtime import describe_semantic

    try:
        semantic = runtime.semantic_status(verify=True)
        headline, details, attention = describe_semantic(semantic)
    except Exception as exc:
        print(f"Semantic:     unknown ({type(exc).__name__}: {exc})")
        return
    print(f"Semantic:     {headline}")
    # Only when the extra is missing: a package installed and failing is not
    # fixed by installing it (the "why" line names the root cause then).
    if semantic and not semantic.get("active") and "is not installed" in str(semantic.get("reason") or ""):
        print(
            "              Without it, recall matches words only, and ideas you keep "
            "returning to can't be noticed. Add it with: "
            'pip install "mnemos-continuity[embeddings]", then: mnemos embeddings download'
        )
    for detail in details:
        print(f"              {detail}")
    from .simple_runtime import describe_recall_index
    from .watchdog import flagged

    # The watchdog's flag about recall's meaning index carries the last pass's
    # reason, and is printed with the others: said once.
    try:
        recall_index = (
            None if flagged(watched, "recall_index")
            else describe_recall_index(runtime.recall_index_status())
        )
    except Exception:
        recall_index = None
    if recall_index:
        print(f"Recall index: {recall_index}")
    # Whether an import works depends on the interpreter, so say which one
    # answered. The MCP server reports its own answer in mnemos_health.
    print(f"              checked in Python {platform.python_version()} ({sys.executable})")
    for warning in attention:
        print(f"  ATTENTION:  {warning}")


def _print_continuity_status(runtime) -> None:
    """Report whether continuity is actually reaching this agent."""
    try:
        signals = runtime.continuity_signals()
    except Exception:
        return
    notes = signals["notes_active"]
    print(f"Continuity:   {notes} note(s), {signals['empty_context_streak']} empty packet(s) in a row")
    for warning in signals["warnings"]:
        print(f"  ATTENTION:  {warning}")

    # Damage from a version that truncated memories it could not read. The
    # user has no other way to discover this: the store reports healthy, and
    # the memories still exist — they just no longer say anything.
    try:
        damaged = runtime.repair_softening(dry_run=True)
    except Exception:
        return
    if damaged:
        print(
            f"  ATTENTION:  {damaged} memory(ies) were truncated by an earlier "
            "version and can be restored — run 'mnemos repair-softening'"
        )


def _print_legacy_status(runtime) -> None:
    """Report memory the scope migration left where no read reaches.

    The store looks healthy from every other angle: its counts include only
    what is scoped, and the rest never errors. It simply never comes back.
    Transcript-indexer output left hidden is the recommended state, not a
    fault, so it alone raises no ATTENTION; the health card still counts it.
    """
    from .simple_runtime import format_legacy_summary

    try:
        counts = runtime.legacy_counts()
    except Exception:
        return
    if counts.get("lessons") or counts.get("other"):
        print(f"  ATTENTION:  {format_legacy_summary(counts)}")


def _print_background_status(scope) -> None:
    """Tell the user whether memory does anything between sessions: the
    upkeep, and the quiet hours.

    Without a scheduler, Mnemos only maintains itself opportunistically
    while a session happens to be open — which is easy to mistake for a
    system that is quietly working in the background.
    """
    try:
        from .setup import scheduler

        backend = scheduler.detect_backend()
        if backend == "unsupported":
            print("Background:   unavailable (no launchd, systemd or crontab)")
            return

        jobs = scheduler.jobs_for(has_model=scheduler.model_is_configured())
        crontab = scheduler.read_crontab() if backend == "crontab" else ""

        def scheduled(job) -> bool:
            if backend == "launchd":
                return (
                    scheduler.launchd_plist_path(scope.agent_id, job).exists()
                    and scheduler.launchd_job_active(scope.agent_id, job)
                )
            if backend == "systemd":
                return (
                    (scheduler.systemd_unit_dir()
                     / scheduler.systemd_unit_names(scope.agent_id, job)[1]).exists()
                    and scheduler.systemd_timer_active(scope.agent_id, job)
                )
            return scheduler.cron_has(crontab, scope.agent_id, job.name)

        installed = sum(1 for job in jobs if scheduled(job))
        if installed:
            print(f"Background:   {installed} job(s) scheduled via {backend}")
        else:
            print(
                f"Background:   not scheduled — run 'mnemos daemon install --write' "
                f"({backend})"
            )
        if any(scheduled(job) for job in scheduler.HOUR_JOBS):
            print(f"Quiet hours:  on (mnemos daemon status says when; '{_HOURS_OFF}' ends them)")
        else:
            print(f"Quiet hours:  off ('{_HOURS_ON}' turns them on)")
    except Exception:
        print("Background:   unknown")


def _cmd_identity(args: argparse.Namespace) -> int:
    """Computed-vs-declared identity operations."""
    from .identity_diff import run_accept_command, run_diff_command

    if getattr(args, "identity_command", None) == "diff":
        return run_diff_command(args)
    if getattr(args, "identity_command", None) == "accept":
        return run_accept_command(args)
    print("Usage: mnemos identity {diff|accept}", file=sys.stderr)
    return 1


def _cmd_mcp(args: argparse.Namespace) -> int:
    """MCP client helper commands."""
    if args.mcp_command != "install":
        print("Usage: mnemos mcp install {claude|claude-code|cursor|codex|generic}", file=sys.stderr)
        return 1
    if args.mode == "advanced":
        print(ADVANCED_MODE_NOTE, file=sys.stderr)

    snippet = _mcp_server_snippet(
        name=args.name,
        mode=args.mode,
        agent_id=args.agent_id,
        db_path=args.db_path,
    )

    if args.write and args.client == "claude":
        from .file_security import atomic_write_text

        path = _claude_desktop_config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            try:
                with open(path) as f:
                    config = json.load(f)
            except json.JSONDecodeError as exc:
                print(f"Refusing to overwrite unparseable {path}: {exc}", file=sys.stderr)
                return 1
        else:
            config = {}
        servers = config.setdefault("mcpServers", {})
        servers.update(snippet)
        atomic_write_text(
            path, json.dumps(config, indent=2) + "\n", backup_existing=True
        )
        print(f"Installed Mnemos MCP config at {path}")
        print("Restart Claude Desktop to expose the new tools.")
        # This one command is all of Claude Desktop's setup, so it does
        # setup's part between sessions too.
        return _background_setup(args, ask_hours=True)

    if args.client == "claude-code":
        # Claude Code keeps its MCP servers in its own config, which its own
        # `claude mcp add` writes (and which honours CLAUDE_CONFIG_DIR); the
        # Claude Desktop file is not read by it.
        parts = [
            "claude", "mcp", "add", "--scope", "user", args.name, "--",
            _mnemos_command(), "serve", "--mode", args.mode,
        ]
        if args.agent_id:
            parts.extend(["--agent-id", args.agent_id])
        if args.db_path:
            parts.extend(["--db-path", args.db_path])
        line = shlex.join(parts)
        if not args.write:
            print(line)
            return 0
        claude = shutil.which("claude")
        if not claude:
            print("Claude Code isn't on your PATH. Run this yourself once it is:")
            print(line)
            return 1
        result = subprocess.run(
            [claude, *parts[1:]], capture_output=True, text=True, check=False
        )
        if result.stdout:
            print(result.stdout, end="")
        if result.stderr:
            print(result.stderr, end="", file=sys.stderr)
        return result.returncode

    if args.write:
        print(
            f"--write is currently supported for Claude Desktop only. Printing {args.client} config instead.",
            file=sys.stderr,
        )

    if args.client == "codex":
        command = _mnemos_command()
        parts = ["codex", "mcp", "add", args.name, "--", command, "serve", "--mode", args.mode]
        if args.agent_id:
            parts.extend(["--agent-id", args.agent_id])
        if args.db_path:
            parts.extend(["--db-path", args.db_path])
        print(" ".join(parts))
        return 0

    print(json.dumps({"mcpServers": snippet}, indent=2))
    if args.client == "claude":
        print()
        print(f"Claude Desktop config path: {_claude_desktop_config_path()}")
        print("Re-run with --write to merge this server into that file.")
    return 0


def _cmd_hermes(args: argparse.Namespace) -> int:
    """Hermes integration helper commands."""
    from .integrations.hermes.installer import (
        build_diagnostics,
        format_diagnostics,
        install_hermes_plugin,
        quickstart_hermes,
        render_plugin_shim,
    )

    if args.hermes_command == "install":
        result = install_hermes_plugin(
            hermes_home=args.hermes_home,
            db_path=args.db_path,
            agent_id=args.agent_id,
            person_id=args.person_id,
            project_scope=args.project_scope,
            mode=args.mode,
            configure_mcp=True if args.with_mcp else None,
            mcp_server_name=args.mcp_name,
            activate=args.activate,
            force=args.force,
            dry_run=args.dry_run,
        )
        print(result.summary())
        return 0 if not result.warnings else 1

    if args.hermes_command == "quickstart":
        result = quickstart_hermes(
            hermes_home=args.hermes_home,
            db_path=args.db_path,
            agent_id=args.agent_id,
            person_id=args.person_id,
            project_scope=args.project_scope,
            provider=args.provider,
            activate_provider=args.activate_provider,
            agent_safe=args.agent_safe,
            mcp_server_name=args.mcp_name,
            dry_run=args.dry_run,
        )
        print(result.summary())
        return 0 if result.ok else 1

    if args.hermes_command == "doctor":
        print(format_diagnostics(build_diagnostics(args.hermes_home)))
        return 0

    if args.hermes_command == "shim":
        print(render_plugin_shim())
        return 0

    print("Usage: mnemos hermes {install|quickstart|doctor|shim}", file=sys.stderr)
    return 1


def _mcp_available() -> bool:
    try:
        import mcp  # noqa: F401
    except Exception:
        return False
    return True


def _mnemos_command() -> str:
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


def _mcp_server_snippet(
    *,
    name: str,
    mode: str,
    agent_id: str | None = None,
    db_path: str | None = None,
) -> dict:
    args = ["serve", "--mode", mode]
    env = {}
    if agent_id:
        env["MNEMOS_AGENT_ID"] = agent_id
    if db_path:
        env["MNEMOS_DB_PATH"] = db_path
    server = {
        "command": _mnemos_command(),
        "args": args,
    }
    if env:
        server["env"] = env
    return {name: server}


def _claude_desktop_config_path() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    if sys.platform.startswith("win"):
        return Path(os.environ.get("APPDATA", str(Path.home()))) / "Claude" / "claude_desktop_config.json"
    return Path.home() / ".config" / "Claude" / "claude_desktop_config.json"


def _without_mnemos_hooks(path: Path, *, write: bool) -> tuple[int, str]:
    """Mnemos's hooks in one hooks file: how many there are, removed with
    ``write``, and why the file was left alone when it was. Anyone else's
    hooks stay, and an event left with none is taken out."""
    if not path.exists():
        return 0, ""
    try:
        settings = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        return 0, f"left {path} alone: it can't be read ({exc})"
    hooks = settings.get("hooks") if isinstance(settings, dict) else None
    if not isinstance(hooks, dict):
        return 0, ""
    found = 0
    for event, subcommand in (("SessionStart", "session-start"), ("UserPromptSubmit", "prompt")):
        listed = hooks.get(event)
        if not isinstance(listed, list):
            continue
        keep = [entry for entry in listed if not _is_mnemos_hook(entry, subcommand)]
        found += len(listed) - len(keep)
        if keep:
            hooks[event] = keep
        else:
            hooks.pop(event, None)
    if found and write:
        from .file_security import atomic_write_text

        atomic_write_text(path, json.dumps(settings, indent=2) + "\n", backup_existing=True)
    return found, ""


def _without_desktop_server(path: Path, name: str, *, write: bool) -> tuple[bool, str]:
    """Claude Desktop's entry for Mnemos's server, when its command is
    Mnemos's, removed with ``write``. Any other server stays."""
    if not path.exists():
        return False, ""
    try:
        config = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        return False, f"left {path} alone: it can't be read ({exc})"
    servers = config.get("mcpServers") if isinstance(config, dict) else None
    entry = servers.get(name) if isinstance(servers, dict) else None
    command = entry.get("command", "") if isinstance(entry, dict) else ""
    if not isinstance(command, str) or not Path(command).stem.lower().startswith("mnemos"):
        return False, ""
    if write:
        from .file_security import atomic_write_text

        del servers[name]
        atomic_write_text(path, json.dumps(config, indent=2) + "\n", backup_existing=True)
    return True, ""


def _remove_registered_server(tool: str, parts: list[str], *, write: bool) -> str:
    """Ask a client's own command to forget Mnemos's server (`claude mcp
    remove`, `codex mcp remove`): what was done, or what to run by hand."""
    line = shlex.join([tool, *parts])
    found = shutil.which(tool)
    if not found:
        return ""
    if not write:
        return f"would run: {line}"
    result = subprocess.run([found, *parts], capture_output=True, text=True, check=False)
    said = " ".join((result.stdout + " " + result.stderr).split())
    if result.returncode == 0:
        return f"ran: {line}"
    if "not found" in said.lower() or "no mcp server" in said.lower():
        return ""
    return f"{line} said: {said[:200]}"


def _cmd_uninstall(args: argparse.Namespace) -> int:
    """Take Mnemos out of every client its setup writes to, and unschedule
    its jobs. Its memories stay: they are the agent's, and this says where
    they are. Without ``--write`` it only says what it would do."""
    write = bool(args.write)
    done: list[str] = []
    problems: list[str] = []

    for label, path in (("Claude Code", _claude_code_settings_path()), ("Codex", _codex_hooks_path())):
        count, problem = _without_mnemos_hooks(path, write=write)
        if problem:
            problems.append(problem)
        if count:
            hooks = "hook" if count == 1 else "hooks"
            done.append(f"{label}: {count} Mnemos {hooks} {'removed from' if write else 'in'} {path}")

    removed, problem = _without_desktop_server(_claude_desktop_config_path(), args.name, write=write)
    if problem:
        problems.append(problem)
    if removed:
        done.append(
            f"Claude Desktop: the {args.name} server {'removed from' if write else 'in'} "
            f"{_claude_desktop_config_path()}"
        )

    for label, tool, parts in (
        ("Claude Code", "claude", ["mcp", "remove", "--scope", "user", args.name]),
        ("Codex", "codex", ["mcp", "remove", args.name]),
    ):
        said = _remove_registered_server(tool, parts, write=write)
        if said.startswith(("ran", "would run")):
            done.append(f"{label}: {said}")
        elif said:
            problems.append(f"{label}: {said}")

    if done:
        print("Removed:" if write else "Would remove:")
        for line in done:
            print(f"  {line}")
    else:
        print("No Mnemos hooks or server entries were found.")

    print()
    blueprint = _blueprint(args)
    jobs = 0 if blueprint["backend"] == "unsupported" else _daemon_uninstall(blueprint, write=write)

    folder = Path(_cli_scope(args).db_path).expanduser().parent
    print()
    print(f"The memories stay, in {folder}. They are the agent's; delete that folder yourself only if you mean to.")
    if not write:
        print("Re-run with --write to remove Mnemos.")
    for problem in problems:
        print(f"Note: {problem}", file=sys.stderr)
    return 1 if (jobs or problems) and write else 0


if __name__ == "__main__":
    sys.exit(main())
