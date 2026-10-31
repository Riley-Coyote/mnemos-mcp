# Engine parity and crash harness (QA1a)

A scripted life (two runners, Mac and phone, 34 ops over six days: introduce, capture, correct by
memory id, by note id and by words, forget, stale corrections, reflect, maintain) is delivered to the
engine messily and the stores are compared with the clean run's. It gates merges into mnemos `main`.

Run it through the live-memory guard, never against a real store:

    scripts/hermetic.sh python -m tests.parity.harness --seeds 3      # JSON report, exit 1 on failure
    MNEMOS_PARITY=1 scripts/hermetic.sh pytest -q tests/parity        # the same, as tests (PARITY_SEEDS=n)

## What it proves

- **Reference.** The life once, in order, in one child process; a store hash after every op.
  Run twice, it must hash the same (the harness isn't vacuous).
- **Exactly-once.** A seeded shuffle adds duplicated and late redeliveries anywhere after an op's
  first delivery. The final hash, the ledger keys and the lineage must match the reference.
- **Crash.** The same stream, with the child process killed by the parent (`os.kill(pid, SIGKILL)`)
  while it waits at a seeded write statement (seen by sqlite's trace hook before it runs, so mid
  transaction). After each kill the store must hash as before or after the op in flight; the rest
  is redelivered from the first unacknowledged delivery, and the end must match the reference.
- **Lineage** (`canon.lineage_problems`): every ledger row complete; no two live engrams with the
  same words; every supersedes/superseded_by names an engram that exists, the two sides agree, no
  engram has two successors, no loops; every note successor exists; every live engram is indexed.
- **Collisions.** The reflection-queue collision rate: of the stale corrections (the phone correcting
  an id the Mac already changed), how many sent work to the reflection queue, and how many the engine
  applied to the lineage's head. Also the queue's own "already asked" refusals.

Every failure message names its seed: rerun with that seed to reproduce.

## The hash (`canon.py`, MEMORY-HOME §7)

sha256 over these tables' rows, each sorted by primary key and written as canonical JSON:
engrams, connections, versions, archive, beliefs, functional_memories, hypomnema_entries,
journal_entries, notes, reflection_queue, agent_identity, lived_days, memory_sessions,
session_reinforcements, consolidation_log, emotional_state_history, and meta minus
`schema_version`, `min_code_version`, `code_version_*_first_opened_at` and the one-time migration
markers (`engram_authors_labeled`, `hermes_auto_writes_labeled`, `capture_pairs_linked`).

Left out, and why: `host_mutations` and `host_mutation_dead_letters` (the ledger: rowids and
timings differ on replay; checked by key instead), `memory_trace` (a log of calls, and replays are
calls), `embeddings` and `passage_vectors` (a rebuildable cache outside the transaction),
`engrams_fts*` (derived; checked against engrams), `sqlite_sequence` (SQLite's counters).
A table in neither list fails the harness, so a new one has to be classified here.

## Determinism

The worker freezes the clock per op (the op's `observed_at`) and makes ids follow from the op
(`determinism.py`: `datetime`, `ulid.new`, `uuid.uuid4`), runs with `PYTHONHASHSEED=0` (the engine
writes an engram's tags in set order), and makes a fresh runtime per delivery (v1 counts a session
per runtime instance and reads the runner's session from `CLAUDE_CODE_SESSION_ID`).

## Adding a way in (MN1a, MN5a)

`drivers.py` holds one class per way an op reaches the engine. Add the class and one line in
`DRIVERS`, then run `--driver <name>`:

- **MN1a, protocol v2:** `HostMutationV2.deliver` calls `execute_host_mutation(..., protocol_version=2,
  context={"session": op.session, "observed_at": op.observed_at, "base_seq": ..., "origin": op.runner})`.
- **MN5a, the home:** `HomeHTTP.deliver` POSTs the op to a home started on a temp `/data` and returns
  its JSON answer. Its new tables go in `canon.HASHED` or `canon.EXCLUDED`.

Cross-driver parity is then one comparison: the v1 reference hash against the new driver's.
