"""MN2: build a synthetic Mnemos store of about 160 MB. Never from anyone's data.

The schema is Mnemos's own (``SQL_CREATE_TABLES``, schema v18 at origin/main
cd8547f), imported from this checkout, so the tables, the FTS5 index and the
passage vectors are laid out exactly as a real store lays them out:

- ``engrams``: one row per memory; the words are synthetic (pseudo-words drawn
  with a Zipf law from a seeded vocabulary), 200 to 1,500 characters.
- ``engrams_fts``: FTS5 over ``content``, ``id`` unindexed, as Mnemos writes it.
- ``passage_vectors``: about one passage per 250 characters plus the whole-text
  passage, as scheme 3 cuts them; each a 384-dim float32 unit vector
  (all-MiniLM-L6-v2's size), random, packed as Mnemos packs them
  (``struct.pack('384f')``).

Five project scopes share one companion, so a scoped recall scores about a
fifth of the vectors, as recall's ``search_candidates`` does.

Usage: python make_store.py OUT.db [--mb 160] [--seed 7]
"""

from __future__ import annotations

import argparse
import hashlib
import os
import random
import sqlite3
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))  # this checkout's mnemos package

from mnemos.store.sqlite_store import SCHEMA_VERSION, SQL_CREATE_TABLES  # noqa: E402

DIMS = 384
MODEL = "all-MiniLM-L6-v2"
SCHEME = 3
AGENT = "companion"
PERSON = "person-synthetic"
SCOPES = [f"project-{i}" for i in range(5)]
SYLLABLES = [
    "ka", "lo", "mi", "ne", "ru", "sa", "to", "vi", "ze", "an", "el", "or", "un", "is",
    "pha", "dro", "qui", "ste", "bra", "mor", "len", "tas", "fin", "gal", "hep", "jur",
]


def vocabulary(rng: random.Random, size: int = 6000) -> list[str]:
    words: set[str] = set()
    while len(words) < size:
        words.add("".join(rng.choice(SYLLABLES) for _ in range(rng.randint(1, 4))))
    return sorted(words)


def sentence(rng: random.Random, vocab: list[str], weights: list[float]) -> str:
    words = rng.choices(vocab, weights=weights, k=rng.randint(6, 22))
    return " ".join(words).capitalize() + "."


def text(rng: random.Random, vocab: list[str], weights: list[float]) -> str:
    target = rng.randint(200, 1500)
    out: list[str] = []
    while sum(len(s) + 1 for s in out) < target:
        out.append(sentence(rng, vocab, weights))
    return " ".join(out)


def unit_vectors(nprng: np.random.Generator, n: int) -> np.ndarray:
    v = nprng.standard_normal((n, DIMS)).astype(np.float32)
    v /= np.linalg.norm(v, axis=1, keepdims=True)
    return v


def build(out: Path, mb: float, seed: int) -> dict:
    if out.exists():
        out.unlink()
    rng = random.Random(seed)
    nprng = np.random.default_rng(seed)
    vocab = vocabulary(rng)
    weights = [1.0 / (rank + 1) for rank in range(len(vocab))]  # Zipf
    conn = sqlite3.connect(out)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SQL_CREATE_TABLES)
    start = datetime(2026, 3, 1, tzinfo=timezone.utc)
    target = mb * 1024 * 1024
    made = passages_made = 0
    t0 = time.perf_counter()
    while True:
        rows, fts, vecs = [], [], []
        for _ in range(500):
            made += 1
            eid = f"engram_{made:08d}"
            body = text(rng, vocab, weights)
            when = (start + timedelta(minutes=made * 7)).isoformat()
            rows.append((
                eid, body, body, AGENT, PERSON, SCOPES[made % len(SCOPES)], when, when,
                rng.random(), int(rng.random() < 0.02),
            ))
            fts.append((body, eid))
            parts = len(body) // 250 + 1
            digest = hashlib.sha256(body.encode()).hexdigest()
            for part, vec in enumerate(unit_vectors(nprng, parts)):
                vecs.append((eid, MODEL, part, digest, DIMS, vec.tobytes(), SCHEME))
            passages_made += parts
        conn.executemany(
            "INSERT INTO engrams (id, content, content_at_encoding, owner_agent_id, person_id, "
            "project_scope, created_at, last_accessed, strength, standing) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)", rows,
        )
        conn.executemany("INSERT INTO engrams_fts (content, id) VALUES (?, ?)", fts)
        conn.executemany(
            "INSERT INTO passage_vectors (item_id, model_name, part, text_hash, dims, embedding, scheme) "
            "VALUES (?,?,?,?,?,?,?)", vecs,
        )
        conn.commit()
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        if out.stat().st_size >= target:
            break
    conn.execute("PRAGMA user_version = %d" % SCHEMA_VERSION)
    conn.commit()
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.close()
    return {
        "path": str(out), "bytes": out.stat().st_size, "engrams": made,
        "passages": passages_made, "seconds": round(time.perf_counter() - t0, 1),
        "schema_version": SCHEMA_VERSION, "seed": seed,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("out", type=Path)
    ap.add_argument("--mb", type=float, default=160)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()
    if "/.mnemos" in str(args.out.resolve()):
        sys.exit("refused: never write under ~/.mnemos")
    print(build(args.out, args.mb, args.seed))


if __name__ == "__main__":
    main()
