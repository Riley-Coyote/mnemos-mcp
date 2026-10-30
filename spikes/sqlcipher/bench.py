"""MN2: recall, write and wake on plain SQLite against SQLCipher, on the synthetic store.

The queries are Mnemos's own shapes at origin/main cd8547f:

- recall, words: ``search_fts_ranked``'s statement (engrams JOIN engrams_fts,
  MATCH, state and scope, ORDER BY rank LIMIT 50).
- recall, meaning: ``search_candidates``'s read of ``passage_vectors`` for the
  candidates (in chunks of 400 ids, as ``_ID_CHUNK``) and the cosine of
  ``_similarities`` with numpy, top 30 by best passage. The query's own vector
  is random: embedding it costs the same on either store and is left out.
  Two candidate sets: one scope (about a fifth of the store), and every memory.
- write: one capture as one transaction: the engram, its FTS row and its
  passages (one per 250 characters plus the whole), then COMMIT, in WAL with
  synchronous=NORMAL as ``SQLiteStore._get_conn`` sets it.
- wake: a fresh process opens the store, keys it, sets Mnemos's pragmas, and
  reads what a wake reads first: the standing memories, the 20 newest, the 30
  strongest, and the count, in the companion's scope. Timed inside the process,
  from connect to the last row; interpreter start is not counted.

Variants:
  plain        the stdlib sqlite3
  plain-sqlcipher-build  SQLCipher's own build, unkeyed: a plain file, the same
               SQLite version as the cipher variants, so version differences
               are not read as the cost of encryption
  cipher-raw   SQLCipher 4 defaults, keyed with a raw 256-bit key (x'..'): no
               KDF, which is how a KMS-unwrapped data key would key it
  cipher-pass  SQLCipher 4 defaults keyed with a passphrase: PBKDF2-HMAC-SHA512,
               256,000 iterations, on every open (wake only; the rest equals raw)
  cipher-raw-cache  raw key, with PRAGMA cache_size=-65536 (64 MiB of decrypted
               pages kept), to show what a larger page cache buys

Usage: python bench.py PLAIN.db [--out results.json]
It makes the encrypted copy itself (sqlcipher_export), next to PLAIN.db.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import random
import shutil
import sqlite3
import statistics
import struct
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import sqlcipher3

DIMS = 384
MODEL = "all-MiniLM-L6-v2"
SCHEME = 3
AGENT, PERSON, SCOPE = "companion", "person-synthetic", "project-0"
RAW_KEY = "x'" + "2b" * 32 + "'"  # a fixed test key; never a real one
PASSPHRASE = "mn2-synthetic-passphrase"
ID_CHUNK = 400

FTS_SQL = (
    "SELECT e.*, f.rank AS fts_rank FROM engrams e JOIN engrams_fts f ON e.id = f.id "
    "WHERE engrams_fts MATCH ? AND e.state = ? AND e.owner_agent_id = ? AND e.person_id = ? "
    "AND e.project_scope = ? ORDER BY rank LIMIT ?"
)


def connect(variant: str, path: Path):
    if variant == "plain":
        conn = sqlite3.connect(str(path), check_same_thread=False)
    elif variant == "plain-sqlcipher-build":
        conn = sqlcipher3.connect(str(path), check_same_thread=False)  # no key: a plain file
    else:
        conn = sqlcipher3.connect(str(path), check_same_thread=False)
        key = PASSPHRASE if variant == "cipher-pass" else RAW_KEY
        conn.execute(f"PRAGMA key = \"{key}\"" if key.startswith("x'") else f"PRAGMA key = '{key}'")
        if variant == "cipher-raw-cache":
            conn.execute("PRAGMA cache_size = -65536")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def encrypt_copy(plain: Path, target: Path, key_sql: str) -> float:
    for suffix in ("", "-wal", "-shm"):
        Path(str(target) + suffix).unlink(missing_ok=True)
    t0 = time.perf_counter()
    conn = sqlcipher3.connect(str(plain))
    conn.execute(f"ATTACH DATABASE '{target}' AS enc KEY {key_sql}")
    conn.execute("SELECT sqlcipher_export('enc')")
    conn.execute("DETACH DATABASE enc")
    conn.close()
    return time.perf_counter() - t0


def stats(samples: list[float]) -> dict:
    ms = sorted(s * 1000 for s in samples)
    return {
        "n": len(ms), "median_ms": round(statistics.median(ms), 2),
        "p95_ms": round(ms[min(len(ms) - 1, int(len(ms) * 0.95))], 2),
        "min_ms": round(ms[0], 2), "max_ms": round(ms[-1], 2),
    }


def query_words(conn, rng: random.Random, n: int) -> list[str]:
    sample = [r[0] for r in conn.execute(
        "SELECT content FROM engrams WHERE rowid % 97 = 0 LIMIT 400")]
    queries = []
    for _ in range(n):
        words = rng.choice(sample).replace(".", " ").lower().split()
        queries.append(" OR ".join(rng.sample(words, min(3, len(words)))))
    return queries


def recall_once(conn, q: str, candidates: list[str], query: np.ndarray) -> tuple[float, float, int]:
    """One recall: (seconds for the words, seconds for the meaning, vectors read)."""
    t0 = time.perf_counter()
    rows = conn.execute(FTS_SQL, (q, "active", AGENT, PERSON, SCOPE, 50)).fetchall()
    t1 = time.perf_counter()
    found = []
    for i in range(0, len(candidates), ID_CHUNK):
        chunk = candidates[i:i + ID_CHUNK]
        found += conn.execute(
            "SELECT item_id, embedding, dims, part, text_hash FROM passage_vectors "
            "WHERE model_name = ? AND scheme >= ? AND item_id IN (%s)" % ",".join("?" * len(chunk)),
            (MODEL, SCHEME, *chunk),
        ).fetchall()
    matrix = np.frombuffer(b"".join(r[1] for r in found), dtype=np.float32).reshape(
        len(found), DIMS).astype(np.float64)
    sims = (matrix @ query) / np.linalg.norm(matrix, axis=1)
    best: dict[str, float] = {}
    for (item_id, *_), s in zip(found, sims.tolist()):
        if s > best.get(item_id, -2.0):
            best[item_id] = s
    sorted(best, key=best.get, reverse=True)[:30]
    t2 = time.perf_counter()
    assert rows, "the words found nothing"
    return t1 - t0, t2 - t1, len(found)


def write_once(conn, eid: str, body: str, vecs: np.ndarray) -> float:
    """One capture: the engram, its FTS row and its passages, one transaction."""
    t0 = time.perf_counter()
    conn.execute(
        "INSERT INTO engrams (id, content, content_at_encoding, owner_agent_id, person_id, "
        "project_scope, created_at, last_accessed) VALUES (?,?,?,?,?,?,datetime(),datetime())",
        (eid, body, body, AGENT, PERSON, SCOPE),
    )
    conn.execute("INSERT INTO engrams_fts (content, id) VALUES (?, ?)", (body, eid))
    conn.executemany(
        "INSERT INTO passage_vectors (item_id, model_name, part, text_hash, dims, embedding, scheme) "
        "VALUES (?,?,?,?,?,?,?)",
        [(eid, MODEL, p, "h", DIMS, v.tobytes(), SCHEME) for p, v in enumerate(vecs)],
    )
    conn.commit()
    return time.perf_counter() - t0


WAKE_CHILD = r"""
import sys, time, json
sys.path.insert(0, sys.argv[3])
import bench
t0 = time.perf_counter()
conn = bench.connect(sys.argv[1], bench.Path(sys.argv[2]))
a = conn.execute("SELECT id, content FROM engrams WHERE standing = 1 AND owner_agent_id = ? AND state = 'active'", (bench.AGENT,)).fetchall()
b = conn.execute("SELECT id, content FROM engrams WHERE owner_agent_id = ? AND state = 'active' ORDER BY created_at DESC LIMIT 20", (bench.AGENT,)).fetchall()
c = conn.execute("SELECT id, content FROM engrams WHERE owner_agent_id = ? AND state = 'active' ORDER BY strength DESC LIMIT 30", (bench.AGENT,)).fetchall()
d = conn.execute("SELECT count(*) FROM engrams WHERE owner_agent_id = ?", (bench.AGENT,)).fetchone()
print(json.dumps({"s": time.perf_counter() - t0, "rows": [len(a), len(b), len(c), d[0]]}))
"""


def wake_once(variant: str, path: Path) -> tuple[float, list[int]]:
    out = subprocess.run(
        [sys.executable, "-c", WAKE_CHILD, variant, str(path), str(Path(__file__).parent)],
        capture_output=True, text=True, check=True,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    got = json.loads(out.stdout)
    return got["s"], got["rows"]


def snapshot(variant: str, path: Path) -> dict:
    """A whole-store copy with SQLite's backup API, as a backup job would take
    one; SQLCipher writes the copy encrypted with the same key."""
    target = path.with_name(path.stem + "-snapshot.db")
    target.unlink(missing_ok=True)
    src = connect(variant, path)
    if variant == "plain":
        dst = sqlite3.connect(str(target))
    else:
        dst = sqlcipher3.connect(str(target))
        dst.execute(f"PRAGMA key = \"{RAW_KEY}\"")
    t0 = time.perf_counter()
    src.backup(dst)
    dt = time.perf_counter() - t0
    dst.close()
    src.close()
    size = target.stat().st_size
    with open(target, "rb") as fh:
        header = fh.read(16)
    target.unlink()
    return {"seconds": round(dt, 2), "bytes": size, "plaintext_header": header == b"SQLite format 3\x00"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("plain", type=Path)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--queries", type=int, default=30)
    ap.add_argument("--writes", type=int, default=100)
    ap.add_argument("--wakes", type=int, default=15)
    args = ap.parse_args()
    if "/.mnemos" in str(args.plain.resolve()):
        sys.exit("refused: never read or write under ~/.mnemos")
    plain = args.plain.resolve()
    work = plain.with_name("bench-plain.db")
    raw = plain.with_name("cipher-raw.db")
    pas = plain.with_name("cipher-pass.db")

    result: dict = {
        "machine": {
            "platform": platform.platform(), "machine": platform.machine(),
            "python": platform.python_version(), "sqlite": sqlite3.sqlite_version,
        },
        "store": {"plain_bytes": plain.stat().st_size},
        "variants": {},
    }
    probe = sqlcipher3.connect(":memory:")
    result["machine"]["sqlcipher"] = probe.execute("PRAGMA cipher_version").fetchone()[0]
    result["machine"]["sqlcipher_sqlite"] = probe.execute("SELECT sqlite_version()").fetchone()[0]
    probe.close()

    # Fresh copies, so every variant starts from the same bytes.
    for suffix in ("", "-wal", "-shm"):
        Path(str(work) + suffix).unlink(missing_ok=True)
    src = sqlite3.connect(str(plain))
    dst = sqlite3.connect(str(work))
    src.backup(dst)
    src.close()
    dst.close()
    result["store"]["encrypt_export_raw_s"] = round(encrypt_copy(plain, raw, f"\"{RAW_KEY}\""), 2)
    result["store"]["encrypt_export_pass_s"] = round(encrypt_copy(plain, pas, f"'{PASSPHRASE}'"), 2)
    result["store"]["cipher_bytes"] = raw.stat().st_size
    with open(raw, "rb") as fh:
        result["store"]["cipher_header_is_plaintext"] = fh.read(16) == b"SQLite format 3\x00"
    check = connect("cipher-raw", raw)
    result["store"]["cipher_integrity"] = check.execute("PRAGMA cipher_integrity_check").fetchall() == []
    result["store"]["cipher_settings"] = {
        name: check.execute(f"PRAGMA {name}").fetchone()[0]
        for name in ("cipher_page_size", "kdf_iter", "cipher_hmac_algorithm", "cipher_kdf_algorithm",
                     "cipher_provider", "cipher_provider_version")
    }
    result["store"]["cipher_fts5_rows"] = check.execute("SELECT count(*) FROM engrams_fts").fetchone()[0]
    check.close()
    try:
        sqlite3.connect(str(raw)).execute("SELECT count(*) FROM engrams").fetchone()
        result["store"]["plain_sqlite_can_read_cipher"] = True
    except sqlite3.DatabaseError as exc:
        result["store"]["plain_sqlite_can_read_cipher"] = f"no: {exc}"

    candidates_scope = [r[0] for r in sqlite3.connect(str(plain)).execute(
        "SELECT id FROM engrams WHERE project_scope = ? AND state = 'active'", (SCOPE,))]
    candidates_all = [r[0] for r in sqlite3.connect(str(plain)).execute(
        "SELECT id FROM engrams WHERE state = 'active'")]
    result["store"]["candidates_scope"] = len(candidates_scope)
    result["store"]["candidates_all"] = len(candidates_all)

    # Every sample is taken for every variant back to back, in a shuffled order,
    # so load from anything else on the machine falls on all of them alike.
    # The ratio to plain is taken per sample, then its median reported.
    raw2 = plain.with_name("cipher-raw-cache.db")
    encrypt_copy(plain, raw2, f"\"{RAW_KEY}\"")
    work2 = plain.with_name("bench-plain-sc.db")
    shutil.copyfile(work, work2)
    paths = {"plain": work, "plain-sqlcipher-build": work2, "cipher-raw": raw, "cipher-raw-cache": raw2}
    conns = {v: connect(v, p) for v, p in paths.items()}
    rng = random.Random(11)
    nprng = np.random.default_rng(11)
    queries = query_words(conns["plain"], rng, args.queries)
    samples: dict = {v: {} for v in paths}

    def add(variant: str, op: str, seconds: float) -> None:
        samples[variant].setdefault(op, []).append(seconds)

    def rounds(n: int, op: str, run) -> None:
        for i in range(n):
            order = list(paths)
            rng.shuffle(order)
            for v in order:
                run(i, v)

    for q in queries[:3]:  # warm every cache once
        for v in paths:
            recall_once(conns[v], q, candidates_scope, np.ones(DIMS) / DIMS ** 0.5)
    vectors_read = {}

    def recall_round(cands: list[str], label: str):
        def run(i: int, v: str) -> None:
            query = np.random.default_rng(i).standard_normal(DIMS)
            query /= np.linalg.norm(query)
            words, meaning, read = recall_once(conns[v], queries[i % len(queries)], cands, query)
            add(v, f"{label}_words", words)
            add(v, f"{label}_meaning", meaning)
            add(v, f"{label}_total", words + meaning)
            vectors_read[label] = read
        return run

    rounds(args.queries, "recall_scope", recall_round(candidates_scope, "recall_scope"))
    rounds(max(5, args.queries // 3), "recall_all", recall_round(candidates_all, "recall_all"))

    bodies = []
    for i in range(args.writes):
        body = " ".join(f"w{rng.randint(0, 5000)}" for _ in range(rng.randint(40, 250)))
        bodies.append((body, nprng.standard_normal((len(body) // 250 + 1, DIMS)).astype(np.float32)))
    rounds(args.writes, "write", lambda i, v: add(
        v, "write", write_once(conns[v], f"bench_{v}_{i:05d}", *bodies[i])))
    for c in conns.values():
        c.close()

    paths_wake = {**paths, "cipher-pass": pas}
    wake_rows = {}

    def wake_run(i: int, v: str) -> None:
        sec, rows = wake_once(v, paths_wake[v])
        add(v, "wake", sec)
        wake_rows[v] = rows
    samples["cipher-pass"] = {}
    for i in range(args.wakes):
        order = list(paths_wake)
        rng.shuffle(order)
        for v in order:
            wake_run(i, v)

    for v, ops in samples.items():
        out = {}
        for op, xs in ops.items():
            out[op] = stats(xs)
            base = samples["plain"].get(op)
            if v != "plain" and base:
                out[op]["ratio_to_plain_median"] = round(statistics.median(
                    x / b for x, b in zip(xs, base) if b > 0), 2)
        result["variants"][v] = out
    result["vectors_read"] = vectors_read
    result["wake_rows"] = wake_rows
    for v in ("plain", "cipher-raw"):
        result["variants"][v]["snapshot"] = snapshot(v, paths[v])
    result["load_average"] = os.getloadavg()

    text = json.dumps(result, indent=2)
    print(text)
    if args.out:
        args.out.write_text(text + "\n")
    for p in (work, raw, pas, raw2, work2):
        for suffix in ("", "-wal", "-shm"):
            Path(str(p) + suffix).unlink(missing_ok=True)


if __name__ == "__main__":
    main()
