"""The log's two documents, read from one mind's memory and never written.

``life`` is small: who the mind is, its quiet hours, its journal, the notes it
left, what its memory asks it, its beliefs, the notes it left itself, what it
made. ``memories`` is every memory of the scope, whole, with how each is tied
to the others; its ``version`` changes only when the memories do, so the page
reads it again only then.

Which mind: the scope the one resolver gives (``resolve_scope``: flags, then
the environment, then ~/.mnemos/config.json, then Mnemos's defaults). The
person's name is ``--person-name`` or MNEMOS_PERSON_NAME; with none, the page
says "you". The mind's name comes from the model that signs its memories,
named the way Mnemos names it (``authorship.display_name``), never from a
store's agent_name, which is whatever the last session to introduce itself
under this scope said.

What it reads, and never writes:

- the store, opened read-only (memories and their ties, the journal, notes,
  questions, beliefs, the notes the mind leaves itself);
- each quiet hour's record (``hours.jsonl``), its stream and prompt, and for a
  practice hour the copy of the store it ran on;
- the studio, where the hours make things (its pictures are served as they
  are, never copied);
- whether anything wakes the hours on its own: a LaunchAgent, a systemd
  user timer or a crontab line that runs ``mnemos … life --hour …`` for this
  agent.

None of those has to exist. A store not yet made is said plainly, and a
machine with no hours, no studio or no schedule gives empty lists, which the
page reads as "no quiet hours yet" and "hours not scheduled".

Ported from the log's first exporter, which wrote these documents to files
every 45 seconds; here they are made on request and never leave memory.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import plistlib
import re
import shutil
import sqlite3
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

from ..authorship import display_name
from ..simple_scope import MnemosScope, named_in_the_environment, resolve_scope
from ..store.sqlite_store import RETIRED_REFLECTION_KINDS

logger = logging.getLogger(__name__)

# The person or project of a store from before memories were filed by them (the column there, but empty): read as
# whatever is unfiled. Only the log reads such a store this way, for a mind found beside its own, and never writes it.
UNFILED = ""

PICTURES = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp"}
MOST_BYTES = 6 * 1024 * 1024
# Links that tied memories together for sharing words like "the", made before
# Mnemos's linking fixes of 2026-09-25, are left out; links formed by real
# recall, lessons, contradictions and supports are always kept.
LINKING_FIXED = datetime(2026, 9, 25, 8, 0, tzinfo=timezone.utc)
AUTOMATIC = {"consolidation_no_llm", "encoding_no_llm", "consolidation", "encoding"}
ENGRAM = re.compile(r"engram_[0-9A-Z]{26}")
HOUR_ID = re.compile(r"[0-9A-Za-z_-]{1,128}")
# Folders in the studio that hold tools, not things an hour made.
NOT_MADE = {"worktrees", "node_modules", "__pycache__"}
MOST_STUDIO_FILES = 5000
# A scheduled command that runs the hours: `mnemos … life --hour mine|ours|dream`.
RUNS_LIFE = re.compile(r"(?:^|[\s/])mnemos(?:\s+\S+)*?\s+life\s")
HOUR_KIND = re.compile(r"--hour[\s=](mine|ours|dream)\b")
NAMED_AGENT = re.compile(r"--agent-id[\s=](\S+)")
# A systemd timer that fires once a day, at a time of day.
ON_CALENDAR = re.compile(r"^OnCalendar=\*-\*-\* (\d{1,2}):(\d{2})(?::\d{2})?\s*$", re.MULTILINE)


def person_name(given: str | None = None) -> str:
    """The person's name: ``given`` (``--person-name``), else MNEMOS_PERSON_NAME,
    in one line; ``""`` when neither says."""
    name = given if given is not None else named_in_the_environment("MNEMOS_PERSON_NAME")
    return " ".join((name or "").split())[:80]


def when(value: Any) -> datetime | None:
    """A stored time as an aware datetime, or None."""
    if not value:
        return None
    try:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def iso(moment: datetime | None) -> str | None:
    return moment.isoformat() if moment else None


def inside(root: Path, path: Path) -> bool:
    """Whether ``path``, links followed, is ``root`` or within it."""
    try:
        return Path(os.path.realpath(path)).is_relative_to(os.path.realpath(root))
    except (OSError, ValueError):
        return False


def open_read_only(path: Path) -> sqlite3.Connection:
    """A connection that cannot write ``path``, and leaves nothing beside it.

    Mnemos keeps its stores in WAL mode. One that no process has open has no
    -wal or -shm file next to it, and a plain read-only open would make both
    (SQLite coordinates readers through them) and leave them there. Opened
    immutable it makes nothing, and with no -wal there is nothing newer to
    miss. A store in use (its -wal is there) is opened read-only in the
    ordinary way and sees every committed write.
    """
    real = Path(path).expanduser().resolve()  # SQLite keeps the -wal beside the file itself, not a link to it
    uri = f"{real.as_uri()}?mode=ro"
    if not Path(f"{real}-wal").exists() and not Path(f"{real}-journal").exists():
        uri += "&immutable=1"
    conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


class _Reading:
    """One read of a store: its connection and the scope every query keeps to.

    Stores written by an older Mnemos lack the newer tables and columns; the
    export reads around them and migrates nothing.
    """

    def __init__(self, conn: sqlite3.Connection, scope: MnemosScope) -> None:
        self.c = conn
        self.scope = scope
        self._columns: dict[str, set[str]] = {}

    def has(self, table: str) -> bool:
        return self.c.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone() is not None

    def columns(self, table: str) -> set[str]:
        if table not in self._columns:
            self._columns[table] = {row[1] for row in self.c.execute(f"PRAGMA table_info({table})")}
        return self._columns[table]

    def scoped(self, table: str, owner: str = "agent_id") -> tuple[str, tuple[str, ...]]:
        """The scope clause for a table, from the columns it has: older tables
        were scoped by agent alone."""
        names = self.columns(table)
        parts, params = [f"{owner}=?"], [self.scope.agent_id]
        for name, value in (("person_id", self.scope.person_id),
                            ("project_scope", self.scope.project_scope)):
            if name in names:
                if value == UNFILED:           # a store from before memories were filed by person and project
                    parts.append(f"({name} IS NULL OR {name}='')")
                    continue
                parts.append(f"{name}=?")
                params.append(value)
        return " AND ".join(parts), tuple(params)

    def col(self, table: str, name: str, default: str = "''") -> str:
        """A column if this store has it, else a stand-in."""
        return name if name in self.columns(table) else f"{default} AS {name}"

    def journal_rows(self, where: str = "", params: tuple = ()) -> list[dict]:
        if not self.has("journal_entries"):
            return []
        clause, scope = self.scoped("journal_entries")
        return [{"id": r["id"], "at": r["created_at"], "text": r["text"], "mood": r["mood"] or "",
                 "written": r["written"] or "", "model": r["model_id"] or "", "hour": r["hour_id"] or ""}
                for r in self.c.execute(
                    f"SELECT * FROM journal_entries WHERE {clause} {where} ORDER BY created_at DESC",
                    (*scope, *params))]

    def note_rows(self, where: str = "", params: tuple = ()) -> list[dict]:
        if not self.has("notes"):
            return []
        clause, scope = self.scoped("notes")
        return [{"id": r["id"], "at": r["created_at"], "kind": r["kind"] or "", "text": r["text"],
                 "author": r["author"] or "", "model": r["model_id"] or "", "replyTo": r["in_reply_to"] or "",
                 "hour": r["hour_id"] or "", "delivered": r["delivered_at"], "read": r["read_at"]}
                for r in self.c.execute(
                    f"SELECT * FROM notes WHERE {clause} {where} ORDER BY created_at DESC",
                    (*scope, *params))]

    def model(self) -> str:
        """The model that signs this mind's memories: the one that introduced
        itself under this scope, else the newest signature on its own words."""
        model = ""
        if self.has("meta"):
            key = f"simple:{self.scope.agent_id}:{self.scope.person_id}:{self.scope.project_scope}:agent_model"
            row = self.c.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
            model = row[0] if row else ""
        if not model and {"author_model", "author_kind"} <= self.columns("engrams"):
            clause, scope = self.scoped("engrams", owner="owner_agent_id")
            row = self.c.execute(
                f"SELECT author_model FROM engrams WHERE {clause} AND author_kind='agent' "
                "AND author_model != '' ORDER BY created_at DESC LIMIT 1", scope).fetchone()
            model = row[0] if row else ""
        return model or ""

    def memory_rows(self, state: str | None = None, limit: int | None = None,
                    offset: int = 0) -> list[sqlite3.Row]:
        """The memories of this scope, active and dormant (or only those in
        ``state``), oldest first and in a stable order, from ``offset`` on, at
        most ``limit`` of them (None: all). The one reading of them, for the
        log and for ``mnemos memories``."""
        clause, scope = self.scoped("engrams", owner="owner_agent_id")
        states = (state,) if state else ("active", "dormant")
        marks = ", ".join("?" for _ in states)
        return list(self.c.execute(
            f"""SELECT id, content, {self.col('engrams', 'impact')}, kind, accessibility, state, created_at,
            last_accessed, {self.col('engrams', 'author_kind', "'unknown'")}, {self.col('engrams', 'author_model')},
            {self.col('engrams', 'author_session')}, {self.col('engrams', 'lineage', "'{}'")},
            {self.col('engrams', 'standing', '0')}, {self.col('engrams', 'strength', '0.5')},
            {self.col('engrams', 'stability', '0.5')}
            FROM engrams WHERE {clause} AND state IN ({marks}) ORDER BY created_at, id
            LIMIT ? OFFSET ?""", (*scope, *states, -1 if limit is None else limit, offset)))

    def state_counts(self) -> dict[str, int]:
        """How many memories this scope holds in each state."""
        clause, scope = self.scoped("engrams", owner="owner_agent_id")
        return {r[0]: r[1] for r in self.c.execute(
            f"SELECT state, count(*) FROM engrams WHERE {clause} GROUP BY state", scope)}

    def kept_rows(self, ids: Any) -> list[sqlite3.Row]:
        """``id``, ``created_at`` and ``lineage`` of the memories of this
        scope that ``ids`` names, in any state: what a line of corrections
        reads to find when its first version was kept."""
        clause, scope = self.scoped("engrams", owner="owner_agent_id")
        lineage = self.col("engrams", "lineage", "'{}'")
        wanted = sorted(set(ids))
        rows: list[sqlite3.Row] = []
        for start in range(0, len(wanted), 400):
            chunk = wanted[start:start + 400]
            marks = ", ".join("?" for _ in chunk)
            rows += self.c.execute(
                f"SELECT id, created_at, {lineage} FROM engrams WHERE {clause} AND id IN ({marks})",
                (*scope, *chunk)).fetchall()
        return rows

    def memories(self) -> tuple[list[dict], str]:
        """Every memory in this scope, whole, with how it's tied to the others
        and how often it came back; and a version that changes when they do."""
        rows = self.memory_rows()
        ids = {r["id"] for r in rows}
        asked: set[str] = set()
        if self.has("reflection_queue"):
            q_clause, q_scope = self.scoped("reflection_queue")
            retired = ", ".join("?" for _ in RETIRED_REFLECTION_KINDS)
            asked = {r[0] for r in self.c.execute(
                f"SELECT target_id FROM reflection_queue WHERE {q_clause} AND answered_at IS NULL "
                f"AND kind NOT IN ({retired})", (*q_scope, *RETIRED_REFLECTION_KINDS))}
        recalls: dict[str, int] = {}
        recalled: list[list[str]] = []
        if self.has("session_reinforcements"):
            for engram_id, at in self.c.execute(
                    "SELECT engram_id, reinforced_at FROM session_reinforcements ORDER BY reinforced_at"):
                if engram_id in ids:
                    recalls[engram_id] = recalls.get(engram_id, 0) + 1
                    recalled.append([engram_id, iso(when(at))])
        ties: dict[str, list] = {i: [] for i in ids}
        lessons: set[str] = set()
        seen: set[tuple] = set()
        if self.has("connections"):
            for r in self.c.execute(
                    "SELECT source_id, target_id, relation, strength, formed_at, formed_by FROM connections"):
                source, target = r["source_id"], r["target_id"]
                if source not in ids or target not in ids or source == target:
                    continue
                born = when(r["formed_at"])
                if (r["formed_by"] in AUTOMATIC and r["relation"] == "co_activated"
                        and (born is None or born < LINKING_FIXED)):
                    continue
                key = (min(source, target), max(source, target), r["relation"])
                if key in seen:
                    continue
                seen.add(key)
                weight = round(r["strength"] or 0, 3)
                # who it goes from, so the drawing can send a fibre the right way; when, and what made it
                ties[source].append([target, r["relation"], weight, iso(born), r["formed_by"] or "", 1])
                ties[target].append([source, r["relation"], weight, iso(born), r["formed_by"] or "", 0])
                if r["relation"] == "distilled_into":
                    lessons.add(target)
        out = []
        for r in rows:
            content, impact = (r["content"] or "").strip(), (r["impact"] or "").strip()
            out.append({
                "id": r["id"], "born": r["created_at"], "touched": r["last_accessed"], "kind": r["kind"] or "",
                "lesson": r["id"] in lessons or "lesson" in (r["kind"] or ""), "standing": bool(r["standing"]),
                "asked": r["id"] in asked, "state": r["state"], "author": r["author_kind"] or "unknown",
                "model": r["author_model"] or "", "acc": round(r["accessibility"] or 0, 3),
                "recalls": recalls.get(r["id"], 0), "ties": sorted(ties[r["id"]], key=lambda tie: -tie[2]),
                "strength": round(r["strength"] if r["strength"] is not None else 0.5, 3),
                "stability": round(r["stability"] if r["stability"] is not None else 0.5, 3),
                "content": content, "impact": impact if impact != content else "",
            })
        digest = hashlib.sha1(usedforsecurity=False)  # a version stamp, not a secret
        digest.update(f"recalled {len(recalled)}".encode())
        for m in out:
            digest.update(f"{m['id']}|{m['state']}|{len(m['content'])}|{len(m['impact'])}|{m['standing']}"
                          f"|{m['asked']}|{len(m['ties'])}".encode())
        return out, recalled, digest.hexdigest()[:12]

    def questions(self) -> list[dict]:
        """Every question its memory asked it, newest first. One of a kind no
        longer asked (the contradiction question) is history once answered;
        still waiting, it is left out, as the wake leaves it out."""
        if not self.has("reflection_queue"):
            return []
        clause, scope = self.scoped("reflection_queue")
        retired = ", ".join("?" for _ in RETIRED_REFLECTION_KINDS)
        return [dict(r) for r in self.c.execute(
            "SELECT id, kind, prompt, excerpt, surfaced_count, created_at, answered_at, answer, target_id "
            f"FROM reflection_queue WHERE {clause} "
            f"AND (answered_at IS NOT NULL OR kind NOT IN ({retired})) ORDER BY created_at DESC",
            (*scope, *RETIRED_REFLECTION_KINDS))]

    def beliefs(self) -> list[dict]:
        if not self.has("beliefs"):
            return []
        out = []
        for r in self.c.execute(
                "SELECT content, confidence, created_at, last_revised, revision_history, supporting_engram_ids "
                "FROM beliefs WHERE agent_id=? AND superseded_by IS NULL", (self.scope.agent_id,)):
            try:
                history = json.loads(r["revision_history"] or "[]")
                supports = json.loads(r["supporting_engram_ids"] or "[]")
            except ValueError:
                history, supports = [], []
            out.append({"text": r["content"], "confidence": r["confidence"], "born": r["created_at"],
                        "revised": r["last_revised"], "revisions": len(history),
                        "history": [{"at": h.get("timestamp"), "from": h.get("old_confidence"),
                                     "to": h.get("new_confidence")}
                                    for h in history[-12:] if isinstance(h, dict)],
                        "supports": [s for s in supports if isinstance(s, str)]})
        return out

    def handoffs(self) -> list[dict]:
        """The notes the mind left itself. Each conversation keeps one current
        note; the ones it replaced are history, not news."""
        if not self.has("hypomnema_entries") or "entry_kind" not in self.columns("hypomnema_entries"):
            return []
        names = self.columns("hypomnema_entries")
        clause, scope = self.scoped("hypomnema_entries")
        clause += " AND entry_kind='handoff'"
        if "authored_by" in names:
            clause += " AND authored_by='agent'"
        if "active" in names:
            clause += " AND active=1"
        return [{"text": r["content"].strip(), "at": r["created_at"], "model": r["author_model"] or ""}
                for r in self.c.execute(
                    f"SELECT content, created_at, {self.col('hypomnema_entries', 'author_model')} "
                    f"FROM hypomnema_entries WHERE {clause} ORDER BY created_at DESC LIMIT 40", scope)]


def _blocks(event: dict) -> list[dict]:
    message = event.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    return [b for b in content if isinstance(b, dict)] if isinstance(content, list) else []


def _events(folder: Path) -> list[dict]:
    path = folder / "stream.jsonl"
    if not path.is_file():
        return []
    events = []
    with path.open(encoding="utf-8", errors="replace") as stream:
        for line in stream:
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if isinstance(event, dict):
                events.append(event)
    return events


def _last_words(events: list[dict]) -> str:
    """The hour's own closing message (the stream's result), so you can read
    how it said the hour went."""
    said = ""
    for event in events:
        if event.get("type") == "result" and isinstance(event.get("result"), str):
            said = event["result"]
    return said


def _denials(events: list[dict]) -> list[str]:
    """Tool calls the fences refused during the hour: the first thing to read
    if an hour seems thin."""
    names: dict[Any, str] = {}
    refused = []
    for event in events:
        for block in _blocks(event):
            if block.get("type") == "tool_use":
                names[block.get("id")] = block.get("name", "")
            elif block.get("type") == "tool_result" and "was denied" in json.dumps(block.get("content"))[:600]:
                refused.append(re.sub(r"^mcp__[A-Za-z0-9_-]+?__", "",
                                      names.get(block.get("tool_use_id"), "a tool")))
    return refused


def _trail(folder: Path, events: list[dict]) -> dict[str, list[str]]:
    """The path an hour walked through the memory, from its own record: the
    memories its waking named, the questions waiting for it (prompt.md), and
    the memories it reached for with its own tools, each in the order it first
    met them. Refused calls reach nothing."""
    woke: list[str] = []
    waiting: list[str] = []
    reached: list[str] = []

    def add(into: list[str], text: str) -> None:
        # what it was handed is counted once; what it reached for counts even
        # when it was handed it first
        for memory in ENGRAM.findall(text):
            if memory not in into and (into is reached or (memory not in woke and memory not in waiting)):
                into.append(memory)

    for event in events:
        if event.get("type") == "system" and event.get("subtype") == "hook_response":
            add(woke, str(event.get("output") or ""))
    prompt = folder / "prompt.md"
    if prompt.is_file():
        add(waiting, prompt.read_text(encoding="utf-8", errors="replace"))
    for event in events:
        for block in _blocks(event):
            if block.get("type") == "tool_use":
                add(reached, json.dumps(block.get("input")))
            elif block.get("type") == "tool_result":
                text = json.dumps(block.get("content"))
                if "was denied" not in text[:600]:
                    add(reached, text)
    return {"woke": woke, "waiting": waiting, "reached": reached}


def _signature(path: Path) -> tuple[int, int] | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    return stat.st_size, stat.st_mtime_ns


def _served_from_a_host() -> bool:
    """Whether a host that hands Mnemos its keys (Hermes) serves this page. Its
    plugin rules keep a plugin to its own data and to the programs it says it
    starts, so from there the page shows the memory and looks at nothing else
    on the machine."""
    from ..llm import host_secrets_active

    return host_secrets_active()


def _launch_agents() -> Path:
    return Path.home() / "Library" / "LaunchAgents"


def _launchd_loaded(label: str) -> bool:
    try:
        return subprocess.run(["launchctl", "list", label], capture_output=True,
                              timeout=5, check=False).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _systemd_units() -> Path:
    return Path.home() / ".config" / "systemd" / "user"


def _systemd_active(timer: str) -> bool:
    try:
        return subprocess.run(["systemctl", "--user", "is-active", "--quiet", timer],
                              capture_output=True, timeout=5, check=False).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _crontab() -> str:
    """This user's crontab, or ``""``. Not read on macOS, where the hours are
    scheduled with launchd."""
    if sys.platform == "darwin" or not shutil.which("crontab"):
        return ""
    try:
        listed = subprocess.run(["crontab", "-l"], capture_output=True, text=True,
                                timeout=5, check=False)
    except (OSError, subprocess.SubprocessError):
        return ""
    return listed.stdout if listed.returncode == 0 else ""


@dataclass
class Exporter:
    """The log's documents for one scope. Keeps what an hour's stream says
    between reads, since a finished hour's record doesn't change."""

    scope: MnemosScope
    person: str = ""
    _hour_cache: dict[str, tuple[Any, dict]] = field(default_factory=dict, repr=False)

    @classmethod
    def for_scope(cls, *, db_path: str | None = None, agent_id: str | None = None,
                  person_id: str | None = None, project_scope: str | None = None,
                  person: str | None = None) -> "Exporter":
        """An exporter for the scope the one resolver gives these flags."""
        return cls(resolve_scope(db_path=db_path, agent_id=agent_id, person_id=person_id,
                                 project_scope=project_scope), person_name(person))

    @property
    def db(self) -> Path:
        return Path(self.scope.db_path).expanduser()

    @property
    def hours_dir(self) -> Path | None:
        """Where the hours keep their records, or None where hours can't run."""
        try:
            from ..life import hours_dir
        except ImportError:  # the runner needs fcntl, which Windows lacks
            return None
        return hours_dir(self.scope.agent_id)

    @property
    def studio_dir(self) -> Path | None:
        try:
            from ..life import studio_dir
        except ImportError:
            return None
        return studio_dir(self.scope.agent_id)

    def _store_shown(self) -> str:
        home, path = str(Path.home()), str(self.db)
        return "~" + path[len(home):] if path == home or path.startswith(home + os.sep) else path

    def identity(self, model: str = "") -> dict:
        """Who this is: the model that signs its memories, named as Mnemos names it."""
        return {"agentId": self.scope.agent_id, "model": model, "unfiled": UNFILED in (self.scope.person_id, self.scope.project_scope),
                "name": (display_name(model) if model else "") or self.scope.agent_id,
                "person": self.person or None, "personId": self.scope.person_id,
                "project": self.scope.project_scope, "store": self._store_shown()}

    def studio(self) -> list[dict]:
        """What the hours made, newest first: every file in the studio, and
        for a picture the address the page shows it from."""
        root = self.studio_dir
        if root is None or not root.is_dir():
            return []
        files: list[dict] = []
        for folder, dirs, names in os.walk(root):
            dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d not in NOT_MADE)
            for name in sorted(names):
                path = Path(folder) / name
                if name.startswith(".") or not inside(root, path):
                    continue  # a link out of the studio is not something it made
                try:
                    stat = path.stat()
                except OSError:
                    continue
                rel = path.relative_to(root).as_posix()
                item = {"path": rel, "bytes": stat.st_size,
                        "at": iso(datetime.fromtimestamp(stat.st_mtime, timezone.utc)), "picture": None}
                if path.suffix.lower() in PICTURES and stat.st_size <= MOST_BYTES:
                    item["picture"] = "../data/studio/" + quote(rel)
                files.append(item)
            if len(files) >= MOST_STUDIO_FILES:
                break
        return sorted(files, key=lambda f: f["at"], reverse=True)

    def _walked(self, hour_id: str, folder: Path) -> dict:
        """What an hour's own record says: its last words, what was refused,
        the trail it walked. Read once per change of its stream and prompt."""
        key = (_signature(folder / "stream.jsonl"), _signature(folder / "prompt.md"))
        cached = self._hour_cache.get(hour_id)
        if cached and cached[0] == key:
            return cached[1]
        events = _events(folder)
        walked = {"said": _last_words(events), "refused": _denials(events), "trail": _trail(folder, events)}
        self._hour_cache[hour_id] = (key, walked)
        return walked

    def hours(self, files: list[dict], live: _Reading) -> list[dict]:
        """Every quiet hour, newest first, from the hours' own record."""
        root = self.hours_dir
        record_path = root / "hours.jsonl" if root else None
        if record_path is None or not record_path.is_file():
            return []
        records = []
        for line in record_path.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if isinstance(record, dict) and HOUR_ID.fullmatch(str(record.get("id") or "")):
                records.append(record)
        out = []
        for r in reversed(records):
            folder = root / r["id"]
            start, end = when(r.get("started_at")), when(r.get("ended_at"))
            practice = r.get("store") == "copy"
            journal: list[dict] = []
            notes: list[dict] = []
            if r.get("journal_ids") or r.get("note_ids"):
                if not practice:
                    journal = live.journal_rows("AND hour_id=?", (r["id"],))
                    notes = live.note_rows("AND hour_id=?", (r["id"],))
                elif (folder / "store.db").is_file():
                    copy = open_read_only(folder / "store.db")
                    try:
                        reading = _Reading(copy, self.scope)
                        journal = reading.journal_rows("AND hour_id=?", (r["id"],))
                        notes = reading.note_rows("AND hour_id=?", (r["id"],))
                    except sqlite3.Error:
                        logger.debug("could not read the practice copy of hour %s", r["id"], exc_info=True)
                    finally:
                        copy.close()
            made = []
            if start and end:
                for item in files:
                    moment = when(item["at"])
                    if moment and start <= moment <= end + timedelta(seconds=30):
                        made.append(item["path"])
            model = r.get("model") or ""
            out.append({
                "id": r["id"], "kind": r.get("kind"), "practice": practice, "status": r.get("status"),
                "reason": r.get("reason") or "", "start": r.get("started_at"), "end": r.get("ended_at"),
                "minutes": round((end - start).total_seconds() / 60, 1) if start and end else None,
                "model": model, "modelName": display_name(model) if model else "",
                "tokens": r.get("tokens"), "waiting": r.get("waiting"),
                # only the row check (by hour id) answers "did this hour write
                # to the real memory"; the first hours were checked by hashing
                # the whole file, which any other session writing at the time
                # would trip
                "untouched": r.get("live_store_untouched"),
                "check": "rows" if "live_store_untouched" in r else (
                    "whole-file" if "live_store_unchanged" in r else None),
                "discarded": r.get("discarded_ids") or [], "journal": journal, "notes": notes, "made": made,
                **self._walked(r["id"], folder),
            })
        return out

    def _runs_hours_here(self, command: str) -> str | None:
        """The kind of hour a scheduled command runs for this agent, or None.
        Only a job that really runs the hours counts: `mnemos … life --hour …`
        (a scheduled session whose instructions merely mention "life" is not an
        hour), for this agent, named or by default."""
        command = f"{command} "
        kind = HOUR_KIND.search(command)
        if not RUNS_LIFE.search(command) or not kind:
            return None
        named = NAMED_AGENT.search(command)
        agent = resolve_scope(agent_id=named.group(1).strip("'\"") if named else None).agent_id
        return kind.group(1) if agent == self.scope.agent_id else None

    @staticmethod
    def jev() -> dict:
        """Jev, the cue's judge, as Settings shows it: whether it's switched
        on, whether a key is saved (never the key), whether the environment
        decides the switch, and what leaves the machine with each message."""
        from .. import jev

        if _served_from_a_host():
            # Never Mnemos's to use there (its key is in a file, and a host's
            # plugin reads no key from one), so the page looks for neither the
            # switch nor the key file.
            return {"on": False, "key": False, "env": False}
        try:
            status = jev.status()
        except Exception:
            return {"on": False, "key": False, "env": False}
        return {"on": status["switched_on"], "key": status["key"],
                "env": bool((os.environ.get(jev.SWITCH_ENV) or "").strip()), "host": status["host"],
                "messageChars": status["message_chars"], "candidates": status["candidates"],
                "lineChars": status["line_chars"]}

    def schedule(self) -> list[dict]:
        """Whether anything wakes the hours on its own: a LaunchAgent, a
        systemd user timer (what `mnemos daemon install --hours` writes where
        systemd runs) or a crontab line that runs them for this agent. ``when``
        is the time of day when the schedule names one, else None.

        Served from inside a host (Hermes), nothing is looked for: the hours
        aren't set from there, and the page reads nobody's LaunchAgents, timers
        or crontab, and starts no program to ask whether one is loaded. Until
        0.6.7 it did, each time the page was read."""
        found = []
        if _served_from_a_host():
            return found
        agents = _launch_agents()
        for plist_path in sorted(agents.glob("*.plist")) if agents.is_dir() else []:
            try:
                with plist_path.open("rb") as handle:
                    plist = plistlib.load(handle)
            except Exception:
                continue
            if not isinstance(plist, dict):
                continue
            args = " ".join(str(a) for a in (plist.get("ProgramArguments") or [plist.get("Program", "")]))
            kind = self._runs_hours_here(args)
            if not kind:
                continue
            label = str(plist.get("Label") or plist_path.stem)
            interval = plist.get("StartCalendarInterval")
            at = None
            if isinstance(interval, dict) and isinstance(interval.get("Hour"), int) \
                    and isinstance(interval.get("Minute", 0), int):
                at = {"Hour": interval["Hour"], "Minute": interval.get("Minute", 0)}
            found.append({"label": label, "when": at, "kind": kind, "loaded": _launchd_loaded(label)})
        units = _systemd_units()
        for service in sorted(units.glob("*.service")) if units.is_dir() else []:
            try:
                lines = service.read_text().splitlines()
            except (OSError, UnicodeDecodeError):
                continue
            command = next((line.partition("=")[2] for line in lines if line.startswith("ExecStart=")), "")
            kind = self._runs_hours_here(command)
            if not kind:
                continue
            timer = service.with_suffix(".timer")
            try:
                daily = ON_CALENDAR.search(timer.read_text())
            except (OSError, UnicodeDecodeError):
                daily = None
            at = {"Hour": int(daily.group(1)), "Minute": int(daily.group(2))} if daily else None
            found.append({"label": timer.name, "when": at, "kind": kind, "loaded": _systemd_active(timer.name)})
        for line in _crontab().splitlines():
            fields = line.split(None, 5)
            if line.lstrip().startswith("#") or len(fields) < 6:
                continue
            kind = self._runs_hours_here(fields[5])
            if not kind:
                continue
            minute, hour = fields[0], fields[1]
            at = ({"Hour": int(hour), "Minute": int(minute)}
                  if hour.isdigit() and minute.isdigit() and fields[2:5] == ["*", "*", "*"] else None)
            found.append({"label": "crontab", "when": at, "kind": kind, "loaded": True})
        return found

    def export(self, now: datetime | None = None) -> tuple[dict, dict]:
        """The page's two documents, ``(life, memories)``. Writes nothing."""
        from ..shared_memory import notebook

        # Inside a host the page is of this agent's memory alone, and the
        # shared one is every agent's: not read here, and the page says so.
        shared = {"status": "elsewhere", "rows": []} if _served_from_a_host() else notebook()
        now = now or datetime.now(timezone.utc)
        if not self.db.is_file():
            return ({"made": iso(now), "missing": True, "identity": self.identity(), "shared": shared},
                    {"version": None, "made": iso(now), "memories": []})
        files = self.studio()
        conn = open_read_only(self.db)
        try:
            reading = _Reading(conn, self.scope)
            who = self.identity(reading.model())
            journal = reading.journal_rows()
            notes = reading.note_rows()
            asks = reading.questions()
            clause, scope = reading.scoped("engrams", owner="owner_agent_id")
            counts = reading.state_counts()
            newest = conn.execute(f"SELECT max(created_at) FROM engrams WHERE {clause}", scope).fetchone()[0]
            beliefs = reading.beliefs()
            handoffs = reading.handoffs()
            memories, recalled, version = reading.memories()
            hours = self.hours(files, reading)
        finally:
            conn.close()
        open_asks = [a for a in asks if not a["answered_at"]]
        by_kind: dict[str, int] = {}
        for ask in open_asks:
            by_kind[ask["kind"]] = by_kind.get(ask["kind"], 0) + 1
        answered = sorted((a for a in asks if a["answered_at"]), key=lambda a: a["answered_at"], reverse=True)
        life = {
            "made": iso(now),
            "identity": who,
            "hours": hours,
            "schedule": self.schedule(),
            "jev": self.jev(),
            "shared": shared,
            "journal": journal,
            "notes": notes,
            "studio": files,
            "questions": {
                "open": len(open_asks), "byKind": by_kind,
                "asked": [{"id": a["id"], "kind": a["kind"], "prompt": (a["prompt"] or "").split(" [")[0],
                           "excerpt": a["excerpt"] or "", "shown": a["surfaced_count"] or 0, "at": a["created_at"],
                           "about": a["target_id"]} for a in open_asks],
                "answered": [{"kind": a["kind"], "prompt": (a["prompt"] or "").split(" [")[0],
                              "excerpt": a["excerpt"] or "", "answer": a["answer"] or "", "at": a["answered_at"],
                              "about": a["target_id"]} for a in answered],
            },
            "memory": {"states": counts, "newest": newest, "storeBytes": self.db.stat().st_size,
                       "version": version, "count": len(memories)},
            "beliefs": beliefs,
            "handoffs": handoffs,
        }
        return life, {"version": version, "made": iso(now), "memories": memories, "recalled": recalled}


# ── What came to mind just now ──

# What each kind of call did to the memories it names: a recall brings them back, a wake is the briefing, a reflection
# answers what the memory asked; a capture or a correction keeps one.
PULSE_READ = {"recall": "recall", "context": "wake", "reflect": "reflect"}
PULSE_WRITTEN = {"capture": "kept", "correct": "kept"}
PULSE_MOST = 120


def pulse(exporter: "Exporter", since: str | None = None, now: datetime | None = None) -> dict:
    """What came to this mind since ``since`` (ISO 8601; with none, the last
    minute): every memory a call brought back, a briefing showed or a capture
    kept (``memory_trace``, one row a call), and every memory the cue offered
    with a message (the session files under ``~/.mnemos/run``), oldest first,
    at most ``PULSE_MOST``. Each event: ``{"key", "at", "kind", "ids",
    "session"}``; ``key`` is the same each time an event is read again, so a
    page that asks with some overlap can tell what it has already shown.
    Reads only; ``now`` is the time to ask from next."""
    from ..cue import run_dir, scope_key

    now = now or datetime.now(timezone.utc)
    floor = when(since) or (now - timedelta(minutes=1))
    after = iso(floor)
    events: list[dict] = []
    if exporter.db.is_file():
        conn = open_read_only(exporter.db)
        try:
            reading = _Reading(conn, exporter.scope)
            if reading.has("memory_trace"):
                clause, scope = reading.scoped("memory_trace")
                for r in conn.execute(
                        f"SELECT id, at, tool, session, read_ids, written_ids FROM memory_trace "
                        f"WHERE {clause} AND at > ? ORDER BY at LIMIT ?", (*scope, after, PULSE_MOST)):
                    tool = r["tool"]
                    kind = PULSE_READ.get(tool) or PULSE_WRITTEN.get(tool)
                    if not kind:
                        continue
                    try:
                        ids = json.loads(r["read_ids"] if tool in PULSE_READ else r["written_ids"]) or []
                    except ValueError:
                        ids = []
                    ids = [i for i in ids if isinstance(i, str) and i.startswith("engram_")]
                    if ids:
                        events.append({"key": f"t{r['id']}", "at": iso(when(r["at"])), "kind": kind, "ids": ids,
                                       "session": r["session"] or ""})
        finally:
            conn.close()
    folder = run_dir()
    key = scope_key(exporter.scope.db_path, exporter.scope.agent_id, exporter.scope.person_id,
                    exporter.scope.project_scope)
    cutoff = floor.timestamp() - 5
    for path in folder.glob(f"shown-*-{key}.json") if folder.is_dir() else []:
        try:
            if path.stat().st_mtime < cutoff:
                continue
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        session = str(data.get("session") or "")
        for offer in data.get("offers") or []:
            at = when(offer.get("at")) if isinstance(offer, dict) else None
            ids = [i for i in (offer.get("ids") or []) if isinstance(i, str)] if at else []
            if at and at > floor and ids:
                events.append({"key": f"c{session[:12]}{iso(at)}", "at": iso(at), "kind": "cue", "ids": ids, "session": session})
    events.sort(key=lambda e: e["at"])
    return {"now": iso(now), "events": events[-PULSE_MOST:]}
