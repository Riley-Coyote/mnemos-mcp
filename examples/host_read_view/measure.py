"""How fast the host read view is on a very large memory, with made-up data.

Run it from the repository's root, with no network:

    uv run python examples/host_read_view/measure.py

For each size (memories in the scope being read; 1,000, 10,000 and 50,000
unless ``--sizes`` says otherwise) it builds one store file in a temporary
folder that holds two residents of that size: wren, who keeps memories about
pat-example in "lighthouse", and otter, who keeps as many about sam-example
in "orchard". Each also has a journal, notes both ways, handoffs, standing
memories and beliefs. Every word is made up.

Then it times ``mnemos.host_view.read_view`` for every section, in this
process and through the command line (``mnemos view``, a process of its own
each call, as a host runs it): one warm-up call, then ``--runs`` timed calls,
reporting the median and the worst in milliseconds, with the reply's size in
bytes and the store file's size. At the largest size it also times
``summary`` while another process holds the store open for writing, its
newest commit still only in the write-ahead log.

How each store is built:

- **capture**: every memory, journal entry, note and handoff written
  through Mnemos's normal write path (``MnemosRuntime``), and every belief
  through ``EngramStore.save_belief``. Used up to ``--capture-up-to``
  (1,000).
- **direct**: the first few of each kind written through that same path;
  every later one is a copy of the rows that path wrote for the last of its
  kind (memories, the search index, the capture's note, the trace row,
  journal entries, notes, beliefs), with new ids, new words and an earlier
  time. The one thing left out is the links capture draws between similar
  memories (the ``connections`` table): the view never reads it, and copying
  it would more than double the file. So a store built this way is smaller
  than one built through capture.

At every size built through capture, the same plan is also built directly,
and the script checks that both give the same ``summary`` counts and the
same number of items in every section, paged to the end. It exits non-zero
if they differ.

Each store is deleted as soon as its size is measured, and the temporary
folder at the end. The home is redirected there, so nothing outside it is
read or written.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import random
import re
import shutil
import sqlite3
import statistics
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

SIGNED = "example-model"
READ = {"agent_id": "wren", "person_id": "pat-example", "project_scope": "lighthouse"}
OTHER = {"agent_id": "otter", "person_id": "sam-example", "project_scope": "orchard"}
SECTIONS = ("summary", "memories", "standing", "journal", "notes", "handoffs", "beliefs")
VOCAB = (
    "amber basin cedar dune ember fjord grove harbour inlet juniper kelp lantern meadow nettle "
    "orchard pebble quarry reed slate thistle umber vale willow yarrow binder ledger shelf tide "
    "table door window kettle ladder rope compass chart lamp wick oil gate fence hedge path bridge "
    "river stone moss fern birch alder rowan heather bracken gorse sorrel clover thyme sage mint"
).split()
# The tables a direct build copies rows into, in the order they are written.
COPIED = ("engrams", "engrams_fts", "hypomnema_entries", "memory_trace", "journal_entries", "notes", "beliefs")
# Memories written per transaction in a direct build, so the write-ahead log
# never grows past one batch.
BATCH = 2_000
_ULID = re.compile(r"^([a-z]+_)?[0-9A-HJKMNP-TV-Z]{26}$")
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_STAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:[+-]\d{2}:\d{2}|Z)?")


# ── The plan: what each resident holds, the same however it's built ──


def plan(n: int) -> dict[str, int]:
    """How much one resident of ``n`` memories holds: one standing memory in
    fifty, a journal entry and a note to the person for every twenty
    memories, a note back for every forty, three handoffs, and a belief for
    every hundred, each resting on two of its memories."""
    return {"memories": n, "journal": n // 20, "notes": n // 20, "replies": n // 40,
            "handoffs": 3, "beliefs": n // 100}


def words(owner: str, kind: str, i: int, count: int) -> str:
    rng = random.Random(f"{owner}/{kind}/{i}")
    return f"{kind.capitalize()} {i} of {owner}: " + " ".join(rng.choice(VOCAB) for _ in range(count)) + "."


def memory_words(owner: str, i: int) -> tuple[str, str, bool]:
    """A memory's words, its impact, and whether it is standing."""
    return words(owner, "memory", i, 36), words(owner, "impact", i, 12), i % 50 == 0


#: Each kind of entry: the word its text starts with, and how many words follow.
ENTRIES = {"journal": ("journal", 70), "notes": ("note", 24), "replies": ("reply", 16), "handoffs": ("handoff", 30)}


def entry_words(owner: str, kind: str, i: int) -> str:
    label, count = ENTRIES[kind]
    return words(owner, label, i, count)


def _memory_id(said: str) -> str:
    return said.split("Memory ID: ", 1)[1].split()[0]


# ── Building through the normal write path ──


def _runtime(db: Path, scope: dict[str, str]):
    from mnemos.simple_runtime import MnemosRuntime

    return MnemosRuntime(db_path=str(db), use_dedicated_model=False, **scope)


def _save_beliefs(db: Path, owner: str, ids: list[str], indexes: range) -> None:
    from mnemos.core.belief import Belief
    from mnemos.store.sqlite_store import EngramStore

    store = EngramStore(db)
    try:
        for b in indexes:
            store.save_belief(Belief(agent_id=owner, content=words(owner, "belief", b, 14), confidence=0.6,
                                     supporting_engram_ids=[ids[2 * b], ids[2 * b + 1]], source="agent",
                                     author_model=SIGNED))
    finally:
        store.close()


def _write(runtime, owner: str, kind: str, i: int) -> list[str]:
    """One write of ``kind`` through the runtime; the memory id, if any."""
    if kind == "memories":
        text, impact, standing = memory_words(owner, i)
        return [_memory_id(runtime.capture(text, impact=impact, signed_as=SIGNED, standing=standing))]
    text = entry_words(owner, kind, i)
    if kind == "journal":
        runtime.journal(text, signed_as=SIGNED)
    elif kind == "notes":
        runtime.note(text, kind="noticed", signed_as=SIGNED)
    elif kind == "replies":
        runtime.person_note(text)
    elif kind == "handoffs":
        runtime.handoff(text, signed_as=SIGNED)
    return []


def build_by_capture(db: Path, n: int) -> None:
    want = plan(n)
    for scope in (READ, OTHER):
        owner = scope["agent_id"]
        runtime = _runtime(db, scope)
        ids: list[str] = []
        try:
            for kind in ("memories", "journal", "notes", "replies", "handoffs"):
                for i in range(want[kind]):
                    ids += _write(runtime, owner, kind, i)
        finally:
            runtime.close()
        _save_beliefs(db, owner, ids, range(want["beliefs"]))


# ── Building directly: copies of what the write path wrote ──


def _marks(db: Path) -> dict[str, int]:
    conn = sqlite3.connect(db)
    try:
        return {t: conn.execute(f"SELECT coalesce(max(rowid), 0) FROM {t}").fetchone()[0] for t in COPIED}
    finally:
        conn.close()


def _rows_since(db: Path, marks: dict[str, int]) -> dict[str, list[dict[str, Any]]]:
    """Every row the write path added to the copied tables since ``marks``."""
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        found = {}
        for table in COPIED:
            columns = "id, content" if table == "engrams_fts" else "*"
            rows = conn.execute(f"SELECT {columns} FROM {table} WHERE rowid > ? ORDER BY rowid",
                                (marks[table],)).fetchall()
            if rows:
                found[table] = [dict(row) for row in rows]
        return found
    finally:
        conn.close()


def _fresh_id(old: str) -> str:
    """A new id of the same shape, made the way Mnemos makes it."""
    from mnemos.core.engram import _gen_ulid

    if _UUID.match(old):
        return str(uuid.uuid4())
    match = _ULID.match(old)
    if not match:
        raise ValueError(f"an id of a shape this script doesn't copy: {old!r}")
    return f"{match.group(1) or ''}{_gen_ulid()}"


def _shift(stamp: str, by: timedelta) -> str:
    moved = datetime.fromisoformat(stamp) + by
    text = moved.isoformat(timespec="microseconds" if "." in stamp else "seconds")
    return text.replace("+00:00", "Z") if stamp.endswith("Z") else text


class Template:
    """The rows one write added, ready to copy with new ids, words and time."""

    def __init__(self, rows: dict[str, list[dict[str, Any]]], texts: list[str]) -> None:
        self.rows = rows
        self.ids = sorted({row["id"] for table, found in rows.items() if table != "engrams_fts"
                           for row in found if isinstance(row.get("id"), str)})
        self.texts = texts
        keys = sorted([*self.ids, *texts], key=len, reverse=True)
        self._keys = re.compile("|".join(re.escape(k) for k in keys))
        self._auto = {table: {row[1] for row in _PK_INTEGERS.get(table, ())} for table in rows}

    def copy(self, new_texts: list[str], by: timedelta, more: dict[str, str] | None = None
             ) -> tuple[dict[str, list[dict[str, Any]]], dict[str, str]]:
        swap = {old: _fresh_id(old) for old in self.ids}
        swap.update(zip(self.texts, new_texts))
        swap.update(more or {})

        def change(value: Any) -> Any:
            if not isinstance(value, str):
                return value
            value = self._keys.sub(lambda m: swap[m.group(0)], value)
            return _STAMP.sub(lambda m: _shift(m.group(0), by), value)

        out = {table: [{k: change(v) for k, v in row.items() if k not in self._auto[table]} for row in found]
               for table, found in self.rows.items()}
        return out, swap


_PK_INTEGERS: dict[str, list[tuple]] = {}


def _learn_columns(db: Path) -> None:
    """Which copied tables number their rows themselves (an INTEGER key the
    copy must leave out, so the store gives it the next number)."""
    conn = sqlite3.connect(db)
    try:
        for table in COPIED:
            if table == "engrams_fts":
                continue
            _PK_INTEGERS[table] = [row for row in conn.execute(f"PRAGMA table_info({table})")
                                   if row[5] and (row[2] or "").upper() == "INTEGER"]
    finally:
        conn.close()


def _insert(conn: sqlite3.Connection, rows: dict[str, list[dict[str, Any]]]) -> None:
    for table in COPIED:
        for row in rows.get(table, ()):
            columns = list(row)
            conn.execute(f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
                         [row[c] for c in columns])


def build_directly(db: Path, n: int) -> None:
    """The first of each kind (and the first two memories: one standing, one
    not) through the normal write path; the rest copied from what it wrote."""
    want = plan(n)
    step = timedelta(minutes=10)
    for scope in (READ, OTHER):
        owner = scope["agent_id"]
        templates: dict[str, Template] = {}
        ids: dict[int, str] = {}
        runtime = _runtime(db, scope)
        try:
            for kind in ("memories", "journal", "notes", "replies", "handoffs"):
                seeded = want[kind] if kind == "handoffs" else min(want[kind], 2 if kind == "memories" else 1)
                for i in range(seeded):
                    before = _marks(db) if db.exists() else dict.fromkeys(COPIED, 0)
                    got = _write(runtime, owner, kind, i)
                    if not _PK_INTEGERS:
                        _learn_columns(db)
                    if kind == "handoffs":
                        continue
                    if kind == "memories":
                        ids[i] = got[0]
                        text, impact, standing = memory_words(owner, i)
                        templates["standing" if standing else "memory"] = Template(
                            _rows_since(db, before), [text, impact])
                    else:
                        templates[kind] = Template(_rows_since(db, before), [entry_words(owner, kind, i)])
        finally:
            runtime.close()
        if want["beliefs"]:
            before = _marks(db)
            _save_beliefs(db, owner, [ids[0], ids[1]], range(1))
            first = _rows_since(db, before)
            templates["beliefs"] = Template(first, [words(owner, "belief", 0, 14), ids[0], ids[1]])

        conn = sqlite3.connect(db, isolation_level=None)
        try:
            conn.execute("BEGIN")
            for i in range(2, want["memories"]):
                text, impact, standing = memory_words(owner, i)
                rows, swap = templates["standing" if standing else "memory"].copy(
                    [text, impact], -step * (want["memories"] - i))
                ids[i] = next(new for old, new in swap.items() if old.startswith("engram_"))
                _insert(conn, rows)
                if i % BATCH == 0:
                    conn.execute("COMMIT")
                    conn.execute("BEGIN")
            for kind in ("journal", "notes", "replies"):
                for i in range(1, want[kind]):
                    rows, _ = templates[kind].copy([entry_words(owner, kind, i)], -step * (want[kind] - i))
                    _insert(conn, rows)
            for b in range(1, want["beliefs"]):
                rows, _ = templates["beliefs"].copy([words(owner, "belief", b, 14), ids[2 * b], ids[2 * b + 1]],
                                                    -step * (want["beliefs"] - b))
                _insert(conn, rows)
            conn.execute("COMMIT")
        finally:
            conn.close()


# ── Reading ──


def _view(db: Path, section: str, **extra: Any) -> dict[str, Any]:
    from mnemos.host_view import read_view

    return read_view(protocol=1, db_path=str(db), section=section, **READ, **extra)


def _shape(db: Path) -> dict[str, Any]:
    """The summary's counts and how many items each list section holds,
    paged to the end, for the reading scope and the other one."""
    from mnemos.host_view import LIST_SECTIONS, read_view

    out: dict[str, Any] = {}
    for scope in (READ, OTHER):
        name = scope["agent_id"]
        out[f"{name}.counts"] = read_view(protocol=1, db_path=str(db), section="summary", **scope)["counts"]
        for section in LIST_SECTIONS:
            cursor, items = None, 0
            while True:
                reply = read_view(protocol=1, db_path=str(db), section=section, limit=200, cursor=cursor, **scope)
                items += len(reply["items"])
                if not reply["truncated"]:
                    break
                cursor = reply["next_cursor"]
            out[f"{name}.{section}"] = items
    return out


def _stats(samples: list[float]) -> dict[str, float]:
    return {"median": round(statistics.median(samples), 1), "worst": round(max(samples), 1)}


def _time_inprocess(db: Path, section: str, runs: int) -> tuple[dict[str, float], int]:
    from mnemos.host_view import render

    reply = _view(db, section)  # the warm-up
    size = len(render(reply).encode("utf-8"))
    samples = []
    for _ in range(runs):
        start = time.perf_counter()
        _view(db, section)
        samples.append((time.perf_counter() - start) * 1000)
    return _stats(samples), size


def _command() -> list[str]:
    """``mnemos view`` as installed beside this Python, else the module."""
    script = Path(sys.executable).parent / "mnemos"
    return [str(script), "view"] if script.is_file() else [sys.executable, "-m", "mnemos.cli", "view"]


def _env(home: Path, bytecode: Path) -> dict[str, str]:
    """A host's process: its own home, and compiled bytecode kept in a
    folder of this run's, as an installed Mnemos keeps it after its first
    run (and none written into the checkout)."""
    return {"HOME": str(home), "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "PYTHONPATH": os.pathsep.join(sys.path), "PYTHONPYCACHEPREFIX": str(bytecode),
            "MNEMOS_DISABLE_DOTENV": "1"}


def _time_cli(argv: list[str], env: dict[str, str], runs: int, status: int = 0) -> dict[str, float]:
    samples = []
    for attempt in range(runs + 1):
        start = time.perf_counter()
        done = subprocess.run([*_command(), *argv], capture_output=True, text=True, timeout=300, env=env)
        took = (time.perf_counter() - start) * 1000
        if done.returncode != status:
            raise SystemExit(f"mnemos view {' '.join(argv)} exited {done.returncode}: {done.stdout}{done.stderr}")
        if attempt:
            samples.append(took)
    return _stats(samples)


def _scope_flags(db: Path) -> list[str]:
    return ["--protocol", "1", "--db-path", str(db), "--agent-id", READ["agent_id"],
            "--person-id", READ["person_id"], "--project-scope", READ["project_scope"]]


_WRITER = """
import sys
from mnemos.simple_runtime import MnemosRuntime
runtime = MnemosRuntime(db_path=sys.argv[1], use_dedicated_model=False,
                        agent_id="wren", person_id="pat-example", project_scope="lighthouse")
runtime.capture("Written while the writer holds the store open.", signed_as="example-model")
conn = runtime._store._get_conn()
conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('example-last-write', '1')")
conn.commit()
print("holding", flush=True)
sys.stdin.readline()
runtime.close()
"""


def _with_live_writer(db: Path, n: int, env: dict[str, str], runs: int, cli: bool) -> dict[str, Any]:
    """``summary`` while another process holds the store open, its newest
    commit still only in the write-ahead log."""
    writer = subprocess.Popen([sys.executable, "-c", _WRITER, str(db)], stdin=subprocess.PIPE,
                              stdout=subprocess.PIPE, text=True, env={**env, "MNEMOS_MAINTENANCE": "inline"})
    try:
        if writer.stdout.readline().strip() != "holding":
            raise SystemExit("the writer didn't start")
        if not Path(f"{db}-wal").is_file():
            raise SystemExit("the writer should be holding the write-ahead log open")
        active = _view(db, "summary")["counts"]["memories"]["active"]
        if active != n + 1:
            raise SystemExit(f"the view didn't read the writer's newest commit ({active}, not {n + 1})")
        inprocess, _ = _time_inprocess(db, "summary", runs)
        out = {"inprocess_ms": inprocess}
        if cli:
            out["cli_ms"] = _time_cli([*_scope_flags(db), "--section", "summary"], env, runs)
        return out
    finally:
        writer.stdin.write("\n")
        writer.stdin.close()
        writer.wait(timeout=600)


# ── The run ──


def machine() -> dict[str, str]:
    chip = platform.processor()
    if sys.platform == "darwin":
        try:
            chip = subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"], capture_output=True,
                                  text=True, timeout=10).stdout.strip() or chip
        except OSError:
            pass
    return {"chip": chip, "system": platform.platform(terse=True), "python": platform.python_version(),
            "sqlite": sqlite3.sqlite_version}


def measure(db: Path, n: int, built_by: str, args: argparse.Namespace, env: dict[str, str]) -> dict[str, Any]:
    row: dict[str, Any] = {"size": n, "built_by": built_by, "store_bytes": db.stat().st_size, "sections": {}}
    for section in SECTIONS:
        inprocess, size = _time_inprocess(db, section, args.runs)
        entry: dict[str, Any] = {"inprocess_ms": inprocess, "reply_bytes": size}
        if section in args.cli:
            entry["cli_ms"] = _time_cli([*_scope_flags(db), "--section", section], env, args.runs)
        row["sections"][section] = entry
    return row


def _fmt(stats: dict[str, float] | None) -> str:
    return f"{stats['median']:>8.1f} {stats['worst']:>8.1f}" if stats else f"{'not run':>17}"


def report_size(row: dict[str, Any]) -> None:
    print(f"\n{row['size']:,} memories in the scope read (and as many in the other), built by "
          f"{row['built_by']} in {row['build_seconds']:.1f} s; store file {row['store_bytes']:,} bytes")
    print(f"  {'section':<9} {'in-process ms':>17}   {'command line ms':>17}   {'reply bytes':>11}")
    print(f"  {'':<9} {'median':>8} {'worst':>8}   {'median':>8} {'worst':>8}")
    for section, entry in row["sections"].items():
        print(f"  {section:<9} {_fmt(entry['inprocess_ms'])}   {_fmt(entry.get('cli_ms'))}   "
              f"{entry['reply_bytes']:>11,}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--sizes", default="1000,10000,50000",
                        help="memories in the scope read, comma separated (default 1000,10000,50000)")
    parser.add_argument("--runs", type=int, default=7, help="timed calls after one warm-up (default 7)")
    parser.add_argument("--capture-up-to", type=int, default=1000,
                        help="build through the normal write path up to this size, and check the direct "
                             "build against it there (default 1000)")
    parser.add_argument("--cli", default=",".join(SECTIONS),
                        help="sections to time through the command line too, comma separated, or 'none'")
    parser.add_argument("--try-200k", action="store_true",
                        help="go on to 200,000 if 50,000 built in under two minutes into a file under 300 MB")
    parser.add_argument("--json", type=Path, help="also write every number to this file")
    args = parser.parse_args(argv)
    sizes = [int(s.replace("_", "")) for s in args.sizes.split(",") if s.strip()]
    args.cli = () if args.cli == "none" else tuple(s for s in args.cli.split(",") if s)

    root = Path(tempfile.mkdtemp(prefix="mnemos-view-measure-"))
    home = root / "home"
    (home / ".mnemos").mkdir(parents=True)
    os.environ["HOME"] = str(home)
    os.environ["MNEMOS_DISABLE_DOTENV"] = "1"
    os.environ["MNEMOS_MAINTENANCE"] = "inline"  # upkeep here, not in a process left running
    for name in ("MNEMOS_AGENT_ID", "MNEMOS_PERSON_ID", "MNEMOS_PROJECT_SCOPE", "MNEMOS_DB_PATH"):
        os.environ.pop(name, None)
    env = _env(home, root / "bytecode")
    results: dict[str, Any] = {"machine": machine(), "runs": args.runs, "command": " ".join(_command()),
                               "sizes": [], "shortcut_checks": []}
    print("Measured on " + ", ".join(f"{k} {v}" for k, v in results["machine"].items()))
    print(f"Each number: {args.runs} timed calls after one warm-up. List sections ask for their first page "
          f"at the default limit. Command line: {results['command']}")
    try:
        if args.cli:
            results["startup_cli_ms"] = _time_cli(["--protocol", "0"], env, args.runs, status=2)
            print(f"Start-up alone (a request refused before any store is opened): "
                  f"median {results['startup_cli_ms']['median']} ms, worst {results['startup_cli_ms']['worst']} ms")
        if args.try_200k and 200_000 not in sizes:
            sizes.append(200_000)
        largest = None
        for n in sizes:
            if n == 200_000 and args.try_200k:
                fifty = next((r for r in results["sizes"] if r["size"] == 50_000 and r["built_by"] == "direct"), None)
                if not fifty or fifty["build_seconds"] >= 120 or fifty["store_bytes"] >= 300 * 2**20:
                    results["size_200000"] = "not run: 50,000 didn't build in under two minutes into a file under 300 MB"
                    print(f"\n200,000: {results['size_200000']}")
                    continue
            ways = ["capture", "direct"] if n <= args.capture_up_to else ["direct"]
            shapes = {}
            for way in ways:
                folder = root / f"{n}-{way}"
                folder.mkdir()
                db = folder / "residents.db"
                start = time.perf_counter()
                (build_by_capture if way == "capture" else build_directly)(db, n)
                built = time.perf_counter() - start
                if Path(f"{db}-wal").exists():
                    raise SystemExit("a build left the store open")
                shapes[way] = _shape(db)
                want = plan(n)
                counts = shapes[way]["wren.counts"]
                expected = (want["memories"], -(-want["memories"] // 50), want["journal"],
                            want["notes"] + want["replies"], want["notes"], want["beliefs"])
                got = (counts["memories"]["active"], counts["standing"], counts["journal"],
                       counts["notes"]["all"], counts["notes"]["unread"], counts["beliefs"])
                if got != expected:
                    raise SystemExit(f"the {way} build at {n:,} holds {got}, not the plan's {expected}")
                row = measure(db, n, way, args, env)
                row["build_seconds"] = round(built, 1)
                results["sizes"].append(row)
                report_size(row)
                if n == max(sizes) and way == ways[-1]:
                    largest = (db, n, folder)
                else:
                    shutil.rmtree(folder)
            if len(shapes) == 2:
                same = shapes["capture"] == shapes["direct"]
                results["shortcut_checks"].append({"size": n, "same": same, "capture": shapes["capture"],
                                                   "direct": shapes["direct"]})
                print(f"\nAt {n:,}: the direct build gives the same summary counts and section lengths as the "
                      f"capture build: {'yes' if same else 'NO'}")
                if not same:
                    print(json.dumps(shapes, indent=1))
                    return 1
        if largest:
            db, n, folder = largest
            results["live_writer"] = {"size": n, **_with_live_writer(db, n, env, args.runs, "summary" in args.cli)}
            live = results["live_writer"]
            print(f"\nsummary at {n:,} with a writer holding the store open: in-process median "
                  f"{live['inprocess_ms']['median']} ms, worst {live['inprocess_ms']['worst']} ms"
                  + (f"; command line median {live['cli_ms']['median']} ms, worst {live['cli_ms']['worst']} ms"
                     if "cli_ms" in live else ""))
            shutil.rmtree(folder)
        if args.json:
            args.json.write_text(json.dumps(results, indent=1) + "\n")
        return 0
    finally:
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
