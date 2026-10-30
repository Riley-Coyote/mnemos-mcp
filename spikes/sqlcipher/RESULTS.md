# MN2: SQLCipher, FTS5, the passage vectors and Litestream

Measured Oct 30, 2026, on macOS 27.0.1, Apple M4 Max (14 cores, 36 GB), Python 3.12.11.
Linux was **not run** (below).

## Answer

- **SQLCipher carries FTS5 and the passage vectors: yes.** The whole Mnemos schema (v18, origin/main
  cd8547f) exports into SQLCipher 4.19.0 unchanged; `cipher_integrity_check` is clean, FTS5 MATCH/bm25
  and the `passage_vectors` BLOB reads work as they do on plain SQLite, and stock sqlite3 refuses the
  file ("file is not a database").
- **Cost: about 2x on recall, under 1 ms on a write, about 160 ms on wake** against the same SQLite
  build unkeyed. With a 64 MiB page cache, a scoped recall is no slower than plain.
- **Litestream can't carry SQLCipher, and can't encrypt its own copies.** Use SQLCipher's own
  encrypted snapshots, or encrypt on our side before upload, not Litestream with SSE.

## How Mnemos stores passage vectors today

In the store's own SQLite file, table `passage_vectors` (`mnemos/store/embedding_index.py`,
`PASSAGE_TABLE_SQL`): one row per passage, `embedding BLOB` = `struct.pack('384f')` (all-MiniLM-L6-v2,
float32), key `(item_id, model_name, part)`. There is no vector index: `search_candidates` reads every
candidate's rows (`item_id IN (...)`, 400 ids a statement) and scores them with numpy cosine
(`_similarities`). So recall reads the vectors from disk each time, and under SQLCipher every page read
that misses SQLCipher's page cache is decrypted and HMAC-checked. That is where the cost lands.

## The synthetic store

`make_store.py` (seed 7): 13,000 memories of pseudo-words (Zipf over a seeded 6,000-word vocabulary),
54,121 passages of random 384-dim unit vectors, 171,761,664 bytes (164 MiB). Five project scopes, so a
scoped recall scores 2,600 memories (10,906 vectors); "all" scores 13,000 (54,121). Nothing comes from
any real store.

## Numbers (median ms; two runs, `results-macos-run1.json` and `-run2.json`)

The machine was heavily loaded (load average 500 to 960, other builders' jobs), so the absolute numbers
are high and the p95s are noise. Every sample was taken for every variant back to back in shuffled
order, so the ratios are the trustworthy part. The fair baseline is **plain, same build** (SQLCipher's
own SQLite 3.53.4, unkeyed); stock sqlite3 here is 3.50.4 and was slower at FTS5 in both runs.

| | plain, same build | SQLCipher, raw key | ratio | SQLCipher, raw key, 64 MiB cache | ratio | SQLCipher, passphrase |
|---|---|---|---|---|---|---|
| recall, one scope (words + meaning) | 81 / 63 | 149 / 128 | 1.85 / 2.02 | 63 / 51 | 0.78 / 0.81 | |
| recall, whole store | 204 / 264 | 473 / 514 | 2.32 / 1.95 | 610 / 521 | 2.98 / 1.97 | |
| write (engram + FTS + passages, COMMIT) | 0.35 / 0.48 | 0.58 / 0.83 | 1.66 / 1.73 | 0.64 / 0.96 | 1.83 / 2.00 | |
| wake (fresh process, open + first reads) | 87 / 71 | 265 / 235 | 3.04 / 3.30 | 160 / 125 | 1.83 / 1.75 | 392 / 353 |

- Words (FTS5) alone are hardly touched: 0.5 to 0.8x stock sqlite3. The cost is the vector read.
- The 64 MiB cache holds one scope's 16 MB of vectors decrypted, so repeat recalls skip decryption.
  It doesn't help the whole-store read (83 MB of vectors), which needs a cache larger than that.
- Passphrase keying adds PBKDF2-HMAC-SHA512 at 256,000 iterations to every open (+120 to 230 ms).
  A KMS-unwrapped raw key (`PRAGMA key = "x'..'"`) skips it.
- Encrypting the existing store (`sqlcipher_export`): 1.3 to 2.4 s. An encrypted snapshot (backup
  API, key carried over): 2.3 s, against 0.7 to 1.2 s plain; the copy is ciphertext from byte 0.
- SQLCipher settings as measured: 4096-byte pages, HMAC-SHA512, PBKDF2-HMAC-SHA512, OpenSSL 3.6.0.

## Per-companion whole-file encryption (`filecrypt.py`)

AES-256-GCM in 1 MiB chunks, data key wrapped with AES key wrap (a local stand-in for KMS; a real KMS
unwrap adds a network round trip, not measured): seal 0.17 s, unseal 0.14 s for 164 MiB, round trip
byte-identical (`filecrypt-macos.json`). Fast, but SQLite can only work on an unsealed plaintext copy,
so the live store, its WAL and anything that copies it (Litestream, volume snapshots) are plaintext
while it's open. That doesn't meet claim 1, so it's a format for exports and backups, not for the
live store.

## Litestream

- **Its own encryption is gone.** v0.5.x has no client-side encryption: "Age client-side encryption is
  unsupported in v0.5.x", removed in the LTX refactor; a config with `age:` stops startup.
  https://litestream.io/reference/config/ (read Oct 30, 2026). The migration guide says the same and
  points to provider-side encryption or SQLCipher: https://litestream.io/docs/migration/ (read Oct 30,
  2026). Latest release v0.5.17, Aug 31, 2026 (GitHub releases API, read Oct 30, 2026).
- **It doesn't replicate SQLCipher databases.** In v0.3.4 a user got "sync error: file is not a
  database" (https://github.com/benbjohnson/litestream/issues/177, closed wontfix). In Oct 2025 the
  maintainer said: "We don't have plans to implement SQLCipher with Litestream"
  (https://github.com/benbjohnson/litestream/issues/777). v0.5 uses modernc-sqlite, which has neither
  SQLCipher nor SQLite3 Multiple Ciphers (https://github.com/benbjohnson/litestream/issues/663, closed
  Dec 29, 2025). All read Oct 30, 2026. Not tested here: Litestream isn't installed, and this package
  installs nothing outside its venv.
- **SSE won't crypto-shred on our host.** Litestream still passes S3 SSE-C/SSE-KMS (config page above),
  but Tigris, Fly's object storage, says SSE-C headers "are accepted but not applied, so
  customer-provided keys are not used" (https://www.tigrisdata.com/docs/api/s3/, read Oct 30, 2026). On
  AWS S3, SSE-C has been off by default for new buckets since April 6, 2026
  (https://aws.amazon.com/about-aws/whats-new/2026/04/s3-default-bucket-security-setting, read Oct 30,
  2026). SSE also leaves the live Fly volume copy plaintext to us.

## Linux

Not run. Docker Desktop is installed, but its daemon wasn't running and didn't come up within about
150 s of `open -a Docker`. OrbStack isn't installed. The scripts are platform-neutral; sqlcipher3 0.6.4
ships Linux wheels. Run `bench.py` in a `python:3.12` container on the Fly machine type before relying
on the 2x.

## Reproduce

```
uv venv -p 3.12 venv && VIRTUAL_ENV=$PWD/venv uv pip install sqlcipher3==0.6.4 numpy cryptography -r ../../pyproject.toml
HOME=$(mktemp -d) PYTHONDONTWRITEBYTECODE=1 venv/bin/python make_store.py plain.db --mb 160
HOME=$(mktemp -d) PYTHONDONTWRITEBYTECODE=1 venv/bin/python bench.py plain.db --queries 60 --writes 200 --wakes 20 --out results.json
HOME=$(mktemp -d) PYTHONDONTWRITEBYTECODE=1 venv/bin/python filecrypt.py plain.db
python summarize.py results.json
```
Every script refuses a path under `.mnemos`. The store (`*.db`) is gitignored.
