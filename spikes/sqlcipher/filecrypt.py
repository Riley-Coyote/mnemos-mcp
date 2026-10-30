"""MN2, the other path: encrypt the whole store file with a per-companion data key.

The data key (AES-256) is wrapped by a stand-in for KMS: AES key wrap
(RFC 3394) under a local test master key. A real KMS adds one network round
trip to unwrap, which is not measured here. The file is sealed in 1 MiB
chunks of AES-256-GCM, each with its own nonce and its index as associated
data, so a chunk can't be moved or replayed.

What it costs: SQLite can't read the sealed file, so the store must be opened
(unsealed to a plaintext working copy) before use and sealed again after
writes. Measured: seal and unseal of the whole synthetic store.

Usage: python filecrypt.py PLAIN.db [--out filecrypt.json]
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.keywrap import aes_key_unwrap, aes_key_wrap

CHUNK = 1 << 20


def seal(src: Path, dst: Path, key: bytes) -> None:
    aead = AESGCM(key)
    with open(src, "rb") as fin, open(dst, "wb") as fout:
        index = 0
        while chunk := fin.read(CHUNK):
            nonce = os.urandom(12)
            fout.write(nonce + aead.encrypt(nonce, chunk, index.to_bytes(8, "big")))
            index += 1


def unseal(src: Path, dst: Path, key: bytes) -> None:
    aead = AESGCM(key)
    with open(src, "rb") as fin, open(dst, "wb") as fout:
        index = 0
        while block := fin.read(12 + CHUNK + 16):
            fout.write(aead.decrypt(block[:12], block[12:], index.to_bytes(8, "big")))
            index += 1


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("plain", type=Path)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--n", type=int, default=5)
    args = ap.parse_args()
    if "/.mnemos" in str(args.plain.resolve()):
        sys.exit("refused: never read under ~/.mnemos")
    master = os.urandom(32)  # stand-in for the KMS key; a test key, thrown away
    data_key = os.urandom(32)
    wrapped = aes_key_wrap(master, data_key)
    t0 = time.perf_counter()
    assert aes_key_unwrap(master, wrapped) == data_key
    unwrap_s = time.perf_counter() - t0
    sealed = args.plain.with_name("filecrypt.sealed")
    opened = args.plain.with_name("filecrypt-open.db")
    seal_t, unseal_t = [], []
    for _ in range(args.n):
        t0 = time.perf_counter()
        seal(args.plain, sealed, data_key)
        seal_t.append(time.perf_counter() - t0)
        t0 = time.perf_counter()
        unseal(sealed, opened, data_key)
        unseal_t.append(time.perf_counter() - t0)
    same = opened.read_bytes() == args.plain.read_bytes()
    result = {
        "bytes": args.plain.stat().st_size, "sealed_bytes": sealed.stat().st_size,
        "seal_s_median": round(statistics.median(seal_t), 3),
        "unseal_s_median": round(statistics.median(unseal_t), 3),
        "seal_s": [round(x, 3) for x in seal_t], "unseal_s": [round(x, 3) for x in unseal_t],
        "local_unwrap_ms": round(unwrap_s * 1000, 3), "round_trip_identical": same,
        "load_average": os.getloadavg(),
    }
    sealed.unlink()
    opened.unlink()
    print(json.dumps(result, indent=2))
    if args.out:
        args.out.write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()
