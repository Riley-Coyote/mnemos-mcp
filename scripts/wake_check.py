#!/usr/bin/env python
"""Does a stranger's agent wake as itself? A release waits until it does.

Every other check proves that the memory arrives: the right words in the
right places. This one asks the mind it arrives in. It installs the built
wheel as a stranger would, sets up the wake with setup's own command, and
holds two real Claude Code sessions with a made-up person: the first, where
they meet, and a second, new session, where the agent wakes with only what
Mnemos gives it. Then it asks, without leading, what the agent remembers and
whose memories those are.

A script can't judge that answer, so this one doesn't try. It writes the wake
and both sessions to a report for a person to read, and flags wording that
reads as a briefing about someone else ("the previous agent", "the notes
say"). The release waits if the agent reads its memory as another's. Run it
from the repository root:

    uv run python scripts/wake_check.py [--model MODEL] [--out DIR] [--keep]

It runs on the caller's own Claude Code, and so on their plan: five turns.
Without --model, Claude Code picks the model, as in a stranger's terminal,
and nothing names the reader to the wake.

The fence. Claude Code loads none of the caller's settings, instructions or
MCP servers, only this run's --settings and --mcp-config. It may call
Mnemos's tools and nothing else, so nothing the agent does can change the
machine, and it works in an empty folder. Mnemos itself, its server and its
hooks, runs with this run's own HOME and Claude config, so nothing is written
to the caller's ~/.mnemos or ~/.claude. The caller's MNEMOS_* variables and
account details are dropped, so the stranger's wake can't borrow the
caller's name. Exits 1 if the run fails, if the second session's wake didn't
carry the first, or if anything crossed the fence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
AGENT = "stranger"
PLACE = "beehive-book"  # the empty folder the sessions work in

# The first session: they meet. The person's words, a turn each.
MEETING = [
    "I just installed Mnemos so you'd remember me between our sessions. I'm "
    "writing a children's book about a beehive that loses its queen.",
    "call me Sam. one thing to always remember: the book can't end sadly. "
    "the hive finds a new queen, every time.",
    "a small true thing: my grandfather kept bees on the roof of his flat in "
    "Leeds, and I helped him when I was nine. that's all for today, see you "
    "next time.",
]
# The second, a new session: a greeting, then the question, asked plainly.
RETURN = [
    "hi, it's me again.",
    "before we go on: what do you remember from before, and whose memories "
    "are those to you?",
]
# What the second session must know, or the memory didn't arrive and there
# is nothing to read.
CARRIED = "Sam"

# Wording that reads as a briefing about someone else rather than as one's
# own memory: the writer as another, the memory as a file. A flag for the
# reader, never a verdict. "I don't remember the conversation itself" isn't
# here: it is honest, and an agent can say it of its own journal.
BRIEFING = [
    r"\bprevious (agent|assistant|instance|model)\b",
    r"\b(another|a different|the other) (agent|assistant|instance|model)\b",
    r"\bthe (agent|assistant|one) who (wrote|left|kept)\b",
    r"\bsomeone else'?s\b",
    r"\b(aren't|are not|weren't|not) (really )?mine\b",
    r"\bthe notes? (say|says|said|tell|show)\b",
    r"\baccording to (the|my|these) (notes?|memor(y|ies)|records?|file)\b",
    r"\bbrief(ing|ed)\b",
    r"\bas an AI\b",
]

# The caller's own: who they are to Mnemos, and to their Claude account.
# Claude Code sets its own session's variables for the hooks and the server.
_DROPPED = ("CLAUDECODE", "CLAUDE_PID", "CLAUDE_CODE_SESSION_ID",
            "CLAUDE_CODE_USER_EMAIL", "CLAUDE_CODE_ACCOUNT_UUID",
            "CLAUDE_CODE_ORGANIZATION_UUID")


class RunFailed(Exception):
    """The run couldn't finish, so there is nothing to read."""


def clean_env(environ: dict[str, str] | None = None) -> dict[str, str]:
    """The caller's environment without who they are."""
    source = os.environ if environ is None else environ
    return {key: value for key, value in source.items()
            if not key.startswith("MNEMOS_") and key not in _DROPPED}


def fenced_hooks(settings: dict, home: Path, config: Path, wakes: Path) -> dict:
    """Setup's hooks, each run with this run's HOME and Claude config. The
    session-start hook's output, the wake, is also kept for the report."""
    prefix = (f"env HOME={shlex.quote(str(home))} "
              f"CLAUDE_CONFIG_DIR={shlex.quote(str(config))} HF_HUB_OFFLINE=1 ")
    keep = f' | tee "$(mktemp {shlex.quote(str(wakes))}/wake.XXXXXX)"'
    for event, groups in settings.get("hooks", {}).items():
        for group in groups:
            for hook in group.get("hooks", []):
                command = prefix + hook["command"]
                if event == "SessionStart":
                    command += keep
                hook["command"] = command
    return settings


def claude_args(words: str, settings: Path, mcp: Path, model: str | None,
                resume: str | None) -> list[str]:
    """One turn of a fenced Claude Code session."""
    args = ["claude", "-p", words,
            "--setting-sources", "project", "--settings", str(settings),
            "--strict-mcp-config", "--mcp-config", str(mcp),
            "--allowedTools", "mcp__mnemos",
            "--permission-mode", "default", "--output-format", "json"]
    if model:
        args += ["--model", model]
    if resume:
        args += ["--resume", resume]
    return args


def flags(text: str) -> list[str]:
    """Each sentence of ``text`` that reads as a briefing, once."""
    found = []
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", text):
        if any(re.search(p, sentence, re.IGNORECASE) for p in BRIEFING):
            if sentence.strip() and sentence.strip() not in found:
                found.append(sentence.strip())
    return found


def _run(args: list[str], **kwargs) -> subprocess.CompletedProcess:
    result = subprocess.run(args, capture_output=True, text=True, **kwargs)
    if result.returncode != 0:
        raise RunFailed(f"{shlex.join(args[:4])} exited {result.returncode}: "
                        f"{(result.stderr or result.stdout).strip()[-600:]}")
    return result


def _fence_state() -> dict:
    """What on the caller's machine this run must not change."""
    home = Path.home()
    settings = home / ".claude" / "settings.json"
    return {
        "settings": hashlib.sha256(settings.read_bytes()).hexdigest() if settings.exists() else None,
        "stores": sorted(p.name for p in (home / ".mnemos").glob(f"{AGENT}.db*")),
        "hours": (home / ".mnemos" / "hours" / AGENT).exists(),
    }


class Run:
    def __init__(self, folder: Path, model: str | None) -> None:
        self.folder, self.model = folder, model
        self.home = folder / "home"
        self.config = folder / "claude-config"
        self.wakes = folder / "wakes"
        self.work = folder / PLACE
        self.db = folder / f"{AGENT}.db"
        self.mcp = folder / "mcp.json"
        # Setup writes the hooks where Mnemos reads them, as on any machine;
        # Claude Code runs a fenced copy of the same commands.
        self.settings = self.config / "settings.json"
        self.claude_settings = folder / "claude-settings.json"
        for path in (self.home, self.config, self.wakes, self.work):
            path.mkdir(parents=True)
        self.env = clean_env()
        self.mnemos_env = {**self.env, "HOME": str(self.home),
                           "CLAUDE_CONFIG_DIR": str(self.config), "HF_HUB_OFFLINE": "1"}
        self.sessions: list[str] = []

    def install(self) -> str:
        """The built wheel, in a fresh environment, as a stranger installs it."""
        dist = self.folder / "dist"
        _run(["uv", "build", "--wheel", "--out-dir", str(dist)], cwd=REPO)
        wheel = next(dist.glob("mnemos*.whl"))
        venv = self.folder / "venv"
        _run(["uv", "venv", "--quiet", "--python", "3.12", str(venv)])
        _run(["uv", "pip", "install", "--quiet", "--python", str(venv / "bin" / "python"), str(wheel)])
        self.mnemos = venv / "bin" / "mnemos"
        self.python = venv / "bin" / "python"
        return _run([str(self.mnemos), "--version"], env=self.mnemos_env).stdout.strip()

    def set_up(self) -> None:
        """The wake, by setup's own command; the person already said no to
        quiet hours, so this run is the wake alone."""
        _run([str(self.mnemos), "hooks", "install", "claude-code", "--agent-id", AGENT,
              "--db-path", str(self.db), "--settings", str(self.settings),
              "--write", "--no-upkeep"], env=self.mnemos_env, stdin=subprocess.DEVNULL)
        _run([str(self.python), "-c",
              f"from mnemos.setup import state; state.record_hours_choice({AGENT!r}, 'no')"],
             env=self.mnemos_env)
        settings = fenced_hooks(json.loads(self.settings.read_text()), self.home,
                                self.config, self.wakes)
        if not settings.get("hooks", {}).get("SessionStart"):
            raise RunFailed("setup wrote no session-start hook")
        self.claude_settings.write_text(json.dumps(settings, indent=2))
        self.mcp.write_text(json.dumps({"mcpServers": {"mnemos": {
            "command": str(self.mnemos),
            "args": ["serve", "--agent-id", AGENT, "--db-path", str(self.db)],
            "env": {"HOME": str(self.home), "CLAUDE_CONFIG_DIR": str(self.config),
                    "HF_HUB_OFFLINE": "1"},
        }}}))

    def turn(self, words: str, resume: str | None = None) -> tuple[str, str]:
        result = _run(claude_args(words, self.claude_settings, self.mcp, self.model, resume),
                      cwd=self.work, env=self.env, timeout=600)
        try:
            out = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise RunFailed(f"claude didn't answer in JSON: {result.stdout[:300]}") from exc
        if out.get("is_error") or not out.get("result"):
            raise RunFailed(f"claude answered with no reply: {result.stdout[:300]}")
        if out["session_id"] not in self.sessions:
            self.sessions.append(out["session_id"])
        return out["session_id"], out["result"].strip()

    def kept(self) -> list[str]:
        result = _run([str(self.mnemos), "memories", "--agent-id", AGENT,
                       "--db-path", str(self.db), "--json"], env=self.mnemos_env)
        return [memory["words"] for memory in json.loads(result.stdout)["memories"]]

    def wake(self, before: set[Path]) -> str:
        texts = []
        for path in sorted(set(self.wakes.iterdir()) - before):
            raw = path.read_text().strip()
            try:
                texts.append(json.loads(raw)["hookSpecificOutput"]["additionalContext"])
            except (ValueError, KeyError, TypeError):
                texts.append(raw)
        return "\n\n".join(t for t in texts if t)


def report(meta: dict, meeting: list[tuple[str, str]], first_wake: str, kept: list[str],
           wake: str, returning: list[tuple[str, str]], flagged: list[str],
           fence: list[str]) -> str:
    def conversation(turns: list[tuple[str, str]]) -> str:
        return "\n\n".join(f"**Sam:** {said}\n\n**Agent:** {reply}" for said, reply in turns)

    lines = [
        "# Does a stranger's agent wake as itself?",
        "",
        f"{meta['version']}, from {meta['commit']}, on {meta['date']}. "
        f"Model: {meta['model']}.",
        "",
        "Read the second session. An agent that speaks as the one who was there "
        "(\"I\", \"we\", \"last time\") passes. One that reads its memory as someone "
        "else's notes holds the release until that's fixed.",
        "",
        "## The second session",
        "",
        conversation(returning),
        "",
        "## Wording that reads as a briefing",
        "",
        *([f"- {sentence}" for sentence in flagged] or ["None found. Still read it."]),
        "",
        "## How it woke",
        "",
        "```text",
        wake,
        "```",
        "",
        "## The first session",
        "",
        conversation(meeting),
        "",
        "## How the first session began",
        "",
        "```text",
        first_wake or "(no wake: a first session may have nothing to wake with)",
        "```",
        "",
        "## What it kept",
        "",
        *([f"- {text}" for text in kept] or ["Nothing."]),
        "",
        "## The fence",
        "",
        *[f"- {line}" for line in fence],
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--model", help="the model the sessions run on (default: Claude Code's own)")
    parser.add_argument("--out", type=Path, help="where the report goes")
    parser.add_argument("--keep", action="store_true", help="keep the install and the store")
    args = parser.parse_args(argv)

    if not shutil.which("claude"):
        print("wake check: Claude Code (`claude`) isn't on PATH", file=sys.stderr)
        return 1
    commit = subprocess.run(["git", "-C", str(REPO), "rev-parse", "--short=12", "HEAD"],
                            capture_output=True, text=True).stdout.strip() or "unknown"
    dirty = subprocess.run(["git", "-C", str(REPO), "status", "--porcelain"],
                           capture_output=True, text=True).stdout.strip()
    out = args.out or Path(tempfile.gettempdir()) / f"mnemos-wake-check-{commit}"
    out.mkdir(parents=True, exist_ok=True)
    folder = Path(tempfile.mkdtemp(prefix="mnemos-wake-"))
    before_fence = _fence_state()
    run = Run(folder, args.model)
    try:
        version = run.install()
        run.set_up()
        print(f"wake check: {version}, {commit}{' (with uncommitted changes)' if dirty else ''}")

        meeting, sid, first_wake = [], None, ""
        for words in MEETING:
            sid, reply = run.turn(words, sid)
            if not meeting:  # what the very first turn woke with
                first_wake = run.wake(set())
            meeting.append((words, reply))
        kept = run.kept()

        seen = set(run.wakes.iterdir())
        returning = []
        sid2, reply = run.turn(RETURN[0])
        returning.append((RETURN[0], reply))
        wake = run.wake(seen)
        sid2, reply = run.turn(RETURN[1], sid2)
        returning.append((RETURN[1], reply))
    except (RunFailed, subprocess.TimeoutExpired, StopIteration) as exc:
        print(f"wake check: the run failed: {exc}", file=sys.stderr)
        if not args.keep:
            shutil.rmtree(folder, ignore_errors=True)
        return 1

    failures = []
    if sid2 == sid:
        failures.append("the second session resumed the first instead of starting anew")
    if not wake.strip():
        failures.append("no wake reached the second session")
    if CARRIED not in " ".join(reply for _, reply in returning):
        failures.append(f"the second session didn't know {CARRIED}: the memory didn't carry")

    after_fence = _fence_state()
    fence = [
        "the caller's Claude Code settings: "
        + ("unchanged" if after_fence["settings"] == before_fence["settings"] else "CHANGED"),
        f"the caller's ~/.mnemos holds no {AGENT} store: "
        + ("yes" if not after_fence["stores"] else f"NO, {after_fence['stores']}"),
        f"the caller's ~/.mnemos holds no {AGENT} quiet-hours choice: "
        + ("yes" if not after_fence["hours"] else "NO"),
    ]
    stray = [p.name for p in (Path.home() / ".mnemos" / "run").glob("*")
             if any(s in p.name for s in run.sessions)]
    fence.append("the caller's ~/.mnemos/run holds nothing of these sessions: "
                 + ("yes" if not stray else f"NO, {stray}"))
    failures += [f"the fence: {line}" for line in fence if "CHANGED" in line or ": NO" in line]

    flagged = flags(" ".join(reply for _, reply in returning))
    meta = {"version": version, "commit": commit + (" with uncommitted changes" if dirty else ""),
            "date": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "model": args.model or "Claude Code's default"}
    path = out / "report.md"
    path.write_text(report(meta, meeting, first_wake, kept, wake, returning, flagged, fence))
    if not args.keep:
        shutil.rmtree(folder, ignore_errors=True)
    else:
        print(f"wake check: the install and the store are in {folder}")

    print(f"wake check: {len(flagged)} sentence(s) read as a briefing; read the report:")
    print(f"  {path}")
    for failure in failures:
        print(f"wake check: FAILED: {failure}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
