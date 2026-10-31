"""The store's meaning as one hash, and the lineage checks (MEMORY-HOME §7).

Two stores are "the same memory" when :func:`store_hash` agrees: sha256 over
the semantic tables' rows, each table's rows sorted by primary key and written
as canonical JSON. File bytes are never compared: page layout, free lists, WAL
state and rowids of rebuildable tables differ between stores that mean the
same thing.

Every table a store holds must be named in :data:`HASHED` or :data:`EXCLUDED`.
A table nobody has classified fails the harness (:func:`unclassified_tables`),
so a package that adds one (MN1a's dead letters, MN5a's registry) says here
whether it is memory.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from pathlib import Path
from typing import Any

# What the memory is (MEMORY-HOME §7).
HASHED: tuple[str, ...] = (
    "engrams", "connections", "versions", "archive", "beliefs",
    "functional_memories", "hypomnema_entries", "journal_entries", "notes",
    "reflection_queue", "agent_identity", "lived_days", "memory_sessions",
    "session_reinforcements", "consolidation_log", "emotional_state_history",
    "meta",
)

# What it isn't, and why.
EXCLUDED: dict[str, str] = {
    # The ledger. Its rows are compared by the exactly-once checks instead
    # (one completed row per key); completed_at is delivery time.
    "host_mutations": "the idempotency ledger: rowids and timings differ on replay",
    "host_mutation_dead_letters": "the ledger's refused attempts (MN1a): received_at is delivery time",
    "memory_trace": "a log of tool calls, one row per call (replays are calls too)",
    "embeddings": "a rebuildable cache, outside the host-mutation transaction",
    "passage_vectors": "a rebuildable cache, outside the host-mutation transaction",
    "sqlite_sequence": "SQLite's AUTOINCREMENT counters; the rows they number are hashed",
}
# engrams_fts and its shadow tables: derived from engrams, checked by rebuilding.
_FTS = re.compile(r"^engrams_fts(_\w+)?$")

# meta keys that record code versions or process times, not memory.
_META_EXCLUDED = re.compile(
    r"^(schema_version"
    r"|min_code_version"
    r"|code_version_\d+_first_opened_at"
    # one-time migrations: their value is when this file was first opened
    r"|engram_authors_labeled|hermes_auto_writes_labeled|capture_pairs_linked)$"
)


def _connect(db: Path | str) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{Path(db)}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _tables(conn: sqlite3.Connection) -> list[str]:
    return [
        row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
        )
    ]


def unclassified_tables(db: Path | str) -> list[str]:
    conn = _connect(db)
    try:
        return [
            name for name in _tables(conn)
            if name not in HASHED and name not in EXCLUDED and not _FTS.match(name)
        ]
    finally:
        conn.close()


def _value(value: Any) -> Any:
    if isinstance(value, bytes):
        return {"$hex": value.hex()}
    return value


def _primary_key(conn: sqlite3.Connection, table: str) -> list[str]:
    info = conn.execute(f"PRAGMA table_info({table})").fetchall()
    keyed = sorted((row["pk"], row["name"]) for row in info if row["pk"])
    return [name for _, name in keyed]


def table_rows(conn: sqlite3.Connection, table: str) -> list[dict[str, Any]]:
    """The table's rows as dicts in primary-key order (then by content, for rowid tables)."""
    rows = [{k: _value(row[k]) for k in row.keys()} for row in conn.execute(f"SELECT * FROM {table}")]
    if table == "meta":
        rows = [row for row in rows if not _META_EXCLUDED.match(str(row.get("key")))]
    pk = _primary_key(conn, table)

    def order(row: dict[str, Any]) -> tuple:
        return (
            json.dumps([row.get(name) for name in pk], sort_keys=True, default=str),
            json.dumps(row, sort_keys=True, default=str),
        )

    return sorted(rows, key=order)


def store_digest(db: Path | str) -> dict[str, str]:
    """sha256 per hashed table; a table the store doesn't have hashes as empty."""
    if not Path(db).exists():
        return {table: _sha([]) for table in HASHED}
    conn = _connect(db)
    try:
        present = set(_tables(conn))
        return {
            table: _sha(table_rows(conn, table) if table in present else [])
            for table in HASHED
        }
    finally:
        conn.close()


def _sha(rows: list[dict[str, Any]]) -> str:
    text = json.dumps(rows, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def store_hash(db: Path | str) -> str:
    """One hash for the whole memory: the per-table hashes, in a fixed order."""
    digest = store_digest(db)
    return _sha([{"table": t, "sha256": digest[t]} for t in HASHED])


def diff_tables(a: Path | str, b: Path | str) -> list[str]:
    """Which hashed tables differ, for a failure message."""
    da, db_ = store_digest(a), store_digest(b)
    return [t for t in HASHED if da[t] != db_[t]]


# ---------------------------------------------------------------------------
# Exactly-once and lineage
# ---------------------------------------------------------------------------

def ledger(db: Path | str) -> list[dict[str, Any]]:
    conn = _connect(db)
    try:
        return [dict(row) for row in conn.execute(
            "SELECT host_namespace, idempotency_key, operation, request_sha256, "
            "result_json, completed_at FROM host_mutations "
            "ORDER BY host_namespace, idempotency_key"
        )]
    finally:
        conn.close()


def lineage_problems(db: Path | str) -> list[str]:
    """Lost, duplicated or forked engrams, and broken lineage, in one store.

    - every ledger row is complete (a claim never outlives its transaction);
    - no two live engrams hold the same words (a duplicated capture);
    - every supersedes / superseded_by names an engram that exists, and the
      two sides agree;
    - an engram is superseded by at most one engram, and following
      superseded_by never loops: a lineage is a line, never a fork, so each
      has at most one live head;
    - every note's superseded_by names a note that exists, at most one live
      note per lineage;
    - the FTS index holds exactly the engrams (it's rebuilt from them).
    """
    problems: list[str] = []
    conn = _connect(db)
    try:
        for row in conn.execute(
            "SELECT host_namespace, idempotency_key FROM host_mutations "
            "WHERE completed_at IS NULL OR result_json IS NULL"
        ):
            problems.append(f"incomplete ledger row {tuple(row)}")

        engrams = {
            row["id"]: dict(row)
            for row in conn.execute("SELECT id, content, state, lineage FROM engrams")
        }
        live_words: dict[str, str] = {}
        for eid, row in sorted(engrams.items()):
            if row["state"] in ("archived", "superseded"):
                continue
            words = " ".join(str(row["content"]).split())
            if words in live_words:
                problems.append(f"duplicated engram: {live_words[words]} and {eid} both hold {words[:60]!r}")
            live_words[words] = eid

        successors: dict[str, list[str]] = {}
        for eid, row in engrams.items():
            try:
                lineage = json.loads(row["lineage"] or "{}")
            except ValueError:
                problems.append(f"{eid}: unreadable lineage")
                continue
            for old in lineage.get("supersedes") or []:
                if old not in engrams:
                    problems.append(f"{eid} supersedes {old}, which is lost")
                    continue
                successors.setdefault(old, []).append(eid)
            later = lineage.get("superseded_by")
            if later and later not in engrams:
                problems.append(f"{eid} is superseded by {later}, which is lost")
        for old, news in successors.items():
            if len(set(news)) > 1:
                problems.append(f"forked lineage: {old} is superseded by {sorted(set(news))}")
            later = json.loads(engrams[old]["lineage"] or "{}").get("superseded_by")
            if later and later not in news:
                problems.append(f"{old} says superseded_by {later}; {sorted(news)} say they supersede it")

        def head(eid: str) -> str:
            seen = {eid}
            while True:
                later = json.loads(engrams[eid]["lineage"] or "{}").get("superseded_by")
                if not later or later not in engrams:
                    return eid
                if later in seen:
                    problems.append(f"lineage loop through {eid}")
                    return eid
                seen.add(later)
                eid = later

        for eid in engrams:
            head(eid)

        notes = {
            row["id"]: dict(row)
            for row in conn.execute("SELECT id, active, superseded_by FROM hypomnema_entries")
        }
        for nid, row in notes.items():
            later = row["superseded_by"]
            if later and later not in notes:
                problems.append(f"note {nid} is superseded by {later}, which is lost")
        for nid in notes:
            seen = {nid}
            cur = nid
            while notes[cur]["superseded_by"] and notes[cur]["superseded_by"] in notes:
                cur = notes[cur]["superseded_by"]
                if cur in seen:
                    problems.append(f"note lineage loop through {nid}")
                    break
                seen.add(cur)

        # Archiving takes an engram out of the index; every live one is in it.
        fts = {row[0] for row in conn.execute("SELECT id FROM engrams_fts")}
        live = {eid for eid, row in engrams.items() if row["state"] != "archived"}
        if not live <= fts or not fts <= set(engrams):
            problems.append(
                f"engrams_fts disagrees with engrams: {len(fts - set(engrams))} extra, "
                f"{len(live - fts)} live ones missing"
            )
    finally:
        conn.close()
    return problems

