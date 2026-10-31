"""Replay the scripted life messily and compare stores: ``python -m tests.parity.harness``.

Run it through the guard: ``scripts/hermetic.sh python -m tests.parity.harness --seeds 3``.

- reference: the life delivered once, in order, in one child; a hash after every op.
- exactly-once: a seeded shuffle adds duplicated and late redeliveries; same final hash.
- crash: the same stream, with the child SIGKILLed at seeded write points mid-transaction;
  after each kill the store hashes as before or after the op in flight, and the rest is
  redelivered from the unacknowledged one; same final hash.
Every failure names its seed.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import signal
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from . import canon
from .life import Op, scripted_life

ROOT = Path(__file__).resolve().parents[2]
_CLEARED = ("CLAUDE_CODE_SESSION_ID", "MNEMOS_HOUR_ID", "MNEMOS_AGENT_MODEL", "MNEMOS_MODEL")


class ParityFailure(AssertionError):
    pass


@dataclass
class Outcome:
    acks: list[dict] = field(default_factory=list)
    killed_at: int | None = None
    done: dict | None = None


def run_worker(db: Path, deliveries: list[Op], *, driver: str = "v1",
               crash_at: int | None = None, hash_each: bool = False) -> Outcome:
    env = {k: v for k, v in os.environ.items() if k not in _CLEARED}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    # The engine writes some sets in iteration order (an engram's tags), which
    # string-hash randomization changes from process to process.
    env["PYTHONHASHSEED"] = "0"
    child = subprocess.Popen(
        [sys.executable, "-m", "tests.parity.worker"], cwd=ROOT, env=env,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
    )
    assert child.stdin and child.stdout
    child.stdin.write(json.dumps({
        "db": str(db), "driver": driver, "crash_at_write": crash_at, "hash_each": hash_each,
        "deliveries": [op.to_json() for op in deliveries],
    }) + "\n")
    child.stdin.flush()
    outcome = Outcome()
    for line in child.stdout:
        if not line.startswith("PARITY "):
            continue
        message = json.loads(line[len("PARITY "):])
        if "write_point" in message:
            os.kill(child.pid, signal.SIGKILL)
            child.wait()
            outcome.killed_at = message["write_point"]
            return outcome
        if "ack" in message:
            outcome.acks.append(message)
        if message.get("done"):
            outcome.done = message
    code = child.wait()
    if code != 0 or outcome.done is None:
        raise ParityFailure(f"worker exited {code} after {len(outcome.acks)} deliveries")
    return outcome


@dataclass
class Reference:
    life: list[Op]
    after: list[str]  # after[i] = hash once op i is applied
    empty: str
    writes: int
    acks: list[dict]
    collisions: dict
    db: Path

    @property
    def final(self) -> str:
        return self.after[-1]

    def before(self, index: int) -> str:
        return self.empty if index == 0 else self.after[index - 1]


def reference(workdir: Path, driver: str = "v1", name: str = "reference.db") -> Reference:
    life = scripted_life()
    db = workdir / name
    empty = canon.store_hash(db)
    outcome = run_worker(db, life, driver=driver, hash_each=True)
    return Reference(
        life=life, after=[a["hash"] for a in outcome.acks], empty=empty,
        writes=outcome.done["writes"], acks=outcome.acks,
        collisions=outcome.done["collisions"], db=db,
    )


def delivery_stream(life: list[Op], seed: int, dup_rate: float = 0.5) -> list[Op]:
    """Every op once in causal order, plus seeded duplicates landing anywhere after their first."""
    rng = random.Random(seed)
    n = len(life)
    events: list[tuple[float, int, Op]] = [(float(i), 0, op) for i, op in enumerate(life)]
    tie = 1
    for i, op in enumerate(life):
        while rng.random() < dup_rate:
            events.append((i + rng.uniform(0.0, n - i + 1.0), tie, op))
            tie += 1
    return [op for _, _, op in sorted(events, key=lambda e: (e[0], e[1]))]


def _check_final(ref: Reference, db: Path, seed: int, what: str) -> None:
    got = canon.store_hash(db)
    if got != ref.final:
        raise ParityFailure(
            f"[{what} seed={seed}] final hash differs from the reference in "
            f"{canon.diff_tables(ref.db, db)}"
        )
    problems = canon.lineage_problems(db)
    if problems:
        raise ParityFailure(f"[{what} seed={seed}] lineage: {problems}")
    keys = [row["idempotency_key"] for row in canon.ledger(db)]
    if sorted(keys) != sorted(op.key for op in ref.life):
        raise ParityFailure(f"[{what} seed={seed}] ledger keys differ from the life's")


def exactly_once(ref: Reference, workdir: Path, seed: int, driver: str = "v1") -> dict:
    stream = delivery_stream(ref.life, seed)
    db = workdir / f"dup-{seed}.db"
    run_worker(db, stream, driver=driver)
    _check_final(ref, db, seed, "exactly-once")
    return {"seed": seed, "deliveries": len(stream), "duplicates": len(stream) - len(ref.life)}


def crash(ref: Reference, workdir: Path, seed: int, max_kills: int = 3, driver: str = "v1") -> dict:
    rng = random.Random(10_000 + seed)
    stream = delivery_stream(ref.life, seed)
    db = workdir / f"crash-{seed}.db"
    position, applied, kills = 0, -1, []
    while position < len(stream):
        crash_at = rng.randint(1, max(1, ref.writes)) if len(kills) < max_kills else None
        outcome = run_worker(db, stream[position:], driver=driver, crash_at=crash_at)
        for ack in outcome.acks:
            applied = max(applied, ack["index"])
        position += len(outcome.acks)
        if outcome.killed_at is None:
            break
        in_flight = stream[position].index
        allowed = {ref.before(applied + 1) if applied >= 0 else ref.empty}
        if in_flight > applied:
            allowed.add(ref.after[in_flight])
        got = canon.store_hash(db)
        if got not in allowed:
            raise ParityFailure(
                f"[crash seed={seed}] killed at write {outcome.killed_at} during {stream[position].key}: "
                "the store is neither before nor after that op"
            )
        kills.append({"write": outcome.killed_at, "op": stream[position].key})
    _check_final(ref, db, seed, "crash")
    return {"seed": seed, "kills": kills}


def collision_rate(ref: Reference) -> dict:
    """What the engine does with stale corrections (ONE-COMPANION "Collisions")."""
    by_key = {op.key: op for op in ref.life}
    stale = [a for a, op in zip(ref.acks, ref.life) if "stale" in by_key[op.key].tags]
    queued = [a for a in stale if a["queue_after"] > a["queue_before"]]
    to_head = [a for a in stale if "acted on its current version" in a["result"]]
    corrections = [op for op in ref.life if op.operation == "correct"]
    return {
        "corrections": len(corrections),
        "stale_corrections": len(stale),
        "collision_rate": round(len(stale) / len(corrections), 4) if corrections else 0.0,
        "stale_sent_to_reflection_queue": len(queued),
        "reflection_queue_collision_rate": round(len(queued) / len(stale), 4) if stale else 0.0,
        "stale_applied_to_head": len(to_head),
        "queue_rows_at_end": ref.acks[-1]["queue_after"],
        "enqueue_attempts": ref.collisions["enqueue_attempts"],
        "enqueue_refused_as_already_asked": ref.collisions["enqueue_refused"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seeds", type=int, default=3)
    parser.add_argument("--crash-seeds", type=int, default=None)
    parser.add_argument("--driver", default="v1")
    args = parser.parse_args(argv)
    with tempfile.TemporaryDirectory(prefix="mnemos-parity-") as tmp:
        work = Path(tmp)
        ref = reference(work, args.driver)
        again = reference(work, args.driver, "reference-2.db")
        report = {
            "driver": args.driver, "ops": len(ref.life), "reference_writes": ref.writes,
            "final_hash": ref.final, "deterministic": again.final == ref.final,
            "reference_lineage_problems": canon.lineage_problems(ref.db),
            "unclassified_tables": canon.unclassified_tables(ref.db),
            "collisions": collision_rate(ref),
            "exactly_once": [], "crash": [], "failures": [],
        }
        for seed in range(args.seeds):
            try:
                report["exactly_once"].append(exactly_once(ref, work, seed, args.driver))
            except ParityFailure as failure:
                report["failures"].append(str(failure))
        for seed in range(args.seeds if args.crash_seeds is None else args.crash_seeds):
            try:
                report["crash"].append(crash(ref, work, seed, driver=args.driver))
            except ParityFailure as failure:
                report["failures"].append(str(failure))
    print(json.dumps(report, indent=2))
    ok = (report["deterministic"] and not report["failures"]
          and not report["reference_lineage_problems"] and not report["unclassified_tables"])
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
